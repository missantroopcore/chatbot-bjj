from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # Configurações Gerais
    APP_NAME: str = "JiuJitsu Cobrança Bot"
    ENVIRONMENT: str = "development"
    PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./jiujitsu_bot.db"

    # WhatsApp Cloud API (Meta)
    WHATSAPP_TOKEN: str = Field(default="EAAG_SIMULATED_TOKEN", description="Token de acesso do Meta Graph API")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="100000000000001", description="ID do número de telefone no WhatsApp Cloud")
    WHATSAPP_VERIFY_TOKEN: str = Field(default="sua_chave_secreta_webhook_meta_123", description="Token para validar o webhook no Meta")
    WHATSAPP_API_VERSION: str = "v20.0"

    # Nomes dos Templates Meta pré-aprovados
    WHATSAPP_TEMPLATE_DUE_SOON: str = "mensalidade_lembrete_3dias"
    WHATSAPP_TEMPLATE_DUE_TODAY: str = "mensalidade_vencimento_hoje"
    WHATSAPP_TEMPLATE_OVERDUE: str = "mensalidade_em_atraso"
    WHATSAPP_TEMPLATE_PAYMENT_CONFIRMED: str = "mensalidade_confirmada"

    # Gateway Asaas
    ASAAS_API_KEY: str = Field(default="$aact_SIMULATED_KEY", description="Chave de API do Asaas")
    ASAAS_ENVIRONMENT: str = Field(default="sandbox", description="'sandbox' ou 'production'")
    ASAAS_WEBHOOK_TOKEN: Optional[str] = "token_secreto_para_validar_webhook_asaas_123"

    # Horário de execução diária do agendador (cron)
    BILLING_RUN_HOUR: int = 8
    BILLING_RUN_MINUTE: int = 0

    @property
    def asaas_base_url(self) -> str:
        if self.ASAAS_ENVIRONMENT.lower() == "production":
            return "https://api.asaas.com/v3"
        return "https://sandbox.asaas.com/api/v3"

    @property
    def whatsapp_api_url(self) -> str:
        return f"https://graph.facebook.com/{self.WHATSAPP_API_VERSION}/{self.WHATSAPP_PHONE_NUMBER_ID}/messages"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
