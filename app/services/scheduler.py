import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.config import settings
from app.database.session import SessionLocal
from app.services.billing import BillingService

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_daily_billing_job():
    """Tarefa diária agendada para gerar cobranças e processar réguas de envio."""
    logger.info("Iniciando rotina diária de faturamento e régua de cobrança...")
    db = SessionLocal()
    try:
        # 1. Gerar cobranças do mês corrente para novas faturas
        created = await BillingService.generate_monthly_invoices(db)
        logger.info(f"Faturas geradas neste ciclo: {created}")

        # 2. Processar réguas (D-3, D-0, D+3)
        summary = await BillingService.process_billing_reminders(db)
        logger.info(f"Lembretes enviados: {summary}")
    except Exception as e:
        logger.error(f"Erro durante a execução do cron de cobrança: {e}", exc_info=True)
    finally:
        db.close()


def start_scheduler():
    """Inicia o agendador de tarefas em segundo plano."""
    trigger = CronTrigger(
        hour=settings.BILLING_RUN_HOUR,
        minute=settings.BILLING_RUN_MINUTE,
    )
    scheduler.add_job(
        run_daily_billing_job,
        trigger=trigger,
        id="daily_billing_job",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Agendador de cobrança iniciado. Execução diária programada para as {settings.BILLING_RUN_HOUR:02d}:{settings.BILLING_RUN_MINUTE:02d}."
    )


def shutdown_scheduler():
    """Finaliza o agendador de tarefas."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Agendador de cobrança finalizado.")
