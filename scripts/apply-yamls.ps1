# aplica os manifestos base: namespace, RBAC e o ConfigMap de pesos.
# o Deployment do operator é aplicado separado no deploy-operator.ps1
. "$PSScriptRoot\_common.ps1"

Push-Location $RepoRoot
try {
    kubectl apply -f k8s/namespace.yaml
    kubectl apply -f k8s/rbac.yaml
    kubectl apply -f k8s/operator-policy-configmap.yaml
}
finally {
    Pop-Location
}

Write-Host "`nNamespace, RBAC e politica do Operator aplicados."
