"""Ponto de entrada da janela. É este arquivo que vira o .exe.

`CampanhaDeAvisos.exe --diagnostico` confere, sem enviar nada, se esta máquina tem
o que o programa precisa, e grava o resultado em saida/diagnostico.txt.
"""

import sys


def diagnostico() -> None:
    from datetime import datetime

    from disparo.ambiente import RAIZ

    linhas = [f"Diagnóstico de {datetime.now():%d/%m/%Y %H:%M}", f"Pasta: {RAIZ}"]

    def conferir(nome, teste):
        try:
            linhas.append(f"OK    {nome}: {teste()}")
        except Exception as erro:
            linhas.append(f"FALHA {nome}: {erro}")

    def navegador():
        from playwright.sync_api import Error, sync_playwright

        with sync_playwright() as pw:
            for canal in ("chrome", "msedge"):
                try:
                    b = pw.chromium.launch(channel=canal, headless=True)
                    versao = b.version
                    b.close()
                    return f"{canal} {versao}"
                except Error:
                    continue
        raise RuntimeError("nem Chrome nem Edge abriram")

    def cofre():
        import keyring

        return type(keyring.get_keyring()).__name__

    def graph():
        import httpx
        import msal

        return f"msal {msal.__version__}, httpx {httpx.__version__}"

    def planilha():
        import openpyxl

        return openpyxl.__version__

    def interface():
        from disparo.janela import pasta_interface

        return "encontrada" if (pasta_interface() / "index.html").exists() else "AUSENTE"

    conferir("Navegador", navegador)
    conferir("Cofre do Windows", cofre)
    conferir("Envio de e-mail", graph)
    conferir("Leitor de planilha", planilha)
    conferir("Interface", interface)

    pasta = RAIZ / "saida"
    pasta.mkdir(exist_ok=True)
    (pasta / "diagnostico.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if "--diagnostico" in sys.argv:
        diagnostico()
    else:
        from disparo.janela import abrir

        abrir()
