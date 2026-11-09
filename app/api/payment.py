import logging
from fastapi import APIRouter, Request, Header, HTTPException, Depends, status
from sqlalchemy.orm import Session
from typing import Optional
from app.core.config import settings
from app.database.session import get_db
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
    Recebe notificações de pagamentos e alterações de status do gateway Asaas.
    Eventos principais tratados:
    - PAYMENT_RECEIVED: Pagamento do Pix confirmado pela instituição financeira.
    - PAYMENT_CONFIRMED: Cobrança quitada no Asaas.
    - PAYMENT_OVERDUE: Cobrança venceu e entrou em atraso.
    """
    # Validação do token de segurança do webhook (apenas se for uma chave real de produção)
    if (
        settings.ASAAS_WEBHOOK_TOKEN
        and not settings.ASAAS_WEBHOOK_TOKEN.startswith("token_secreto")
        and asaas_access_token != settings.ASAAS_WEBHOOK_TOKEN
    ):
        logger.warning(f"Tentativa de webhook Asaas com token inválido: {asaas_access_token}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token do webhook inválido")

    payload = await request.json()
    event = payload.get("event")
    payment = payload.get("payment", {})
    payment_id = payment.get("id")

    logger.info(f"Webhook Asaas recebido: Evento='{event}', Payment ID='{payment_id}'")
    print(f"\n💵 [WEBHOOK ASAAS] Evento recebido: '{event}' | ID de Pagamento: {payment_id}", flush=True)

    if not payment_id:
        return {"status": "ignored", "reason": "Sem ID de pagamento"}

    if event in ["PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"]:
        success = await BillingService.confirm_payment(db, payment_id)
        return {"status": "processed", "event": event, "confirmed": success}

    elif event == "PAYMENT_OVERDUE":
        from app.database.models import Invoice
        invoice = db.query(Invoice).filter(Invoice.asaas_payment_id == payment_id).first()
        if invoice and invoice.status != "PAID":
            invoice.status = "OVERDUE"
            db.commit()
            logger.info(f"Fatura {invoice.id} marcada como OVERDUE via webhook Asaas.")

    return {"status": "received", "event": event}
