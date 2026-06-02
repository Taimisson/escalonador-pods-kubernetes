# roda o scheduler direto na máquina (sem operator no cluster), usando o kubeconfig local útil pra debugar o algoritmo ao vivo sem ter que rebuildar a imagem toda hora.
param(
    [int]$MaxPods = 15,
    [string]$Namespace = "scheduler-lab"
)

. "$PSScriptRoot\_common.ps1"

Invoke-RepoPython -m scheduler_lab.cli schedule `
    --namespace $Namespace `
    --scheduler-name custom-scheduler `
    --report reports/custom-decisions.jsonl `
    --policy-file k8s/operator-policy-configmap.yaml `
    --max-pods $MaxPods `
    --idle-timeout 180
