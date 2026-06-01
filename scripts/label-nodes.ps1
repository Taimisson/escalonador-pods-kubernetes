# aqui mora o "truque" do trabalho: o kind cria workers iguais, então eu coloco
# labels diferentes de disco e latência em cada um pra simular hardware distinto.
# é isso que o k8s_model.py lê depois pra montar o WorkerState.
. "$PSScriptRoot\_common.ps1"

$nodesJson = kubectl get nodes -o json | ConvertFrom-Json
$workers = @(
    $nodesJson.items |
        Where-Object {
            $labelNames = @()
            if ($_.metadata.labels) {
                $labelNames = @($_.metadata.labels.PSObject.Properties.Name)
            }
            -not ($labelNames -contains "node-role.kubernetes.io/control-plane") -and
            -not ($labelNames -contains "node-role.kubernetes.io/master")
        } |
        ForEach-Object { $_.metadata.name } |
        Sort-Object
)

if ($workers.Count -lt 2) {
    throw "O trabalho exige no minimo 2 workers. Workers encontrados: $($workers.Count)"
}

$configs = @(
    @{ diskMib = "1200"; latencyMs = "10"; profile = "balanced"; diskClass = "medium"; latencyClass = "low"    },
    @{ diskMib = "2200"; latencyMs = "35"; profile = "storage";  diskClass = "high";   latencyClass = "medium" },
    @{ diskMib = "900";  latencyMs = "85"; profile = "memory";   diskClass = "low";    latencyClass = "high"   }
)

for ($i = 0; $i -lt $workers.Count; $i++) {
    $node = $workers[$i]
    $cfg = $configs[$i % $configs.Count]
    kubectl label node $node `
        "scheduler.lab/role=worker" `
        "scheduler.lab/disk-mib=$($cfg.diskMib)" `
        "scheduler.lab/latency-ms=$($cfg.latencyMs)" `
        "scheduler.lab/profile=$($cfg.profile)" `
        "scheduler.lab/disk-class=$($cfg.diskClass)" `
        "scheduler.lab/latency-class=$($cfg.latencyClass)" `
        --overwrite
}

kubectl get nodes -L scheduler.lab/role,scheduler.lab/disk-mib,scheduler.lab/latency-ms,scheduler.lab/profile
