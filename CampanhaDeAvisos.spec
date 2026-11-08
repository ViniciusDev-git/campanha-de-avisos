# -*- mode: python ; coding: utf-8 -*-
"""Empacotamento da Campanha de Avisos.

A interface (HTML, CSS, fontes) vai dentro do programa, e o motor do Playwright
também: quem recebe o instalador não precisa de Python nem de Node. O navegador
não vai junto, porque a ferramenta usa o Chrome ou o Edge já instalados.
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

webview_dados, webview_binarios, webview_ocultos = collect_all("webview")
playwright_dados = collect_data_files("playwright")

analise = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=webview_binarios,
    datas=[("disparo/ui", "disparo/ui"), *webview_dados, *playwright_dados],
    hiddenimports=[
        *webview_ocultos,
        *collect_submodules("playwright"),
        # keyring acha o cofre do Windows por entry point, invisível à análise.
        "keyring.backends.Windows",
        "clr_loader",
        "pythonnet",
        "msal",
        "httpx",
    ],
    excludes=["tkinter", "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "numpy"],
    noarchive=False,
)

pacote = PYZ(analise.pure)

programa = EXE(
    pacote,
    analise.scripts,
    [],
    exclude_binaries=True,
    name="CampanhaDeAvisos",
    console=False,
    icon="disparo/ui/icone.ico",
    version=None,
)

COLLECT(programa, analise.binaries, analise.datas, name="CampanhaDeAvisos")
