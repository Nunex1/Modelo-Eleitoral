$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonLampiadim = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonLampiadim)) {
    throw 'Ambiente .venv ausente. Crie-o com python -m venv .venv e instale Lampiadim_MVP/requirements.txt.'
}
& $pythonLampiadim -m streamlit run Lampiadim_MVP/app.py --server.address 127.0.0.1 --server.port 8501
