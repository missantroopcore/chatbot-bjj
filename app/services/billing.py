"""Geração de faturas mensais e régua de cobrança (D-3, D-0, D+3)."""
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import extract
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.utils import today_local, due_date_for, add_months, brl
from app.database.models import Student, Subscription, Invoice
from app.services.asaas import asaas_service
from app.services import messaging
from app.services.whatsapp import WhatsAppError

logger = logging.getLogger(__name__)


def _first_name(student: Student) -> str:
    return (student.name or "").split()[0] if student.name else "aluno(a)"


class BillingService:
    # ------------------------------------------------------------------ #
    # Geração de faturas
    # ------------------------------------------------------------------ #
    @staticmethod
    def candidate_due_dates(sub: Subscription, today: date) -> List[date]:
        """
        Vencimentos que devem ter fatura hoje: o do mês corrente (se a matrícula já existia)
        e o do mês seguinte quando faltam até BILLING_ADVANCE_DAYS dias.
        """
        enrolled = (sub.created_at or datetime.utcnow()).date()
        result = []
        for offset in (0, 1):
            y, m = add_months(today.year, today.month, offset)
            d = due_date_for(y, m, sub.due_day)
            if d < enrolled:
                continue  # não cobra mês anterior à matrícula
            if (d - today).days <= settings.BILLING_ADVANCE_DAYS:
                result.append(d)
        return result

    @staticmethod
    async def create_invoice(db: Session, sub: Subscription, due: date, today: date) -> Optional[Invoice]:
        student, plan = sub.student, sub.plan

        if asaas_service.is_configured() and not student.cpf:
            print(f"⚠️  [SEM CPF] {student.name}: o Asaas exige CPF para emitir Pix. Cadastre o CPF do aluno.", flush=True)
            return None

        if not student.asaas_customer_id:
            try:
                student.asaas_customer_id = await asaas_service.create_or_get_customer(
                    name=student.name, phone=student.phone, cpf=student.cpf, email=student.email,
                )
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Erro ao criar cliente Asaas para {student.name}: {e}")
                print(f"❌ Erro ao criar cliente no Asaas para {student.name}: {e}", flush=True)
                return None

        # O Asaas não aceita vencimento no passado: se o vencimento já passou, cobra para hoje
        charge_due = max(due, today)
        description = f"Mensalidade {settings.ACADEMY_NAME} ({plan.name}) - {due.strftime('%m/%Y')}"
        try:
            charge = await asaas_service.create_pix_charge(
                customer_id=student.asaas_customer_id,
                value=plan.price,
                due_date=charge_due.strftime("%Y-%m-%d"),
                description=description,
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Falha ao criar cobrança Asaas para {student.name}: {e}")
            print(f"❌ Erro ao gerar cobrança para {student.name}: {e}", flush=True)
            return None

        invoice = Invoice(
            student_id=student.id,
            subscription_id=sub.id,
            amount=plan.price,
            due_date=charge_due,
            status="PENDING",
            asaas_payment_id=charge.get("payment_id"),
            pix_copy_paste=charge.get("pix_copy_paste"),
            pix_qr_code_url=charge.get("pix_qr_code_url"),
            invoice_url=charge.get("invoice_url"),
        )
        db.add(invoice)
        db.commit()
        print(f"✅ [FATURA CRIADA] {student.name} | {brl(plan.price)} | Vencimento: {charge_due}", flush=True)
        return invoice

    @staticmethod
    async def generate_monthly_invoices(db: Session, today: Optional[date] = None) -> int:
        today = today or today_local()
        subscriptions = (
            db.query(Subscription)
            .join(Student)
            .filter(Subscription.is_active == True, Student.is_active == True)  # noqa: E712
            .all()
        )
        created = 0
        for sub in subscriptions:
            for due in BillingService.candidate_due_dates(sub, today):
                exists = (
                    db.query(Invoice)
                    .filter(
                        Invoice.subscription_id == sub.id,
                        extract("year", Invoice.due_date) == due.year,
                        extract("month", Invoice.due_date) == due.month,
                    )
                    .first()
                )
                if exists:
                    continue
                if await BillingService.create_invoice(db, sub, due, today):
                    created += 1
        return created

    # ------------------------------------------------------------------ #
    # Régua de cobrança
    # ------------------------------------------------------------------ #
    @staticmethod
    def template_params(kind: str, inv: Invoice) -> List[str]:
        """Parâmetros na MESMA ordem das variáveis {{n}} dos templates (ver scripts/create_whatsapp_templates.py)."""
        name = _first_name(inv.student)
        pix = inv.pix_copy_paste or inv.invoice_url or "Consulte a secretaria"
        due = inv.due_date.strftime("%d/%m/%Y")
        value = brl(inv.amount)
        if kind == "due_soon":
            return [name, value, due, pix]
        if kind == "due_today":
            return [name, value, pix]
        if kind == "overdue":
            return [name, value, due, pix]
        if kind == "confirmed":
            return [name, value]
        raise ValueError(kind)

    @staticmethod
    async def _send_reminder(db: Session, inv: Invoice, kind: str, template: str, flag: str) -> bool:
        student = inv.student
        try:
            await messaging.send_template(
                db, student.phone, template, BillingService.template_params(kind, inv),
                student_id=student.id, message_type=f"billing_{kind}",
            )
        except WhatsAppError as e:
            # Não marca como enviado: tenta de novo na próxima execução
            print(f"❌ [{kind}] Falha ao enviar para {student.name}: {e}", flush=True)
            return False
        setattr(inv, flag, True)
        db.commit()
        print(f"📤 [{kind}] Enviado para {student.name} ({student.phone})", flush=True)
        return True

    @staticmethod
    async def process_billing_reminders(db: Session, today: Optional[date] = None) -> Dict[str, int]:
        today = today or today_local()
        summary = {"d_minus_3": 0, "d_today": 0, "d_overdue": 0, "failed": 0}

        def active(q):
            return q.join(Student).filter(Student.is_active == True)  # noqa: E712

        # D-3: lembrete amigável
        for inv in active(db.query(Invoice)).filter(
            Invoice.status == "PENDING",
            Invoice.due_date == today + timedelta(days=3),
            Invoice.reminder_sent_soon == False,  # noqa: E712
        ).all():
            ok = await BillingService._send_reminder(db, inv, "due_soon", settings.WHATSAPP_TEMPLATE_DUE_SOON, "reminder_sent_soon")
            summary["d_minus_3" if ok else "failed"] += 1

        # D-0: vence hoje
        for inv in active(db.query(Invoice)).filter(
            Invoice.status == "PENDING",
            Invoice.due_date == today,
            Invoice.reminder_sent_today == False,  # noqa: E712
        ).all():
            ok = await BillingService._send_reminder(db, inv, "due_today", settings.WHATSAPP_TEMPLATE_DUE_TODAY, "reminder_sent_today")
            summary["d_today" if ok else "failed"] += 1

        # Marca como vencidas as que passaram do vencimento
        for inv in db.query(Invoice).filter(Invoice.status == "PENDING", Invoice.due_date < today).all():
            inv.status = "OVERDUE"
        db.commit()

        # D+3: cobrança de atraso (uma vez)
        for inv in active(db.query(Invoice)).filter(
            Invoice.status == "OVERDUE",
            Invoice.due_date <= today - timedelta(days=3),
            Invoice.reminder_sent_overdue == False,  # noqa: E712
        ).all():
            ok = await BillingService._send_reminder(db, inv, "overdue", settings.WHATSAPP_TEMPLATE_OVERDUE, "reminder_sent_overdue")
            summary["d_overdue" if ok else "failed"] += 1

        return summary

    # ------------------------------------------------------------------ #
    # Pagamento
    # ------------------------------------------------------------------ #
    @staticmethod
    async def confirm_payment(db: Session, asaas_payment_id: str) -> bool:
        """Webhook Asaas confirmou o pagamento: dá baixa e agradece pelo WhatsApp."""
        invoice = db.query(Invoice).filter(Invoice.asaas_payment_id == asaas_payment_id).first()
        if not invoice:
            logger.warning(f"Pagamento recebido para fatura não encontrada: {asaas_payment_id}")
            return False
        if invoice.status == "PAID":
            return True  # Asaas manda RECEIVED e CONFIRMED; agradece só uma vez

        invoice.status = "PAID"
        invoice.paid_at = datetime.utcnow()
        db.commit()
        student = invoice.student
        print(f"💚 [PAGO] {student.name} pagou {brl(invoice.amount)} (fatura {invoice.id})", flush=True)

        try:
            await messaging.send_template(
                db, student.phone, settings.WHATSAPP_TEMPLATE_PAYMENT_CONFIRMED,
                BillingService.template_params("confirmed", invoice),
                student_id=student.id, message_type="billing_confirmed",
            )
        except WhatsAppError as e:
            logger.error(f"Erro ao notificar pagamento ao aluno {student.name}: {e}")
        return True
