# apaga o cluster kind inteiro. usado no fim de tudo pra limpar a máquina
param(
    [string]$ClusterName = "sisop-scheduler"
)

. "$PSScriptRoot\_common.ps1"

Assert-Command kind
kind delete cluster --name $ClusterName
