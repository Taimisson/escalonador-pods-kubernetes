# implanta o operator no cluster de ponta a ponta
# builda a imagem -> carrega no kind -> aplica os YAMLs -> espera o rollout
# -NoBuild pula o build se a imagem já estiver pronta.
param(
    [string]$ClusterName = "sisop-scheduler",
    [string]$ImageName = "custom-scheduler-operator:0.1.0",
    [switch]$NoBuild
)

. "$PSScriptRoot\_common.ps1"

Assert-Command docker
Assert-Command kind
Assert-Command kubectl

Push-Location $RepoRoot
try {
    if (-not $NoBuild) {
        & "$PSScriptRoot\build-operator-image.ps1" -ImageName $ImageName
    }

    # carrega a imagem direto no kind (sem registry) por isso o Deployment usa IfNotPresent
    kind load docker-image $ImageName --name $ClusterName

    kubectl apply -f k8s/namespace.yaml
    kubectl apply -f k8s/rbac.yaml
    kubectl apply -f k8s/operator-policy-configmap.yaml
    kubectl apply -f k8s/operator-deployment.yaml

    kubectl delete pod -n scheduler-lab -l app.kubernetes.io/name=custom-scheduler-operator --ignore-not-found --wait=true
    kubectl rollout status deployment/custom-scheduler-operator -n scheduler-lab --timeout=120s
    kubectl get pods -n scheduler-lab -l app.kubernetes.io/name=custom-scheduler-operator -o wide
}
finally {
    Pop-Location
}

Write-Host "`nOperator custom-scheduler implantado no cluster."
