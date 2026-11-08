"use strict";

/* Interface da Campanha de Avisos. Não decide nada que importe: pergunta ao motor
   (janela.py) e mostra. As travas de segurança moram no Python. */

const PASSOS = [
  ["planilha", "Planilha"],
  ["mensagens", "Mensagens"],
  ["ensaio", "Ensaio (opcional)"],
  ["disparo", "Disparo"],
];
const CANAL = { email: "E-mail", whatsapp: "WhatsApp", sms: "SMS" };
const SITUACAO = {
  pendente: ["Na fila", "l-fila"],
  enviando: ["Enviando", "l-aceso"],
  enviado: ["Avisado", "l-aceso"],
  incerto: ["Conferir", "l-alerta"],
  falhou: ["Falhou", "l-alerta"],
  sem_whatsapp: ["Sem WhatsApp", "l-sem"],
  duplicado: ["Já recebeu", "l-fila"],
  cancelado: ["Cancelado", "l-sem"],
  devolvido: ["Devolvido", "l-sem"],
};
const VARIAVEIS = [
  ["primeiro_nome", "Primeiro nome"],
  ["nome", "Nome completo"],
  ["numero_inscricao", "Número de Inscrição"],
  ["parcelas", "Parcelas"],
  ["pendencias", "Lista de pendências"],
];
const DETALHES = {
  "numero nao esta no WhatsApp": "Número sem WhatsApp",
  "mensagem ja consta na conversa": "A mensagem já estava na conversa",
  "execucao interrompida durante o envio": "O programa fechou durante o envio",
  "mensagem na conversa, sem confirmacao de envio": "Apareceu na conversa, sem confirmação",
  "mensagem nao apareceu na conversa": "Não apareceu na conversa",
  "sem confirmacao de envio": "Sem confirmação de envio",
  "lista nao_enviar": "Retirado da campanha",
  "saiu da planilha": "Saiu da planilha",
};
const RITMOS = [["contagotas", "Conta-gotas"], ["prudente", "Prudente"], ["padrao", "Padrão"], ["acelerado", "Acelerado"]];

const api = () => window.pywebview.api;
const num = (n) => Number(n || 0).toLocaleString("pt-BR");
const $ = (s, r = document) => r.querySelector(s);

let estado = null;
let telaAtual = "planilha";
let assinatura = "";
let painelCanal = "whatsapp";
const local = {
  lendo: false, erroPlanilha: "", canalTexto: "whatsapp", editandoInternos: false,
  internos: [], confirmar: null, erro: {}, ritmo: null, filtro: "", busca: "", inicio: 0,
  arquivoParcial: "", avisoPlanilha: "",
};

/* Monta elementos com textContent: nome de cliente nunca vira HTML. */
function h(tag, attrs, ...filhos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    el.append(f.nodeType ? f : document.createTextNode(String(f)));
  }
  return el;
}

function anexar(el, ...filhos) {
  el.append(...filhos.flat().filter((f) => f !== null && f !== undefined && f !== false));
}

const plural = (n, um, varios) => `${num(n)} ${n === 1 ? um : varios}`;

function ir(tela) {
  telaAtual = tela;
  local.confirmar = null;
  if (tela !== "contatos") local.filtro = "";
  document.body.dataset.tela = tela;
  assinatura = "";
  pintar(true);
  $("#tela").scrollTop = 0;
  $("#tela").focus({ preventScroll: true });
}

/* ---- leitura do estado ------------------------------------------------ */

const totalCanal = (c) => estado.canais[c].total;
const enviados = (c) => estado.canais[c].contagem.enviado || 0;
const pendentes = (c) => estado.canais[c].contagem.pendente || 0;
const conferir = (c) => (estado.canais[c].contagem.incerto || 0) + (estado.canais[c].contagem.falhou || 0);
const tarefa = (c) => estado.canais[c].tarefa;
const ativa = (c) => Boolean(tarefa(c) && tarefa(c).ativa);
const algumaAtiva = () => ["email", "whatsapp"].some(ativa);

function etapaFeita(tela) {
  const c = estado.canais;
  if (tela === "planilha") return Boolean(estado.importacao);
  if (tela === "mensagens") return c.email.texto_definido && c.whatsapp.texto_definido;
  if (tela === "ensaio") return c.email.ensaio_aprovado && c.whatsapp.ensaio_aprovado;
  if (tela === "disparo") return estado.importacao && !pendentes("email") && !pendentes("whatsapp");
  return false;
}

/* Por que este canal não pode ensaiar ou disparar agora, em linguagem de gente. */
function faltas(canal, paraDisparo) {
  const c = estado.canais[canal];
  const lista = [];
  if (canal === "sms") return [["O SMS aguarda a definição do fornecedor.", null]];
  if (paraDisparo && !estado.importacao) lista.push(["Falta carregar a planilha.", "planilha"]);
  if (!c.texto_definido) lista.push(["Falta escrever a mensagem.", "mensagens"]);
  if (canal === "email") {
    if (!estado.ajustes.responder_para) lista.push(["Falta informar o e-mail que recebe as respostas.", "ajustes"]);
    if (!estado.ajustes.segredo_gravado) lista.push(["A TI precisa gravar o acesso do aplicativo de envio neste computador.", "ajustes"]);
  }
  if (!paraDisparo && !estado.internos) lista.push(["Falta cadastrar os contatos da equipe.", null]);
  return lista;
}

function descreverFim(t) {
  if (t.erro) return { tom: "alerta", texto: t.erro };
  const r = t.resultado || {};
  const m = r.motivo || "";
  if (t.tipo === "ensaio") {
    return r.aprovado
      ? { tom: "bom", texto: "Ensaio aprovado. Confira nos aparelhos se chegou tudo." }
      : { tom: "alerta", texto: m.includes("sem confirmacao")
        ? "As mensagens podem ter chegado, mas o programa não conseguiu confirmar o envio. Confira nos aparelhos e chame a TI antes de disparar."
        : `Ensaio reprovado: ${m}.` };
  }
  if (m === "fila concluida") return { tom: "bom", texto: "Todos os contatos deste canal foram processados." };
  if (m.startsWith("meta de")) return { tom: "bom", texto: `Teste concluído com ${plural(r.enviados, "envio", "envios")}. Confira e, se estiver tudo certo, inicie o disparo.` };
  if (m === "parada pedida pelo operador") return { tom: "calmo", texto: "Pausado. Nada será enviado até você retomar." };
  if (m === "fora da janela de envio") return { tom: "calmo", texto: "Fora do horário de envio. Tente de novo dentro do horário." };
  if (m.startsWith("limite diario")) return { tom: "calmo", texto: "O limite de envios de hoje foi atingido. Retome amanhã." };
  if (m.includes("sem confirmacao")) return { tom: "alerta", texto: "Parou por segurança: três envios seguidos ficaram sem confirmação. Confira se o número está conectado e retome." };
  if (m.includes("sem WhatsApp")) return { tom: "alerta", texto: "Parou por segurança: muitos números seguidos não têm WhatsApp. Confira a planilha antes de retomar." };
  return { tom: "alerta", texto: `Parou por segurança: ${m}` };
}

/* ---- laterais --------------------------------------------------------- */

function pintarPassos() {
  $("#passos").replaceChildren(...PASSOS.map(([id, nome]) => h("li", null,
    h("button", {
      "data-ir": id,
      "aria-current": telaAtual === id ? "step" : null,
      "data-feita": etapaFeita(id) || null,
    }, h("i"), nome))));
  document.querySelectorAll(".extras [data-ir]").forEach((b) => {
    if (b.dataset.ir === telaAtual) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
}

/* ---- telas ------------------------------------------------------------ */

function telaPlanilha() {
  const imp = estado.importacao;
  const parcial = local.arquivoParcial;
  const erro = local.erroPlanilha && h("div", { class: "aviso", role: "alert" }, local.erroPlanilha,
    parcial && h("div", { class: "canal-acoes" },
      h("button", { class: "b", onclick: () => priorizarLista(parcial) }, "Priorizar esta lista"),
      h("button", { class: "b s", onclick: () => lerPlanilha(parcial, true) }, "Carregar mesmo assim")));
  const feito = local.avisoPlanilha && h("p", { class: "certo" }, local.avisoPlanilha);

  if (!imp) {
    return [
      h("h1", null, "Comece pela planilha de cobrança"),
      h("p", { class: "lead" }, "Nada é enviado nesta etapa. A ferramenta só confere quem deve ser avisado e por qual contato."),
      erro,
      h("div", { class: "zona" },
        h("div", null, botaoPlanilha("Escolher planilha", false)),
        h("p", { class: "nota" }, "Arquivo .xlsx exportado do sistema")),
    ];
  }

  const quando = new Date(imp.quando);
  const dia = quando.toLocaleDateString("pt-BR");
  const hora = quando.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const motivos = Object.entries(imp.motivos_retidos);
  return [
    h("h1", null, `${num(imp.pessoas)} pessoas na campanha`),
    h("p", { class: "lead" }, `Planilha lida em ${dia}, às ${hora}, com ${num(imp.linhas)} inscrições.`),
    erro,
    feito,
    h("div", { class: "linhas secao" },
      h("div", null, h("span", null, "E-mail"), h("span", null, `${num(totalCanal("email"))} mensagens`)),
      h("div", null, h("span", null, "WhatsApp"), h("span", null, `${num(totalCanal("whatsapp"))} mensagens`)),
      h("div", null, h("span", null, "SMS"), h("small", null, "Aguardando fornecedor"))),
    motivos.length > 0 && h("div", { class: "secao" },
      h("h2", null, `${num(imp.retidos)} pessoas ficaram de fora`),
      h("div", { class: "linhas" }, motivos.map(([m, n]) =>
        h("div", null, h("span", null, nomeMotivo(m)), h("span", null, num(n)))))),
    h("div", { class: "acoes" },
      h("button", { class: "b", "data-ir": "mensagens" }, "Continuar"),
      h("button", { class: "b s", "data-ir": "fora" }, "Ver quem ficou de fora"),
      botaoPlanilha("Trocar planilha", true),
      h("button", {
        class: "b s",
        disabled: local.lendo || algumaAtiva(),
        title: "Põe as pessoas de uma planilha na frente da fila do WhatsApp, sem tirar ninguém.",
        onclick: () => priorizarLista(),
      }, "Priorizar lista")),
  ];
}

const dataBr = (iso) => new Date(iso + "T12:00").toLocaleDateString("pt-BR");

function nomeMotivo(m) {
  if (m === "valor abaixo do minimo") return `Valor abaixo de R$ ${Number(estado.ajustes.valor_minimo).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
  if (m === "vencido apenas depois do corte") return `Vencido só depois de ${dataBr(estado.importacao.corte)}`;
  if (m === "sem nenhum contato valido") return "Sem contato válido";
  if (m === "sem nome") return "Sem nome";
  return m;
}

function botaoPlanilha(rotulo, secundario) {
  return h("button", {
    class: secundario ? "b s" : "b",
    disabled: local.lendo || algumaAtiva(),
    title: algumaAtiva() ? "Pause os envios para trocar a planilha." : null,
    onclick: escolherPlanilha,
  }, local.lendo ? "Lendo a planilha…" : rotulo);
}

async function escolherPlanilha() {
  const arquivo = await api().escolher_planilha();
  if (arquivo) await lerPlanilha(arquivo, false);
}

async function lerPlanilha(arquivo, forcar) {
  local.lendo = true; local.erroPlanilha = ""; local.arquivoParcial = ""; local.avisoPlanilha = ""; pintar(true);
  const r = await api().carregar_planilha(arquivo, forcar);
  local.lendo = false;
  if (r.erro) { local.erroPlanilha = r.erro; local.arquivoParcial = r.arquivo_parcial || ""; }
  await atualizar();
  pintar(true);
}

async function priorizarLista(escolhido) {
  const arquivo = escolhido || await api().escolher_planilha();
  if (!arquivo) return;
  local.lendo = true; local.erroPlanilha = ""; local.arquivoParcial = ""; local.avisoPlanilha = ""; pintar(true);
  const r = await api().priorizar_planilha(arquivo);
  local.lendo = false;
  if (r.erro) local.erroPlanilha = r.erro;
  else {
    const fora = r.ja_avisados + r.sem_contato + r.fora_da_campanha;
    local.avisoPlanilha = `${plural(r.na_frente, "pessoa foi", "pessoas foram")} para a frente da fila do WhatsApp.` +
      (fora ? ` ${plural(fora, "pessoa ficou", "pessoas ficaram")} como estava: ${r.ja_avisados} já avisadas, ${r.sem_contato} sem WhatsApp, ${r.fora_da_campanha} fora da campanha.` : "");
  }
  await atualizar();
  pintar(true);
}

function telaFora() {
  const raiz = h("div", { class: "tela" },
    h("h1", null, "Quem ficou de fora"),
    h("p", { class: "lead" }, "Estas pessoas não recebem nada nesta campanha."));
  const corpo = h("tbody");
  anexar(raiz,
    h("div", { class: "tabela" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Nome"), h("th", null, "Motivo"))), corpo)),
    h("div", { class: "acoes" }, h("button", { class: "b s", "data-ir": "planilha" }, "Voltar")));
  api().retidos().then((lista) => {
    corpo.replaceChildren(...lista.map((p) =>
      h("tr", null, h("td", null, p.nome), h("td", null, nomeMotivo(p.motivo)))));
  });
  return raiz;
}

/* Editor: quem escreve vê [Primeiro nome]; o motor recebe {{primeiro_nome}}. */
const paraTela = (t) => VARIAVEIS.reduce((s, [v, n]) => s.replaceAll(`{{${v}}}`, `[${n}]`), t);
const paraMotor = (t) => VARIAVEIS.reduce((s, [v, n]) => s.replaceAll(`[${n}]`, `{{${v}}}`), t);

function telaMensagens() {
  const canal = local.canalTexto;
  const raiz = h("div", { class: "tela" }, h("h1", null, "Escreva a mensagem"));
  const aba = (c) => h("button", {
    role: "tab", "aria-selected": String(c === canal),
    onclick: () => { local.canalTexto = c; pintar(true); },
  }, CANAL[c]);
  const assunto = canal === "email" ? h("input", { type: "text", class: "assunto", placeholder: "Assunto do e-mail", "aria-label": "Assunto do e-mail" }) : null;
  const caixa = h("textarea", { class: "editor", "aria-label": `Texto para ${CANAL[canal]}`, placeholder: "Escreva aqui o texto. Use os botões abaixo para incluir os dados de cada pessoa." });
  const conta = h("span", { class: "conta" });
  const retorno = h("div", { "aria-live": "polite" });

  const previa = async () => {
    const t = paraMotor(caixa.value);
    conta.textContent = canal === "sms" ? `${num(caixa.value.length)} de 160 caracteres, antes dos dados` : `${num(caixa.value.length)} caracteres`;
    conta.classList.toggle("demais", canal === "sms" && caixa.value.length > 160);
    const r = await api().previa(canal, t, assunto ? paraMotor(assunto.value) : "");
    pintarPrevias(r, t);
  };
  let espera;
  const adiar = () => { clearTimeout(espera); espera = setTimeout(previa, 180); };
  caixa.addEventListener("input", adiar);
  if (assunto) assunto.addEventListener("input", adiar);

  const salvar = async (depois) => {
    retorno.replaceChildren();
    const r = await api().salvar_texto(canal, paraMotor(caixa.value), assunto ? paraMotor(assunto.value) : "");
    if (r.erro) { retorno.append(h("div", { class: "aviso", role: "alert" }, traduzirErroTexto(r.erro))); return; }
    await atualizar();
    if (depois) ir(depois);
    else retorno.append(h("p", { class: "certo" }, "Mensagem salva."));
  };

  anexar(raiz,
    h("div", { class: "abas", role: "tablist", "aria-label": "Canal" }, ["whatsapp", "email", "sms"].map(aba)),
    assunto, caixa,
    h("div", { class: "chips" }, VARIAVEIS.map(([, nome]) => h("button", {
      onclick: () => {
        caixa.setRangeText(`[${nome}]`, caixa.selectionStart, caixa.selectionEnd, "end");
        caixa.focus(); adiar();
      },
    }, nome)), conta),
    retorno,
    h("div", { class: "acoes" },
      h("button", { class: "b", onclick: () => salvar(null) }, "Salvar"),
      h("button", { class: "b s", onclick: () => salvar("ensaio") }, "Salvar e ensaiar")));

  api().ler_texto(canal).then((t) => {
    caixa.value = paraTela(t.texto || "");
    if (assunto) assunto.value = paraTela(t.assunto || "");
    previa();
  });
  return raiz;
}

function traduzirErroTexto(e) {
  if (e.includes("vazio") || e.includes("ainda nao foi definido")) return "Escreva o texto antes de salvar.";
  if (e.includes("inexistentes")) return "O texto tem um dado que não existe. Use os botões abaixo da caixa para incluir os dados.";
  return e;
}

function pintarPrevias(r, texto) {
  const bolha = (t) => h("div", { class: t ? "bolha" : "bolha vazia" }, t || "A prévia aparece aqui enquanto você escreve.");
  if (r.erro) {
    $("#previas").replaceChildren(h("p", { class: "rot" }, traduzirErroTexto(r.erro)));
    return;
  }
  $("#previas").replaceChildren(
    r.assunto ? h("p", { class: "rot" }, `Assunto: ${r.assunto}`) : "",
    h("p", { class: "rot" }, "Número de uma pessoa"), bolha(texto.trim() && r.um),
    h("p", { class: "rot" }, "Número com duas pessoas"), bolha(texto.trim() && r.dois));
}

function situacaoEnsaio(canal) {
  const c = estado.canais[canal];
  const t = c.tarefa && c.tarefa.tipo === "ensaio" ? c.tarefa : null;
  if (t && t.ativa) return { tom: "vivo", texto: "Enviando para a equipe…" };
  if (c.ensaio_aprovado) return { tom: "bom", texto: "Aprovado" };
  if (t && t.fim) return descreverFim(t);
  return { tom: "", texto: "Ainda não ensaiado" };
}

function telaEnsaio() {
  const aprovados = estado.canais.email.ensaio_aprovado && estado.canais.whatsapp.ensaio_aprovado;
  if (local.editandoInternos) return telaInternos();
  const linha = (canal) => {
    const s = situacaoEnsaio(canal);
    const f = faltas(canal, false);
    return h("div", { class: "canal" },
      h("div", { class: "canal-topo" },
        h("h2", null, CANAL[canal]),
        h("span", { class: "canal-situacao", "data-tom": s.tom }, h("i"), s.tom === "alerta" ? "Reprovado" : s.texto)),
      s.tom === "alerta" && h("p", { class: "aviso", role: "alert" }, s.texto),
      canal !== "sms" && f.length === 0 && !ativa(canal) && h("div", { class: "canal-acoes" },
        h("button", {
          class: s.tom === "bom" ? "b s" : "b",
          onclick: async () => { await api().iniciar_ensaio(canal); await atualizar(); },
        }, s.tom === "bom" ? "Ensaiar de novo" : "Enviar ensaio")),
      f.map(faltaEl));
  };
  return [
    h("h1", null, aprovados ? "Ensaio aprovado" : "Teste com a equipe"),
    h("p", { class: "lead" }, aprovados
      ? "Confira nos aparelhos e nas caixas se chegou tudo como esperado."
      : "Opcional. Serve para ver se a ferramenta está funcionando, com dados fictícios. Você pode ir direto ao disparo."),
    h("div", { class: "secao" }, ["email", "whatsapp"].map(linha)),
    h("p", { class: "nota", style: "margin-top:12px" }, estado.internos
      ? `${plural(estado.internos, "contato", "contatos")} da equipe na lista.`
      : "Nenhum contato da equipe cadastrado."),
    h("div", { class: "acoes" },
      h("button", { class: "b", "data-ir": "disparo" }, "Ir para o disparo"),
      h("button", { class: "b s", onclick: abrirInternos }, estado.internos ? "Editar contatos da equipe" : "Cadastrar contatos da equipe")),
  ];
}

function faltaEl([texto, destino]) {
  return h("p", { class: "pre" }, texto, " ", destino && h("button", { class: "link", "data-ir": destino }, "Resolver"));
}

async function abrirInternos() {
  local.internos = await api().internos();
  if (!local.internos.length) local.internos = [{ nome: "", celular: "", email: "" }];
  local.editandoInternos = true; local.erro.internos = "";
  pintar(true);
}

function telaInternos() {
  const linhas = h("div");
  const pintarLinhas = () => linhas.replaceChildren(...local.internos.map((p, i) => {
    const campo = (k, rotulo) => h("input", {
      type: "text", placeholder: rotulo, "aria-label": rotulo, value: p[k],
      oninput: (e) => { p[k] = e.target.value; },
    });
    return h("div", { class: "pessoa-edit" }, campo("nome", "Nome"), campo("celular", "Celular com DDD"), campo("email", "E-mail"),
      h("button", { class: "tira", "aria-label": `Remover ${p.nome || "contato"}`, onclick: () => { local.internos.splice(i, 1); pintarLinhas(); } }, "Remover"));
  }));
  pintarLinhas();
  return [
    h("h1", null, "Contatos da equipe"),
    h("p", { class: "lead" }, "Quem recebe o ensaio. Use contatos reais da equipe para conferir nos aparelhos."),
    h("div", { class: "secao" }, linhas,
      h("button", { class: "link", style: "margin-top:12px", onclick: () => { local.internos.push({ nome: "", celular: "", email: "" }); pintarLinhas(); } }, "Adicionar contato")),
    local.erro.internos && h("div", { class: "aviso", role: "alert" }, local.erro.internos),
    h("div", { class: "acoes" },
      h("button", {
        class: "b",
        onclick: async () => {
          const r = await api().salvar_internos(local.internos);
          if (r.erro) { local.erro.internos = r.erro; pintar(true); return; }
          local.editandoInternos = false; await atualizar(); pintar(true);
        },
      }, "Salvar contatos"),
      h("button", { class: "b s", onclick: () => { local.editandoInternos = false; pintar(true); } }, "Cancelar")),
  ];
}

function situacaoDisparo(canal) {
  const t = tarefa(canal);
  const total = totalCanal(canal);
  if (t && t.ativa && t.tipo !== "ensaio") {
    if (t.parando) return { tom: "vivo", rotulo: "Pausando", texto: "Terminando o envio em andamento…" };
    if (!estado.janela_aberta) return { tom: "calmo", rotulo: "Aguardando horário", texto: `Retoma sozinho às ${estado.ajustes.janela_inicio}.` };
    if (canal === "whatsapp" && t.tipo === "disparo" && ritmoEscolhido() === "contagotas" && estado.canais[canal].enviados_hoje >= estado.ajustes.conversas_dia)
      return { tom: "calmo", rotulo: "Aguardando amanhã", texto: `As ${estado.ajustes.conversas_dia} conversas de hoje já foram enviadas. Retoma sozinho no próximo dia de envio.` };
    return { tom: "vivo", rotulo: t.tipo === "piloto" ? "Testando" : "Enviando", texto: `Dentro do horário, até as ${estado.ajustes.janela_fim}.` };
  }
  if (t && t.fim && t.tipo !== "ensaio") {
    const fim = descreverFim(t);
    return { ...fim, rotulo: fim.tom === "alerta" ? "Parado" : fim.tom === "bom" ? "Concluído" : "Pausado" };
  }
  if (total && !pendentes(canal)) return { tom: "bom", rotulo: "Concluído", texto: "Todos os contatos deste canal foram processados." };
  return { tom: "", rotulo: "Pronto", texto: "" };
}

function blocoCanal(canal) {
  const total = totalCanal(canal);
  const s = situacaoDisparo(canal);
  const f = faltas(canal, true);
  const emAndamento = ativa(canal);
  const retomar = enviados(canal) > 0;
  const fila = pendentes(canal);
  const confirmando = local.confirmar && local.confirmar.canal === canal;

  const pedir = (tipo) => { local.confirmar = { canal, tipo }; pintar(true); };
  const iniciar = async () => {
    const { tipo } = local.confirmar;
    local.confirmar = null;
    if (tipo === "piloto") await api().iniciar_piloto(canal, 5, canal === "whatsapp" ? ritmoEscolhido() : null);
    else await api().iniciar_disparo(canal, canal === "whatsapp" ? ritmoEscolhido() : null);
    await atualizar(); pintar(true);
  };

  return h("div", { class: "canal", "data-canal": canal },
    h("div", { class: "canal-topo" },
      h("h2", null, CANAL[canal]),
      h("span", { class: "canal-situacao", "data-tom": s.tom }, h("i"), s.rotulo)),
    h("p", { class: "canal-numero" },
      h("span", { "data-conta": canal }, num(enviados(canal))),
      h("small", null, `de ${num(total)} avisados`)),
    s.texto && (s.tom === "alerta"
      ? h("p", { class: "aviso", role: "alert" }, s.texto)
      : h("p", { class: "canal-texto" }, s.texto)),
    estado.canais[canal].urgentes > 0 && h("p", { class: "pre" }, `${plural(estado.canais[canal].urgentes, "contato com prioridade sai", "contatos com prioridade saem")} primeiro.`),
    conferir(canal) > 0 && h("p", { class: "pre" }, `${plural(conferir(canal), "contato", "contatos")} para conferir. `,
      h("button", { class: "link", onclick: () => { local.filtro = "incerto"; painelCanal = canal; ir("contatos"); } }, "Ver")),

    !emAndamento && fila > 0 && !confirmando && canal === "whatsapp" && controleRitmo(),

    !emAndamento && fila > 0 && f.length > 0 && f.map(faltaEl),

    !emAndamento && fila > 0 && f.length === 0 && !confirmando &&
      h("div", { class: "canal-acoes" },
        h("button", { class: "b", onclick: () => pedir("disparo") }, retomar ? "Retomar" : "Iniciar disparo"),
        !retomar && h("button", { class: "b s", onclick: () => pedir("piloto") }, "Testar com 5 pessoas")),

    confirmando && h("div", { class: "confirma" },
      h("p", null, local.confirmar.tipo === "piloto"
        ? `Isto envia a mensagem para 5 clientes de verdade, por ${CANAL[canal]}.`
        : `Isto envia a mensagem para ${plural(fila, "contato", "contatos")} de verdade, por ${CANAL[canal]}.`),
      !estado.canais[canal].ensaio_aprovado && h("p", { class: "nota" }, "Este texto não tem ensaio aprovado."),
      canal === "whatsapp" && h("p", { class: "nota" }, `Ritmo ${nomeRitmo()}, cerca de ${vazao(ritmoEscolhido())}. O navegador vai abrir; deixe a janela aberta.`),
      canal === "whatsapp" && local.confirmar.tipo !== "piloto" && ritmoEscolhido() !== "contagotas" &&
        h("p", { class: "aviso", role: "alert" }, "Os ritmos por hora já causaram a restrição da linha. O Conta-gotas é o mais seguro."),
      h("div", { class: "canal-acoes" },
        h("button", { class: "b", onclick: iniciar }, "Sim, enviar"),
        h("button", { class: "b s", onclick: () => { local.confirmar = null; pintar(true); } }, "Cancelar"))),

    emAndamento && h("div", { class: "canal-acoes" },
      h("button", {
        class: "b s", disabled: tarefa(canal).parando,
        onclick: async () => { await api().parar(canal); await atualizar(); pintar(true); },
      }, "Pausar")));
}

function ritmoEscolhido() { return local.ritmo || estado.ajustes.ritmo; }
function nomeRitmo() { return RITMOS.find(([id]) => id === ritmoEscolhido())[1]; }
function vazao(id) { return id === "contagotas" ? `${estado.ajustes.conversas_dia} por dia` : `${estado.ritmos[id]} por hora`; }

function controleRitmo() {
  return h("div", { class: "ritmos", role: "radiogroup", "aria-label": "Ritmo do WhatsApp" },
    RITMOS.map(([id, nome]) => h("label", null,
      h("input", {
        type: "radio", name: "ritmo", checked: ritmoEscolhido() === id,
        onchange: () => { local.ritmo = id; api().salvar_ajuste("whatsapp", { ritmo: id }); },
      }),
      nome, h("small", null, vazao(id)))));
}

function acompanhando() {
  return ["email", "whatsapp"].some((c) => {
    const t = tarefa(c);
    return enviados(c) > 0 || (t && t.tipo !== "ensaio");
  });
}

function tituloDisparo() {
  if (!estado.importacao) return "Carregue a planilha para começar";
  const pronto = ["email", "whatsapp"].some((c) => !faltas(c, true).length);
  return pronto ? `Tudo pronto para avisar ${plural(estado.importacao.pendentes, "pessoa", "pessoas")}` : "Faltam alguns passos antes do disparo";
}

function telaDisparo() {
  const acomp = acompanhando();
  const recentes = ["whatsapp", "email"]
    .flatMap((c) => estado.canais[c].recentes.map((r) => ({ ...r, canal: c })))
    .sort((a, b) => b.atualizado_em.localeCompare(a.atualizado_em))
    .slice(0, 6);
  const terminou = estado.importacao && !pendentes("email") && !pendentes("whatsapp") && !algumaAtiva();
  return [
    !acomp && h("h1", null, tituloDisparo()),
    !acomp && h("p", { class: "lead" }, `As mensagens saem das ${estado.ajustes.janela_inicio} às ${estado.ajustes.janela_fim}. Você pode pausar quando quiser, e a ferramenta para sozinha se algo parecer errado.`),
    h("div", { class: acomp ? "" : "secao" }, ["whatsapp", "email"].map(blocoCanal)),
    h("div", { class: "canal" }, h("div", { class: "canal-topo" }, h("h2", null, "SMS"), h("span", { class: "canal-situacao" }, h("i"), "Aguardando fornecedor"))),
    recentes.length > 0 && h("div", { class: "recentes" },
      h("h2", null, "Últimos avisos"),
      h("ul", null, recentes.map((r) => h("li", null,
        h("time", null, r.atualizado_em.slice(11, 16)),
        h("span", null, r.nomes.map(formatarNome).join(", ")),
        h("em", null, SITUACAO[r.status] && r.status !== "enviado" ? SITUACAO[r.status][0] : CANAL[r.canal]))))),
    h("div", { class: "acoes" },
      terminou && h("p", { class: "certo" }, "Campanha concluída."),
      acomp && h("button", { class: "b s", onclick: exportar }, "Exportar relatório")),
  ];
}

async function exportar() {
  const r = await api().exportar_relatorio();
  if (!r.erro) await api().abrir_pasta_saida();
  anunciar(r.erro || "Relatório exportado.");
}

function anunciar(texto) { $("#anuncio").textContent = texto; }

function telaContatos() {
  const raiz = h("div", { class: "tela" }, h("h1", null, "Contatos"));
  const corpo = h("tbody");
  const pagina = h("span");
  const anterior = h("button", { class: "b s", onclick: () => { local.inicio = Math.max(0, local.inicio - 50); carregar(); } }, "Anterior");
  const proximo = h("button", { class: "b s", onclick: () => { local.inicio += 50; carregar(); } }, "Próxima");
  const acao = h("div");

  async function carregar() {
    const r = await api().listar(painelCanal, local.filtro, local.busca, local.inicio);
    corpo.replaceChildren(...(r.itens.length ? r.itens.map((i) => {
      const [nome, classe] = SITUACAO[i.status] || [i.status, "l-fila"];
      return h("tr", null,
        h("td", null, i.pessoas.map((p) => h("div", null, formatarNome(p.nome),
          h("small", null, p.planos.map(([n, q]) => `Inscrição ${n}, ${q} parcela${q === 1 ? "" : "s"}`).join(" · "))))),
        h("td", null, formatarDestino(i.destino)),
        h("td", null, h("span", { class: "situacao" }, h("i", { class: classe }), nome), i.detalhe && h("small", null, DETALHES[i.detalhe] || i.detalhe)));
    }) : [h("tr", null, h("td", { colspan: "3" }, "Nenhum contato encontrado."))]));
    const fim = Math.min(local.inicio + 50, r.total);
    pagina.textContent = r.total ? `${num(local.inicio + 1)} a ${num(fim)} de ${num(r.total)}` : "";
    anterior.disabled = local.inicio === 0;
    proximo.disabled = fim >= r.total;
    acao.replaceChildren();
    if (local.filtro === "incerto" && r.total) {
      acao.append(h("div", { class: "aviso calmo" },
        "Confira no WhatsApp ou na caixa de enviados se estas mensagens saíram. Só devolva à fila as que não saíram, porque quem está aqui pode receber de novo. ",
        h("button", {
          class: "link",
          onclick: async () => { await api().liberar_incertos(painelCanal); local.filtro = ""; await atualizar(); pintar(true); },
        }, "Devolver todos à fila")));
    }
  }

  const busca = h("input", {
    type: "search", placeholder: "Buscar por nome, inscrição, celular ou e-mail", "aria-label": "Buscar contato", value: local.busca,
    oninput: (e) => { local.busca = e.target.value; local.inicio = 0; clearTimeout(busca._t); busca._t = setTimeout(carregar, 220); },
  });
  const filtro = h("select", {
    "aria-label": "Filtrar por situação",
    onchange: (e) => { local.filtro = e.target.value; local.inicio = 0; carregar(); },
  }, h("option", { value: "" }, "Todas as situações"),
  Object.entries(SITUACAO).filter(([k]) => k !== "duplicado").map(([k, [n]]) => h("option", { value: k }, n)));
  filtro.value = local.filtro;

  const fora = h("input", { type: "text", placeholder: "CPF, celular ou e-mail", "aria-label": "Contato que não deve receber" });
  const retorno = h("p", { class: "nota", "aria-live": "polite" });
  const abas = h("div", { class: "abas", role: "tablist" }, ["whatsapp", "email"].map((c) => h("button", {
    role: "tab", "aria-selected": String(c === painelCanal),
    onclick: () => { painelCanal = c; local.inicio = 0; pintar(true); },
  }, CANAL[c])));

  anexar(raiz, abas, h("div", { class: "filtros" }, busca, filtro), acao,
    h("div", { class: "tabela" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Pessoas"), h("th", null, "Contato"), h("th", null, "Situação"))), corpo)),
    h("div", { class: "paginas" }, pagina, h("div", { class: "canal-acoes", style: "margin:0" }, anterior, proximo)),
    h("div", { class: "secao" },
      h("h2", null, "Retirar alguém da campanha"),
      h("div", { class: "adiciona" }, fora, h("button", {
        class: "b s",
        onclick: async () => {
          if (!fora.value.trim()) return;
          const r = await api().adicionar_nao_enviar(fora.value);
          retorno.textContent = r.erro || `${fora.value.trim()} não receberá mais nada. Vale na hora.`;
          fora.value = "";
        },
      }, "Retirar")), retorno));
  carregar();
  return raiz;
}

function formatarNome(n) {
  const baixas = new Set(["da", "de", "do", "das", "dos", "e"]);
  return String(n).toLowerCase().split(/\s+/).map((p, i) =>
    (i && baixas.has(p) ? p : p.charAt(0).toUpperCase() + p.slice(1))).join(" ");
}

function formatarDestino(d) {
  if (d.includes("@")) return d;
  const m = d.match(/^55(\d{2})(\d{5})(\d{4})$/);
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : d;
}

function telaAjustes() {
  const a = estado.ajustes;
  const campo = (id, rotulo, valor, tipo = "text", extra = {}) =>
    h("label", { class: "campo-f" }, rotulo, h("input", { id, type: tipo, value: valor, ...extra }));
  const retorno = h("div", { "aria-live": "polite" });
  const ok = (t) => retorno.replaceChildren(h("p", { class: "certo" }, t));
  const falha = (t) => retorno.replaceChildren(h("div", { class: "aviso", role: "alert" }, t));
  const v = (id) => document.getElementById(id).value.trim();

  const salvar = async () => {
    const horario = { janela_inicio: v("a-ini"), janela_fim: v("a-fim") };
    const resultados = await Promise.all([
      api().salvar_ajuste("email", { responder_para: v("a-resp"), tenant_id: v("a-tenant"), client_id: v("a-client"), ...horario }),
      api().salvar_ajuste("whatsapp", { ...horario, conversas_dia: Math.max(1, Math.round(Number(v("a-gotas")) || estado.ajustes.conversas_dia)) }),
      api().salvar_ajuste("campanha", { valor_minimo: Number(v("a-min")) }),
    ]);
    const erro = resultados.find((r) => r.erro);
    if (erro) { falha(erro.erro); return; }
    if (v("a-segredo")) {
      const r = await api().gravar_segredo(v("a-segredo"));
      if (r.erro) { falha(r.erro); return; }
      document.getElementById("a-segredo").value = "";
    }
    await atualizar();
    ok("Ajustes salvos.");
  };

  return h("div", { class: "tela" },
    h("h1", null, "Ajustes"),
    h("div", { class: "ajustes" },
      h("section", null, h("h2", null, "Respostas dos clientes"),
        campo("a-resp", "E-mail que recebe as respostas", a.responder_para, "text", { placeholder: "atendimento@exemplo.com" })),
      h("section", null, h("h2", null, "Horário de envio"),
        h("div", { class: "grade-2" }, campo("a-ini", "Começa às", a.janela_inicio, "time"), campo("a-fim", "Termina às", a.janela_fim, "time"))),
      h("section", null, h("h2", null, "WhatsApp em conta-gotas"),
        h("p", null, "Quantas conversas novas a linha abre por dia, espalhadas pelo horário de envio. Quanto maior, maior o risco de restrição."),
        campo("a-gotas", "Conversas novas por dia", a.conversas_dia, "number", { step: "1", min: "1" })),
      h("section", null, h("h2", null, "Quem entra na campanha"),
        h("p", null, "Vale na próxima vez que a planilha for carregada."),
        campo("a-min", "Valor mínimo em aberto (R$)", a.valor_minimo, "number", { step: "0.01", min: "0" }),
        h("p", { class: "nota" }, `Hoje entram vencimentos até ${dataBr(a.corte_hoje)}. Até o dia 15 ficam de fora os vencimentos do mês atual; do dia 16 em diante entram os que venceram do dia 1 ao dia 15.`)),
      h("section", null, h("h2", null, "Acesso do aplicativo de envio (Microsoft Graph)"),
        h("p", null, `Para a TI. Envio por ${a.remetente}. O segredo fica no cofre do Windows deste computador.`),
        h("div", { class: "grade-2" }, campo("a-tenant", "Tenant ID", a.tenant_id), campo("a-client", "Client ID", a.client_id)),
        campo("a-segredo", a.segredo_gravado ? "Segredo: já gravado neste computador. Preencha só para trocar." : "Segredo", "", "password", { autocomplete: "off" }))),
    retorno,
    h("div", { class: "acoes" },
      h("button", { class: "b", onclick: salvar }, "Salvar ajustes"),
      h("button", { class: "b s", onclick: exportar }, "Exportar relatório")));
}

/* ---- pintura ---------------------------------------------------------- */

const TELAS = {
  planilha: telaPlanilha, fora: telaFora, mensagens: telaMensagens, ensaio: telaEnsaio,
  disparo: telaDisparo, contatos: telaContatos, ajustes: telaAjustes,
};
/* Telas com campos de texto não podem ser refeitas enquanto a pessoa digita. */
const COM_CAMPOS = new Set(["mensagens", "ajustes", "contatos", "fora"]);

function resumoParaAssinatura() {
  const canais = Object.fromEntries(Object.entries(estado.canais).map(([c, v]) => [c, {
    texto: v.texto_definido, ensaio: v.ensaio_aprovado, tarefa: v.tarefa, total: v.total,
    pendente: v.contagem.pendente > 0, conferir: (v.contagem.incerto || 0) + (v.contagem.falhou || 0),
    enviou: (v.contagem.enviado || 0) > 0,
    ultimo: telaAtual === "disparo" && v.recentes[0] ? v.recentes[0].id : 0,
  }]));
  return JSON.stringify([telaAtual, canais, estado.importacao && estado.importacao.quando, estado.internos,
    estado.ajustes, estado.janela_aberta, local.lendo, local.erroPlanilha, local.editandoInternos, local.confirmar]);
}

function pintar(forcar) {
  if (!estado) return;
  pintarPassos();
  document.body.classList.toggle("acompanhando", telaAtual === "disparo" && acompanhando());

  const nova = resumoParaAssinatura();
  const mudou = nova !== assinatura;
  if (forcar || (mudou && !COM_CAMPOS.has(telaAtual))) {
    assinatura = nova;
    const foco = document.activeElement && document.activeElement.dataset.manterFoco;
    const conteudo = TELAS[telaAtual]();
    const raiz = conteudo.nodeType ? conteudo : h("div", { class: "tela" }, conteudo);
    if (forcar === true) raiz.style.animation = "";
    else raiz.style.animation = "none";
    $("#tela").replaceChildren(raiz);
    if (foco) { const el = document.querySelector(`[data-manter-foco="${foco}"]`); if (el) el.focus(); }
  }
  document.querySelectorAll("[data-conta]").forEach((el) => { el.textContent = num(enviados(el.dataset.conta)); });
  pintarPainel();
}

/* ---- painel de lâmpadas ----------------------------------------------- */

const cv = $("#lampadas");
const cx = cv.getContext("2d");
const halo = document.createElement("canvas");
halo.width = halo.height = 64;
{
  const c = halo.getContext("2d");
  const g = c.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, "rgba(246,232,196,.2)");
  g.addColorStop(1, "rgba(246,232,196,0)");
  c.fillStyle = g; c.fillRect(0, 0, 64, 64);
}
const semMovimento = matchMedia("(prefers-reduced-motion: reduce)").matches;
let mapa = [];
let mapaAnterior = [];
let geometria = null;
const acesasEm = new Map();
let animando = false;

function pintarPainel() {
  const msgs = telaAtual === "mensagens";
  $("#previas").hidden = !msgs;
  $("#campo").hidden = msgs;
  $("#legenda").hidden = msgs;
  $("#leitura").hidden = msgs;
  $("#painel-canais").hidden = msgs;
  $("#painel-titulo").textContent = msgs ? "Como vai chegar" : "Painel da campanha";
  document.querySelectorAll("[data-painel]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.painel === painelCanal)));
  $("#painel-vazio").hidden = Boolean(estado.importacao);
  cv.setAttribute("aria-label", `${num(enviados(painelCanal))} de ${num(totalCanal(painelCanal))} contatos avisados por ${CANAL[painelCanal]}`);
  if (!msgs) carregarMapa();
}

async function carregarMapa() {
  const novo = await api().mapa(painelCanal);
  if (!semMovimento && mapaAnterior.length === novo.length) {
    const agora = performance.now();
    novo.forEach((s, i) => { if (s === "enviado" && mapaAnterior[i] !== "enviado") acesasEm.set(i, agora); });
  }
  mapa = novo; mapaAnterior = novo;
  desenhar();
}

function corDe(status) {
  if (status === "enviado") return "#f6e8c4";
  if (status === "enviando") return "#e0a24a";
  if (status === "incerto" || status === "falhou") return "#d9583c";
  return "#3b474d";
}

function desenhar() {
  const caixa = cv.parentElement;
  const w = caixa.clientWidth, alt = caixa.clientHeight;
  if (!w || !alt) return;
  const d = devicePixelRatio || 1;
  if (cv.width !== Math.round(w * d) || cv.height !== Math.round(alt * d)) { cv.width = Math.round(w * d); cv.height = Math.round(alt * d); }
  cx.setTransform(d, 0, 0, d, 0, 0);
  cx.clearRect(0, 0, w, alt);

  const vazio = !mapa.length;
  const n = vazio ? 1500 : mapa.length;
  const col = Math.max(1, Math.floor(w / Math.sqrt((w * alt) / n)));
  const linhas = Math.ceil(n / col);
  const passo = Math.min(w / col, alt / linhas);
  const r = Math.min(3.6, passo * 0.3);
  const ox = (w - passo * col) / 2;
  geometria = { col, passo, ox, n };
  const agora = performance.now();
  let pendenteAnim = false;

  for (let i = 0; i < n; i++) {
    const x = ox + ((i % col) + 0.5) * passo;
    const y = (Math.floor(i / col) + 0.5) * passo;
    const s = vazio ? "" : mapa[i];
    if (s === "enviado") {
      let brilho = 1;
      const t0 = acesasEm.get(i);
      if (t0 !== undefined) {
        const p = (agora - t0) / 900;
        if (p >= 1) acesasEm.delete(i);
        else { brilho = 1 + (1 - p) * (1 - p) * 2.4; pendenteAnim = true; }
      }
      const tam = Math.min(passo * 1.7, r * 5.5) * brilho;
      cx.drawImage(halo, x - tam / 2, y - tam / 2, tam, tam);
    }
    if (s === "sem_whatsapp" || s === "cancelado" || s === "devolvido") {
      cx.strokeStyle = "#5d6b72"; cx.lineWidth = 1;
      cx.beginPath(); cx.arc(x, y, r - 0.5, 0, 7); cx.stroke();
      continue;
    }
    cx.fillStyle = vazio ? "#2a3337" : corDe(s);
    cx.beginPath(); cx.arc(x, y, r, 0, 7); cx.fill();
  }
  if (pendenteAnim && !animando) {
    animando = true;
    requestAnimationFrame(() => { animando = false; desenhar(); });
  }
}

function lampadaEm(ev) {
  if (!geometria || !mapa.length) return -1;
  const q = cv.getBoundingClientRect();
  const c = Math.floor((ev.clientX - q.left - geometria.ox) / geometria.passo);
  const l = Math.floor((ev.clientY - q.top) / geometria.passo);
  if (c < 0 || c >= geometria.col || l < 0) return -1;
  const i = l * geometria.col + c;
  return i < mapa.length ? i : -1;
}

cv.addEventListener("mousemove", (ev) => {
  const i = lampadaEm(ev);
  cv.classList.toggle("interativo", i >= 0);
  if (i >= 0) {
    const nome = (SITUACAO[mapa[i]] || [mapa[i]])[0];
    $("#leitura").textContent = `Contato ${num(i + 1)} de ${num(mapa.length)}: ${nome}. Clique para ver quem é.`;
  }
});
cv.addEventListener("mouseleave", () => { $("#leitura").textContent = ""; });
cv.addEventListener("click", async (ev) => {
  const i = lampadaEm(ev);
  if (i < 0) return;
  const r = await api().listar(painelCanal, "", "", i);
  const item = r.itens[0];
  if (!item) return;
  const nomes = item.pessoas.map((p) => formatarNome(p.nome)).join(", ");
  const inscr = item.pessoas.flatMap((p) => p.planos.map(([n]) => n)).join(", ");
  const leitura = $("#leitura");
  leitura.replaceChildren(h("b", null, nomes), ` · Inscrição ${inscr} · ${(SITUACAO[item.status] || [item.status])[0]}`);
});
new ResizeObserver(() => desenhar()).observe($("#campo"));

/* ---- ciclo ------------------------------------------------------------ */

async function atualizar() {
  estado = await api().estado();
  pintar(false);
}

document.addEventListener("click", (ev) => {
  const alvo = ev.target.closest("[data-ir]");
  if (alvo) { local.editandoInternos = false; ir(alvo.dataset.ir); return; }
  const canal = ev.target.closest("[data-painel]");
  if (canal) { painelCanal = canal.dataset.painel; mapaAnterior = []; pintarPainel(); }
});

window.addEventListener("pywebviewready", async () => {
  estado = await api().estado();
  telaAtual = !estado.importacao ? "planilha" : acompanhando() ? "disparo" : "planilha";
  document.body.dataset.tela = telaAtual;
  pintar(true);
  setInterval(() => atualizar().catch(() => {}), 1500);
});
