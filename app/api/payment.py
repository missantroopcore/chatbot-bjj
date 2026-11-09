"""Webhook do Asaas (notificações de pagamento)."""
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.database.models import Invoice
from app.services.billing import BillingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/asaas", tags=["Asaas Webhook"])


@router.post("")
async def receive_asaas_event(
    request: Request,
    asaas_access_token: Optional[str] = Header(None, alias="asaas-access-token"),
    db: Session = Depends(get_db),
):
    """
    Eventos tratados:
    - PAYMENT_RECEIVED / PAYMENT_CONFIRMED: dá baixa e agradece pelo WhatsApp.
    - PAYMENT_OVERDUE: marca como vencida.
    - PAYMENT_DELETED / PAYMENT_REFUNDED: marca como cancelada.
    """
    expected = settings.ASAAS_WEBHOOK_TOKEN
    if expected and not expected.startswith("token_secreto"):
        if not asaas_access_token or not hmac.compare_digest(asaas_access_token, expected):
            logger.warning("Webhook Asaas com token inválido rejeitado.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token do webhook inválido")

    payload = await request.json()
    event = payload.get("event")
    payment_id = (payload.get("payment") or {}).get("id")

    logger.info(f"Webhook Asaas: evento={event} payment={payment_id}")
    print(f"\n💵 [WEBHOOK ASAAS] Evento '{event}' | Pagamento {payment_id}", flush=True)

    if not payment_id:
        return {"status": "ignored", "reason": "Sem ID de pagamento"}

    if event in ("PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"):
        confirmed = await BillingService.confirm_payment(db, payment_id)
        return {"status": "processed", "event": event, "confirmed": confirmed}

    invoice = db.query(Invoice).filter(Invoice.asaas_payment_id == payment_id).first()
    if invoice:
        if event == "PAYMENT_OVERDUE" and invoice.status == "PENDING":
            invoice.status = "OVERDUE"
        elif event in ("PAYMENT_DELETED", "PAYMENT_REFUNDED", "PAYMENT_CHARGEBACK_REQUESTED"):
            invoice.status = "CANCELLED"
        db.commit()

    # Sempre 200: o Asaas pausa a fila de webhooks se receber erros repetidos
    return {"status": "received", "event": event}
