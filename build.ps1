# Gera o programa e o instalador. Aborta se algum teste falhar.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& .venv\Scripts\python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Testes falharam: nada foi empacotado." }
& .venv\Scripts\python -m PyInstaller CampanhaDeAvisos.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar." }
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" instalador\CampanhaDeAvisos.iss
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o instalador." }
