import asyncio
import hashlib
import hmac
import json
from datetime import date, datetime

from app.core.config import settings
from app.database.models import Invoice, MessageLog, Subscription
from app.services.billing import BillingService
from app.services import messaging
from app.services.whatsapp import WhatsAppError


def wa_payload(from_phone, text, wamid="wamid.1", kind="text"):
    msg = {"from": from_phone, "id": wamid, "timestamp": "1700000000", "type": kind}
    if kind == "text":
        msg["text"] = {"body": text}
    elif kind == "interactive":
        msg["interactive"] = {"type": "button_reply", "button_reply": {"id": text, "title": text}}
    return {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": from_phone, "profile": {"name": "Carlos"}}],
            "messages": [msg],
        }}]}],
    }


def setup_student(client, db, due_day=10, phone="5592988887777"):
    plan = client.post("/api/plans", json={"name": "Adulto", "price": 160}).json()
    student = client.post("/api/students", json={"name": "Carlos Gracie", "phone": phone, "cpf": "12345678900"}).json()
    sub = client.post("/api/subscriptions", json={"student_id": student["id"], "plan_id": plan["id"], "due_day": due_day}).json()
    # matrícula "antiga" para poder cobrar o mês corrente
    s = db.get(Subscription, sub["id"])
    s.created_at = datetime(2020, 1, 1)
    db.commit()
    return student


def outbound(db, phone_like=None):
    q = db.query(MessageLog).filter(MessageLog.direction == "OUTBOUND")
    return q.order_by(MessageLog.id).all()


def test_webhook_verification(client):
    r = client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-test", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    r = client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "42"})
    assert r.status_code == 403


def test_signature_validation(client, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "segredo")
    body = json.dumps(wa_payload("5592988887777", "oi")).encode()
    r = client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=errado"})
    assert r.status_code == 401
    sig = hmac.new(b"segredo", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook/whatsapp", content=body, headers={"X-Hub-Signature-256": f"sha256={sig}",
                                                                "Content-Type": "application/json"})
    assert r.status_code == 200


def test_billing_cycle_and_reminders(client, db):
    setup_student(client, db, due_day=10)
    today = date(2026, 11, 7)  # D-3 do vencimento 10/11
    created = asyncio.run(BillingService.generate_monthly_invoices(db, today=today))
    assert created == 1
    # não duplica
    assert asyncio.run(BillingService.generate_monthly_invoices(db, today=today)) == 0

    summary = asyncio.run(BillingService.process_billing_reminders(db, today=today))
    assert summary["d_minus_3"] == 1
    inv = db.query(Invoice).one()
    assert inv.reminder_sent_soon and inv.due_date == date(2026, 11, 10)

    summary = asyncio.run(BillingService.process_billing_reminders(db, today=date(2026, 11, 10)))
    assert summary["d_today"] == 1
    summary = asyncio.run(BillingService.process_billing_reminders(db, today=date(2026, 11, 13)))
    assert summary["d_overdue"] == 1
    db.refresh(inv)
    assert inv.status == "OVERDUE"


def test_invoice_generated_for_next_month(client, db):
    setup_student(client, db, due_day=2)
    created = asyncio.run(BillingService.generate_monthly_invoices(db, today=date(2026, 11, 28)))
    # nov/02 (atrasada, cobrada para hoje) + dez/02 (dentro dos 5 dias de antecedência)
    dues = sorted(i.due_date for i in db.query(Invoice).all())
    assert created == 2
    assert dues == [date(2026, 11, 28), date(2026, 12, 2)]


def test_reminder_not_marked_when_whatsapp_fails(client, db, monkeypatch):
    setup_student(client, db, due_day=10)
    today = date(2026, 11, 7)
    asyncio.run(BillingService.generate_monthly_invoices(db, today=today))

    async def boom(*a, **k):
        raise WhatsAppError("template não aprovado", code=132001)

    monkeypatch.setattr(messaging.whatsapp_service, "send_template_message", boom)
    summary = asyncio.run(BillingService.process_billing_reminders(db, today=today))
    assert summary["failed"] == 1
    assert db.query(Invoice).one().reminder_sent_soon is False
    assert db.query(MessageLog).filter(MessageLog.status == "failed").count() == 1


def test_inbound_pix_with_phone_without_ninth_digit_and_dedup(client, db):
    setup_student(client, db, due_day=10, phone="5592988887777")
    asyncio.run(BillingService.generate_monthly_invoices(db, today=date(2026, 11, 7)))
    inv = db.query(Invoice).one()

    payload = wa_payload("559288887777", "me manda o pix", wamid="wamid.ABC")  # wa_id SEM o 9
    assert client.post("/webhook/whatsapp", json=payload).status_code == 200
    assert client.post("/webhook/whatsapp", json=payload).status_code == 200  # reenvio da Meta

    inbound = db.query(MessageLog).filter(MessageLog.direction == "INBOUND").all()
    assert len(inbound) == 1 and inbound[0].student_id is not None
    sent = [m.content for m in outbound(db) if not m.message_type.startswith("template")]
    assert any(inv.pix_copy_paste == c for c in sent)


def test_handoff_pauses_bot(client, db):
    setup_student(client, db)
    client.post("/webhook/whatsapp", json=wa_payload("5592988887777", "MENU_HUMAN", wamid="w1", kind="interactive"))
    n = len(outbound(db))
    client.post("/webhook/whatsapp", json=wa_payload("5592988887777", "oi", wamid="w2"))
    assert len(outbound(db)) == n  # bot em silêncio
    assert len(client.get("/api/handoffs").json()) == 1

    client.post("/webhook/whatsapp", json=wa_payload("5592988887777", "menu", wamid="w3"))
    assert len(outbound(db)) == n + 1  # voltou com o menu


def test_asaas_payment_webhook(client, db):
    setup_student(client, db, due_day=10)
    asyncio.run(BillingService.generate_monthly_invoices(db, today=date(2026, 11, 7)))
    inv = db.query(Invoice).one()
    for event in ("PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"):
        r = client.post("/webhook/asaas", json={"event": event, "payment": {"id": inv.asaas_payment_id}})
        assert r.status_code == 200
    db.refresh(inv)
    assert inv.status == "PAID"
    confirmations = [m for m in outbound(db) if m.message_type == "billing_confirmed"]
    assert len(confirmations) == 1  # agradece só uma vez


def test_admin_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "chave")
    assert client.get("/api/students").status_code == 401
    assert client.get("/api/students", headers={"X-API-Key": "chave"}).status_code == 200
    # webhooks continuam abertos para Meta/Asaas
    assert client.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-test",
                                                   "hub.challenge": "1"}).status_code == 200
