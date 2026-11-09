"""API administrativa: alunos, planos, matrículas, faturas, mensagens e atendimento."""
import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from app.api.security import require_api_key
from app.core.config import settings
from app.core.utils import normalize_phone, phone_variants, today_local
from app.database.session import get_db
from app.database.models import Student, Plan, Subscription, Invoice, MessageLog, Conversation
from app.services import messaging
from app.services.asaas import asaas_service
from app.services.billing import BillingService
from app.services.whatsapp import whatsapp_service, WhatsAppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Gestão de Alunos e Cobrança"], dependencies=[Depends(require_api_key)])


# ---------------- Schemas ---------------- #
class StudentCreate(BaseModel):
    name: str = Field(..., examples=["Carlos Gracie"])
    phone: str = Field(..., examples=["5511999998888"])
    email: Optional[str] = Field(None, examples=["carlos@exemplo.com"])
    cpf: Optional[str] = Field(None, examples=["12345678900"])
    belt: Optional[str] = Field("Branca", examples=["Azul"])
    notes: Optional[str] = None


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    cpf: Optional[str] = None
    belt: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str
    email: Optional[str]
    cpf: Optional[str]
    belt: Optional[str]
    is_active: bool
    asaas_customer_id: Optional[str]


class PlanCreate(BaseModel):
    name: str = Field(..., examples=["Adulto Livre"])
    price: float = Field(..., gt=0, examples=[160.00])
    description: Optional[str] = Field(None, examples=["Acesso ilimitado a todas as aulas"])


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price: float
    description: Optional[str]
    is_active: bool


class SubscriptionCreate(BaseModel):
    student_id: int
    plan_id: int
    due_day: int = Field(..., ge=1, le=31, examples=[10])


class SubscriptionUpdate(BaseModel):
    plan_id: Optional[int] = None
    due_day: Optional[int] = Field(None, ge=1, le=31)
    is_active: Optional[bool] = None


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: int
    plan_id: int
    due_day: int
    is_active: bool


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: int
    amount: float
    due_date: date
    status: str
    asaas_payment_id: Optional[str]
    pix_copy_paste: Optional[str]
    invoice_url: Optional[str]
    paid_at: Optional[datetime]
    reminder_sent_soon: bool
    reminder_sent_today: bool
    reminder_sent_overdue: bool


class MessageLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: Optional[int]
    phone: str
    direction: str
    message_type: Optional[str]
    content: str
    status: Optional[str]
    error: Optional[str]
    created_at: datetime


class HandoffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    phone: str
    student_id: Optional[int]
    handoff_until: Optional[datetime]
    handoff_reason: Optional[str]
    last_inbound_at: Optional[datetime]


class TestMessageRequest(BaseModel):
    phone: str
    message: str = "Teste de integração do bot da academia 🥋"


class TestTemplateRequest(BaseModel):
    phone: str
    template_name: str = Field("hello_world", description="'hello_world' já vem aprovado em toda conta nova (idioma en_US)")
    parameters: List[str] = []
    language_code: Optional[str] = Field(None, examples=["en_US"])


class ManualPayment(BaseModel):
    note: Optional[str] = Field(None, examples=["Pagou em dinheiro na recepção"])


# ---------------- Alunos ---------------- #
def _get_or_404(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(status_code=404, detail=f"{label} não encontrado(a).")
    return obj


@router.post("/students", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
def create_student(student_in: StudentCreate, db: Session = Depends(get_db)):
    phone = normalize_phone(student_in.phone)
    if len(phone) < 12:
        raise HTTPException(status_code=400, detail="Telefone inválido. Use DDI + DDD + número, ex.: 5592999998888.")
    if db.query(Student).filter(Student.phone.in_(phone_variants(phone))).first():
        raise HTTPException(status_code=400, detail="Telefone já cadastrado para outro aluno.")

    student = Student(
        name=student_in.name.strip(),
        phone=phone,
        email=student_in.email,
        cpf="".join(c for c in (student_in.cpf or "") if c.isdigit()) or None,
        belt=student_in.belt,
        notes=student_in.notes,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@router.get("/students", response_model=List[StudentResponse])
def list_students(active: Optional[bool] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Student)
    if active is not None:
        q = q.filter(Student.is_active == active)
    return q.order_by(Student.name).offset(skip).limit(limit).all()


@router.get("/students/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Student, student_id, "Aluno")


@router.patch("/students/{student_id}", response_model=StudentResponse)
def update_student(student_id: int, data: StudentUpdate, db: Session = Depends(get_db)):
    student = _get_or_404(db, Student, student_id, "Aluno")
    changes = data.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalize_phone(changes["phone"])
    if "cpf" in changes and changes["cpf"]:
        changes["cpf"] = "".join(c for c in changes["cpf"] if c.isdigit())
    for k, v in changes.items():
        setattr(student, k, v)
    db.commit()
    db.refresh(student)
    return student


@router.delete("/students/{student_id}", response_model=StudentResponse)
def deactivate_student(student_id: int, db: Session = Depends(get_db)):
    """Desativa o aluno e suas matrículas (o histórico é mantido). Para de receber cobranças."""
    student = _get_or_404(db, Student, student_id, "Aluno")
    student.is_active = False
    for sub in student.subscriptions:
        sub.is_active = False
    db.commit()
    db.refresh(student)
    return student


# ---------------- Planos ---------------- #
@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(plan_in: PlanCreate, db: Session = Depends(get_db)):
    plan = Plan(name=plan_in.name, price=plan_in.price, description=plan_in.description)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/plans", response_model=List[PlanResponse])
def list_plans(db: Session = Depends(get_db)):
    return db.query(Plan).filter(Plan.is_active == True).all()  # noqa: E712


# ---------------- Matrículas ---------------- #
@router.post("/subscriptions", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
def create_subscription(sub_in: SubscriptionCreate, db: Session = Depends(get_db)):
    _get_or_404(db, Student, sub_in.student_id, "Aluno")
    _get_or_404(db, Plan, sub_in.plan_id, "Plano")
    sub = Subscription(student_id=sub_in.student_id, plan_id=sub_in.plan_id, due_day=sub_in.due_day)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("/subscriptions", response_model=List[SubscriptionResponse])
def list_subscriptions(student_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Subscription)
    if student_id:
        q = q.filter(Subscription.student_id == student_id)
    return q.all()


@router.patch("/subscriptions/{sub_id}", response_model=SubscriptionResponse)
def update_subscription(sub_id: int, data: SubscriptionUpdate, db: Session = Depends(get_db)):
    sub = _get_or_404(db, Subscription, sub_id, "Matrícula")
    changes = data.model_dump(exclude_unset=True)
    if "plan_id" in changes:
        _get_or_404(db, Plan, changes["plan_id"], "Plano")
    for k, v in changes.items():
        setattr(sub, k, v)
    db.commit()
    db.refresh(sub)
    return sub


# ---------------- Faturas ---------------- #
@router.get("/invoices", response_model=List[InvoiceResponse])
def list_invoices(status: Optional[str] = None, student_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Invoice)
    if status:
        q = q.filter(Invoice.status == status.upper())
    if student_id:
        q = q.filter(Invoice.student_id == student_id)
    return q.order_by(Invoice.due_date.desc()).all()


@router.post("/invoices/{invoice_id}/mark-paid", response_model=InvoiceResponse)
async def mark_invoice_paid(invoice_id: int, body: Optional[ManualPayment] = None, db: Session = Depends(get_db)):
    """Baixa manual (pagamento em dinheiro, por exemplo). Envia a confirmação no WhatsApp."""
    inv = _get_or_404(db, Invoice, invoice_id, "Fatura")
    if inv.status == "PAID":
        return inv
    if inv.asaas_payment_id:
        await BillingService.confirm_payment(db, inv.asaas_payment_id)
    else:
        inv.status, inv.paid_at = "PAID", datetime.utcnow()
        db.commit()
    db.refresh(inv)
    return inv


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceResponse)
async def cancel_invoice(invoice_id: int, db: Session = Depends(get_db)):
    inv = _get_or_404(db, Invoice, invoice_id, "Fatura")
    if inv.status == "PAID":
        raise HTTPException(status_code=400, detail="Fatura já paga não pode ser cancelada.")
    try:
        await asaas_service.cancel_payment(inv.asaas_payment_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Não foi possível cancelar no Asaas: {e}")
    inv.status = "CANCELLED"
    db.commit()
    db.refresh(inv)
    return inv


@router.post("/invoices/{invoice_id}/resend")
async def resend_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Reenvia a cobrança ao aluno pelo template adequado (a vencer, vence hoje ou em atraso)."""
    inv = _get_or_404(db, Invoice, invoice_id, "Fatura")
    if inv.status not in ("PENDING", "OVERDUE"):
        raise HTTPException(status_code=400, detail=f"Fatura com status {inv.status} não pode ser cobrada.")
    today = today_local()
    if inv.due_date > today:
        kind, template = "due_soon", settings.WHATSAPP_TEMPLATE_DUE_SOON
    elif inv.due_date == today:
        kind, template = "due_today", settings.WHATSAPP_TEMPLATE_DUE_TODAY
    else:
        kind, template = "overdue", settings.WHATSAPP_TEMPLATE_OVERDUE
    try:
        await messaging.send_template(db, inv.student.phone, template, BillingService.template_params(kind, inv),
                                      student_id=inv.student_id, message_type=f"billing_{kind}_manual")
    except WhatsAppError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "sent", "template": template}


@router.post("/billing/run-now")
async def trigger_billing_cycle(force: bool = False, db: Session = Depends(get_db)):
    """
    Roda agora o ciclo completo (gerar faturas + régua), sem esperar o horário diário.
    ?force=true reseta os lembretes JÁ ENVIADOS das faturas em aberto (só para testes!).
    """
    print("\n" + "=" * 65 + "\n🥋 [TRIGGER MANUAL] Ciclo de cobrança iniciado via API!\n" + "=" * 65, flush=True)
    if force:
        for inv in db.query(Invoice).filter(Invoice.status.in_(["PENDING", "OVERDUE"])).all():
            inv.reminder_sent_today = inv.reminder_sent_soon = inv.reminder_sent_overdue = False
        db.commit()

    total_subs = db.query(Subscription).filter(Subscription.is_active == True).count()  # noqa: E712
    created = await BillingService.generate_monthly_invoices(db)
    reminders = await BillingService.process_billing_reminders(db)
    print(f"🏁 [FIM] Faturas criadas: {created} | Lembretes: {reminders}\n" + "=" * 65, flush=True)

    message = f"{created} nova(s) fatura(s) gerada(s)."
    if total_subs == 0:
        message = "Nenhuma matrícula ativa. Use POST /api/subscriptions antes de gerar cobrança."
    return {
        "status": "success",
        "active_subscriptions": total_subs,
        "invoices_created": created,
        "reminders_sent": reminders,
        "message": message,
    }


# ---------------- Mensagens e atendimento ---------------- #
@router.get("/messages", response_model=List[MessageLogResponse])
def list_messages(phone: Optional[str] = None, student_id: Optional[int] = None, failed_only: bool = False,
                  limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(MessageLog)
    if phone:
        q = q.filter(MessageLog.phone.in_(phone_variants(phone)))
    if student_id:
        q = q.filter(MessageLog.student_id == student_id)
    if failed_only:
        q = q.filter(MessageLog.status == "failed")
    return q.order_by(MessageLog.id.desc()).limit(limit).all()


@router.get("/handoffs", response_model=List[HandoffResponse])
def list_handoffs(db: Session = Depends(get_db)):
    """Alunos que pediram atendimento humano e estão com o bot pausado."""
    return (
        db.query(Conversation)
        .filter(Conversation.handoff_until != None, Conversation.handoff_until > datetime.utcnow())  # noqa: E711
        .order_by(Conversation.handoff_until.desc())
        .all()
    )


@router.post("/handoffs/{phone}/resolve")
def resolve_handoff(phone: str, db: Session = Depends(get_db)):
    """Encerra o atendimento humano: o bot volta a responder esse número."""
    convs = db.query(Conversation).filter(Conversation.phone.in_(phone_variants(phone))).all()
    if not convs:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    for c in convs:
        c.handoff_until = None
    db.commit()
    return {"status": "resolved"}


@router.post("/whatsapp/reply")
async def reply_as_staff(req: TestMessageRequest, db: Session = Depends(get_db)):
    """Responde um aluno como professor/secretaria (texto livre: só dentro da janela de 24h)."""
    try:
        await messaging.send_text(db, req.phone, req.message, message_type="staff_reply", raise_on_error=True)
    except WhatsAppError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "sent"}


# ---------------- Diagnóstico ---------------- #
@router.get("/whatsapp/status")
def whatsapp_status():
    """Mostra se as integrações estão em modo real ou simulação."""
    return {
        "whatsapp_configured": whatsapp_service.is_configured(),
        "webhook_signature_check": bool(settings.WHATSAPP_APP_SECRET),
        "asaas_configured": asaas_service.is_configured(),
        "asaas_environment": settings.ASAAS_ENVIRONMENT,
        "admin_api_protected": bool(settings.ADMIN_API_KEY),
        "timezone": settings.TIMEZONE,
        "templates": {
            "due_soon": settings.WHATSAPP_TEMPLATE_DUE_SOON,
            "due_today": settings.WHATSAPP_TEMPLATE_DUE_TODAY,
            "overdue": settings.WHATSAPP_TEMPLATE_OVERDUE,
            "confirmed": settings.WHATSAPP_TEMPLATE_PAYMENT_CONFIRMED,
        },
    }


@router.post("/test/send-message")
async def test_send_message(req: TestMessageRequest):
    """Texto livre de teste. Na conta nova, o número precisa ter mandado mensagem ao bot nas últimas 24h."""
    try:
        result = await whatsapp_service.send_text_message(req.phone, req.message)
    except WhatsAppError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "success", "result": result}


@router.post("/test/send-template")
async def test_send_template(req: TestTemplateRequest):
    """Teste de template. Use 'hello_world' + language_code 'en_US' antes de aprovar os seus."""
    try:
        result = await whatsapp_service.send_template_message(req.phone, req.template_name, req.parameters,
                                                              language_code=req.language_code)
    except WhatsAppError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"status": "success", "result": result}
