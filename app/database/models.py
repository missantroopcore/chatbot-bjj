from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.session import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=False)  # Ex: 5511999998888
    email = Column(String(120), nullable=True)
    cpf = Column(String(14), nullable=True)  # Necessário para emitir cobrança com Pix no Asaas
    belt = Column(String(30), default="Branca")  # Branca, Azul, Roxa, Marrom, Preta, etc.
    notes = Column(Text, nullable=True)
    asaas_customer_id = Column(String(50), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="student", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="student")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # Ex: "Plano Adulto - Livre", "Kids 3x na semana"
    price = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    subscriptions = relationship("Subscription", back_populates="plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    due_day = Column(Integer, nullable=False)  # Dia do vencimento (ex: 5, 10, 15)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
    invoices = relationship("Invoice", back_populates="subscription")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    
    amount = Column(Float, nullable=False)
    due_date = Column(Date, nullable=False, index=True)
    status = Column(String(30), default="PENDING", index=True)  # PENDING, PAID, OVERDUE, CANCELLED
    
    # Dados da transação Asaas
    asaas_payment_id = Column(String(60), unique=True, index=True, nullable=True)
    pix_copy_paste = Column(Text, nullable=True)
    pix_qr_code_url = Column(Text, nullable=True)
    invoice_url = Column(Text, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # Controle de régua de disparos para evitar mensagens repetidas
    reminder_sent_soon = Column(Boolean, default=False)      # Lembrete 3 dias antes
    reminder_sent_today = Column(Boolean, default=False)     # Lembrete no dia do vencimento
    reminder_sent_overdue = Column(Boolean, default=False)   # Cobrança de atraso

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = relationship("Student", back_populates="invoices")
    subscription = relationship("Subscription", back_populates="invoices")


class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    phone = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)  # INBOUND ou OUTBOUND
    message_type = Column(String(20), default="text")
    content = Column(Text, nullable=False)
    wamid = Column(String(128), nullable=True, index=True)  # ID da mensagem na Meta
    status = Column(String(20), nullable=True)  # sent, delivered, read, failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProcessedWebhookMessage(Base):
    """IDs (wamid) de mensagens já processadas. A Meta reenvia webhooks; isso evita respostas duplicadas."""
    __tablename__ = "processed_webhook_messages"

    wamid = Column(String(128), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """Estado da conversa por telefone (ex.: aluno pediu atendimento humano e o bot deve ficar em silêncio)."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    handoff_until = Column(DateTime, nullable=True)  # UTC; enquanto no futuro, o bot não responde
    handoff_reason = Column(Text, nullable=True)
    last_inbound_at = Column(DateTime, nullable=True)  # UTC; janela de 24h da Meta para texto livre
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
