"""
Tradução entre objetos da API do Kubernetes e os dados que o scoring entende.

Do lado do K8s os objetos vêm cheios de metadata, labels, annotations, status, spec, conditions. Do lado do scoring.py ele só quer PodRequest (cpu_m, memory_mib, disk_mib, profile) e WorkerState (capacities, used). Esse arquivo vai pegar o objeto bagunçado da API e devolve a ficha limpa.
"""

from __future__ import annotations
from collections import defaultdict

from scheduler_lab.quantity import parse_cpu_millicores, parse_mib
from scheduler_lab.scoring import PodRequest, WorkerState

# labels que marcam node como control-plane. control-plane é o "cérebro" do cluster e não deve receber Pods do experimento
CONTROL_PLANE_LABELS = (
    "node-role.kubernetes.io/control-plane",
    "node-role.kubernetes.io/master",
)

# rótulos próprios do projeto, todos com prefixo scheduler.lab/
PROFILE_KEY = "scheduler.lab/profile"      # qual perfil de pesos usar (light, cpu, storage...)
BATCH_KEY = "scheduler.lab/batch"          # default ou custom (qual bateria do experimento)
WORKLOAD_KEY = "scheduler.lab/workload"    # marca os Pods do experimento (usado pra delete em massa nos scripts)


def is_active_pod(pod):
    # pod "ativo" = ainda não terminou. uso isso pra ignorar Succeeded/Failed na hora de somar uso
    phase = getattr(getattr(pod, "status", None), "phase", None)
    return phase not in {"Succeeded", "Failed"}


def pod_batch(pod):
    # devolve a bateria do Pod (default ou custom). vazio se o label n existir
    labels = getattr(getattr(pod, "metadata", None), "labels", None) or {}
    return labels.get(BATCH_KEY, "")


def pod_profile(pod):
    # tenta na annotation primeiro, depois no label e se n achar nenhum cai em "balanced"
    metadata = getattr(pod, "metadata", None)
    annotations = getattr(metadata, "annotations", None) or {}
    labels = getattr(metadata, "labels", None) or {}
    return annotations.get(PROFILE_KEY) or labels.get(PROFILE_KEY) or "balanced"


def pod_custom_weights(pod):
    # pega overrides individuais (annotation scheduler.lab/weight-cpu, etc.).
    # valor inválido (não numérico) é ignorado em silêncio pra n derrubar o scheduler
    annotations = getattr(getattr(pod, "metadata", None), "annotations", None) or {}
    mapping = {
        "cpu": "scheduler.lab/weight-cpu",
        "memory": "scheduler.lab/weight-memory",
        "disk": "scheduler.lab/weight-disk",
        "latency": "scheduler.lab/weight-latency",
    }
    weights: dict[str, float] = {}
    for metric, annotation in mapping.items():
        if annotation in annotations:
            try:
                weights[metric] = float(annotations[annotation])
            except ValueError:
                continue
    return weights


def pod_request(pod):
    # monta a "ficha limpa" do Pod (PodRequest) pro scoring usar
    spec = getattr(pod, "spec", None)
    metadata = getattr(pod, "metadata", None)
    namespace = getattr(metadata, "namespace", "default")
    name = getattr(metadata, "name", "pod")

    # regra do Kubernetes pro pedido efetivo do Pod:
    #   - containers principais rodam em paralelo, então SOMA dos requests
    #   - initContainers rodam UM de cada vez, então o pico é o MÁXIMO
    #   - o pedido efetivo é o MAIOR entre os dois
    app = _sum_container_requests(getattr(spec, "containers", None) or [])
    init = _max_container_requests(getattr(spec, "init_containers", None) or [])
    cpu_m = max(app["cpu_m"], init["cpu_m"])
    memory_mib = max(app["memory_mib"], init["memory_mib"])
    disk_mib = max(app["disk_mib"], init["disk_mib"])

    return PodRequest(
        name=f"{namespace}/{name}",
        cpu_m=cpu_m,
        memory_mib=memory_mib,
        disk_mib=disk_mib,
        profile=pod_profile(pod),
        weights=pod_custom_weights(pod),
    )


def node_is_worker(node, include_control_plane=False):
    # control-plane é o "cérebro" do cluster, n é pra receber Pods do experimento.
    # mas posso forçar incluir ele se quiser (flag --include-control-plane do CLI)
    labels = getattr(getattr(node, "metadata", None), "labels", None) or {}
    if include_control_plane:
        return True
    return not any(label in labels for label in CONTROL_PLANE_LABELS)


def node_is_ready(node):
    # checa a condition Ready=True. ignora workers que ainda tão subindo ou que caíram
    conditions = getattr(getattr(node, "status", None), "conditions", None) or []
    for condition in conditions:
        if condition.type == "Ready":
            return condition.status == "True"
    return False


def worker_state_from_node(node, usage):
    # monta a "ficha" do Worker juntando capacidade (do node) com uso (do aggregate_usage)
    metadata = node.metadata
    labels = metadata.labels or {}
    allocatable = node.status.allocatable or {}
    node_usage = usage.get(metadata.name, {})

    # truque do projeto: o kind n simula disco/latência diferente entre workers, então finjo isso via label.
    # se tiver scheduler.lab/disk-mib uso ele, senão cai no ephemeral-storage real do node.
    # latência sempre vem do label scheduler.lab/latency-ms (padrão 50ms se n tiver)
    disk_from_label = labels.get("scheduler.lab/disk-mib")
    disk_capacity_mib = int(disk_from_label) if disk_from_label else parse_mib(allocatable.get("ephemeral-storage"))
    latency_ms = float(labels.get("scheduler.lab/latency-ms", "50"))

    return WorkerState(
        name=metadata.name,
        cpu_capacity_m=parse_cpu_millicores(allocatable.get("cpu")),
        memory_capacity_mib=parse_mib(allocatable.get("memory")),
        disk_capacity_mib=disk_capacity_mib,
        latency_ms=latency_ms,
        cpu_used_m=node_usage.get("cpu_m", 0),
        memory_used_mib=node_usage.get("memory_mib", 0),
        disk_used_mib=node_usage.get("disk_mib", 0),
        pod_count=node_usage.get("pod_count", 0),
    )


def aggregate_usage(pods, batch=None):
    # varre todos os Pods ativos e soma quanto cada Worker já tá usando.
    # se passar batch, filtra só por aquela bateria (útil pros relatórios separados)
    usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for pod in pods:
        if not is_active_pod(pod):
            continue
        if batch and pod_batch(pod) != batch:
            continue
        # ignora Pods ainda sem node atribuído (não escalonados)
        node_name = getattr(getattr(pod, "spec", None), "node_name", None)
        if not node_name:
            continue
        request = pod_request(pod)
        usage[node_name]["cpu_m"] += request.cpu_m
        usage[node_name]["memory_mib"] += request.memory_mib
        usage[node_name]["disk_mib"] += request.disk_mib
        usage[node_name]["pod_count"] += 1
    return usage


def _sum_container_requests(containers):
    # soma requests dos containers principais (rodam em paralelo, somar faz sentido)
    total = {"cpu_m": 0, "memory_mib": 0, "disk_mib": 0}
    for container in containers:
        request = _container_request(container)
        for key in total:
            total[key] += request[key]
    return total


def _max_container_requests(containers):
    # initContainers rodam UM de cada vez, então o pedido total é o pico (max), não a soma
    maximum = {"cpu_m": 0, "memory_mib": 0, "disk_mib": 0}
    for container in containers:
        request = _container_request(container)
        for key in maximum:
            maximum[key] = max(maximum[key], request[key])
    return maximum


def _container_request(container):
    # extrai os 3 recursos pedidos por UM container.
    # já passa pelos parsers do quantity.py pra virar inteiro (millicores e MiB)
    resources = getattr(container, "resources", None)
    requests = getattr(resources, "requests", None) or {}
    return {
        "cpu_m": parse_cpu_millicores(requests.get("cpu")),
        "memory_mib": parse_mib(requests.get("memory")),
        "disk_mib": parse_mib(requests.get("ephemeral-storage")),
    }
