import logging
from typing import Dict, Any
from datetime import date, timedelta, datetime
from sqlalchemy.orm import Session
from app.database.models import Student, Subscription, Invoice, MessageLog
from app.services.asaas import asaas_service
from app.services.whatsapp import whatsapp_service
from app.core.config import settings

logger = logging.getLogger(__name__)


class BillingService:
    @staticmethod
    async def generate_monthly_invoices(db: Session) -> int:
        """
        Varre todas as assinaturas ativas e gera a cobrança do mês corrente se ainda não existir.
        Gera o Pix no Asaas e armazena os códigos para envio.
        """
        today = date.today()
        subscriptions = (
            db.query(Subscription)
            .join(Student)
            .filter(Subscription.is_active == True, Student.is_active == True)
            .all()
        )

        created_count = 0

        for sub in subscriptions:
            student = sub.student
            plan = sub.plan

            # Calcular data de vencimento no mês corrente
            # Tratar meses com menos dias (ex: dia 31 em fevereiro/abril)
            try:
                due_date = date(today.year, today.month, sub.due_day)
            except ValueError:
                # Se o dia não existe no mês (ex: 31/02), usa o último dia do mês
                if today.month in [4, 6, 9, 11]:
                    due_date = date(today.year, today.month, 30)
                elif today.month == 2:
                    is_leap = (today.year % 4 == 0 and today.year % 100 != 0) or (today.year % 400 == 0)
                    due_date = date(today.year, today.month, 29 if is_leap else 28)
                else:
                    due_date = date(today.year, today.month, 28)

            # Se o vencimento deste mês já passou e estamos gerando agora, ou se queremos gerar com antecedência
            existing_invoice = (
                db.query(Invoice)
                .filter(
                    Invoice.subscription_id == sub.id,
                    Invoice.due_date >= date(today.year, today.month, 1),
                    Invoice.due_date <= due_date + timedelta(days=5),
                )
                .first()
            )

            if existing_invoice:
                print(f"ℹ️  [FATURA EXISTENTE] Aluno {student.name} já possui fatura para este ciclo (Venc: {existing_invoice.due_date}, Status: {existing_invoice.status}).", flush=True)
                continue

            # 1. Garantir que o aluno tem ID no Asaas
            if not student.asaas_customer_id:
                try:
                    customer_id = await asaas_service.create_or_get_customer(
                        name=student.name,
                        phone=student.phone,
                        cpf=student.cpf,
                        email=student.email,
                    )
                    student.asaas_customer_id = customer_id
                    db.commit()
                except Exception as e:
                    logger.error(f"Erro ao criar cliente Asaas para {student.name}: {e}")
                    print(f"❌ Erro ao criar cliente no Asaas para {student.name}: {e}", flush=True)
                    continue

            # 2. Criar cobrança no Asaas
            description = f"Mensalidade Jiu-Jitsu ({plan.name}) - {today.strftime('%m/%Y')}"
            try:
                charge_data = await asaas_service.create_pix_charge(
                    customer_id=student.asaas_customer_id,
                    value=plan.price,
                    due_date=due_date.strftime("%Y-%m-%d"),
                    description=description,
                )

                invoice = Invoice(
                    student_id=student.id,
                    subscription_id=sub.id,
                    amount=plan.price,
                    due_date=due_date,
                    status="PENDING",
                    asaas_payment_id=charge_data.get("payment_id"),
                    pix_copy_paste=charge_data.get("pix_copy_paste"),
                    pix_qr_code_url=charge_data.get("pix_qr_code_url"),
                    invoice_url=charge_data.get("invoice_url"),
                )
                db.add(invoice)
                db.commit()
                created_count += 1
                print(f"✅ [FATURA CRIADA] Aluno: {student.name} | Valor: R$ {plan.price:.2f} | Vencimento: {due_date}", flush=True)
            except Exception as e:
                logger.error(f"Falha ao criar cobrança Asaas para {student.name}: {e}")
                print(f"❌ Erro ao gerar cobrança para {student.name}: {e}", flush=True)
                db.rollback()

        return created_count

    @staticmethod
    async def process_billing_reminders(db: Session) -> Dict[str, int]:
        """
        Régua de cobrança automática:
        1. D-3: Faltam 3 dias para o vencimento.
        2. D-0: Vence hoje.
        3. D+3: Venceu há 3 dias e continua pendente.
        """
        today = date.today()
        summary = {"d_minus_3": 0, "d_today": 0, "d_overdue": 0}

        # 1. D - 3 (Lembrete amigável)
        target_date_soon = today + timedelta(days=3)
        invoices_soon = (
            db.query(Invoice)
            .filter(
                Invoice.status == "PENDING",
                Invoice.due_date == target_date_soon,
                Invoice.reminder_sent_soon == False,
            )
            .all()
        )

        for inv in invoices_soon:
            student = inv.student
            try:
                # Parâmetros padrão do template: [Nome, Valor, DataVencimento, PixCopiaECola]
                params = [
                    student.name.split()[0],
                    f"R$ {inv.amount:.2f}",
                    inv.due_date.strftime("%d/%m/%Y"),
                    inv.pix_copy_paste or "Consulte a secretaria",
                ]
                await whatsapp_service.send_template_message(
                    to_phone=student.phone,
                    template_name=settings.WHATSAPP_TEMPLATE_DUE_SOON,
                    parameters=params,
                )
                inv.reminder_sent_soon = True
                
                db.add(MessageLog(
                    student_id=student.id,
                    phone=student.phone,
                    direction="OUTBOUND",
                    message_type="template_due_soon",
                    content=f"Lembrete D-3 enviado para {student.name}",
                ))
                db.commit()
                summary["d_minus_3"] += 1
            except Exception as e:
                logger.error(f"Erro ao enviar lembrete D-3 para {student.name}: {e}")
                db.rollback()

        # 2. D - 0 (Vence hoje)
        invoices_today = (
            db.query(Invoice)
            .filter(
                Invoice.status == "PENDING",
                Invoice.due_date == today,
                Invoice.reminder_sent_today == False,
            )
            .all()
        )

        for inv in invoices_today:
            student = inv.student
            try:
                params = [
                    student.name.split()[0],
                    f"R$ {inv.amount:.2f}",
                    inv.pix_copy_paste or "Consulte a secretaria",
                ]
                await whatsapp_service.send_template_message(
                    to_phone=student.phone,
                    template_name=settings.WHATSAPP_TEMPLATE_DUE_TODAY,
                    parameters=params,
                )
                inv.reminder_sent_today = True

                db.add(MessageLog(
                    student_id=student.id,
                    phone=student.phone,
                    direction="OUTBOUND",
                    message_type="template_due_today",
                    content=f"Lembrete D-0 enviado para {student.name}",
                ))
                db.commit()
                summary["d_today"] += 1
            except Exception as e:
                logger.error(f"Erro ao enviar lembrete D-0 para {student.name}: {e}")
                db.rollback()

        # 3. D + 3 (Cobrança de atraso amigável)
        target_date_overdue = today - timedelta(days=3)
        invoices_overdue = (
            db.query(Invoice)
            .filter(
                Invoice.status.in_(["PENDING", "OVERDUE"]),
                Invoice.due_date <= target_date_overdue,
                Invoice.reminder_sent_overdue == False,
            )
            .all()
        )

        for inv in invoices_overdue:
            student = inv.student
            try:
                inv.status = "OVERDUE"
                params = [
                    student.name.split()[0],
                    f"R$ {inv.amount:.2f}",
                    inv.due_date.strftime("%d/%m/%Y"),
                    inv.pix_copy_paste or "Consulte a secretaria",
                ]
                await whatsapp_service.send_template_message(
                    to_phone=student.phone,
                    template_name=settings.WHATSAPP_TEMPLATE_OVERDUE,
                    parameters=params,
                )
                inv.reminder_sent_overdue = True

                db.add(MessageLog(
                    student_id=student.id,
                    phone=student.phone,
                    direction="OUTBOUND",
                    message_type="template_overdue",
                    content=f"Cobrança de atraso enviada para {student.name}",
                ))
                db.commit()
                summary["d_overdue"] += 1
            except Exception as e:
                logger.error(f"Erro ao enviar cobrança de atraso para {student.name}: {e}")
                db.rollback()

        return summary

    @staticmethod
    async def confirm_payment(db: Session, asaas_payment_id: str) -> bool:
        """
        Recebe a confirmação de pagamento do webhook Asaas, atualiza o banco
        e envia mensagem de agradecimento pelo WhatsApp.
        """
        invoice = (
            db.query(Invoice)
            .filter(Invoice.asaas_payment_id == asaas_payment_id)
            .first()
        )

        if not invoice:
            logger.warning(f"Pagamento recebido para fatura não encontrada: {asaas_payment_id}")
            return False

        if invoice.status == "PAID":
            return True

        invoice.status = "PAID"
        invoice.paid_at = datetime.utcnow()
        student = invoice.student

        db.add(MessageLog(
            student_id=student.id,
            phone=student.phone,
            direction="OUTBOUND",
            message_type="payment_confirmation",
            content=f"Pagamento confirmado para fatura {invoice.id} - R$ {invoice.amount:.2f}",
        ))
        db.commit()

        # Enviar mensagem no WhatsApp confirmando recebimento
        try:
            params = [student.name.split()[0], f"R$ {invoice.amount:.2f}"]
            await whatsapp_service.send_template_message(
                to_phone=student.phone,
                template_name=settings.WHATSAPP_TEMPLATE_PAYMENT_CONFIRMED,
                parameters=params,
            )
        except Exception as e:
            logger.error(f"Erro ao notificar confirmação de pagamento ao aluno {student.name}: {e}")

        return True

