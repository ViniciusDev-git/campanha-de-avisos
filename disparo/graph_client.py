"""Cliente do Microsoft Graph para envio pela caixa corporativa.

Autenticação app-only (client credentials): o app tem identidade própria, não
depende de ninguém estar logado e não quebra quando a senha da caixa muda.
Exige, no Entra ID, a permissão de aplicação `Mail.Send` com consentimento do
administrador e — obrigatoriamente — uma ApplicationAccessPolicy no Exchange
Online limitando o app à caixa noreply@. Sem essa política, esta credencial
envia como qualquer caixa da empresa.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path

GRAPH = "https://graph.microsoft.com/v1.0"
ESCOPO = ["https://graph.microsoft.com/.default"]

# O sendMail carrega a mensagem inteira em JSON e o Graph recusa payload acima
# de ~4 MB. Base64 infla o anexo em ~33%, então 3 MB de arquivo é o teto seguro
# para o caminho simples; acima disso o envio usa upload session.
LIMITE_ANEXO_INLINE = 3 * 1024 * 1024
TAMANHO_DO_BLOCO = 5 * 1024 * 1024

_STATUS_TEMPORARIOS = {408, 429, 500, 502, 503, 504}

PERMISSAO_DE_ENVIO = "Mail.Send"


def _permissoes_do_token(token: str) -> list[str]:
    """Permissoes de aplicacao que o token carrega (claim `roles`).

    O token e um JWT: cabecalho.payload.assinatura, cada parte em base64url.
    So o payload interessa e a assinatura nao precisa ser validada — o token
    acabou de chegar do proprio Entra ID por HTTPS, nao veio de terceiro.
    Devolve lista vazia se o formato nao for o esperado; quem chama trata isso
    como "nao sei", nunca como "nao tem permissao".
    """
    import json

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # base64url vem sem preenchimento
        dados = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return []

    papeis = dados.get("roles", [])
    return [str(p) for p in papeis] if isinstance(papeis, list) else []


class ErroDeEnvio(Exception):
    """Falha ao enviar. `permanente` distingue o que não adianta retentar."""

    def __init__(self, mensagem: str, permanente: bool = False, status: int = 0):
        super().__init__(mensagem)
        self.permanente = permanente
        self.status = status


@dataclass
class Anexo:
    nome: str
    conteudo: bytes
    tipo: str = "application/pdf"

    @classmethod
    def de_arquivo(cls, caminho: str | Path) -> "Anexo":
        caminho = Path(caminho)
        return cls(nome=caminho.name, conteudo=caminho.read_bytes())

    @property
    def tamanho(self) -> int:
        return len(self.conteudo)


class GraphClient:
    """Envia e-mails como uma caixa específica do tenant."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        remetente: str,
        responder_para: str = "",
        salvar_em_enviados: bool = True,
        tentativas: int = 3,
        timeout: float = 60.0,
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self._client_secret = client_secret
        self.remetente = remetente
        self.responder_para = responder_para
        self.salvar_em_enviados = salvar_em_enviados
        self.tentativas = max(1, tentativas)
        self.timeout = timeout

        self._app = None
        self._token = ""
        self._token_expira_em = 0.0
        self._http = None

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------

    def _autenticador(self):
        if self._app is None:
            import msal

            self._app = msal.ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self._client_secret,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            )
        return self._app

    def token(self) -> str:
        """Token de aplicação, renovado com 5 minutos de folga.

        O MSAL mantém o próprio cache; a folga evita o caso em que o token vence
        entre a validação e a chegada da requisição ao servidor.
        """
        if self._token and time.monotonic() < self._token_expira_em - 300:
            return self._token

        resposta = self._autenticador().acquire_token_for_client(scopes=ESCOPO)

        if "access_token" not in resposta:
            raise ErroDeEnvio(
                _traduzir_erro_de_token(resposta), permanente=True
            )

        self._token = resposta["access_token"]
        self._token_expira_em = time.monotonic() + float(resposta.get("expires_in", 3600))
        return self._token

    def testar_conexao(self) -> str:
        """Confirma que dá para enviar, antes de começar o lote.

        A verificação é feita pelo próprio token, não por uma chamada extra ao
        Graph. O token app-only traz no claim `roles` exatamente as permissões
        que o administrador consentiu — então ler esse claim prova as três
        coisas que interessam (credencial válida, Mail.Send concedida,
        consentimento dado) sem pedir privilégio nenhum além do necessário.

        A versão anterior fazia `GET /users/{caixa}`, que exige `User.Read.All`
        — permissão de leitura de TODO o diretório, que este app não tem motivo
        para ter. O resultado era um 403 que parecia falta de Mail.Send e mandava
        quem estava configurando procurar o problema no lugar errado.
        """
        papeis = _permissoes_do_token(self.token())

        if papeis and PERMISSAO_DE_ENVIO not in papeis:
            concedidas = ", ".join(sorted(papeis)) or "nenhuma"
            raise ErroDeEnvio(
                f"O aplicativo não tem a permissão {PERMISSAO_DE_ENVIO}. "
                f"Permissões concedidas hoje: {concedidas}. "
                "No Entra ID: Permissões de API > Adicionar permissão > "
                "Microsoft Graph > Permissões de aplicativo > Mail.Send, e "
                "depois 'Conceder consentimento do administrador'.",
                permanente=True,
            )

        if not papeis:
            # Sem o claim não dá para afirmar nada; o envio real dirá.
            return (
                "Autenticado no tenant. Não foi possível ler as permissões do "
                "token — faça um ensaio antes de disparar para clientes."
            )

        nome = self._descrever_caixa()
        return f"{PERMISSAO_DE_ENVIO} concedida. {nome}"

    def _descrever_caixa(self) -> str:
        """Nome da caixa remetente, quando o app tiver permissão para lê-lo.

        É um extra: confirma visualmente que o endereço está certo. Exige
        `User.Read.All`, que a maioria das instalações não concede — e não
        deve mesmo, já que enviar não depende disso.
        """
        try:
            resposta = self._requisitar(
                "GET",
                f"{GRAPH}/users/{self.remetente}?$select=mail,displayName",
            )
            dados = resposta.json()
            nome = dados.get("displayName") or dados.get("mail")
            return f"Caixa: {nome}" if nome else f"Caixa: {self.remetente}"
        except ErroDeEnvio as erro:
            if erro.status in (401, 403):
                return (
                    f"Remetente: {self.remetente} (o nome da caixa não pôde ser "
                    "conferido porque o app não tem User.Read.All — isso não "
                    "impede o envio)."
                )
            if erro.status == 404:
                return (
                    f"ATENÇÃO: a caixa {self.remetente} não foi encontrada no "
                    "tenant. Confira o campo 'Enviar como'."
                )
            return f"Remetente: {self.remetente}"

    # ------------------------------------------------------------------
    # Envio
    # ------------------------------------------------------------------

    def enviar(
        self,
        destinatario: str,
        assunto: str,
        corpo_html: str,
        anexos: list[Anexo] | None = None,
    ) -> str:
        """Envia uma mensagem e devolve o Internet Message-ID, quando disponível.

        Um destinatário por mensagem, sempre. Agrupar clientes em cópia faria um
        cliente ver o e-mail dos outros — incidente de LGPD com dado financeiro.

        O corpo vai como HTML; o Exchange Online deriva a alternativa em texto
        puro na entrega, então não é preciso montar multipart à mão.
        """
        anexos = anexos or []
        grandes = [a for a in anexos if a.tamanho > LIMITE_ANEXO_INLINE]

        if grandes:
            return self._enviar_com_rascunho(destinatario, assunto, corpo_html, anexos)
        return self._enviar_direto(destinatario, assunto, corpo_html, anexos)

    def _enviar_direto(
        self,
        destinatario: str,
        assunto: str,
        corpo_html: str,
        anexos: list[Anexo],
    ) -> str:
        mensagem = self._montar_mensagem(destinatario, assunto, corpo_html)
        mensagem["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": anexo.nome,
                "contentType": anexo.tipo,
                "contentBytes": base64.b64encode(anexo.conteudo).decode("ascii"),
            }
            for anexo in anexos
        ]

        self._requisitar(
            "POST",
            f"{GRAPH}/users/{self.remetente}/sendMail",
            json={
                "message": mensagem,
                "saveToSentItems": self.salvar_em_enviados,
            },
        )
        # O sendMail devolve 202 sem corpo: o Graph aceitou a mensagem e vai
        # entregá-la. Não há Message-ID nesse caminho — a prova de envio fica no
        # ledger local e na cópia em Itens Enviados.
        return ""

    def _enviar_com_rascunho(
        self,
        destinatario: str,
        assunto: str,
        corpo_html: str,
        anexos: list[Anexo],
    ) -> str:
        """Caminho para anexo grande: rascunho, upload em blocos, envio.

        Mais lento e com mais chamadas, então só é usado quando o anexo não cabe
        no payload do sendMail.
        """
        mensagem = self._montar_mensagem(destinatario, assunto, corpo_html)
        rascunho = self._requisitar(
            "POST", f"{GRAPH}/users/{self.remetente}/messages", json=mensagem
        ).json()
        id_mensagem = rascunho["id"]
        message_id = rascunho.get("internetMessageId", "")

        for anexo in anexos:
            if anexo.tamanho > LIMITE_ANEXO_INLINE:
                self._subir_anexo(id_mensagem, anexo)
            else:
                self._requisitar(
                    "POST",
                    f"{GRAPH}/users/{self.remetente}/messages/{id_mensagem}/attachments",
                    json={
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": anexo.nome,
                        "contentType": anexo.tipo,
                        "contentBytes": base64.b64encode(anexo.conteudo).decode("ascii"),
                    },
                )

        self._requisitar(
            "POST", f"{GRAPH}/users/{self.remetente}/messages/{id_mensagem}/send"
        )
        return message_id

    def _subir_anexo(self, id_mensagem: str, anexo: Anexo) -> None:
        sessao = self._requisitar(
            "POST",
            f"{GRAPH}/users/{self.remetente}/messages/{id_mensagem}"
            "/attachments/createUploadSession",
            json={
                "AttachmentItem": {
                    "attachmentType": "file",
                    "name": anexo.nome,
                    "size": anexo.tamanho,
                    "contentType": anexo.tipo,
                }
            },
        ).json()

        url = sessao["uploadUrl"]
        total = anexo.tamanho
        inicio = 0
        while inicio < total:
            fim = min(inicio + TAMANHO_DO_BLOCO, total) - 1
            bloco = anexo.conteudo[inicio : fim + 1]
            # A URL de upload já carrega a própria autorização; mandar o Bearer
            # junto faz o serviço de storage recusar o bloco.
            self._requisitar(
                "PUT",
                url,
                conteudo=bloco,
                cabecalhos={
                    "Content-Range": f"bytes {inicio}-{fim}/{total}",
                    "Content-Length": str(len(bloco)),
                },
                autenticar=False,
            )
            inicio = fim + 1

    def _montar_mensagem(
        self, destinatario: str, assunto: str, corpo_html: str
    ) -> dict:
        mensagem: dict = {
            "subject": assunto,
            "body": {"contentType": "HTML", "content": corpo_html},
            "toRecipients": [{"emailAddress": {"address": destinatario}}],
        }
        if self.responder_para:
            # Sem isto, a resposta do cliente cai em noreply@ e some. Em cobrança
            # o cliente responde: "já paguei", "meu boleto veio errado".
            mensagem["replyTo"] = [
                {"emailAddress": {"address": self.responder_para}}
            ]
        return mensagem

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _cliente_http(self):
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def _requisitar(
        self,
        metodo: str,
        url: str,
        json: dict | None = None,
        conteudo: bytes | None = None,
        cabecalhos: dict | None = None,
        autenticar: bool = True,
    ):
        """Faz a chamada com retentativa em falha temporária.

        Respeita o `Retry-After` do Graph: quando o serviço diz por quanto tempo
        recuar, insistir antes disso só prolonga a limitação.
        """
        import httpx

        finais = dict(cabecalhos or {})
        if autenticar:
            finais["Authorization"] = f"Bearer {self.token()}"

        cliente = self._cliente_http()
        ultimo_erro: ErroDeEnvio | None = None

        for tentativa in range(1, self.tentativas + 1):
            try:
                resposta = cliente.request(
                    metodo, url, json=json, content=conteudo, headers=finais
                )
            except httpx.RequestError as erro:
                ultimo_erro = ErroDeEnvio(f"Falha de rede: {erro}")
                self._recuar(tentativa)
                continue

            if resposta.status_code < 400:
                return resposta

            temporario = resposta.status_code in _STATUS_TEMPORARIOS
            mensagem = _traduzir_erro_http(resposta)
            ultimo_erro = ErroDeEnvio(
                mensagem, permanente=not temporario, status=resposta.status_code
            )
            if not temporario:
                raise ultimo_erro

            espera = _segundos_de_espera(resposta, tentativa)
            if tentativa < self.tentativas:
                time.sleep(espera)

        raise ultimo_erro or ErroDeEnvio("Falha desconhecida no envio.")

    def _recuar(self, tentativa: int) -> None:
        if tentativa < self.tentativas:
            time.sleep(min(2 ** tentativa, 30))

    def fechar(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, *_) -> None:
        self.fechar()


# ----------------------------------------------------------------------
# Tradução de erros
# ----------------------------------------------------------------------


def _segundos_de_espera(resposta, tentativa: int) -> float:
    cabecalho = resposta.headers.get("Retry-After", "")
    if cabecalho:
        try:
            return min(float(cabecalho), 300.0)
        except ValueError:
            pass
    return min(2 ** tentativa, 30)


def _traduzir_erro_de_token(resposta: dict) -> str:
    codigo = resposta.get("error", "")
    descricao = resposta.get("error_description", "")

    if codigo == "invalid_client" or "AADSTS7000215" in descricao:
        return (
            "Client secret inválido ou expirado. Gere um novo segredo no App "
            "Registration e regrave-o na tela Ajustes. "
            f"[{codigo}]"
        )
    if "AADSTS700016" in descricao or codigo == "unauthorized_client":
        return (
            "Client ID não encontrado neste tenant. Confira tenant_id e "
            f"client_id no config.toml ou na tela Ajustes. [{codigo}]"
        )
    if "AADSTS900023" in descricao:
        return f"Tenant ID inválido. Confira o config.toml. [{codigo}]"
    return f"Falha ao autenticar no Microsoft 365: {descricao or codigo}"


def _traduzir_erro_http(resposta) -> str:
    """Converte o erro do Graph em uma frase que diz o que fazer.

    Os três erros de estreia deste app são sempre os mesmos — falta de
    consentimento do administrador, ApplicationAccessPolicy bloqueando a caixa e
    remetente digitado errado — e o texto cru do Graph não deixa isso claro.
    """
    try:
        corpo = resposta.json().get("error", {})
        codigo = corpo.get("code", "")
        detalhe = corpo.get("message", "")
    except Exception:
        codigo, detalhe = "", (resposta.text or "")[:300]

    status = resposta.status_code

    if status == 401:
        return (
            "Não autorizado (401). O token foi recusado — confira se a permissão "
            "Mail.Send (de aplicação) recebeu 'Grant admin consent' no Entra ID. "
            f"[{codigo}] {detalhe}"
        )
    if status == 403:
        # Erro de DIRETORIO: o app tentou ler dados de usuario e nao tem
        # User.Read.All. Nada a ver com enviar e-mail — dizer "falta Mail.Send"
        # aqui manda quem configura procurar no lugar errado.
        if codigo == "Authorization_RequestDenied" or "Insufficient privileges" in detalhe:
            return (
                "Sem permissão para ler dados de usuário no diretório (403). Isto "
                "é diferente de não poder enviar: exige User.Read.All, que este "
                "app não precisa ter. Se o erro apareceu ao ENVIAR, confira a "
                "ApplicationAccessPolicy; se apareceu ao testar a conexão, pode "
                f"ignorar. [{codigo}] {detalhe}"
            )
        return (
            "Acesso negado (403) ao enviar. As duas causas usuais: falta o "
            "consentimento do administrador para Mail.Send, ou a "
            "ApplicationAccessPolicy do Exchange não libera este app para a caixa "
            f"remetente. [{codigo}] {detalhe}"
        )
    if status == 404:
        return (
            "Caixa não encontrada (404). Confira o campo 'remetente' no config.toml "
            f"— ele precisa ser uma caixa existente no tenant. [{codigo}] {detalhe}"
        )
    if status == 413:
        return "Mensagem grande demais (413): o anexo excede o limite do servidor."
    if status == 429:
        return (
            "Limite de envio atingido (429). O Microsoft 365 está pedindo para "
            "reduzir o ritmo — diminua o limite diário ou espere alguns minutos."
        )
    if status in (500, 502, 503, 504):
        return f"Instabilidade no serviço Microsoft ({status}). Nova tentativa em curso."

    return f"Erro {status} do Microsoft Graph. [{codigo}] {detalhe}"
