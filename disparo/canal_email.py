"""Envio de e-mail pelo Microsoft Graph, a partir de uma caixa remetente (ex.: noreply@).

Tenant ID e Client ID vêm do `config.toml` (seção [email]) ou dos ajustes feitos
na janela. O segredo do aplicativo fica sempre no cofre de credenciais do sistema
(Cofre do Windows), nunca em arquivo.
"""

from __future__ import annotations

from . import fila as F
from .graph_client import ErroDeEnvio, GraphClient
from .motor import ParadaObrigatoria, Resultado

SERVICO_KEYRING = "CampanhaDeAvisos"


def _preenchido(valor: str) -> bool:
    """O modelo de configuração traz GUIDs zerados, que não são credencial."""
    return bool(str(valor or "").replace("0", "").replace("-", "").strip())


def identificadores(secao: dict) -> tuple[str, str]:
    """(tenant_id, client_id), ou vazios se esta máquina ainda não os tem."""
    tenant, cliente = secao.get("tenant_id", ""), secao.get("client_id", "")
    if _preenchido(tenant) and _preenchido(cliente):
        return tenant, cliente
    return "", ""


def tem_segredo(secao: dict) -> bool:
    import keyring

    _, cliente = identificadores(secao)
    return bool(cliente and keyring.get_password(SERVICO_KEYRING, cliente))


def gravar_segredo(secao: dict, segredo: str) -> None:
    import keyring

    _, cliente = identificadores(secao)
    if not cliente:
        raise ParadaObrigatoria("Informe primeiro o Client ID.", nada_saiu=True)
    keyring.set_password(SERVICO_KEYRING, cliente, segredo)


def conectar(secao: dict, remetente: str, responder_para: str) -> GraphClient:
    import keyring

    tenant, cliente = identificadores(secao)
    if not tenant or not cliente:
        raise ParadaObrigatoria("Faltam o Tenant ID e o Client ID do aplicativo de envio.", nada_saiu=True)
    segredo = keyring.get_password(SERVICO_KEYRING, cliente)
    if not segredo:
        raise ParadaObrigatoria(
            "O segredo do aplicativo de envio ainda não foi gravado neste computador.", nada_saiu=True
        )
    return GraphClient(
        tenant_id=tenant,
        client_id=cliente,
        client_secret=segredo,
        remetente=remetente,
        responder_para=responder_para,
    )


class ClienteEmail:
    def __init__(self, graph: GraphClient):
        self.graph = graph

    def enviar(self, destino: str, conteudo: dict[str, str]) -> Resultado:
        try:
            self.graph.enviar(destino, conteudo["assunto"], conteudo["html"])
        except ErroDeEnvio as erro:
            if erro.status in (401, 403, 404) or erro.status == 0 and erro.permanente:
                # Credencial ou caixa: vale para o lote inteiro, não para este cliente.
                raise ParadaObrigatoria(str(erro), nada_saiu=True) from erro
            if erro.permanente:
                return Resultado(F.FALHOU, str(erro))
            return Resultado(F.INCERTO, str(erro))
        return Resultado(F.ENVIADO)
