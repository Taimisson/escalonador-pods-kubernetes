# cria os Pods de teste de uma bateria (default, custom ou as duas)
# por padrão limpa os Pods antigos antes. -NoCleanup pula essa limpeza
param(
    [ValidateSet("default", "custom", "both")]
    [string]$Mode = "custom",
    [switch]$NoCleanup
)

. "$PSScriptRoot\_common.ps1"

Push-Location $RepoRoot
try {
    if (-not $NoCleanup) {
        if ($Mode -eq "both") {
            kubectl delete pod -n scheduler-lab -l "scheduler.lab/workload=test" --ignore-not-found --wait=true
        }
        else {
            kubectl delete pod -n scheduler-lab -l "scheduler.lab/batch=$Mode" --ignore-not-found --wait=true
        }
    }

    if ($Mode -eq "default" -or $Mode -eq "both") {
        kubectl apply -f k8s/pods/default-scheduler-pods.yaml
    }
    if ($Mode -eq "custom" -or $Mode -eq "both") {
        kubectl apply -f k8s/pods/custom-scheduler-pods.yaml
    }

    kubectl get pods -n scheduler-lab -o wide
}
finally {
    Pop-Location
}
