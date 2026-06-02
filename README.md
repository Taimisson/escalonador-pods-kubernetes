# Escalonador de Pods Kubernetes

Projeto individual de Laboratorio de Sistemas Operacionais usando Kubernetes real localmente com `kind` e um Operator customizado.

O objetivo e comparar o `default-scheduler` do Kubernetes com um **Operator de escalonamento** que roda dentro do proprio cluster e usa quatro metricas:

- CPU livre/ocupada;
- memoria livre/ocupada;
- disco/ephemeral-storage simulado por Worker;
- latencia de rede simulada por Worker.

O projeto cria um cluster com 1 control-plane e 3 workers, executa mais de 10 Pods com requisitos diferentes, mostra onde cada Pod foi alocado, calcula estatisticas por Worker e gera uma comparacao tecnica entre as duas estrategias.

Nesta versao, toda a parte de escalonamento customizado roda no Kubernetes:

- o algoritmo fica empacotado em uma imagem Docker;
- a imagem e carregada no cluster `kind`;
- o Operator roda como `Deployment`;
- os pesos do algoritmo ficam em um `ConfigMap`;
- as permissoes ficam em `ServiceAccount`, `ClusterRole` e `ClusterRoleBinding`;
- os Pods customizados usam `schedulerName: custom-scheduler`.

## Arquitetura

```text
Usuario / scripts
      |
      v
kind cluster local
      |
      +-- control-plane: API Server + default-scheduler
      |
      +-- worker 1: disk medio, baixa latencia
      +-- worker 2: disk alto, latencia media
      +-- worker 3: disk baixo, alta latencia
      |
      +-- custom-scheduler-operator (Deployment)
            |
            +-- le ConfigMap de politica
            +-- observa Pods Pending
            +-- calcula score por Worker
            +-- faz Binding Pod -> Worker

Pods default  -> schedulerName: default-scheduler
Pods custom   -> schedulerName: custom-scheduler
```

O Operator customizado nao substitui o scheduler nativo do cluster. Ele roda em paralelo e so processa Pods que possuem:

```yaml
spec:
  schedulerName: custom-scheduler
```

## Algoritmo

Para cada Pod pendente, o scheduler:

1. lista os Workers prontos;
2. calcula recursos ja ocupados por Pods ativos;
3. filtra Workers sem CPU, memoria ou disco suficientes;
4. calcula uma pontuacao para cada Worker viavel;
5. escolhe o maior score;
6. cria um `Binding` real pela API do Kubernetes;
7. anota o Pod com score/node escolhido;
8. grava a decisao em log dentro do Pod do Operator.

Formula base:

```text
score = peso_cpu     * cpu_livre_normalizada
      + peso_memoria * memoria_livre_normalizada
      + peso_disco   * disco_livre_normalizado
      + peso_latencia * latencia_normalizada
```

A latencia e normalizada de modo que menor latencia gera maior nota. Os pesos mudam conforme o perfil do Pod: `cpu`, `memory`, `storage`, `latency`, `balanced` ou `light`.

Os pesos ficam no Kubernetes em:

```text
k8s/operator-policy-configmap.yaml
```

## Estrutura

```text
.
|-- k8s/
|   |-- kind-cluster.yaml
|   |-- namespace.yaml
|   |-- rbac.yaml
|   |-- operator-policy-configmap.yaml
|   |-- operator-deployment.yaml
|   `-- pods/
|       |-- default-scheduler-pods.yaml
|       `-- custom-scheduler-pods.yaml
|-- scripts/
|   |-- check-tools.ps1
|   |-- install-deps.ps1
|   |-- build-operator-image.ps1
|   |-- deploy-operator.ps1
|   |-- create-cluster.ps1
|   |-- label-nodes.ps1
|   |-- run-baseline.ps1
|   |-- run-custom.ps1
|   |-- compare-schedulers.ps1
|   |-- show-report.ps1
|   |-- show-operator-logs.ps1
|   |-- cleanup.ps1
|   `-- delete-cluster.ps1
|-- src/scheduler_lab/
|   |-- cli.py
|   |-- k8s_scheduler.py
|   |-- k8s_model.py
|   |-- scoring.py
|   |-- reports.py
|   `-- quantity.py
|-- tests/
`-- reports/
```

## Pre-requisitos

Instale antes de executar:

- Docker Desktop;
- kind;
- kubectl;
- Python 3.10+;
- Git.

No Windows, uma forma simples de instalar `kind` e `kubectl` e via `winget`:

```powershell
winget install -e --id Kubernetes.kind
winget install -e --id Kubernetes.kubectl
```

Se ainda nao tiver Docker Desktop:

```powershell
winget install -e --id Docker.DockerDesktop
```

No PowerShell, entre na pasta do projeto:

```powershell
cd C:\Users\taimi\Desktop\sis_op\escalonador-pods-kubernetes
Set-ExecutionPolicy -Scope Process Bypass
```

Cheque ferramentas:

```powershell
.\scripts\check-tools.ps1
```

## Passo a passo completo

1. Instale as dependencias Python:

```powershell
.\scripts\install-deps.ps1
```

2. Crie o cluster local com 1 control-plane e 3 workers:

```powershell
.\scripts\create-cluster.ps1
```

3. Confira os Workers e as metricas simuladas:

```powershell
kubectl get nodes -L scheduler.lab/disk-mib,scheduler.lab/latency-ms,scheduler.lab/profile
```

4. Rode a bateria com o scheduler padrao:

```powershell
.\scripts\run-baseline.ps1
```

5. Implante o Operator no Kubernetes:

```powershell
.\scripts\deploy-operator.ps1
```

Esse script:

- cria a imagem Docker do Operator;
- carrega a imagem no cluster `kind`;
- aplica `ServiceAccount`, `RBAC`, `ConfigMap` e `Deployment`;
- espera o rollout do Operator.

6. Rode a bateria com o scheduler customizado via Operator:

```powershell
.\scripts\run-custom.ps1
```

7. Compare as duas execucoes:

```powershell
.\scripts\compare-schedulers.ps1
```

Esse script roda baseline, implanta o Operator, roda custom e gera:

- `reports/baseline-snapshot.json`;
- `reports/custom-snapshot.json`;
- `reports/custom-decisions.jsonl`;
- `reports/comparison.json`.

## Execucao manual acompanhando o Operator

Se quiser mostrar o Operator observando Pods pendentes ao vivo:

Terminal 1:

```powershell
cd C:\Users\taimi\Desktop\sis_op\escalonador-pods-kubernetes
.\scripts\deploy-operator.ps1
kubectl logs -n scheduler-lab deployment/custom-scheduler-operator -f
```

Terminal 2:

```powershell
cd C:\Users\taimi\Desktop\sis_op\escalonador-pods-kubernetes
.\scripts\create-pods.ps1 -Mode custom
```

Depois veja o relatorio:

```powershell
.\scripts\show-report.ps1 -Batch custom
```

## Comandos uteis para demonstracao

Ver Pods e Workers:

```powershell
kubectl get pods -n scheduler-lab -o wide
kubectl describe pod -n scheduler-lab custom-storage-01
kubectl get nodes --show-labels
```

Ver logs e decisoes:

```powershell
.\scripts\show-operator-logs.ps1
Get-Content .\reports\custom-scheduler.log
Get-Content .\reports\custom-decisions.jsonl
```

Rodar testes unitarios do algoritmo:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

## Como validar

O projeto funcionou se:

- `kubectl get nodes` mostrar 1 control-plane e pelo menos 2 workers;
- `kubectl get pods -n scheduler-lab -o wide` mostrar Pods distribuidos nos workers;
- Pods customizados tiverem `schedulerName: custom-scheduler`;
- existir um Pod `custom-scheduler-operator` rodando no namespace `scheduler-lab`;
- `kubectl logs -n scheduler-lab deployment/custom-scheduler-operator` mostrar scores por Worker;
- `reports/custom-decisions.jsonl` tiver uma linha por Pod escalonado depois de `run-custom.ps1`;
- `reports/custom-snapshot.json` mostrar uso de CPU, memoria e disco por Worker;
- `reports/comparison.json` comparar default e custom.

## Limpeza

Remover apenas os Pods do experimento:

```powershell
.\scripts\cleanup.ps1
```

Remover Pods do experimento e o Operator:

```powershell
.\scripts\cleanup.ps1 -DeleteOperator
```

Remover namespace:

```powershell
.\scripts\cleanup.ps1 -DeleteNamespace
```

Apagar o cluster kind:

```powershell
.\scripts\delete-cluster.ps1
```

## Troubleshooting

Se o PowerShell bloquear scripts:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

Se o cluster nao subir, confira se o Docker Desktop esta aberto:

```powershell
docker ps
```

Se Pods customizados ficarem `Pending`, confira se o scheduler esta rodando:

```powershell
kubectl get pods -n scheduler-lab -l app.kubernetes.io/name=custom-scheduler-operator
kubectl logs -n scheduler-lab deployment/custom-scheduler-operator
kubectl get pods -n scheduler-lab -o wide
```

Se a imagem demorar para baixar, o agendamento ainda pode ter funcionado. Verifique a coluna `NODE`:

```powershell
kubectl get pods -n scheduler-lab -o wide
```
