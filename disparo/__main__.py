"""Linha de comando da campanha, para a TI. Ver `python -m disparo --help`."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime

from . import fila as F
from . import operacao as O
from . import planilha
from .ambiente import abrir_fila, caminho, carregar_config
from .modelos import ModeloInvalido, Modelos
from .motor import ParadaObrigatoria, _mascarar
from .ritmo import PERFIS


def cmd_preparar(args, cfg) -> int:
    r = O.preparar(cfg, args.planilha)
    print(f"Linhas lidas ......... {r['linhas']}")
    print(f"Pessoas na campanha .. {r['pessoas']}")
    print(f"Retidas .............. {r['retidos']}  -> {r['arquivo_retidos']}")
    for motivo, n in r["motivos_retidos"].items():
        print(f"    {motivo}: {n}")
    print(f"Sem celular valido ... {sum(r['sem_celular'].values())}  {r['sem_celular']}")
    print(f"Sem e-mail valido .... {sum(r['sem_email'].values())}  {r['sem_email']}")
    print(f"Com envio pendente ... {r['pendentes']}")
    print(f"Fila: {r['fila']}")
    return 0


def cmd_status(args, cfg) -> int:
    fila = abrir_fila(cfg)
    for canal, contagem in fila.contagem().items():
        print(f"{canal:<9} " + (", ".join(f"{k}={v}" for k, v in sorted(contagem.items())) or "vazio"))
    pendentes = fila.contagem()["whatsapp"].get(F.PENDENTE, 0)
    print("\nProjecao do WhatsApp (estimativa, sem contar paradas):")
    for nome in ("prudente", "padrao", "acelerado"):
        por_hora = PERFIS[nome].por_hora()
        print(f"  {nome:<10} ~{por_hora}/h -> {pendentes / por_hora:.1f} h de janela")
    fila.fechar()
    return 0


def cmd_previa(args, cfg) -> int:
    fila = abrir_fila(cfg)
    modelos = Modelos(caminho(cfg["campanha"]["mensagens"]), args.canal)
    for item in fila.amostra(args.canal, args.quantos, args.agrupados):
        conteudo = modelos.montar(item.contatos)
        print(f"--- para {_mascarar(item.destino)}")
        print(conteudo.get("texto") or f"Assunto: {conteudo['assunto']}\n{conteudo['html']}")
    fila.fechar()
    return 0


def cmd_liberar(args, cfg) -> int:
    fila = abrir_fila(cfg)
    print(f"{fila.liberar_incertos(args.canal)} envio(s) incerto(s) voltaram para a fila.")
    fila.fechar()
    return 0


def cmd_relatorio(args, cfg) -> int:
    fila = abrir_fila(cfg)
    saida = caminho(cfg["campanha"]["saida"])
    saida.mkdir(exist_ok=True)
    arquivo = saida / f"relatorio-{datetime.now():%Y%m%d-%H%M%S}.csv"
    linhas = fila.relatorio()
    with open(arquivo, "w", newline="", encoding="utf-8-sig") as f:
        escrita = csv.writer(f, delimiter=";")
        escrita.writerow(linhas[0].keys() if linhas else [])
        escrita.writerows(tuple(l) for l in linhas)
    print(f"{len(linhas)} linhas -> {arquivo}")
    fila.fechar()
    return 0


def cmd_teste(args, cfg) -> int:
    r = O.ensaiar(cfg, args.canal)
    print(f"\nEnviados: {r['enviados']} de {r['total']}  Outros: {r['outros']}")
    if not r["aprovado"]:
        print(f"ENSAIO REPROVADO: {r['motivo']}.")
        return 1
    print("Ensaio aprovado. Confira nos aparelhos e caixas se chegou tudo e se o texto esta certo.")
    return 0


def cmd_enviar(args, cfg) -> int:
    if not args.confirmar:
        print("Nada foi enviado. Este comando dispara para clientes reais: use --confirmar.")
        return 1
    balanco = O.disparar(cfg, args.canal, args.maximo, args.ritmo, not args.sem_aguardar)
    print(f"\nEnviados: {balanco.enviados}  Outros: {balanco.outros}")
    print(f"Motivo da parada: {balanco.motivo_parada}")
    return 0 if balanco.motivo_parada == "fila concluida" else 2


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(prog="disparo", description="Campanha de inadimplencia")
    sub = p.add_subparsers(dest="comando", required=True)

    c = sub.add_parser("preparar", help="le a planilha e monta a fila")
    c.add_argument("planilha")
    c.set_defaults(fn=cmd_preparar)

    c = sub.add_parser("status", help="mostra o andamento")
    c.set_defaults(fn=cmd_status)

    c = sub.add_parser("previa", help="mostra as mensagens montadas, sem enviar")
    c.add_argument("canal", choices=F.CANAIS)
    c.add_argument("--quantos", type=int, default=3)
    c.add_argument("--agrupados", action="store_true", help="so contatos com varias pessoas")
    c.set_defaults(fn=cmd_previa)

    c = sub.add_parser("teste", help="ensaio com a lista interna; libera o disparo")
    c.add_argument("canal", choices=F.CANAIS)
    c.set_defaults(fn=cmd_teste)

    c = sub.add_parser("enviar", help="dispara para os clientes da fila")
    c.add_argument("canal", choices=F.CANAIS)
    c.add_argument("--confirmar", action="store_true")
    c.add_argument("--maximo", type=int, help="para depois de N envios (piloto)")
    c.add_argument("--ritmo", choices=("prudente", "padrao", "acelerado"))
    c.add_argument("--sem-aguardar", action="store_true", help="encerra ao fechar a janela")
    c.set_defaults(fn=cmd_enviar)

    c = sub.add_parser("liberar-incertos", help="devolve os incertos a fila, apos conferir")
    c.add_argument("canal", choices=F.CANAIS)
    c.set_defaults(fn=cmd_liberar)

    c = sub.add_parser("relatorio", help="exporta o resultado em CSV")
    c.set_defaults(fn=cmd_relatorio)

    args = p.parse_args()
    try:
        return args.fn(args, carregar_config())
    except (O.Recusado, ParadaObrigatoria, ModeloInvalido, planilha.PlanilhaInvalida) as erro:
        print(f"PARADA: {erro}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
