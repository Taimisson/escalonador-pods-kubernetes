# cria o .venv (se ainda não existir) e instala as dependências do projeto.
# instala em modo editável (-e .) pra poder importar scheduler_lab sem mexer no PYTHONPATH
. "$PSScriptRoot\_common.ps1"

Push-Location $RepoRoot
try {
    if (-not (Test-Path ".venv")) {
        $python = Get-RepoPython
        & $python -m venv .venv
    }

    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    & $venvPython -m pip install -e .
}
finally {
    Pop-Location
}

Write-Host "`nDependencias instaladas em .venv."
