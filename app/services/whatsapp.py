import logging
from typing import List, Optional, Dict, Any
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class WhatsAppService:
    def __init__(self):
        self.api_url = settings.whatsapp_api_url
        self.headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }

    def is_configured(self) -> bool:
        """Verifica se as credenciais do WhatsApp parecem válidas e não são placeholders."""
        token = (settings.WHATSAPP_TOKEN or "").strip()
        phone_id = (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
        if not token or not phone_id:
            return False
        dummy_markers = ["SIMULATED", "...", "EAAG...", "seu_token", "100000000000001"]
        return not any(marker in token for marker in dummy_markers) and phone_id != "100000000000001"

    async def send_text_message(self, to_phone: str, message: str) -> Dict[str, Any]:
        """
        Envia mensagem de texto comum via WhatsApp Cloud API.
        """
        clean_phone = to_phone.replace("+", "").replace("-", "").replace(" ", "").strip()
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }

        if not self.is_configured():
            print("\n" + "-" * 50, flush=True)
            print(f"📱 [SIMULAÇÃO WHATSAPP MENSAGEM]", flush=True)
            print(f"   Destinatário: {clean_phone}", flush=True)
            print(f"   Conteúdo:\n{message}", flush=True)
            print("-" * 50 + "\n", flush=True)
            return {"status": "simulated", "to": clean_phone, "body": message}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, json=payload, headers=self.headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as err:
            logger.warning(
                f"[AVISO WHATSAPP] Falha ao enviar mensagem real para {clean_phone} ({err}). Exibindo na simulação:\n{message}"
            )
            return {"status": "simulated_fallback", "to": clean_phone, "body": message}

    async def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        parameters: Optional[List[str]] = None,
        language_code: str = "pt_BR",
    ) -> Dict[str, Any]:
        """
        Envia mensagem baseada em Template pré-aprovado pela Meta.
        Obrigatório para iniciar conversas ativas de cobrança fora da janela de 24h.
        """
        clean_phone = to_phone.replace("+", "").replace("-", "").replace(" ", "").strip()

        components = []
        if parameters:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in parameters],
            })

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }

        if not self.is_configured():
            print("\n" + "-" * 50, flush=True)
            print(f"📱 [SIMULAÇÃO WHATSAPP TEMPLATE]", flush=True)
            print(f"   Destinatário: {clean_phone}", flush=True)
            print(f"   Template: '{template_name}'", flush=True)
            print(f"   Parâmetros: {parameters}", flush=True)
            print("-" * 50 + "\n", flush=True)
            return {
                "status": "simulated",
                "to": clean_phone,
                "template": template_name,
                "parameters": parameters,
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, json=payload, headers=self.headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as err:
            logger.warning(
                f"[AVISO WHATSAPP TEMPLATE] Falha no envio real ({err}). Exibindo na simulação:\nPara: {clean_phone} | Template: '{template_name}' | Parâmetros: {parameters}"
            )
            return {
                "status": "simulated_fallback",
                "to": clean_phone,
                "template": template_name,
                "parameters": parameters,
            }


whatsapp_service = WhatsAppService()
