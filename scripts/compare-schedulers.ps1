# o script roda a bateria default, depois a custom, e no fim gera o comparison.json com o comparativo das duas estratégias.
. "$PSScriptRoot\_common.ps1"

Push-Location $RepoRoot
try {
    Write-Host "`n=== Rodando bateria com default-scheduler ==="
    & "$PSScriptRoot\run-baseline.ps1"

    Write-Host "`n=== Rodando bateria com custom-scheduler ==="
    & "$PSScriptRoot\run-custom.ps1"

    Invoke-RepoPython -m scheduler_lab.cli compare `
        --baseline reports/baseline-snapshot.json `
        --custom reports/custom-snapshot.json `
        --output-json reports/comparison.json
}
finally {
    Pop-Location
}
