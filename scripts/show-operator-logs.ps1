# atalho pra ver os logs do Pod do operator (as decisões de score ao vivo)
. "$PSScriptRoot\_common.ps1"

kubectl logs -n scheduler-lab deployment/custom-scheduler-operator --tail=200
