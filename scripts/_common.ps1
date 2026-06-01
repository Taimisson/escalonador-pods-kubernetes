# funções compartilhadas pelos outros scripts. todo .ps1 começa com . "$PSScriptRoot\_common.ps1" pra herdar essas helpers e o $RepoRoot.
$ErrorActionPreference = "Stop"

# raiz do repo (uma pasta acima de scripts/). uso pra rodar tudo do lugar certo
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# acha o Python certo: prioriza o do .venv, senão tenta python ou py do sistema
function Get-RepoPython {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return "py"
    }
    throw "Python nao encontrado. Instale Python 3.10+ antes de continuar."
}

# roda o Python do repo já dentro da pasta raiz (pra achar o pacote src/)
function Invoke-RepoPython {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    $python = Get-RepoPython
    Push-Location $RepoRoot
    try {
        & $python @Arguments
    }
    finally {
        Pop-Location
    }
}

# garante que uma ferramenta existe (docker, kind, kubectl...) ou aborta com erro claro
function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Comando obrigatorio nao encontrado: $Name"
    }
}
