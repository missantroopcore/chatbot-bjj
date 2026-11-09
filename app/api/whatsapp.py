"""Webhook da WhatsApp Cloud API (Meta)."""
import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, Query, Response, BackgroundTasks, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import MessageLog, ProcessedWebhookMessage
from app.services import bot
from app.services.whatsapp import whatsapp_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/whatsapp", tags=["WhatsApp Webhook"])


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Verificação exigida pela Meta ao cadastrar a URL do webhook."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook Meta verificado com sucesso.")
        return Response(content=hub_challenge, media_type="text/plain", status_code=200)

    logger.warning("Falha na validação do token do Webhook Meta.")
    return Response(content="Verificação falhou", status_code=status.HTTP_403_FORBIDDEN)


def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Confere o header X-Hub-Signature-256 (HMAC-SHA256 do corpo com o App Secret)."""
    if not settings.WHATSAPP_APP_SECRET:
        return True  # sem App Secret configurado (desenvolvimento) não há como validar
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


@router.post("")
async def receive_whatsapp_event(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe mensagens e status de entrega. Responde 200 imediatamente e processa em segundo plano,
    pois a Meta reenvia o evento se a resposta demorar.
    """
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        logger.warning("Webhook WhatsApp com assinatura inválida rejeitado.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura inválida")

    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return {"status": "ignored", "reason": "JSON inválido"}

    background_tasks.add_task(process_webhook_payload, data)
    return {"status": "received"}


def _extract_text(msg: dict) -> str:
    msg_type = msg.get("type")
    if msg_type == "text":
        return msg.get("text", {}).get("body", "").strip()
    if msg_type == "interactive":
        it = msg.get("interactive", {})
        reply = it.get("button_reply") or it.get("list_reply") or {}
        return reply.get("id") or reply.get("title") or ""
    if msg_type == "button":  # botão de resposta rápida de um template
        btn = msg.get("button", {})
        return btn.get("payload") or btn.get("text") or ""
    if msg_type in ("image", "document"):
        media = msg.get(msg_type, {})
        return media.get("caption") or media.get("filename") or ""
    return ""


async def process_webhook_payload(data: dict) -> None:
    db = SessionLocal()
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}

                for msg in value.get("messages", []):
                    wamid = msg.get("id")
                    if wamid:
                        try:
                            db.add(ProcessedWebhookMessage(wamid=wamid))
                            db.commit()
                        except IntegrityError:
                            db.rollback()
                            logger.info(f"Mensagem {wamid} já processada (reenvio da Meta). Ignorando.")
                            continue

                    from_phone = msg.get("from", "")
                    msg_type = msg.get("type", "text")
                    text = _extract_text(msg)

                    await whatsapp_service.mark_as_read(wamid)

                    if msg_type not in ("text", "interactive", "button", "image", "document"):
                        # áudio, figurinha, localização etc.: mostra o menu
                        text = ""
                    try:
                        await bot.handle_inbound(
                            db, from_phone, text, msg_type=msg_type, wamid=wamid,
                            profile_name=contacts.get(from_phone),
                        )
                    except Exception as e:  # um erro numa mensagem não pode travar as outras
                        db.rollback()
                        logger.error(f"Erro ao responder {from_phone}: {e}", exc_info=True)

                for st in value.get("statuses", []):
                    _apply_status(db, st)
    except Exception as e:
        logger.error(f"Erro ao processar webhook do WhatsApp: {e}", exc_info=True)
    finally:
        db.close()


def _apply_status(db, st: dict) -> None:
    """Atualiza o status (sent/delivered/read/failed) da mensagem enviada."""
    wamid, new_status = st.get("id"), st.get("status")
    log = db.query(MessageLog).filter(MessageLog.wamid == wamid, MessageLog.direction == "OUTBOUND").first()
    if not log:
        return
    order = {"simulated": 0, "sent": 1, "delivered": 2, "read": 3}
    if new_status == "failed":
        errors = st.get("errors") or [{}]
        err = errors[0]
        log.status = "failed"
        log.error = f"{err.get('code')}: {err.get('title')} - {(err.get('error_data') or {}).get('details', '')}"
        logger.warning(f"Mensagem {wamid} para {log.phone} FALHOU na entrega: {log.error}")
    elif order.get(new_status, -1) > order.get(log.status or "", 0):
        log.status = new_status
    db.commit()
