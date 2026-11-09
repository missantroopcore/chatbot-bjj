import logging
from fastapi import APIRouter, Request, Query, Response, Depends, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.database.session import get_db
from app.database.models import Student, Invoice, MessageLog
from app.services.whatsapp import whatsapp_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/whatsapp", tags=["WhatsApp Webhook"])


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Endpoint de verificação de Webhook exigido pelo Meta for Developers.
    Quando você cadastra a URL no painel da Meta, ela envia um GET com token e challenge.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook Meta verificado com sucesso.")
        return Response(content=hub_challenge, media_type="text/plain", status_code=200)

    logger.warning("Falha na validação do token do Webhook Meta.")
    return Response(content="Verificação falhou", status_code=status.HTTP_403_FORBIDDEN)


@router.post("")
async def receive_whatsapp_message(request: Request, db: Session = Depends(get_db)):
    """
    Recebe eventos de mensagens recebidas e status de envio da Cloud API do WhatsApp.
    """
    data = await request.json()
    logger.debug(f"Payload recebido do WhatsApp: {data}")

    try:
        # Percorrer a estrutura padrão de payload da Meta
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    from_phone = msg.get("from")  # Ex: 5511999998888
                    msg_type = msg.get("type")
                    
                    if msg_type == "text":
                        user_text = msg.get("text", {}).get("body", "").strip()
                        await process_inbound_message(from_phone, user_text, db)
                    elif msg_type == "interactive":
                        # Caso use botões interativos no futuro
                        interactive = msg.get("interactive", {})
                        btn_id = interactive.get("button_reply", {}).get("id") or interactive.get("list_reply", {}).get("id")
                        await process_inbound_message(from_phone, btn_id or "1", db)

    except Exception as e:
        logger.error(f"Erro ao processar mensagem do WhatsApp: {e}", exc_info=True)

    # Sempre retorne HTTP 200 para a Meta não reenviar o webhook repetidamente
    return {"status": "success"}


async def process_inbound_message(phone: str, text: str, db: Session):
    """Lógica de resposta rápida para mensagens dos alunos."""
    clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").strip()
    print(f"\n💬 [WHATSAPP RECEBIDO] Mensagem de {clean_phone}: '{text}'", flush=True)
    
    # Registrar log da mensagem de entrada
    db.add(MessageLog(
        phone=clean_phone,
        direction="INBOUND",
        message_type="text",
        content=text,
    ))
    db.commit()

    # Buscar aluno pelo telefone (tenta com DDI ou sem)
    student = db.query(Student).filter(
        (Student.phone == clean_phone) |
        (Student.phone == clean_phone[-11:]) |
        (Student.phone == f"55{clean_phone}")
    ).first()

    first_name = student.name.split()[0] if student else "Guerreiro(a)"
    lower_text = text.lower()

    # 1. Aluno pedindo Pix / mensalidade / opção 1
    if any(k in lower_text for k in ["pix", "pagar", "pagamento", "mensalidade", "segunda via", "boleto"]) or lower_text == "1":
        if not student:
            reply = "Oss! Não encontramos seu cadastro com este número. Por favor, procure o professor no tatame ou envie seu nome completo."
            await whatsapp_service.send_text_message(clean_phone, reply)
            return

        # Buscar faturas pendentes ou vencidas do aluno
        pending_invoice = (
            db.query(Invoice)
            .filter(
                Invoice.student_id == student.id,
                Invoice.status.in_(["PENDING", "OVERDUE"])
            )
            .order_by(Invoice.due_date.asc())
            .first()
        )

        if pending_invoice:
            due_str = pending_invoice.due_date.strftime("%d/%m/%Y")
            pix_code = pending_invoice.pix_copy_paste or "Não disponível no momento"
            
            msg1 = (
                f"Olá, {first_name}! 🥋\n\n"
                f"Sua mensalidade de *R$ {pending_invoice.amount:.2f}* tem vencimento em *{due_str}*.\n\n"
                f"Abaixo está a sua chave Pix Copia e Cola:"
            )
            await whatsapp_service.send_text_message(clean_phone, msg1)
            # Enviar o Pix em mensagem separada para facilitar o 'copiar' no celular
            await whatsapp_service.send_text_message(clean_phone, pix_code)
        else:
            reply = f"Olá, {first_name}! 🥋 Todas as suas mensalidades estão em dia. Muito obrigado e bons treinos! Oss!"
            await whatsapp_service.send_text_message(clean_phone, reply)
        return

    # 2. Aluno pedindo suporte humano / professor / opção 2
    if any(k in lower_text for k in ["mestre", "professor", "ajuda", "humano", "atendente", "falar"]) or lower_text == "2":
        reply = (
            f"Oss, {first_name}! Encaminhamos o seu contato para a secretaria e o professor. "
            f"Em breve alguém responderá por aqui. Se for urgente, nos procure no horário de treino! 🥋"
        )
        await whatsapp_service.send_text_message(clean_phone, reply)
        return

    # 3. Mensagem padrão / Menu de opções
    menu = (
        f"Olá, {first_name}! Tudo bem? 🥋\n\n"
        f"Sou o assistente virtual da academia de Jiu-Jitsu. Digite o número da opção desejada:\n\n"
        f"1️⃣ - Segunda via de Pix da mensalidade\n"
        f"2️⃣ - Falar com o Mestre / Secretaria\n\n"
        f"Oss!"
    )
    await whatsapp_service.send_text_message(clean_phone, menu)
