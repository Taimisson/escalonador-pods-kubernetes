# builda a imagem Docker do operator a partir do Dockerfile na raiz
param(
    [string]$ImageName = "custom-scheduler-operator:0.1.0"
)

. "$PSScriptRoot\_common.ps1"

Assert-Command docker

Push-Location $RepoRoot
try {
    docker build -t $ImageName .
}
finally {
    Pop-Location
}

Write-Host "`nImagem do Operator criada: $ImageName"
