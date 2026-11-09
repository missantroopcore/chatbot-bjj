"""Cliente da WhatsApp Business Cloud API (Meta)."""
import logging
import re
from typing import List, Optional, Dict, Any, Tuple

import httpx

from app.core.config import settings
from app.core.utils import normalize_phone

logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    """Falha real ao falar com a Meta. Quem chama decide o que fazer (ex.: não marcar lembrete como enviado)."""

    def __init__(self, message: str, code: Optional[int] = None, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


# Códigos de erro mais comuns da Cloud API, com dica em português
META_ERROR_HINTS = {
    131047: "Fora da janela de 24h: só é possível enviar TEMPLATE para este contato.",
    131026: "Número não tem WhatsApp ou não pode receber mensagens.",
    131030: "Número não está na lista de destinatários de teste (adicione-o no painel da Meta).",
    132000: "Quantidade de parâmetros diferente do template aprovado.",
    132001: "Template não existe ou ainda não foi aprovado neste idioma.",
    132012: "Formato de parâmetro inválido para o template.",
    190: "Token de acesso inválido ou expirado. Gere um token permanente (System User).",
    131056: "Muitas mensagens para o mesmo número em pouco tempo (rate limit).",
}


def _clean_template_param(value: Any) -> str:
    """A Meta rejeita parâmetros com quebra de linha, tab ou mais de 4 espaços seguidos."""
    text = str(value).replace("\n", " ").replace("\t", " ")
    text = re.sub(r" {4,}", "   ", text).strip()
    return text or "-"


class WhatsAppService:
    def __init__(self):
        self.timeout = 15.0

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }

    def is_configured(self) -> bool:
        """Verifica se as credenciais do WhatsApp são reais e não placeholders."""
        token = (settings.WHATSAPP_TOKEN or "").strip()
        phone_id = (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
        if not token or not phone_id:
            return False
        dummy_markers = ["SIMULATED", "...", "seu_token"]
        return not any(m in token for m in dummy_markers) and phone_id != "100000000000001"

    # ------------------------------------------------------------------ #
    async def _post(self, payload: Dict[str, Any], summary: str) -> Dict[str, Any]:
        if not self.is_configured():
            print("\n" + "-" * 50, flush=True)
            print("📱 [SIMULAÇÃO WHATSAPP]", flush=True)
            print(summary, flush=True)
            print("-" * 50 + "\n", flush=True)
            return {"status": "simulated", "messages": [{"id": None}]}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(settings.whatsapp_api_url, json=payload, headers=self.headers)
        except httpx.HTTPError as err:
            raise WhatsAppError(f"Erro de rede ao chamar a Meta: {err}") from err

        if response.is_success:
            return response.json()

        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {"message": response.text}
        code = error.get("code")
        hint = META_ERROR_HINTS.get(code, "")
        detail = (error.get("error_data") or {}).get("details") or error.get("message")
        msg = f"Meta recusou a mensagem (HTTP {response.status_code}, código {code}): {detail}"
        if hint:
            msg += f" | Dica: {hint}"
        logger.error(msg)
        raise WhatsAppError(msg, code=code, details=error)

    @staticmethod
    def message_id(result: Dict[str, Any]) -> Optional[str]:
        msgs = result.get("messages") or [{}]
        return msgs[0].get("id")

    # ------------------------------------------------------------------ #
    async def send_text_message(self, to_phone: str, message: str) -> Dict[str, Any]:
        """Texto livre. Só funciona dentro da janela de 24h após a última mensagem do aluno."""
        to = normalize_phone(to_phone)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": True, "body": message[:4096]},
        }
        return await self._post(payload, f"   Para: {to}\n   Texto:\n{message}")

    async def send_buttons(self, to_phone: str, body: str, buttons: List[Tuple[str, str]], footer: Optional[str] = None) -> Dict[str, Any]:
        """Mensagem com até 3 botões de resposta rápida. buttons = [(id, título até 20 caracteres)]."""
        to = normalize_phone(to_phone)
        interactive: Dict[str, Any] = {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                    for bid, title in buttons[:3]
                ]
            },
        }
        if footer:
            interactive["footer"] = {"text": footer[:60]}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        labels = " | ".join(f"[{t}]" for _, t in buttons)
        return await self._post(payload, f"   Para: {to}\n   Texto:\n{body}\n   Botões: {labels}")

    async def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        parameters: Optional[List[str]] = None,
        language_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Template pré-aprovado pela Meta. Obrigatório para iniciar conversa (fora da janela de 24h)."""
        to = normalize_phone(to_phone)
        params = [_clean_template_param(p) for p in (parameters or [])]
        components = []
        if params:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in params],
            })
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code or settings.WHATSAPP_TEMPLATE_LANGUAGE},
                "components": components,
            },
        }
        return await self._post(payload, f"   Para: {to}\n   Template: '{template_name}'\n   Parâmetros: {params}")

    async def mark_as_read(self, wamid: str) -> None:
        """Mostra os 'tiques azuis' para o aluno. Falha aqui nunca deve quebrar o fluxo."""
        if not wamid or not self.is_configured():
            return
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": wamid}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await client.post(settings.whatsapp_api_url, json=payload, headers=self.headers)
        except httpx.HTTPError as err:
            logger.debug(f"Não foi possível marcar {wamid} como lida: {err}")


whatsapp_service = WhatsAppService()
