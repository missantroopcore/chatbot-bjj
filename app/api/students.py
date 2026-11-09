import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date
from app.database.session import get_db
from app.database.models import Student, Plan, Subscription, Invoice
from app.services.billing import BillingService
from app.services.whatsapp import whatsapp_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Gestão de Alunos e Cobrança"])


# ---------------- Schemas Pydantic ---------------- #
class StudentCreate(BaseModel):
    name: str = Field(..., example="Carlos Gracie")
    phone: str = Field(..., example="5511999998888")
    email: Optional[str] = Field(None, example="carlos@exemplo.com")
    cpf: Optional[str] = Field(None, example="12345678900")
    belt: Optional[str] = Field("Branca", example="Azul")
    notes: Optional[str] = None


class StudentResponse(BaseModel):
    id: int
    name: str
    phone: str
    email: Optional[str]
    cpf: Optional[str]
    belt: str
    is_active: bool
    asaas_customer_id: Optional[str]

    class Config:
        from_attributes = True


class PlanCreate(BaseModel):
    name: str = Field(..., example="Adulto Livre")
    price: float = Field(..., example=160.00)
    description: Optional[str] = Field(None, example="Acesso ilimitado a todas as aulas")


class PlanResponse(BaseModel):
    id: int
    name: str
    price: float
    description: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class SubscriptionCreate(BaseModel):
    student_id: int
    plan_id: int
    due_day: int = Field(..., ge=1, le=31, example=10)


class SubscriptionResponse(BaseModel):
    id: int
    student_id: int
    plan_id: int
    due_day: int
    is_active: bool

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    id: int
    student_id: int
    amount: float
    due_date: date
    status: str
    asaas_payment_id: Optional[str]
    pix_copy_paste: Optional[str]
    invoice_url: Optional[str]

    class Config:
        from_attributes = True


class TestMessageRequest(BaseModel):
    phone: str
    message: str


# ---------------- Endpoints Alunos ---------------- #
@router.post("/students", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
def create_student(student_in: StudentCreate, db: Session = Depends(get_db)):
    clean_phone = student_in.phone.replace("+", "").replace("-", "").replace(" ", "").strip()
    existing = db.query(Student).filter(Student.phone == clean_phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Telefone já cadastrado para outro aluno.")

    student = Student(
        name=student_in.name,
        phone=clean_phone,
        email=student_in.email,
        cpf=student_in.cpf,
        belt=student_in.belt,
        notes=student_in.notes,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@router.get("/students", response_model=List[StudentResponse])
def list_students(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Student).offset(skip).limit(limit).all()


# ---------------- Endpoints Planos ---------------- #
@router.post("/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def create_plan(plan_in: PlanCreate, db: Session = Depends(get_db)):
    plan = Plan(name=plan_in.name, price=plan_in.price, description=plan_in.description)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/plans", response_model=List[PlanResponse])
def list_plans(db: Session = Depends(get_db)):
    return db.query(Plan).filter(Plan.is_active == True).all()


# ---------------- Endpoints Assinaturas ---------------- #
@router.post("/subscriptions", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
def create_subscription(sub_in: SubscriptionCreate, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == sub_in.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Aluno não encontrado.")

    plan = db.query(Plan).filter(Plan.id == sub_in.plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plano não encontrado.")

    sub = Subscription(
        student_id=sub_in.student_id,
        plan_id=sub_in.plan_id,
        due_day=sub_in.due_day,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


# ---------------- Endpoints Faturas e Cobrança ---------------- #
@router.get("/invoices", response_model=List[InvoiceResponse])
def list_invoices(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Invoice)
    if status:
        query = query.filter(Invoice.status == status.upper())
    return query.order_by(Invoice.due_date.desc()).all()


@router.post("/billing/run-now")
async def trigger_billing_cycle(force: bool = False, db: Session = Depends(get_db)):
    """
    Dispara manualmente o ciclo completo de faturamento e régua de cobrança.
    Ideal para testar sem esperar o horário do cron diário.
    Use ?force=true para resetar os lembretes já enviados e re-testar.
    """
    print("\n" + "=" * 65, flush=True)
    print("🥋 [TRIGGER MANUAL] Ciclo de cobrança iniciado via API!", flush=True)
    print("=" * 65, flush=True)

    if force:
        print("⚠️ [MODO FORCE] Resetando lembretes enviados para re-teste...", flush=True)
        for inv in db.query(Invoice).all():
            inv.reminder_sent_today = False
            inv.reminder_sent_soon = False
            inv.reminder_sent_overdue = False
        db.commit()

    total_subs = db.query(Subscription).filter(Subscription.is_active == True).count()
    print(f"📊 Assinaturas ativas no banco de dados: {total_subs}", flush=True)

    created_invoices = await BillingService.generate_monthly_invoices(db)
    reminders = await BillingService.process_billing_reminders(db)

    print(f"🏁 [FIM DO CICLO] Faturas criadas: {created_invoices} | Lembretes enviados: {reminders}", flush=True)
    print("=" * 65 + "\n", flush=True)

    message = f"{created_invoices} nova(s) fatura(s) gerada(s)."
    if total_subs == 0:
        message = "Atenção: Nenhuma assinatura ativa cadastrada ainda. Use POST /api/subscriptions para matricular o aluno no plano antes de gerar cobrança."

    return {
        "status": "success",
        "active_subscriptions": total_subs,
        "invoices_created": created_invoices,
        "reminders_sent": reminders,
        "message": message,
    }


@router.post("/test/send-message")
async def test_send_message(req: TestMessageRequest):
    """Envia uma mensagem de teste para verificar a integração com o WhatsApp."""
    result = await whatsapp_service.send_text_message(req.phone, req.message)
    return {"status": "success", "result": result}
