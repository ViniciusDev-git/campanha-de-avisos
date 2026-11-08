"""Roda o cliente num Chrome real contra uma página que imita o WhatsApp Web.

Prova o fluxo e as paradas. A estrutura do balão foi copiada da página real em
05/11/2026, mas o simulador não acompanha mudanças do WhatsApp: quem prova que os
seletores ainda batem é o ensaio com o número real.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from disparo import fila as F
from disparo.canal_whatsapp import ClienteWhatsApp
from disparo.motor import ParadaObrigatoria

PAGINA = """<!doctype html><meta charset=utf-8><div id=app></div><script>
const q=new URLSearchParams(location.search), n=q.get('phone')||'', t=q.get('text')||'';
const app=document.getElementById('app');
let seq=0;
function balao(texto,rotulo,icone,cauda){
 const r=document.createElement('div'); r.setAttribute('data-testid','conv-msg-'+(++seq));
 r.innerHTML='<div data-testid=msg-container>'+(cauda?'<span data-testid=tail-out data-icon=tail-out></span>':'')
  +'<div><span class=t></span></div><div data-testid=msg-meta role=button>'
  +(rotulo?'<span aria-label=" '+rotulo+' "><svg><title>'+icone+'</title></svg></span>':'')+'</div></div>';
 r.querySelector('.t').innerText=texto; document.getElementById('msgs').appendChild(r);
}
if(location.pathname==='/'){app.innerHTML='<div id=pane-side></div>'}
else if(n.endsWith('02')){app.innerHTML='<div id=pane-side></div><div role=dialog>O número de telefone compartilhado por url é inválido.</div>'}
else if(n.endsWith('04')){app.innerHTML='<div data-testid=qrcode></div>'}
else if(n.endsWith('05')){app.innerHTML='<div id=pane-side></div><div role=dialog>Esta conta foi banida do WhatsApp</div>'}
else{
 app.innerHTML='<div id=pane-side></div><div id=main><div id=msgs></div><footer><div contenteditable=true id=c></div></footer></div>';
 document.getElementById('c').innerText=t;
 if(n.endsWith('06'))balao(t,'Entregue','wds-ic-read',true);
 if(n.endsWith('07'))balao(t,'','',false);
 document.getElementById('c').addEventListener('keydown',e=>{ if(e.key!=='Enter')return; e.preventDefault();
  const x=e.target.innerText;
  if(n.endsWith('03'))balao(x,'Pendente','wds-ic-pending',true);
  else if(n.endsWith('08'))balao(x,'Enviada','wds-ic-sent',false);
  else balao(x,'Entregue','wds-ic-read',true);
  e.target.innerText='';
 });
}
</script>"""


class Servidor(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGINA.encode("utf-8"))

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module")
def cliente(tmp_path_factory):
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Servidor)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    c = ClienteWhatsApp(
        tmp_path_factory.mktemp("sessao"),
        url=f"http://127.0.0.1:{servidor.server_port}",
        headless=True, espera_login=10, espera_abrir=4, espera_confirmar=2,
        espera_historico=0.3,
    )
    c.abrir()
    yield c
    c.fechar()
    servidor.shutdown()


TEXTO = {"texto": "Olá Maria, aviso da empresa.\nSegunda linha com acentuação & símbolo"}


def test_envio_confirmado(cliente):
    assert cliente.enviar("5511900000001", TEXTO).status == F.ENVIADO


def test_numero_sem_whatsapp(cliente):
    assert cliente.enviar("5511900000002", TEXTO).status == F.SEM_WHATSAPP


def test_sem_confirmacao_fica_incerto(cliente):
    assert cliente.enviar("5511900000003", TEXTO).status == F.INCERTO


def test_sessao_caiu_para_e_nada_saiu(cliente):
    with pytest.raises(ParadaObrigatoria) as e:
        cliente.enviar("5511900000004", TEXTO)
    assert e.value.nada_saiu


def test_conta_banida_para(cliente):
    with pytest.raises(ParadaObrigatoria) as e:
        cliente.enviar("5511900000005", TEXTO)
    assert "restrição" in str(e.value)


def test_mensagem_ja_na_conversa_nao_repete(cliente):
    assert cliente.enviar("5511900000006", TEXTO).status == F.DUPLICADO


def test_balao_recebido_com_o_mesmo_texto_nao_bloqueia(cliente):
    assert cliente.enviar("5511900000007", TEXTO).status == F.ENVIADO


def test_balao_sem_cauda_com_um_tique_confirma(cliente):
    assert cliente.enviar("5511900000008", TEXTO).status == F.ENVIADO


def test_ensaio_permite_repetir_na_mesma_conversa(cliente):
    cliente.permitir_repetida = True
    try:
        assert cliente.enviar("5511900000006", TEXTO).status == F.ENVIADO
    finally:
        cliente.permitir_repetida = False
