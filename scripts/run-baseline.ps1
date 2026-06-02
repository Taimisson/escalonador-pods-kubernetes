# roda a bateria do scheduler padrao q é limpar, criar os Pods default, esperar assentar e gera o snapshot baseline que vai servir de comparação.
. "$PSScriptRoot\_common.ps1"

Push-Location $RepoRoot
try {
    kubectl delete pod -n scheduler-lab -l "scheduler.lab/workload=test" --ignore-not-found --wait=true
    kubectl apply -f k8s/pods/default-scheduler-pods.yaml
    Start-Sleep -Seconds 8
    kubectl get pods -n scheduler-lab -o wide
    Invoke-RepoPython -m scheduler_lab.cli report `
        --namespace scheduler-lab `
        --batch default `
        --output-json reports/baseline-snapshot.json
}
finally {
    Pop-Location
}
