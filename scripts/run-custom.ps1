# roda a bateria do scheduler customizado q implanta o operator, cria os Pods custom, espera todos receberem node, puxa os logs/decisões e gera o snapshot custom.
. "$PSScriptRoot\_common.ps1"

Push-Location $RepoRoot
try {
    kubectl delete pod -n scheduler-lab -l "scheduler.lab/workload=test" --ignore-not-found --wait=true

    $logPath = Join-Path $RepoRoot "reports\custom-scheduler.log"
    $decisionPath = Join-Path $RepoRoot "reports\custom-decisions.jsonl"
    Remove-Item -LiteralPath $logPath,$decisionPath -ErrorAction SilentlyContinue

    & "$PSScriptRoot\deploy-operator.ps1"

    kubectl apply -f k8s/pods/custom-scheduler-pods.yaml

    # fica observando até todos os 15 Pods receberem nodeName ou estourar o tempo.
    # é o operator fazendo o binding ao vivo enquanto esse loop acompanha
    $deadline = (Get-Date).AddSeconds(150)
    do {
        Start-Sleep -Seconds 2
        $podsJson = kubectl get pods -n scheduler-lab -l "scheduler.lab/batch=custom" -o json | ConvertFrom-Json
        $scheduled = @($podsJson.items | Where-Object { $_.spec.nodeName })
        $total = @($podsJson.items).Count
        Write-Host "Pods customizados alocados: $($scheduled.Count)/$total"
    } while (($total -lt 15 -or $scheduled.Count -lt $total) -and (Get-Date) -lt $deadline)

    if ($scheduled.Count -lt $total) {
        kubectl get pods -n scheduler-lab -o wide
        throw "Nem todos os Pods customizados receberam nodeName dentro do tempo esperado."
    }

    kubectl logs -n scheduler-lab deployment/custom-scheduler-operator --tail=300 | Tee-Object -FilePath $logPath
    $decisionContent = kubectl exec -n scheduler-lab deployment/custom-scheduler-operator -- cat /tmp/custom-decisions.jsonl
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($decisionPath, (($decisionContent -join [Environment]::NewLine) + [Environment]::NewLine), $utf8NoBom)

    Start-Sleep -Seconds 5
    kubectl get pods -n scheduler-lab -o wide
    Invoke-RepoPython -m scheduler_lab.cli report `
        --namespace scheduler-lab `
        --batch custom `
        --decision-log reports/custom-decisions.jsonl `
        --output-json reports/custom-snapshot.json
}
finally {
    Pop-Location
}
