from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # Configurações Gerais
    APP_NAME: str = "JiuJitsu Cobrança Bot"
    ACADEMY_NAME: str = "Academia de Jiu-Jitsu"
    ENVIRONMENT: str = "development"
    PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./jiujitsu_bot.db"
    TIMEZONE: str = Field(default="America/Manaus", description="Fuso usado para datas de vencimento e agendador")

    # Chave que protege os endpoints administrativos (/api/*). Envie no header X-API-Key.
    # Vazia = API aberta (aceitável só em desenvolvimento local).
    ADMIN_API_KEY: str = ""

    # Telefone do professor/secretaria (com DDI) avisado quando um aluno pede atendimento humano
    ADMIN_PHONE: str = ""
    # Por quantas horas o bot fica em silêncio depois que o aluno pede atendimento humano
    HANDOFF_HOURS: int = 12

    # WhatsApp Cloud API (Meta)
    WHATSAPP_TOKEN: str = Field(default="EAAG_SIMULATED_TOKEN", description="Token de acesso do Meta Graph API")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="100000000000001", description="ID do número de telefone no WhatsApp Cloud")
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = Field(default="", description="ID da conta WhatsApp Business (WABA) - usado para criar templates")
    WHATSAPP_VERIFY_TOKEN: str = Field(default="sua_chave_secreta_webhook_meta_123", description="Token para validar o webhook no Meta")
    WHATSAPP_APP_SECRET: str = Field(default="", description="App Secret do app Meta - valida a assinatura X-Hub-Signature-256")
    WHATSAPP_API_VERSION: str = "v21.0"
    WHATSAPP_TEMPLATE_LANGUAGE: str = "pt_BR"

    # Nomes dos Templates Meta pré-aprovados
    WHATSAPP_TEMPLATE_DUE_SOON: str = "mensalidade_lembrete_3dias"
    WHATSAPP_TEMPLATE_DUE_TODAY: str = "mensalidade_vencimento_hoje"
    WHATSAPP_TEMPLATE_OVERDUE: str = "mensalidade_em_atraso"
    WHATSAPP_TEMPLATE_PAYMENT_CONFIRMED: str = "mensalidade_confirmada"

    # Gateway Asaas
    ASAAS_API_KEY: str = Field(default="$aact_SIMULATED_KEY", description="Chave de API do Asaas")
    ASAAS_ENVIRONMENT: str = Field(default="sandbox", description="'sandbox' ou 'production'")
    ASAAS_WEBHOOK_TOKEN: Optional[str] = "token_secreto_para_validar_webhook_asaas_123"

    # Régua de cobrança
    BILLING_RUN_HOUR: int = 8
    BILLING_RUN_MINUTE: int = 0
    # Com quantos dias de antecedência a fatura é gerada (>= 3 para o lembrete D-3 funcionar)
    BILLING_ADVANCE_DAYS: int = 5

    @property
    def asaas_base_url(self) -> str:
        if self.ASAAS_ENVIRONMENT.lower() == "production":
            return "https://api.asaas.com/v3"
        return "https://sandbox.asaas.com/api/v3"

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.WHATSAPP_API_VERSION}"

    @property
    def whatsapp_api_url(self) -> str:
        return f"{self.graph_base_url}/{self.WHATSAPP_PHONE_NUMBER_ID}/messages"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
