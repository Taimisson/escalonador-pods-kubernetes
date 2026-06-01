# confere se as ferramentas obrigatórias estão instaladas antes de começar.
# evita erro chato no meio do caminho por falta de docker/kind/kubectl
. "$PSScriptRoot\_common.ps1"

$tools = @("docker", "kind", "kubectl", "git")
foreach ($tool in $tools) {
    Assert-Command $tool
    Write-Host "[ok] $tool"
}

$python = Get-RepoPython
& $python --version

Write-Host "`nFerramentas basicas encontradas."
