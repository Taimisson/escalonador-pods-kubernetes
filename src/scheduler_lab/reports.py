"""
Relatórios e comparação das baterias.

Depois que os Pods rodam, esse módulo lê o estado do cluster e monta:
- um "snapshot" de uma bateria (default ou custom): tabela de Pods, de Workers
  e estatísticas (uso médio, desequilíbrio entre workers, latência média);
- uma comparação lado a lado entre as duas baterias.

É o que prova, no fim, se o scheduler customizado distribuiu melhor que o padrão.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean

from kubernetes import client, config

from scheduler_lab.k8s_model import (
    aggregate_usage,
    is_active_pod,
    node_is_ready,
    node_is_worker,
    pod_batch,
    pod_profile,
    pod_request,
    worker_state_from_node,
)
from scheduler_lab.table import render_table


class KubernetesReporter:
    def __init__(self, namespace, batch, decision_log=None, kubeconfig=None, include_control_plane=False):
        self.namespace = namespace
        self.batch = batch                # qual bateria reportar: default ou custom
        self.decision_log = decision_log  # caminho do .jsonl com as decisões (só a custom tem)
        self.kubeconfig = kubeconfig
        self.include_control_plane = include_control_plane
        self.api = None

    def snapshot(self):
        # tira uma "foto" da bateria: junta Pods, Workers e estatísticas num dict só
        self._load_config()
        assert self.api is not None

        # pega só os Pods dessa bateria (default ou custom) pelo label
        pods = self.api.list_namespaced_pod(namespace=self.namespace).items
        batch_pods = [pod for pod in pods if pod_batch(pod) == self.batch]
        nodes = self.api.list_node().items
        usage = aggregate_usage(batch_pods, batch=self.batch)

        # monta a lista de workers prontos com seu uso já calculado
        workers = []
        for node in nodes:
            if not node_is_worker(node, include_control_plane=self.include_control_plane):
                continue
            if not node_is_ready(node):
                continue
            workers.append(worker_state_from_node(node, usage))

        # uma linha por Pod, dizendo onde caiu, que perfil tem e qual score recebeu
        worker_by_name = {worker.name: worker for worker in workers}
        pod_rows = []
        for pod in sorted(batch_pods, key=lambda item: item.metadata.name):
            request = pod_request(pod)
            node_name = pod.spec.node_name or ""
            worker = worker_by_name.get(node_name)
            annotations = pod.metadata.annotations or {}
            pod_rows.append(
                {
                    "name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "node": node_name,
                    "scheduler": pod.spec.scheduler_name or "default-scheduler",
                    "profile": pod_profile(pod),
                    "cpu_m": request.cpu_m,
                    "memory_mib": request.memory_mib,
                    "disk_mib": request.disk_mib,
                    "latency_ms": worker.latency_ms if worker else None,
                    "selected_score": annotations.get("scheduler.lab/selected-score"),
                    "active": is_active_pod(pod),
                }
            )

        stats = _build_stats(pod_rows, workers)
        decisions = _load_decisions(self.decision_log)
        return {
            "namespace": self.namespace,
            "batch": self.batch,
            "pods": pod_rows,
            "workers": [_worker_to_dict(worker) for worker in workers],
            "stats": stats,
            "decisions": decisions,
        }

    def print_snapshot(self, snapshot):
        # imprime o snapshot em 3 tabelas: Pods, Workers e Estatísticas
        # (+ as últimas decisões, quando for a bateria custom)
        print(f"\nRelatorio da bateria: {snapshot['batch']}")
        print("=" * 72)
        print("\nPods")
        print(
            render_table(
                ["pod", "phase", "worker", "sched", "perfil", "cpu", "mem", "disk", "lat", "score"],
                [
                    [
                        pod["name"],
                        pod["phase"],
                        pod["node"] or "-",
                        pod["scheduler"],
                        pod["profile"],
                        f"{pod['cpu_m']}m",
                        f"{pod['memory_mib']}Mi",
                        f"{pod['disk_mib']}Mi",
                        f"{pod['latency_ms']:.0f}ms" if pod["latency_ms"] is not None else "-",
                        _format_selected_score(pod["selected_score"]),
                    ]
                    for pod in snapshot["pods"]
                ],
            )
        )

        print("\nWorkers")
        print(
            render_table(
                ["worker", "pods", "cpu usado/livre", "mem usado/livre", "disk usado/livre", "lat"],
                [
                    [
                        worker["name"],
                        worker["pod_count"],
                        f"{worker['cpu_used_m']}m/{worker['cpu_free_m']}m",
                        f"{worker['memory_used_mib']}Mi/{worker['memory_free_mib']}Mi",
                        f"{worker['disk_used_mib']}Mi/{worker['disk_free_mib']}Mi",
                        f"{worker['latency_ms']:.0f}ms",
                    ]
                    for worker in snapshot["workers"]
                ],
            )
        )

        stats = snapshot["stats"]
        print("\nEstatisticas")
        print(
            render_table(
                ["metrica", "valor"],
                [
                    ["pods criados", stats["total_pods"]],
                    ["pods alocados", stats["scheduled_pods"]],
                    ["pods pendentes", stats["pending_pods"]],
                    ["uso medio CPU", f"{stats['avg_cpu_usage_ratio']:.2%}"],
                    ["uso medio memoria", f"{stats['avg_memory_usage_ratio']:.2%}"],
                    ["uso medio disco", f"{stats['avg_disk_usage_ratio']:.2%}"],
                    ["desequilibrio CPU", f"{stats['cpu_imbalance']:.2%}"],
                    ["desequilibrio memoria", f"{stats['memory_imbalance']:.2%}"],
                    ["desequilibrio disco", f"{stats['disk_imbalance']:.2%}"],
                    ["latencia media dos Pods", f"{stats['avg_pod_latency_ms']:.1f}ms"],
                ],
            )
        )

        if snapshot["decisions"]:
            print("\nUltimas decisoes do scheduler customizado")
            rows = []
            for decision in snapshot["decisions"][-10:]:
                rows.append(
                    [
                        decision["pod"],
                        decision["selected_node"] or "-",
                        f"{decision['selected_score']:.2f}" if decision["selected_score"] is not None else "-",
                        _compact_scores(decision),
                    ]
                )
            print(render_table(["pod", "worker escolhido", "score", "scores por worker"], rows))

    def _load_config(self):
        # mesma lógica do scheduler: tenta kubeconfig local, senão usa in-cluster
        try:
            config.load_kube_config(config_file=self.kubeconfig)
        except config.ConfigException:
            config.load_incluster_config()
        self.api = client.CoreV1Api()


def compare_snapshots(baseline_path, custom_path):
    # lê os dois snapshots salvos em JSON e monta o comparativo default x custom
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    custom = json.loads(Path(custom_path).read_text(encoding="utf-8"))
    result = {
        "baseline": baseline["stats"],
        "custom": custom["stats"],
        "pod_distribution_baseline": baseline["stats"]["pod_distribution"],
        "pod_distribution_custom": custom["stats"]["pod_distribution"],
        "technical_summary": [
            "O default-scheduler aloca Pods usando principalmente requests de CPU/memoria e regras internas.",
            "O custom-scheduler usa CPU, memoria, disco simulado e latencia simulada por worker.",
            "Perfis storage e latency alteram os pesos e tendem a escolher workers com mais disco ou menor latencia.",
        ],
    }
    return result


def print_comparison(comparison):
    # imprime a tabela final comparando as duas estratégias lado a lado
    baseline = comparison["baseline"]
    custom = comparison["custom"]
    print("\nComparacao: default-scheduler x custom-scheduler")
    print("=" * 72)
    print(
        render_table(
            ["metrica", "default", "custom"],
            [
                ["pods alocados", baseline["scheduled_pods"], custom["scheduled_pods"]],
                ["pendentes", baseline["pending_pods"], custom["pending_pods"]],
                ["desequilibrio CPU", f"{baseline['cpu_imbalance']:.2%}", f"{custom['cpu_imbalance']:.2%}"],
                ["desequilibrio memoria", f"{baseline['memory_imbalance']:.2%}", f"{custom['memory_imbalance']:.2%}"],
                ["desequilibrio disco", f"{baseline['disk_imbalance']:.2%}", f"{custom['disk_imbalance']:.2%}"],
                ["latencia media", f"{baseline['avg_pod_latency_ms']:.1f}ms", f"{custom['avg_pod_latency_ms']:.1f}ms"],
            ],
        )
    )
    print("\nDistribuicao default:", comparison["pod_distribution_baseline"])
    print("Distribuicao custom: ", comparison["pod_distribution_custom"])
    print("\nLeitura tecnica:")
    for line in comparison["technical_summary"]:
        print(f"- {line}")


def _build_stats(pods, workers):
    # calcula os números que viram a tabela de estatísticas e a comparação
    scheduled = [pod for pod in pods if pod["node"]]   # quem já caiu num node
    pending = [pod for pod in pods if not pod["node"]] # quem ficou sem node
    distribution = Counter(pod["node"] for pod in scheduled)  # quantos Pods por worker

    # taxa de ocupação de cada worker (usado / capacidade) por recurso
    cpu_ratios = [_ratio(worker.cpu_used_m, worker.cpu_capacity_m) for worker in workers]
    mem_ratios = [_ratio(worker.memory_used_mib, worker.memory_capacity_mib) for worker in workers]
    disk_ratios = [_ratio(worker.disk_used_mib, worker.disk_capacity_mib) for worker in workers]
    latencies = [pod["latency_ms"] for pod in scheduled if pod["latency_ms"] is not None]

    # o "imbalance" (desequilíbrio) é o ponto chave da comparação:
    # quanto menor, mais parelho ficou o uso entre os workers = distribuição melhor
    return {
        "total_pods": len(pods),
        "scheduled_pods": len(scheduled),
        "pending_pods": len(pending),
        "pod_distribution": dict(distribution),
        "avg_cpu_usage_ratio": mean(cpu_ratios) if cpu_ratios else 0,
        "avg_memory_usage_ratio": mean(mem_ratios) if mem_ratios else 0,
        "avg_disk_usage_ratio": mean(disk_ratios) if disk_ratios else 0,
        "cpu_imbalance": _imbalance(cpu_ratios),
        "memory_imbalance": _imbalance(mem_ratios),
        "disk_imbalance": _imbalance(disk_ratios),
        "avg_pod_latency_ms": mean(latencies) if latencies else 0,
    }


def _worker_to_dict(worker):
    # serializa um WorkerState pro JSON do snapshot (capacidade, uso e livre de cada recurso)
    return {
        "name": worker.name,
        "pod_count": worker.pod_count,
        "latency_ms": worker.latency_ms,
        "cpu_capacity_m": worker.cpu_capacity_m,
        "cpu_used_m": worker.cpu_used_m,
        "cpu_free_m": worker.cpu_free_m,
        "memory_capacity_mib": worker.memory_capacity_mib,
        "memory_used_mib": worker.memory_used_mib,
        "memory_free_mib": worker.memory_free_mib,
        "disk_capacity_mib": worker.disk_capacity_mib,
        "disk_used_mib": worker.disk_used_mib,
        "disk_free_mib": worker.disk_free_mib,
    }


def _load_decisions(path):
    # lê o .jsonl de decisões (uma linha JSON por Pod). uso utf-8-sig pra engolir
    # o BOM que o PowerShell às vezes coloca no começo do arquivo
    if not path:
        return []
    report_path = Path(path)
    if not report_path.exists():
        return []
    decisions = []
    for line in report_path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            decisions.append(json.loads(line))
    return decisions


def _compact_scores(decision):
    # resume os scores de todos os workers numa string só (ex.: "worker-a=85.2, worker-b=-")
    items = []
    for score in decision.get("scores", []):
        value = "-" if not score["feasible"] else f"{score['score']:.1f}"
        items.append(f"{score['node']}={value}")
    return ", ".join(items)


def _format_selected_score(value):
    # formata o score que veio da annotation. se não der pra converter, mostra como tá
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}"
    except ValueError:
        return value


def _ratio(value, total):
    # divisão protegida contra zero (usado / capacidade)
    if total <= 0:
        return 0
    return float(value) / float(total)


def _imbalance(values):
    # desequilíbrio = diferença entre o worker mais cheio e o mais vazio.
    # 0 = todos no mesmo nível (distribuição perfeita)
    if not values:
        return 0
    return max(values) - min(values)
