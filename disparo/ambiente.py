"""Onde a campanha mora em disco e como a configuração é carregada.

O `config.toml` traz os padrões; o que a pessoa ajusta pela janela fica em
`dados/ajustes.json`, por cima dele. Assim uma atualização do programa nunca
apaga o que foi configurado.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import tomllib
from datetime import time
from pathlib import Path

from .fila import Fila
from .ritmo import Janela


def _encontrar_raiz() -> Path:
    if os.environ.get("CAMPANHA_PASTA"):
        return Path(os.environ["CAMPANHA_PASTA"])
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent
    pasta = Path(sys.executable).resolve().parent
    for candidata in (pasta, *pasta.parents):
        if (candidata / "config.toml").exists():
            return candidata
    return pasta


RAIZ = _encontrar_raiz()

# Dois canais terminam juntos e a tela salva vários grupos em paralelo: sem esta
# trava, uma gravação apaga a outra.
TRAVA_ARQUIVOS = threading.Lock()


def caminho(bruto: str) -> Path:
    p = Path(bruto)
    return p if p.is_absolute() else RAIZ / p


def _arquivo_ajustes(cfg: dict) -> Path:
    return caminho(cfg["campanha"]["banco"]).parent / "ajustes.json"


def carregar_config() -> dict:
    with open(RAIZ / "config.toml", "rb") as arquivo:
        cfg = tomllib.load(arquivo)
    ajustes = _arquivo_ajustes(cfg)
    if ajustes.exists():
        for secao, valores in json.loads(ajustes.read_text(encoding="utf-8")).items():
            cfg.setdefault(secao, {}).update(valores)
    return cfg


def salvar_ajustes(cfg: dict, secao: str, valores: dict) -> None:
    arquivo = _arquivo_ajustes(cfg)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with TRAVA_ARQUIVOS:
        atuais = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
        atuais.setdefault(secao, {}).update(valores)
        arquivo.write_text(json.dumps(atuais, ensure_ascii=False, indent=2), encoding="utf-8")


def abrir_fila(cfg: dict) -> Fila:
    return Fila(caminho(cfg["campanha"]["banco"]))


def janela_de(secao: dict) -> Janela:
    return Janela(
        time.fromisoformat(secao["janela_inicio"]),
        time.fromisoformat(secao["janela_fim"]),
        tuple(secao["dias"]),
    )
