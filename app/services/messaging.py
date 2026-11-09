"""Envio de mensagens com registro no banco (MessageLog), usado pelo bot e pela régua de cobrança."""
import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.utils import normalize_phone
from app.database.models import MessageLog
from app.services.whatsapp import whatsapp_service, WhatsAppError

logger = logging.getLogger(__name__)


def _log(db: Session, phone: str, message_type: str, content: str, student_id: Optional[int],
         result: Optional[dict] = None, error: Optional[str] = None) -> MessageLog:
    if error:
        status = "failed"
    elif result and result.get("status") == "simulated":
        status = "simulated"
    else:
        status = "sent"
    entry = MessageLog(
        student_id=student_id,
        phone=normalize_phone(phone),
        direction="OUTBOUND",
        message_type=message_type,
        content=content,
        wamid=whatsapp_service.message_id(result) if result else None,
        status=status,
        error=error,
    )
    db.add(entry)
    db.commit()
    return entry


async def send_text(db: Session, phone: str, body: str, student_id: Optional[int] = None,
                    message_type: str = "text", raise_on_error: bool = False) -> bool:
    try:
        result = await whatsapp_service.send_text_message(phone, body)
        _log(db, phone, message_type, body, student_id, result)
        return True
    except WhatsAppError as err:
        _log(db, phone, message_type, body, student_id, error=str(err))
        if raise_on_error:
            raise
        return False


async def send_buttons(db: Session, phone: str, body: str, buttons: List[Tuple[str, str]],
                       student_id: Optional[int] = None, footer: Optional[str] = None) -> bool:
    try:
        result = await whatsapp_service.send_buttons(phone, body, buttons, footer=footer)
        _log(db, phone, "interactive", body, student_id, result)
        return True
    except WhatsAppError as err:
        # Se o botão falhar por algum motivo, tenta texto puro com as opções numeradas
        _log(db, phone, "interactive", body, student_id, error=str(err))
        options = "\n".join(f"{i}️⃣ {title}" for i, (_, title) in enumerate(buttons, start=1))
        return await send_text(db, phone, f"{body}\n\n{options}", student_id=student_id)


async def send_template(db: Session, phone: str, template_name: str, parameters: List[str],
                        student_id: Optional[int] = None, message_type: Optional[str] = None) -> bool:
    """Envia template. Em falha real, registra e levanta WhatsAppError (a régua NÃO marca como enviado)."""
    content = f"Template {template_name}: {parameters}"
    try:
        result = await whatsapp_service.send_template_message(phone, template_name, parameters)
        _log(db, phone, message_type or f"template:{template_name}", content, student_id, result)
        return True
    except WhatsAppError as err:
        _log(db, phone, message_type or f"template:{template_name}", content, student_id, error=str(err))
        raise
