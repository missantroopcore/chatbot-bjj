"""Lógica de conversa do chatbot (atendimento receptivo no WhatsApp)."""
import logging
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.utils import normalize_phone, phone_variants, brl
from app.database.models import Student, Invoice, MessageLog, Conversation
from app.services import messaging

logger = logging.getLogger(__name__)

# IDs dos botões do menu
BTN_PIX = "MENU_PIX"
BTN_STATUS = "MENU_STATUS"
BTN_HUMAN = "MENU_HUMAN"

MENU_BUTTONS = [
    (BTN_PIX, "Pix da mensalidade"),
    (BTN_STATUS, "Minha situação"),
    (BTN_HUMAN, "Falar c/ professor"),
]

KW_PIX = ["pix", "pagar", "pagamento", "mensalidade", "segunda via", "2a via", "2 via", "boleto", "codigo", "chave", "fatura", "cobranca"]
KW_STATUS = ["situacao", "status", "devendo", "debito", "em dia", "atrasad", "pendente", "quanto devo", "vencimento"]
KW_HUMAN = ["mestre", "professor", "humano", "atendente", "atendimento", "secretaria", "falar com", "pessoa"]
KW_PAID = ["paguei", "ja paguei", "comprovante", "transferi", "fiz o pix", "pago"]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def detect_intent(text: str) -> str:
    """Retorna: pix | status | human | paid | menu."""
    t = _normalize(text)
    if t in ("1", BTN_PIX.lower()):
        return "pix"
    if t in ("2", BTN_STATUS.lower()):
        return "status"
    if t in ("3", BTN_HUMAN.lower()):
        return "human"
    if any(k in t for k in KW_PAID):
        return "paid"
    if any(k in t for k in KW_HUMAN):
        return "human"
    if any(k in t for k in KW_STATUS):
        return "status"
    if any(k in t for k in KW_PIX):
        return "pix"
    return "menu"


def find_student(db: Session, phone: str) -> Optional[Student]:
    return (
        db.query(Student)
        .filter(Student.phone.in_(phone_variants(phone)))
        .order_by(Student.is_active.desc())
        .first()
    )


def _get_conversation(db: Session, phone: str, student: Optional[Student]) -> Conversation:
    conv = db.query(Conversation).filter(Conversation.phone == phone).first()
    if not conv:
        conv = Conversation(phone=phone)
        db.add(conv)
    if student:
        conv.student_id = student.id
    conv.last_inbound_at = datetime.utcnow()
    db.commit()
    return conv


def _open_invoices(db: Session, student: Student):
    return (
        db.query(Invoice)
        .filter(Invoice.student_id == student.id, Invoice.status.in_(["PENDING", "OVERDUE"]))
        .order_by(Invoice.due_date.asc())
        .all()
    )


async def handle_inbound(db: Session, phone: str, text: str, msg_type: str = "text",
                         wamid: Optional[str] = None, profile_name: Optional[str] = None) -> str:
    """
    Processa uma mensagem recebida e responde. Retorna a intenção tratada (útil para testes/logs).
    'phone' é o wa_id enviado pela Meta; respondemos sempre para ele.
    """
    phone = normalize_phone(phone)
    student = find_student(db, phone)

    db.add(MessageLog(
        student_id=student.id if student else None,
        phone=phone,
        direction="INBOUND",
        message_type=msg_type,
        content=text or f"[{msg_type}]",
        wamid=wamid,
        status="received",
    ))
    db.commit()

    conv = _get_conversation(db, phone, student)
    sid = student.id if student else None
    first_name = student.name.split()[0] if student else (profile_name.split()[0] if profile_name else "guerreiro(a)")

    # Comprovante enviado como imagem/documento
    if msg_type in ("image", "document"):
        intent = "paid"
    else:
        intent = detect_intent(text)

    # Atendimento humano em andamento: bot fica em silêncio, exceto se o aluno pedir o menu
    if conv.handoff_until and conv.handoff_until > datetime.utcnow():
        if intent == "menu" and _normalize(text) in ("menu", "bot", "#bot"):
            conv.handoff_until = None
            db.commit()
        else:
            print(f"🤫 [HANDOFF] {phone} em atendimento humano; bot não respondeu.", flush=True)
            return "handoff_silent"

    print(f"\n💬 [WHATSAPP RECEBIDO] {phone} ({first_name}): '{text}' -> intenção: {intent}", flush=True)

    if intent in ("pix", "status") and not student:
        await messaging.send_buttons(
            db, phone,
            f"Oss, {first_name}! Não encontrei nenhum aluno cadastrado com este número de WhatsApp. 🤔\n\n"
            f"Fale com o professor para atualizar seu cadastro.",
            [(BTN_HUMAN, "Falar c/ professor")],
        )
        return "unknown_student"

    if intent == "pix":
        await _reply_pix(db, phone, student, first_name)
    elif intent == "status":
        await _reply_status(db, phone, student, first_name)
    elif intent == "human":
        await _start_handoff(db, phone, conv, student, first_name, reason=text)
    elif intent == "paid":
        await _reply_paid(db, phone, student, first_name, text, msg_type)
    else:
        await messaging.send_buttons(
            db, phone,
            f"Oss, {first_name}! 🥋 Sou o assistente virtual da *{settings.ACADEMY_NAME}*.\n\nComo posso ajudar?",
            MENU_BUTTONS,
            student_id=sid,
            footer="Ou digite: pix, situação ou professor",
        )
    return intent


async def _reply_pix(db: Session, phone: str, student: Student, first_name: str):
    invoices = _open_invoices(db, student)
    if not invoices:
        await messaging.send_text(
            db, phone,
            f"Oss, {first_name}! 🥋 Você não tem nenhuma mensalidade em aberto. Tudo em dia, bons treinos!",
            student_id=student.id,
        )
        return

    inv = invoices[0]
    label = "venceu em" if inv.status == "OVERDUE" else "vence em"
    extra = f"\n\n(Você tem {len(invoices)} mensalidades em aberto; esta é a mais antiga.)" if len(invoices) > 1 else ""
    intro = (
        f"Olá, {first_name}! 🥋\n\n"
        f"Sua mensalidade de *{brl(inv.amount)}* {label} *{inv.due_date.strftime('%d/%m/%Y')}*.{extra}\n\n"
        f"Vou enviar o *Pix Copia e Cola* na próxima mensagem; é só tocar e segurar para copiar."
    )
    if inv.invoice_url:
        intro += f"\n\nSe preferir, pague pelo link: {inv.invoice_url}"
    await messaging.send_text(db, phone, intro, student_id=student.id)

    if inv.pix_copy_paste:
        # Pix sozinho numa mensagem: facilita o "copiar" no celular
        await messaging.send_text(db, phone, inv.pix_copy_paste, student_id=student.id, message_type="pix_code")
    else:
        await messaging.send_text(
            db, phone,
            "O código Pix desta cobrança ainda não está disponível. Use o link acima ou fale com o professor.",
            student_id=student.id,
        )


async def _reply_status(db: Session, phone: str, student: Student, first_name: str):
    invoices = _open_invoices(db, student)
    last_paid = (
        db.query(Invoice)
        .filter(Invoice.student_id == student.id, Invoice.status == "PAID")
        .order_by(Invoice.due_date.desc())
        .first()
    )
    if not invoices:
        body = f"Oss, {first_name}! ✅ Sua situação está *em dia*."
        if last_paid:
            body += f"\nÚltima mensalidade paga: vencimento {last_paid.due_date.strftime('%d/%m/%Y')} ({brl(last_paid.amount)})."
        await messaging.send_text(db, phone, body, student_id=student.id)
        return

    lines = []
    for inv in invoices:
        icon = "🔴 vencida" if inv.status == "OVERDUE" else "🟡 a vencer"
        lines.append(f"• {inv.due_date.strftime('%d/%m/%Y')} — {brl(inv.amount)} ({icon})")
    total = sum(i.amount for i in invoices)
    body = (
        f"Oss, {first_name}! Estas são suas mensalidades em aberto:\n\n" + "\n".join(lines) +
        f"\n\nTotal: *{brl(total)}*"
    )
    await messaging.send_buttons(db, phone, body, [(BTN_PIX, "Receber o Pix"), (BTN_HUMAN, "Falar c/ professor")],
                                 student_id=student.id)


async def _start_handoff(db: Session, phone: str, conv: Conversation, student: Optional[Student],
                         first_name: str, reason: str):
    conv.handoff_until = datetime.utcnow() + timedelta(hours=settings.HANDOFF_HOURS)
    conv.handoff_reason = reason
    db.commit()

    await messaging.send_text(
        db, phone,
        f"Oss, {first_name}! Avisei o professor/secretaria e alguém vai te responder por aqui em breve. 🥋\n\n"
        f"Enquanto isso o assistente automático fica pausado. Para voltar ao menu, digite *menu*.",
        student_id=student.id if student else None,
    )
    await notify_admin(
        db,
        f"🔔 Pedido de atendimento no WhatsApp\n"
        f"Aluno: {student.name if student else 'não cadastrado'}\n"
        f"Telefone: +{phone}\n"
        f"Mensagem: {reason}",
    )


async def _reply_paid(db: Session, phone: str, student: Optional[Student], first_name: str, text: str, msg_type: str):
    await messaging.send_text(
        db, phone,
        f"Obrigado, {first_name}! 🙏 Pagamentos via Pix costumam ser confirmados em poucos segundos, "
        f"e você recebe a confirmação automaticamente por aqui.\n\n"
        f"Se já pagou e não recebeu a confirmação em até 1 hora, digite *professor*.",
        student_id=student.id if student else None,
    )
    if msg_type in ("image", "document"):
        await notify_admin(
            db,
            f"📎 {student.name if student else 'Contato não cadastrado'} (+{phone}) enviou um comprovante/arquivo no WhatsApp.",
        )


async def notify_admin(db: Session, body: str) -> None:
    """
    Avisa o professor/secretaria. Observação: por regra da Meta, texto livre só chega se o
    ADMIN_PHONE tiver mandado mensagem para o número do bot nas últimas 24h. O aviso também
    fica disponível em GET /api/handoffs.
    """
    if not settings.ADMIN_PHONE:
        logger.info(f"ADMIN_PHONE não configurado. Aviso não enviado: {body}")
        return
    ok = await messaging.send_text(db, settings.ADMIN_PHONE, body, message_type="admin_alert")
    if not ok:
        logger.warning("Não foi possível avisar o ADMIN_PHONE (provável janela de 24h fechada). Veja /api/handoffs.")
