import logging
import uuid
from typing import Dict, Any, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


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
        """
        clean_phone = phone.replace("+", "").replace("-", "").replace(" ", "").strip()
        local_phone = clean_phone[2:] if clean_phone.startswith("55") else clean_phone

        if not self.is_configured():
            mock_id = f"cus_simulated_{uuid.uuid4().hex[:8]}"
            print(f"💳 [SIMULAÇÃO ASAAS] Cliente criado no Asaas: {name} (ID: {mock_id})", flush=True)
            return mock_id

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                query_param = f"cpfCnpj={cpf}" if cpf else f"mobilePhone={local_phone}"
                search_url = f"{self.base_url}/customers?{query_param}"
                resp = await client.get(search_url, headers=self.headers)
                
                if resp.is_success:
                    data = resp.json()
                    if data.get("data") and len(data["data"]) > 0:
                        return data["data"][0]["id"]

                payload = {
                    "name": name,
                    "mobilePhone": local_phone,
                }
                if cpf:
                    payload["cpfCnpj"] = cpf.replace(".", "").replace("-", "").strip()
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
            if err.response.status_code == 401:
                mock_id = f"cus_simulated_{uuid.uuid4().hex[:8]}"
                logger.warning(
                    f"[AVISO ASAAS] Chave de API não autorizada (401). Utilizando simulação de cliente: {mock_id}"
                )
                return mock_id
            raise

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
            if err.response.status_code == 401:
                mock_pay_id = f"pay_simulated_{uuid.uuid4().hex[:8]}"
                mock_pix = f"00020126580014br.gov.bcb.pix0136{uuid.uuid4()}520400005303986540{value:.2f}5802BR5915JiuJitsuSchool6009SaoPaulo62070503***6304"
                logger.warning(
                    f"[AVISO ASAAS] Chave de API não autorizada (401). Utilizando cobrança simulada: {mock_pay_id}"
                )
                return {
                    "payment_id": mock_pay_id,
                    "invoice_url": f"https://sandbox.asaas.com/i/{mock_pay_id}",
                    "pix_copy_paste": mock_pix,
                    "pix_qr_code_url": None,
                }
            raise


asaas_service = AsaasService()
