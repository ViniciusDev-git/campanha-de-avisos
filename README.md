# Campanha de Avisos

Aplicativo para Windows que transforma uma planilha de títulos vencidos em avisos
individuais de cobrança por **e-mail**, **WhatsApp Web** e **SMS**. Foi pensado
para equipes de cobrança e atendimento sem conhecimento técnico: a janela conduz
o trabalho em etapas (planilha, textos, ensaio, disparo), anda num ritmo
cuidadoso e para sozinha quando algo parece errado.

> **English summary.** *Campanha de Avisos* is a Windows desktop app (Python +
> pywebview) that turns a spreadsheet of overdue accounts into one notice per
> customer, sent by e-mail (Microsoft Graph), WhatsApp Web (browser automation
> through Playwright) and SMS (queue only, no gateway yet). It consolidates rows
> per person, keeps a SQLite ledger so nobody is notified twice, honours a
> do-not-send list, sends only inside a time window and stops safely on any sign
> of trouble. **WhatsApp Web automation may violate WhatsApp's Terms of Service
> and get the number banned; use it only with contacts who opted in, comply with
> data-protection law (LGPD/GDPR) and prefer the official WhatsApp Business API
> in production.** Install with `pip install -r requirements.txt`, copy
> `config.example.toml` to `config.toml`, run `python app.py`; run the tests with
> `pytest tests`. MIT licensed.

---

> [!WARNING]
> **Aviso sobre o WhatsApp.** A automação do WhatsApp Web **pode violar os Termos
> de Serviço do WhatsApp e levar ao bloqueio do número**. O ritmo "conta-gotas"
> reduz o risco, mas não o elimina, e os limites do WhatsApp não são públicos.
>
> - Use **somente com contatos que consentiram** em receber mensagens.
> - Respeite a **LGPD** (Lei 13.709/2018): base legal para o tratamento, finalidade
>   clara, canal de oposição (a lista `nao_enviar.txt` existe para isso) e cuidado
>   com dados de terceiros.
> - Em produção, **prefira a API oficial do WhatsApp Business** (Cloud API).
>
> O canal continua no código por decisão do autor. O uso é de sua inteira
> responsabilidade.

## O que faz

- **Lê a planilha** (.xlsx) com uma linha por título/plano e consolida por pessoa
  (CPF): cada pessoa recebe um aviso só, no contato mais confiável.
- **Retém com motivo** quem não deve receber: valor abaixo do mínimo, vencimento
  depois da data de corte, sem nome, sem nenhum contato válido. Gera um CSV dos
  retidos em `saida/`.
- **Valida contatos**: celular brasileiro com DDD real e nono dígito (número de
  10 dígitos é recusado, sem "chute"), e-mail bem formado, e-mails do domínio da
  própria empresa recusados.
- **Agrupa** quem divide o mesmo celular ou e-mail numa mensagem só, listando
  todos os nomes e inscrições.
- **Nunca mostra valores** nas mensagens: a variável de valor não existe.
- **Fila em SQLite** com estados (pendente, enviado, incerto, sem WhatsApp,
  duplicado, cancelado...). Envio sem confirmação fica "incerto" para uma pessoa
  conferir; nada é reenviado automaticamente.
- **Travas de segurança**: janela de horário e dias, limite diário, lista
  `nao_enviar.txt` relida a cada envio, arquivo `PARAR-<canal>` para parar com
  segurança, proteção contra planilha parcial que cancelaria a campanha.
- **Ensaio** com a lista interna da equipe (dados fictícios), pelo mesmo motor do
  disparo real, sem tocar na fila dos clientes.
- **Relatório** em CSV de tudo o que foi enviado.

## Canais

| Canal | Como envia | Observações |
|---|---|---|
| E-mail | Microsoft Graph (`sendMail`), autenticação de aplicativo (client credentials) | Exige um App Registration no Microsoft Entra ID com a permissão de aplicativo `Mail.Send` e consentimento do administrador. Recomenda-se fortemente uma *ApplicationAccessPolicy* no Exchange Online limitando o app à caixa remetente. O segredo fica no Cofre do Windows (via `keyring`), nunca em arquivo. |
| WhatsApp | WhatsApp Web num Chrome ou Edge local, automatizado com Playwright; sessão salva em `sessao_whatsapp/` (QR Code lido uma vez) | Veja o aviso acima. Ritmos: `contagotas` (recomendado), `prudente`, `padrao`, `acelerado`. |
| SMS | Apenas fila e modelo de texto (limite de 160 caracteres) | Ainda sem gateway: o envio recusa até que um fornecedor seja integrado. |

## Requisitos

- Windows 10 ou 11 (a janela usa WebView2; o envio de WhatsApp usa o Chrome ou o
  Edge já instalados).
- Python 3.11 ou mais novo (testado com 3.12).
- Para o e-mail: um tenant do Microsoft 365 e permissão para registrar um app no
  Entra ID.
- Para gerar o instalador: [Inno Setup 6](https://jrsoftware.org/isinfo.php).

## Instalação

```powershell
git clone https://github.com/ViniciusDev-git/campanha-de-avisos.git
cd campanha-de-avisos
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt        # programa
pip install -r requirements-dev.txt    # + testes e empacotamento
```

O Playwright usa o Chrome ou o Edge da máquina (`channel="chrome"`/`"msedge"`),
então não é preciso rodar `playwright install`.

## Configuração

1. Copie o modelo e ajuste:

   ```powershell
   copy config.example.toml config.toml
   ```

   O `config.toml` está no `.gitignore`. Os principais campos:

   | Seção | Campo | Para quê |
   |---|---|---|
   | `[campanha]` | `empresa` | Nome no topo do e-mail. |
   | | `dominios_internos` | Domínios da sua empresa; e-mails deles no cadastro do cliente são recusados. |
   | | `valor_minimo` | Total vencido abaixo disto fica retido. |
   | | `vencido_ate` | `"automatico"` (até o dia 15 nada do mês atual entra; do dia 16 em diante entra o que venceu do dia 1 ao 15) ou uma data fixa `"AAAA-MM-DD"`. |
   | | `banco`, `mensagens`, `saida`, `nao_enviar`, `parar`, `teste_interno` | Caminhos (relativos à pasta do programa). |
   | `[whatsapp]` | `ritmo`, `conversas_dia`, `janela_inicio`, `janela_fim`, `dias`, `limite_diario` | Ritmo e horário do WhatsApp. |
   | `[email]` | `tenant_id`, `client_id`, `remetente`, `responder_para`, horário e limite | Microsoft Graph. `responder_para` é obrigatório: é para onde vão as respostas dos clientes. |
   | `[sms]` | `gateway` | Reservado. |

   Tudo o que for alterado pela tela **Ajustes** fica em `dados/ajustes.json`, por
   cima do `config.toml`. O segredo do aplicativo de e-mail é gravado pela tela
   Ajustes no Cofre do Windows.

2. Crie a lista do ensaio, `teste_interno.csv` (separador `;`), só com contatos
   da equipe:

   ```csv
   nome;celular;email
   Equipe Exemplo;11912345678;equipe@exemplo.com
   ```

3. Crie `nao_enviar.txt` (um CPF, celular ou e-mail por linha). Pode ficar vazio.

4. Escreva os textos pela própria janela (etapa **Textos**) ou edite
   `mensagens/`. Variáveis disponíveis: `{{primeiro_nome}}`, `{{nome}}`,
   `{{parcelas}}`, `{{numero_inscricao}}`, `{{pendencias}}`, `{{filial}}`. Modelo
   com variável inexistente ou com a marca `PENDENTE_DEFINIR` trava o envio.

### Formato da planilha

Primeira aba do .xlsx, com estas colunas (os nomes podem ser trocados em
`COLUNAS`, no topo de `disparo/planilha.py`):

| Coluna | Conteúdo |
|---|---|
| `ID_Plano` | Número do título/plano (aparece como "Número de Inscrição"). |
| `nome_cliente` | Nome do cliente. |
| `Valor Vencido` | Valor vencido do plano (nunca vai para a mensagem). |
| `Parcelas Vencidas` | Quantidade de parcelas em aberto. |
| `Maior Atraso` | Data do vencimento mais antigo (usada no corte). |
| `fantasia_filiais` | Unidade/filial. |
| `cpf_cliente` | CPF (zeros à esquerda são recuperados). |
| `tel_cliente`, `cel_cliente` | Telefones; o celular tem prioridade. |
| `email_cliente` | E-mail. |

## Como rodar

```powershell
python app.py                 # abre a janela
python app.py --diagnostico   # confere a máquina sem enviar nada (saida/diagnostico.txt)
```

Linha de comando, para a TI:

```powershell
python -m disparo preparar planilha.xlsx      # lê a planilha e monta a fila
python -m disparo status                      # andamento por canal
python -m disparo previa whatsapp --quantos 3 # mensagens montadas, sem enviar
python -m disparo teste email                 # ensaio com a lista interna
python -m disparo enviar whatsapp --confirmar --maximo 5   # piloto
python -m disparo liberar-incertos whatsapp   # devolve os incertos à fila, após conferir
python -m disparo relatorio                   # exporta CSV em saida/
```

Para ver a janela com dados sintéticos e envio falso (nada sai):

```powershell
python tests\demo_janela.py C:\temp\demo-campanha
```

### Gerar o executável e o instalador

```powershell
.\build.ps1
```

O script roda os testes, compila com PyInstaller (`CampanhaDeAvisos.spec`) e gera
o instalador com Inno Setup (`instalador\CampanhaDeAvisos.iss`). Antes do primeiro
build, troque o `AppId` do `.iss` por um GUID seu. O instalador leva o
`config.example.toml` como `config.toml` e modelos vazios de mensagens; nenhum
dado de campanha vai junto.

## Testes

```powershell
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Os testes usam apenas dados fictícios gerados na hora. O
`test_whatsapp_simulado.py` abre um Chrome ou Edge real contra uma página local
que imita o WhatsApp Web; nada é enviado a ninguém.

## Estrutura

```
campanha-de-avisos/
├── app.py                  # ponto de entrada da janela (vira o .exe)
├── disparo/
│   ├── __main__.py         # linha de comando (python -m disparo)
│   ├── ambiente.py         # pastas e carga da configuração
│   ├── planilha.py         # leitura da planilha, validação e consolidação por pessoa
│   ├── fila.py             # fila/ledger em SQLite
│   ├── modelos.py          # textos das mensagens e variáveis
│   ├── motor.py            # laço de envio com travas de segurança
│   ├── ritmo.py            # ritmos e janela de horário
│   ├── operacao.py         # preparar, ensaiar, disparar (usado pela janela e pela CLI)
│   ├── canal_email.py      # canal de e-mail
│   ├── graph_client.py     # cliente do Microsoft Graph
│   ├── canal_whatsapp.py   # canal de WhatsApp Web (Playwright)
│   ├── janela.py           # ponte entre a interface e o Python (pywebview)
│   └── ui/                 # interface HTML/CSS/JS, fonte e ícone
├── mensagens/              # modelos de texto (genéricos)
├── tests/                  # testes (pytest) e demo com dados sintéticos
├── instalador/             # script do Inno Setup e modelos do instalador
├── config.example.toml     # modelo de configuração
├── build.ps1               # testes + PyInstaller + Inno Setup
├── CampanhaDeAvisos.spec   # configuração do PyInstaller
├── DESIGN.md / PRODUCT.md  # decisões de design e de produto
└── requirements*.txt
```

Pastas criadas em uso e ignoradas pelo Git: `dados/` (fila e ajustes),
`saida/` (relatórios e retidos), `sessao_whatsapp/` (sessão do navegador).

## Privacidade

Este repositório não contém dados reais. Não versione planilhas, a pasta
`dados/`, `saida/`, a sessão do WhatsApp nem o `config.toml`: o `.gitignore` já
cobre esses casos. Capturas de tela devem usar a demo com dados sintéticos.

## Licença

[MIT](LICENSE) © 2026 Vinicius Mendes. A fonte Figtree, embutida em
`disparo/ui/fontes/`, é distribuída sob a SIL Open Font License 1.1.
