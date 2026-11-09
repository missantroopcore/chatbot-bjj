# 🥋 Chatbot de Cobrança de Mensalidade (Jiu-Jitsu)

Sistema inteligente de cobrança recorrente e atendimento automatizado para escolas e academias de artes marciais via **WhatsApp Cloud API** e gateway de pagamentos **Asaas**.

---

## 🚀 Funcionalidades

- **Régua de Cobrança Automatizada**:
  - **D - 3**: Lembrete amigável com 3 dias de antecedência contendo o Pix Copia e Cola.
  - **D - 0**: Notificação no dia do vencimento.
  - **D + 3**: Cobrança de atraso amigável com chave Pix atualizada.
- **Integração Asaas (Pix Instantâneo)**:
  - Criação automática de clientes e cobranças Pix.
  - Baixa automática via Webhook assim que o aluno realiza a transferência.
- **Atendimento Receptivo via WhatsApp**:
  - Responde dúvidas comuns de alunos (Segunda via de Pix, status da mensalidade).
  - Transbordo para atendimento humano (Professor/Secretaria).
- **Agendador Integrado (APScheduler)**:
  - Execução diária programada (ex: às 08:00) para varrer faturas e enviar mensagens.
- **Painel de API Swagger interativo**:
  - Cadastro de Alunos, Planos e Assinaturas via `/docs`.

---

## 🛠️ Tecnologias Utilizadas

- **Linguagem**: Python 3.10+
- **Framework Web**: FastAPI
- **Banco de Dados**: SQLite (padrão) ou PostgreSQL via SQLAlchemy
- **Cliente HTTP**: HTTPX (Assíncrono)
- **Agendamento**: APScheduler
- **Mensageria**: WhatsApp Business Cloud API (Meta)
- **Gateway**: Asaas API v3

---

## 📂 Estrutura do Projeto

```
jiujitsu-cobranca-bot/
├── app/
│   ├── api/
│   │   ├── whatsapp.py      # Webhook de verificação e recepção de mensagens Meta
│   │   ├── payment.py       # Webhook de notificação de pagamento Asaas
│   │   └── students.py      # CRUD de alunos, planos, assinaturas e trigger manual
│   ├── core/
│   │   └── config.py        # Configurações e leitura de variáveis de ambiente
│   ├── database/
│   │   ├── session.py       # Conexão e sessão SQLAlchemy
│   │   └── models.py        # Tabelas (Student, Plan, Subscription, Invoice, MessageLog)
│   ├── services/
│   │   ├── asaas.py         # Cliente HTTP Asaas (Pix, clientes, cobranças)
│   │   ├── whatsapp.py      # Cliente HTTP WhatsApp Cloud API (templates e texto)
│   │   ├── billing.py       # Lógica da régua de cobrança e confirmações
│   │   └── scheduler.py     # Agendador diário da rotina de cobrança
│   └── main.py              # Inicialização FastAPI e eventos de ciclo de vida
├── requirements.txt
├── .env.example
└── README.md
```

---

## ⚙️ Passo a Passo de Instalação e Execução

### 1. Criar e Ativar Ambiente Virtual

```bash
cd /home/Johann/jiujitsu-cobranca-bot
python3 -m venv venv
source venv/bin/activate
```

### 2. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 3. Configurar Variáveis de Ambiente

Copie o arquivo de exemplo para `.env`:

```bash
cp .env.example .env
```

Edite o arquivo `.env` preenchendo suas credenciais quando estiver com elas em mãos:
- `WHATSAPP_TOKEN`: Token temporário ou permanente do Meta Graph API.
- `WHATSAPP_PHONE_NUMBER_ID`: ID do número de telefone no painel da Meta.
- `WHATSAPP_VERIFY_TOKEN`: Qualquer texto secreto escolhido por você (ex: `minha_chave_secreta_meta_123`).
- `ASAAS_API_KEY`: Chave gerada no Asaas (Sandbox ou Produção).

> **Dica de Desenvolvimento:** Mesmo antes de preencher as chaves reais, o sistema funciona em **modo de simulação automática**, registrando os disparos e faturas nos logs sem gerar erros de conexão.

### 4. Iniciar o Servidor

```bash
uvicorn app.main:app --reload --port 8000
```

Acesse a documentação interativa em seu navegador:
👉 **http://localhost:8000/docs**

---

## 🌐 Configuração dos Webhooks

Para receber mensagens do WhatsApp e notificações de pagamento do Asaas em sua máquina local durante o desenvolvimento, utilize uma ferramenta de túnel como o **ngrok** ou **localtunnel**:

```bash
ngrok http 8000
```

Você receberá uma URL pública HTTPS (ex: `https://abcd-123.ngrok-free.app`).

### 1. Meta for Developers (WhatsApp Cloud API)
1. Acesse o portal [Meta for Developers](https://developers.facebook.com/).
2. Vá em **WhatsApp > Configuração da API > Webhook**.
3. Clique em **Editar**:
   - **URL de Retorno de Chamada**: `https://seu-dominio.ngrok-free.app/webhook/whatsapp`
   - **Verificar Token**: O mesmo valor definido em `WHATSAPP_VERIFY_TOKEN` no `.env`.
4. Em **Campos do Webhook**, assine o evento **`messages`**.

### 2. Asaas (Notificação de Pagamentos)
1. Acesse o painel do Asaas (Sandbox: [sandbox.asaas.com](https://sandbox.asaas.com/)).
2. Vá em **Configurações da Conta > Integrações > Webhooks para Cobranças**.
3. Adicione a URL: `https://seu-dominio.ngrok-free.app/webhook/asaas`.
4. Ative os eventos:
   - `Cobrança recebida` (`PAYMENT_RECEIVED`)
   - `Cobrança confirmada` (`PAYMENT_CONFIRMED`)
   - `Cobrança vencida` (`PAYMENT_OVERDUE`)

---

## 📝 Templates de Mensagem do WhatsApp (Meta)

Como a régua de cobrança inicia contato com o aluno fora da janela de 24 horas, você deve criar os seguintes templates no **Gerenciador do WhatsApp** (Categoria: **UTILIDADE**):

1. **`mensalidade_lembrete_3dias`**:
   > *"Olá {{1}}, tudo bem?🥋 Passando para lembrar que sua mensalidade de Jiu-Jitsu no valor de {{2}} vence em {{3}}.\n\nChave Pix Copia e Cola:\n{{4}}"*

2. **`mensalidade_vencimento_hoje`**:
   > *"Oss {{1}}! Hoje é o dia de vencimento da sua mensalidade no valor de {{2}}.\n\nChave Pix Copia e Cola:\n{{3}}\n\nNos vemos no tatame!"*

3. **`mensalidade_em_atraso`**:
   > *"Olá {{1}}, notamos que sua mensalidade de {{2}} com vencimento em {{3}} ainda está em aberto.\n\nVocê pode regularizar usando o Pix Copia e Cola abaixo:\n{{4}}\n\nQualquer dúvida, responda a esta mensagem. Oss!"*

4. **`mensalidade_confirmada`**:
   > *"Oss {{1}}! Seu pagamento de {{2}} foi confirmado com sucesso. Bom treino! 🥋"*

---

## 🧪 Como Testar o Fluxo Manualmente

1. Abra o Swagger em **`http://localhost:8000/docs`**.
2. No endpoint `POST /api/plans`, cadastre um plano (ex: "Adulto Livre", R$ 150.00).
3. No endpoint `POST /api/students`, cadastre um aluno com seu número de WhatsApp com DDI e DDD (ex: `5511999998888`).
4. No endpoint `POST /api/subscriptions`, vincule o aluno ao plano e defina o dia do vencimento.
5. Chame o endpoint `POST /api/billing/run-now`:
   - Ele criará a fatura do mês.
   - Gerará o código Pix no Asaas.
   - Enviará a notificação via WhatsApp para o aluno!
