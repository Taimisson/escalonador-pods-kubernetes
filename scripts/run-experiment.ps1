# Roda a comparacao default x custom N vezes e agrega os resultados.
# Serve pra mostrar a VARIABILIDADE entre execucoes (a ordem de chegada dos
# Pods muda a alocacao) e tirar media/min/max em vez de uma rodada so.
#
# Uso:   .\scripts\run-experiment.ps1 -Runs 20
# Saida: reports\experiment-runs.csv  (uma linha por execucao)  + resumo no console
#
# Obs.: cada execucao roda a bateria default e a custom (via compare-schedulers.ps1),
# entao 20 execucoes levam alguns minutos. Comece com -Runs 10 pra testar.
param([int]$Runs = 20)

. "$PSScriptRoot\_common.ps1"

$csv = Join-Path $RepoRoot "reports\experiment-runs.csv"
"run,baseline_disk_imb,baseline_lat,baseline_cpu_imb,baseline_mem_imb,custom_disk_imb,custom_lat,custom_cpu_imb,custom_mem_imb" |
    Out-File -FilePath $csv -Encoding utf8

for ($i = 1; $i -le $Runs; $i++) {
    Write-Host "`n========== Execucao $i / $Runs ==========" -ForegroundColor Cyan
    & "$PSScriptRoot\compare-schedulers.ps1"

    $c = Get-Content (Join-Path $RepoRoot "reports\comparison.json") -Raw | ConvertFrom-Json
    $b = $c.baseline; $u = $c.custom
    "$i,$($b.disk_imbalance),$($b.avg_pod_latency_ms),$($b.cpu_imbalance),$($b.memory_imbalance),$($u.disk_imbalance),$($u.avg_pod_latency_ms),$($u.cpu_imbalance),$($u.memory_imbalance)" |
        Add-Content -Path $csv
}

# ----- resumo -----
$rows = Import-Csv $csv
function Stat([double[]]$vals) {
    $m = $vals | Measure-Object -Average -Minimum -Maximum
    $sd = if ($vals.Count -gt 1) {
        [math]::Sqrt((($vals | ForEach-Object { ($_ - $m.Average) * ($_ - $m.Average) } | Measure-Object -Sum).Sum) / $vals.Count)
    } else { 0 }
    "media={0:N3}  desvio={1:N3}  min={2:N3}  max={3:N3}" -f $m.Average, $sd, $m.Minimum, $m.Maximum
}
Write-Host "`n=== RESUMO ($Runs execucoes) ===" -ForegroundColor Green
Write-Host ("desequilibrio disco  default: " + (Stat ([double[]]($rows.baseline_disk_imb))))
Write-Host ("desequilibrio disco  custom : " + (Stat ([double[]]($rows.custom_disk_imb))))
Write-Host ("latencia media (ms)  default: " + (Stat ([double[]]($rows.baseline_lat))))
Write-Host ("latencia media (ms)  custom : " + (Stat ([double[]]($rows.custom_lat))))
Write-Host "`nCSV completo salvo em: $csv"
Write-Host "(disco em fracao: 0,667 = 66,7%)"
