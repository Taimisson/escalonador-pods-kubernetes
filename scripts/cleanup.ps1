# limpeza em níveis: sem flag só apaga os Pods de teste
# -DeleteOperator tira também o operator e o ConfigMap
# -DeleteNamespace apaga o namespace inteiro de uma vez
param(
    [switch]$DeleteNamespace,
    [switch]$DeleteOperator
)

. "$PSScriptRoot\_common.ps1"

if ($DeleteNamespace) {
    kubectl delete namespace scheduler-lab --ignore-not-found
}
else {
    kubectl delete pod -n scheduler-lab -l "scheduler.lab/workload=test" --ignore-not-found --wait=true
    if ($DeleteOperator) {
        kubectl delete deployment -n scheduler-lab custom-scheduler-operator --ignore-not-found
        kubectl delete configmap -n scheduler-lab custom-scheduler-policy --ignore-not-found
    }
}

Write-Host "`nLimpeza concluida."
