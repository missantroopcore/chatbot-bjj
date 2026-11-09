import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database.session import init_db
from app.api import whatsapp, payment, students
from app.services.scheduler import start_scheduler, shutdown_scheduler
from app.services.whatsapp import whatsapp_service
from app.services.asaas import asaas_service

# Configuração de Logs para garantir exibição no terminal do Uvicorn
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger("jiujitsu_bot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização: criar tabelas do banco de dados
    logger.info("Preparando banco de dados...")
    init_db()

    # Avisos de configuração para não ir para produção pela metade
    if not whatsapp_service.is_configured():
        logger.warning("WhatsApp em MODO SIMULAÇÃO (WHATSAPP_TOKEN/WHATSAPP_PHONE_NUMBER_ID não configurados).")
    elif not settings.WHATSAPP_APP_SECRET:
        logger.warning("WHATSAPP_APP_SECRET vazio: a assinatura do webhook da Meta NÃO está sendo validada.")
    if not asaas_service.is_configured():
        logger.warning("Asaas em MODO SIMULAÇÃO (ASAAS_API_KEY não configurada). Os códigos Pix são falsos.")
    if not settings.ADMIN_API_KEY:
        logger.warning("ADMIN_API_KEY vazio: os endpoints /api/* estão abertos. Defina antes de expor o servidor.")

    # Iniciar agendador diário da régua de cobrança
    start_scheduler()
    logger.info(f"Aplicação '{settings.APP_NAME}' iniciada com sucesso.")

    yield

    # Encerramento
    shutdown_scheduler()
    logger.info("Aplicação finalizada.")


app = FastAPI(
    title=settings.APP_NAME,
    description="Chatbot de Cobrança de Mensalidades para Escola de Jiu-Jitsu com WhatsApp Cloud API e Asaas",
    version="1.0.0",
    lifespan=lifespan,
)

# Configuração de CORS (caso queira conectar um painel web frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro dos Routers
app.include_router(whatsapp.router)
app.include_router(payment.router)
app.include_router(students.router)


@app.get("/", tags=["Health Check"])
def root():
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "docs_url": "/docs",
        "whatsapp_mode": "real" if whatsapp_service.is_configured() else "simulação",
        "asaas_mode": "real" if asaas_service.is_configured() else "simulação",
    }
