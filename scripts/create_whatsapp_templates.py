"""
Cria (ou consulta) os templates de cobrança na sua conta do WhatsApp Business via Graph API.

Uso (na raiz do projeto, com o .env preenchido):
    python -m scripts.create_whatsapp_templates           # cria os 4 templates
    python -m scripts.create_whatsapp_templates --status  # mostra status de aprovação

Requer no .env: WHATSAPP_TOKEN e WHATSAPP_BUSINESS_ACCOUNT_ID (ID da conta WhatsApp Business,
fica em WhatsApp > Configuração da API no painel da Meta).

Regras da Meta já respeitadas aqui: o texto não pode começar nem terminar com variável,
variáveis não podem ficar coladas e cada template precisa de exemplos.
"""
import sys

import httpx

from app.core.config import settings

PIX_EXEMPLO = "00020101021226820014br.gov.bcb.pix2560pix.asaas.com/qr/cobv/exemplo5204000053039865802BR6304ABCD"

QUICK_REPLIES = {
    "type": "BUTTONS",
    "buttons": [
        {"type": "QUICK_REPLY", "text": "Já paguei"},
        {"type": "QUICK_REPLY", "text": "Falar com professor"},
    ],
}

TEMPLATES = [
    {
        "name": settings.WHATSAPP_TEMPLATE_DUE_SOON,
        "body": (
            "Olá, {{1}}! 🥋 Passando para lembrar que sua mensalidade da academia, no valor de {{2}}, vence em {{3}}.\n\n"
            "Para pagar, copie o código Pix Copia e Cola abaixo e cole no app do seu banco:\n\n"
            "{{4}}\n\n"
            "Se você já pagou, pode desconsiderar esta mensagem. Oss!"
        ),
        "example": ["Carlos", "R$ 160,00", "10/11/2026", PIX_EXEMPLO],
        "buttons": True,
    },
    {
        "name": settings.WHATSAPP_TEMPLATE_DUE_TODAY,
        "body": (
            "Oss, {{1}}! Hoje é o dia do vencimento da sua mensalidade da academia, no valor de {{2}}.\n\n"
            "Código Pix Copia e Cola para pagamento:\n\n"
            "{{3}}\n\n"
            "Se você já pagou, pode desconsiderar. Nos vemos no tatame!"
        ),
        "example": ["Carlos", "R$ 160,00", PIX_EXEMPLO],
        "buttons": True,
    },
    {
        "name": settings.WHATSAPP_TEMPLATE_OVERDUE,
        "body": (
            "Olá, {{1}}, tudo bem? Notamos que sua mensalidade da academia de {{2}}, com vencimento em {{3}}, "
            "ainda está em aberto.\n\n"
            "Você pode regularizar pelo Pix Copia e Cola abaixo:\n\n"
            "{{4}}\n\n"
            "Se já pagou ou precisa conversar, é só responder esta mensagem. Oss!"
        ),
        "example": ["Carlos", "R$ 160,00", "10/11/2026", PIX_EXEMPLO],
        "buttons": True,
    },
    {
        "name": settings.WHATSAPP_TEMPLATE_PAYMENT_CONFIRMED,
        "body": "Oss, {{1}}! Recebemos o pagamento da sua mensalidade no valor de {{2}}. Obrigado e bons treinos! 🥋",
        "example": ["Carlos", "R$ 160,00"],
        "buttons": False,
    },
]


def _check_env():
    token = (settings.WHATSAPP_TOKEN or "").strip()
    if not token or "SIMULATED" in token:
        sys.exit(
            "WHATSAPP_TOKEN está vazio. Abra o arquivo .env e cole o token logo depois do sinal de igual,\n"
            "na mesma linha, sem espaços nem aspas:  WHATSAPP_TOKEN=EAAU...\n"
            "Depois salve o arquivo (Ctrl+S) e rode de novo."
        )
    if not token.startswith("EAA"):
        sys.exit("O WHATSAPP_TOKEN não parece um token da Meta (deveria começar com 'EAA'). Confira o .env.")
    if not settings.WHATSAPP_BUSINESS_ACCOUNT_ID:
        sys.exit("Preencha WHATSAPP_BUSINESS_ACCOUNT_ID no .env antes de rodar este script.")


def _url() -> str:
    return f"{settings.graph_base_url}/{settings.WHATSAPP_BUSINESS_ACCOUNT_ID}/message_templates"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN.strip()}"}


def _print_error(r: httpx.Response) -> None:
    """Mostra a mensagem de erro da Meta de forma legível."""
    try:
        err = r.json().get("error", {})
    except ValueError:
        print(f"HTTP {r.status_code}: {r.text[:500]}")
        return
    print(
        f"HTTP {r.status_code} | código {err.get('code')}/{err.get('error_subcode')} | "
        f"{err.get('error_user_title') or ''} {err.get('error_user_msg') or err.get('message')}"
    )
    if err.get("code") == 190:
        print("Dica: token inválido/expirado ou colado com caracteres a mais. Confira a linha WHATSAPP_TOKEN no .env.")
    elif err.get("code") in (100, 200, 10):
        print("Dica: o token não tem acesso a esta conta do WhatsApp (WABA). Confira as permissões do usuário do sistema.")


def create_all():
    _check_env()
    with httpx.Client(timeout=30) as client:
        for t in TEMPLATES:
            components = [{"type": "BODY", "text": t["body"], "example": {"body_text": [t["example"]]}}]
            if t["buttons"]:
                components.append(QUICK_REPLIES)
            payload = {
                "name": t["name"],
                "language": settings.WHATSAPP_TEMPLATE_LANGUAGE,
                "category": "UTILITY",
                "components": components,
            }
            r = client.post(_url(), json=payload, headers=_headers())
            if r.is_success:
                data = r.json()
                print(f"✅ {t['name']}: criado (status: {data.get('status')}, id: {data.get('id')})")
            else:
                print(f"❌ {t['name']}:", end=" ")
                _print_error(r)
    print("\nA aprovação costuma levar de minutos a algumas horas. Confira com --status.")


def show_status():
    _check_env()
    names = {t["name"] for t in TEMPLATES}
    with httpx.Client(timeout=30) as client:
        r = client.get(_url(), params={"limit": 200, "fields": "name,status,language,category,rejected_reason"},
                       headers=_headers())
        if not r.is_success:
            _print_error(r)
            sys.exit(1)
        found = [t for t in r.json().get("data", []) if t["name"] in names]
    if not found:
        print("Nenhum dos templates de cobrança foi encontrado. Rode o script sem --status para criá-los.")
    for t in found:
        extra = f" | motivo: {t.get('rejected_reason')}" if t.get("status") == "REJECTED" else ""
        print(f"{t['name']:<32} {t['language']:<6} {t['category']:<10} {t['status']}{extra}")


if __name__ == "__main__":
    show_status() if "--status" in sys.argv else create_all()
