# cria o cluster kind (se já não existir), aplica os YAMLs base e rotula os workers.
# é o primeiro passo depois de instalar as deps.
param(
    [string]$ClusterName = "sisop-scheduler"
)

. "$PSScriptRoot\_common.ps1"

Assert-Command docker
Assert-Command kind
Assert-Command kubectl

Push-Location $RepoRoot
try {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $clustersOutput = @(kind get clusters 2>$null)
    $kindExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference

    if ($kindExitCode -eq 0) {
        $clusters = @($clustersOutput)
    }
    else {
        $clusters = @()
    }

    if ($clusters -notcontains $ClusterName) {
        kind create cluster --name $ClusterName --config k8s/kind-cluster.yaml --wait 120s
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao criar o cluster kind '$ClusterName'. Verifique Docker Desktop/WSL2 e tente novamente."
        }
    }
    else {
        Write-Host "Cluster kind '$ClusterName' ja existe."
    }

    kubectl config use-context "kind-$ClusterName"
    if ($LASTEXITCODE -ne 0) {
        throw "Contexto kubectl kind-$ClusterName nao encontrado. O cluster nao foi criado corretamente."
    }

    & "$PSScriptRoot\apply-yamls.ps1"
    & "$PSScriptRoot\label-nodes.ps1"
    kubectl get nodes -o wide
}
finally {
    Pop-Location
}
