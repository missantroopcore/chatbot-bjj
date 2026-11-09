import logging
import uuid
from typing import Dict, Any, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class AsaasError(Exception):
    pass


def _describe(err: httpx.HTTPStatusError) -> str:
    """Mensagem legível do erro do Asaas (ex.: CPF inválido, chave sem permissão)."""
    status_code = err.response.status_code
    try:
        errors = err.response.json().get("errors", [])
        detail = "; ".join(e.get("description", "") for e in errors) or err.response.text
    except ValueError:
        detail = err.response.text
    if status_code == 401:
        detail = "Chave de API do Asaas inválida ou do ambiente errado (sandbox x produção). " + detail
    return f"Asaas HTTP {status_code}: {detail}"


class AsaasService:
    def __init__(self):
        self.base_url = settings.asaas_base_url
        self.headers = {
            "access_token": settings.ASAAS_API_KEY,
            "Content-Type": "application/json",
        }

    def is_configured(self) -> bool:
        """Verifica se a chave de API do Asaas é real e não simulada ou exemplo de .env."""
        key = (settings.ASAAS_API_KEY or "").strip()
        if not key:
            return False
        dummy_markers = ["SIMULATED", "...", "$aact_YTU5YTE0M2M6N2Nm", "sua_chave", "sua_api_key"]
        return not any(marker in key for marker in dummy_markers)

    async def create_or_get_customer(
        self,
        name: str,
        phone: str,
        cpf: Optional[str] = None,
        email: Optional[str] = None,
    ) -> str:
        """
        Cria um cliente no Asaas ou retorna o ID caso já exista.
        Atenção: o Asaas exige CPF/CNPJ do cliente para emitir cobrança.
        """
        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").strip()
        local_phone = clean_phone[2:] if clean_phone.startswith("55") else clean_phone

        if not self.is_configured():
            mock_id = f"cus_simulated_{uuid.uuid4().hex[:8]}"
            print(f"💳 [SIMULAÇÃO ASAAS] Cliente criado no Asaas: {name} (ID: {mock_id})", flush=True)
            return mock_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                clean_cpf = "".join(ch for ch in (cpf or "") if ch.isdigit())
                params = {"cpfCnpj": clean_cpf} if clean_cpf else {"mobilePhone": local_phone}
                resp = await client.get(f"{self.base_url}/customers", params=params, headers=self.headers)
                
                if resp.is_success:
                    data = resp.json()
                    if data.get("data") and len(data["data"]) > 0:
                        return data["data"][0]["id"]

                payload = {
                    "name": name,
                    "mobilePhone": local_phone,
                }
                if clean_cpf:
                    payload["cpfCnpj"] = clean_cpf
                if email:
                    payload["email"] = email

                create_resp = await client.post(
                    f"{self.base_url}/customers",
                    json=payload,
                    headers=self.headers,
                )
                create_resp.raise_for_status()
                customer_data = create_resp.json()
                return customer_data["id"]
        except httpx.HTTPStatusError as err:
            raise AsaasError(_describe(err)) from err

    async def create_pix_charge(
        self,
        customer_id: str,
        value: float,
        due_date: str,  # YYYY-MM-DD
        description: str,
    ) -> Dict[str, Any]:
        """
        Gera uma cobrança via Pix no Asaas e já busca o Pix Copia e Cola.
        """
        if not self.is_configured():
            mock_pay_id = f"pay_simulated_{uuid.uuid4().hex[:8]}"
            mock_pix = f"00020126580014br.gov.bcb.pix0136{uuid.uuid4()}520400005303986540{value:.2f}5802BR5915JiuJitsuSchool6009SaoPaulo62070503***6304"
            print(f"💰 [SIMULAÇÃO ASAAS] Cobrança Pix criada: R$ {value:.2f} para {customer_id} (ID: {mock_pay_id})", flush=True)
            print(f"🔑 [SIMULAÇÃO ASAAS] Pix Copia e Cola gerado: {mock_pix[:40]}...", flush=True)
            return {
                "payment_id": mock_pay_id,
                "invoice_url": f"https://sandbox.asaas.com/i/{mock_pay_id}",
                "pix_copy_paste": mock_pix,
                "pix_qr_code_url": None,
            }

        payload = {
            "customer": customer_id,
            "billingType": "PIX",
            "value": round(value, 2),
            "dueDate": due_date,
            "description": description,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/payments",
                    json=payload,
                    headers=self.headers,
                )
                resp.raise_for_status()
                payment_data = resp.json()
                payment_id = payment_data["id"]
                invoice_url = payment_data.get("invoiceUrl")

                pix_resp = await client.get(
                    f"{self.base_url}/payments/{payment_id}/pixQrCode",
                    headers=self.headers,
                )
                pix_copy_paste = None
                pix_qr_code_url = None

                if pix_resp.is_success:
                    pix_data = pix_resp.json()
                    pix_copy_paste = pix_data.get("payload")
                    pix_qr_code_url = pix_data.get("encodedImage")

                return {
                    "payment_id": payment_id,
                    "invoice_url": invoice_url,
                    "pix_copy_paste": pix_copy_paste,
                    "pix_qr_code_url": pix_qr_code_url,
                }
        except httpx.HTTPStatusError as err:
            raise AsaasError(_describe(err)) from err

    async def cancel_payment(self, payment_id: str) -> None:
        """Remove a cobrança no Asaas (usado ao cancelar uma fatura)."""
        if not self.is_configured() or not payment_id or payment_id.startswith("pay_simulated"):
            return
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(f"{self.base_url}/payments/{payment_id}", headers=self.headers)
                resp.raise_for_status()
        except httpx.HTTPStatusError as err:
            raise AsaasError(_describe(err)) from err


asaas_service = AsaasService()
