# 📱 Conectando o bot ao WhatsApp (Meta Cloud API): passo a passo

Tempo estimado: 30–60 min de configuração + espera pela aprovação dos templates.

## 1. Criar o app na Meta
1. Acesse <https://developers.facebook.com/apps> → **Criar app** → tipo **Empresa (Business)**.
2. Vincule a um **Portfólio empresarial** (Business Manager). Se não tiver, crie um em <https://business.facebook.com>.
3. No painel do app, adicione o produto **WhatsApp** → **Configurar**.

A Meta cria automaticamente um **número de teste** e uma **conta do WhatsApp Business (WABA)**.

## 2. Copiar os IDs para o `.env`
Em **WhatsApp → Configuração da API (API Setup)**:
| Campo no painel | Variável no `.env` |
|---|---|
| Identificação do número de telefone (Phone number ID) | `WHATSAPP_PHONE_NUMBER_ID` |
| Identificação da conta do WhatsApp Business (WABA ID) | `WHATSAPP_BUSINESS_ACCOUNT_ID` |
| Token de acesso temporário (vale 24h; serve só para o primeiro teste) | `WHATSAPP_TOKEN` |

Em **Configurações do app → Básico**, copie a **Chave secreta do app** para `WHATSAPP_APP_SECRET`.

Ainda em *API Setup*, no campo **Para (To)**, adicione o seu celular como destinatário de teste
(o número de teste só envia para até 5 números cadastrados ali).

## 3. Primeiro teste de envio
> Em contas novas a Meta pode exigir a **verificação do negócio** antes de qualquer envio (erro `131031 Business Account locked`).
> Nesse caso, o recebimento funciona, mas os envios só são liberados depois da verificação (passo 7).

Suba o servidor (`uvicorn app.main:app --reload`) e, em <http://localhost:8000/docs>, chame
`POST /api/test/send-template`:
```json
{ "phone": "5592999998888", "template_name": "hello_world", "language_code": "en_US" }
```
Chegou no seu WhatsApp? A parte de **envio** está funcionando.
`GET /api/whatsapp/status` mostra se cada integração está em modo real ou simulação.

## 4. Token permanente (obrigatório para produção)
O token temporário expira em 24h. Para um token que não expira:
1. <https://business.facebook.com/settings> → **Usuários → Usuários do sistema** → **Adicionar** (função *Administrador*).
2. **Atribuir ativos** (menu "..." → *Assign assets*):
   - **Apps** → o seu app → *Manage app* (acesso total);
   - **Messaging accounts → Linked accounts** → a conta cujo ID é o `WHATSAPP_BUSINESS_ACCOUNT_ID` → *Everything*.
   > ⚠️ No painel novo da Meta, a WABA aparece em **Messaging accounts**, não em "WhatsApp accounts".
   > Se atribuir só "WhatsApp accounts", a API responde `código 100/33 ... does not exist ... missing permissions`.
3. **Gerar novo token** → escolha o app → validade **Nunca** → permissões
   `whatsapp_business_messaging` e `whatsapp_business_management`.
4. Cole em `WHATSAPP_TOKEN` e reinicie o servidor.

## 5. Webhook (receber mensagens dos alunos)
A Meta precisa de uma URL **HTTPS pública**. Em desenvolvimento use o ngrok:
```bash
ngrok http 8000
```
Em **WhatsApp → Configuração (Configuration) → Webhook → Editar**:
- **URL de retorno de chamada**: `https://SEU-ENDERECO/webhook/whatsapp`
- **Token de verificação**: o mesmo valor de `WHATSAPP_VERIFY_TOKEN`
- Clique em **Verificar e salvar**, depois em **Gerenciar** e assine o campo **`messages`**.

Teste: mande "oi" do seu celular para o número do bot. Ele deve responder com o menu de botões.

> Se a URL do ngrok mudar (plano grátis muda a cada reinício), atualize no painel.

## 6. Criar os templates de cobrança
Toda mensagem que **o bot inicia** (lembretes D-3, D-0, D+3 e confirmação de pagamento) precisa ser um
template aprovado. Com `WHATSAPP_TOKEN` e `WHATSAPP_BUSINESS_ACCOUNT_ID` no `.env`:
```bash
python -m scripts.create_whatsapp_templates           # cria os 4 templates (categoria UTILIDADE)
python -m scripts.create_whatsapp_templates --status  # acompanha a aprovação
```
Quando todos estiverem **APPROVED**, rode `POST /api/billing/run-now` para testar a régua.

Os templates já vêm com os botões **"Já paguei"** e **"Falar com professor"**, que o bot entende.

## 7. Colocar o número real da academia
1. **WhatsApp → Configuração da API → Adicionar número de telefone**.
2. O número **não pode estar em uso** no app WhatsApp/WhatsApp Business do celular.
   Use um chip novo ou apague a conta do app nesse número antes.
3. Confirme por SMS/ligação e aguarde a aprovação do **nome de exibição**.
4. Troque `WHATSAPP_PHONE_NUMBER_ID` pelo ID do novo número.
5. Adicione uma forma de pagamento em **Configurações de pagamento** da WABA: a Meta cobra por
   template enviado (as respostas dentro da janela de 24h após o aluno escrever não são cobradas como template).
6. Faça a **verificação da empresa** no Business Manager para aumentar o limite diário de conversas.

## 8. Regras da Meta que o bot já respeita
- **Janela de 24h**: texto livre só pode ser enviado até 24h depois da última mensagem do aluno; fora dela, apenas templates.
  Por isso a régua usa templates e o menu/Pix sob demanda usa texto.
- **Nono dígito**: o WhatsApp às vezes entrega o número sem o 9 (ex.: `559288887777`). O bot encontra o aluno nos dois formatos.
- **Reenvios do webhook**: a Meta pode mandar o mesmo evento mais de uma vez; o bot ignora duplicados.
- **Assinatura**: com `WHATSAPP_APP_SECRET` preenchido, requisições falsas no webhook são recusadas.

## Erros comuns
| Erro | Causa / solução |
|---|---|
| `131030` | Destinatário não está na lista de teste. Adicione em *API Setup → To*. |
| `131047` | Janela de 24h fechada. Só templates podem ser enviados. |
| `132001` | Template inexistente, não aprovado, ou idioma diferente de `pt_BR`. |
| `132000` | Número de variáveis diferente do template aprovado. |
| `190` | Token expirado/inválido. Gere o token permanente (passo 4). |
| `131031` | Conta bloqueada para envio: faça a verificação do negócio no Business Manager. |
| `100` / subcódigo `33` | O token não tem acesso à WABA: atribua a conta em *Messaging accounts* ao usuário do sistema. |
| Webhook não verifica | `WHATSAPP_VERIFY_TOKEN` diferente do painel, ou URL não é HTTPS pública. |
| Bot não responde | Campo `messages` não assinado no webhook, ou assinatura inválida (confira `WHATSAPP_APP_SECRET`). |
