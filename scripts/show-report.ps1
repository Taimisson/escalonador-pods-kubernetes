# mostra o relatório de uma bateria no terminal (sem salvar JSON).
# na bateria custom também passa o log de decisões pra aparecer os scores.
param(
    [ValidateSet("default", "custom")]
    [string]$Batch = "custom"
)

. "$PSScriptRoot\_common.ps1"

$args = @(
    "-m", "scheduler_lab.cli", "report",
    "--namespace", "scheduler-lab",
    "--batch", $Batch
)

if ($Batch -eq "custom") {
    $args += @("--decision-log", "reports/custom-decisions.jsonl")
}

Invoke-RepoPython @args
