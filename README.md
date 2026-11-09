# 🥋 Chatbot de Cobrança de Mensalidade (Jiu-Jitsu)

Cobrança recorrente e atendimento automatizado para academias de artes marciais via
**WhatsApp Cloud API (Meta)** e **Asaas (Pix)**.

> **Conectar ao WhatsApp:** siga o guia **[docs/WHATSAPP_SETUP.md](docs/WHATSAPP_SETUP.md)**.

---

## 🚀 Funcionalidades

**Régua de cobrança automática** (todo dia às 08:00, no fuso `TIMEZONE`)
- Gera a fatura Pix no Asaas até `BILLING_ADVANCE_DAYS` dias antes do vencimento (inclusive virando o mês).
- **D-3** lembrete · **D-0** vence hoje · **D+3** em atraso, com o Pix Copia e Cola no template.
- Se o WhatsApp recusar o envio, o lembrete **não** é marcado como enviado e tenta de novo no dia seguinte.
- Baixa automática via webhook do Asaas e mensagem de confirmação ao aluno (só uma vez).

**Atendimento no WhatsApp** (menu com botões)
- **Pix da mensalidade**: envia valor, vencimento, link e o código Pix numa mensagem separada para copiar.
- **Minha situação**: lista mensalidades em aberto e total devido.
- **Falar com professor**: pausa o bot para aquele aluno (`HANDOFF_HOURS`), avisa o `ADMIN_PHONE`
  e aparece em `GET /api/handoffs`. O aluno digita *menu* para voltar ao bot.
- **"Já paguei" / comprovante (foto ou PDF)**: explica a confirmação automática e avisa a secretaria.
- Entende texto livre ("me manda o pix", "estou devendo?", "quero falar com o mestre").
- Reconhece o aluno com ou sem o nono dígito, ignora webhooks duplicados, marca mensagens como lidas
  e registra o status de entrega (enviada/entregue/lida/falhou) de cada mensagem.

**Segurança**
- Assinatura `X-Hub-Signature-256` da Meta validada com `WHATSAPP_APP_SECRET`.
- Token do webhook Asaas validado com `ASAAS_WEBHOOK_TOKEN`.
- Endpoints administrativos `/api/*` protegidos por `X-API-Key` (`ADMIN_API_KEY`).
- Com chaves reais configuradas, **nunca** cai em modo simulação silenciosamente (um Pix falso nunca é enviado a um aluno).

---

## 📂 Estrutura

```
app/
├── api/
│   ├── whatsapp.py    # Webhook Meta: verificação, assinatura, mensagens e status de entrega
│   ├── payment.py     # Webhook Asaas: pago, vencido, cancelado/estornado
│   ├── students.py    # API admin: alunos, planos, matrículas, faturas, mensagens, atendimento, testes
│   └── security.py    # X-API-Key
├── core/
│   ├── config.py      # Variáveis de ambiente
│   └── utils.py       # Telefone (nono dígito), datas/fuso, formatação R$
├── database/
│   ├── models.py      # Student, Plan, Subscription, Invoice, MessageLog, Conversation, ProcessedWebhookMessage
│   └── session.py     # Conexão + criação de tabelas e migração leve de colunas
├── services/
│   ├── bot.py         # Conversa: intenções, menu, Pix, situação, atendimento humano
│   ├── messaging.py   # Envio + registro no banco
│   ├── whatsapp.py    # Cliente da Cloud API (texto, botões, templates, lido)
│   ├── asaas.py       # Cliente Asaas (clientes, cobranças Pix, cancelamento)
│   ├── billing.py     # Geração de faturas e régua de cobrança
│   └── scheduler.py   # Agendador diário
└── main.py
scripts/create_whatsapp_templates.py   # Cria os templates na Meta via API
docs/WHATSAPP_SETUP.md                 # Guia de configuração da Meta
tests/                                 # Testes ponta a ponta em modo simulação
```

---

## ⚙️ Instalação

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env           # Linux/Mac: cp .env.example .env
uvicorn app.main:app --reload --port 8000
```
Swagger: **http://localhost:8000/docs** (com `ADMIN_API_KEY` definido, envie o header `X-API-Key` em cada chamada).

Sem chaves preenchidas, tudo roda em **modo simulação**: mensagens e Pix aparecem no terminal.

Rodar os testes:
```bash
pytest -q
```

---

## 🌐 Webhooks

| Serviço | URL | Onde configurar |
|---|---|---|
| WhatsApp (Meta) | `https://SEU-ENDERECO/webhook/whatsapp` | WhatsApp → Configuração → Webhook (campo `messages`) |
| Asaas | `https://SEU-ENDERECO/webhook/asaas` | Integrações → Webhooks (eventos de cobrança) |

No Asaas, defina um **token de autenticação** no cadastro do webhook e coloque o mesmo valor em `ASAAS_WEBHOOK_TOKEN`.
Eventos usados: `PAYMENT_RECEIVED`, `PAYMENT_CONFIRMED`, `PAYMENT_OVERDUE`, `PAYMENT_DELETED`, `PAYMENT_REFUNDED`.

---

## 📝 Templates do WhatsApp

Criados automaticamente por `python -m scripts.create_whatsapp_templates` (categoria **UTILIDADE**, `pt_BR`):

| Template | Variáveis |
|---|---|
| `mensalidade_lembrete_3dias` | {{1}} nome · {{2}} valor · {{3}} vencimento · {{4}} Pix |
| `mensalidade_vencimento_hoje` | {{1}} nome · {{2}} valor · {{3}} Pix |
| `mensalidade_em_atraso` | {{1}} nome · {{2}} valor · {{3}} vencimento · {{4}} Pix |
| `mensalidade_confirmada` | {{1}} nome · {{2}} valor |

Os textos completos estão no script. A Meta não aceita template que termina com variável, por isso o Pix vem no meio do texto.

---

## 🧪 Teste manual do fluxo

1. `POST /api/plans`: cadastre um plano (ex.: "Adulto Livre", 160).
2. `POST /api/students`: aluno com WhatsApp com DDI+DDD (ex.: `5592999998888`) e **CPF** (exigido pelo Asaas).
3. `POST /api/subscriptions`: vincule ao plano com o dia do vencimento.
4. `POST /api/billing/run-now`: gera a fatura e dispara a régua do dia.
5. Mande "oi" para o número do bot e toque em **Pix da mensalidade**.
6. No sandbox do Asaas, confirme o pagamento da cobrança: o aluno recebe a confirmação.

Outros endpoints úteis: `GET /api/messages?failed_only=true`, `GET /api/handoffs`,
`POST /api/handoffs/{phone}/resolve`, `POST /api/whatsapp/reply`, `POST /api/invoices/{id}/mark-paid`,
`POST /api/invoices/{id}/resend`, `POST /api/invoices/{id}/cancel`, `GET /api/whatsapp/status`.

---

## ☁️ Produção

- Servidor **sempre ligado** com HTTPS (o agendador roda dentro da aplicação): VPS, Railway, Render, Fly.io etc.
- Rode com **1 worker** (`uvicorn app.main:app --host 0.0.0.0 --port 8000`) para o agendador não disparar em dobro.
- SQLite precisa de disco persistente; para mais segurança use PostgreSQL em `DATABASE_URL`.
- Preencha `ADMIN_API_KEY`, `WHATSAPP_APP_SECRET` e `ASAAS_WEBHOOK_TOKEN` antes de expor o servidor.
