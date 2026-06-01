"""
Loop principal do scheduler customizado.

Aqui é onde tudo se junta: o operator fica observando Pods Pending que pedem
o nosso schedulerName, calcula o ranking com o scoring, e faz o Binding real
na API do Kubernetes (literalmente diz pro cluster "esse Pod vai nesse Node").

É esse código que roda dentro do Pod do operator no cluster.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from scheduler_lab.k8s_model import (
    aggregate_usage,
    node_is_ready,
    node_is_worker,
    pod_request,
    worker_state_from_node,
)
from scheduler_lab.policy import load_profile_weights
from scheduler_lab.scoring import rank_workers
from scheduler_lab.table import render_table


class KubernetesScheduler:
    def __init__(
        self,
        namespace,
        scheduler_name,
        report_path,
        interval_seconds=2.0,      # de quanto em quanto tempo varre os Pods pendentes
        max_pods=None,             # para depois de agendar N Pods (None = sem limite)
        idle_timeout_seconds=90.0, # desiste se ficar parado sem Pod novo por esse tempo
        once=False,                # roda uma volta só e sai (útil pra teste)
        include_control_plane=False,
        kubeconfig=None,
        policy_file=None,          # caminho do policy.yaml (ConfigMap)
    ):
        self.namespace = namespace
        self.scheduler_name = scheduler_name
        self.report_path = Path(report_path)
        self.interval_seconds = interval_seconds
        self.max_pods = max_pods
        self.idle_timeout_seconds = idle_timeout_seconds
        self.once = once
        self.include_control_plane = include_control_plane
        self.kubeconfig = kubeconfig
        self.policy_file = policy_file
        self.profile_weights: dict[str, dict[str, float]] = {}
        self.api = None              # cliente da API do K8s, preenchido no _load_config
        self.scheduled_count = 0     # contador pro max_pods

    def run(self):
        # prepara tudo: conecta na API, carrega os pesos e zera o arquivo de decisões
        self._load_config()
        self.profile_weights = load_profile_weights(self.policy_file)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text("", encoding="utf-8")

        print(
            f"[scheduler] namespace={self.namespace} schedulerName={self.scheduler_name} "
            f"maxPods={self.max_pods or 'sem limite'}"
        )
        print(f"[scheduler] policyFile={self.policy_file or 'pesos padrao internos'}")
        idle_since = time.monotonic()

        # loop infinito (igual um scheduler de verdade): fica observando o cluster
        while True:
            pending = self._pending_pods()
            if pending:
                idle_since = time.monotonic()  # achou Pod, reseta o relógio de ociosidade
                for pod in pending:
                    # respeita o limite de Pods se foi configurado
                    if self.max_pods is not None and self.scheduled_count >= self.max_pods:
                        print("[scheduler] limite de Pods agendados atingido")
                        return 0
                    self._schedule_one(pod)
            elif self.once:
                # modo --once: uma volta sem Pod pendente já encerra
                print("[scheduler] nenhum Pod pendente encontrado; finalizando --once")
                return 0
            elif self.idle_timeout_seconds > 0 and time.monotonic() - idle_since > self.idle_timeout_seconds:
                # ficou tempo demais sem nada pra fazer, encerra pra não rodar pra sempre
                print("[scheduler] idle-timeout atingido; finalizando")
                return 0

            time.sleep(self.interval_seconds)

    def _load_config(self):
        # tenta o kubeconfig local primeiro (quando rodo fora do cluster, na minha máquina).
        # se falhar, assume que tô rodando DENTRO de um Pod e uso a config in-cluster
        try:
            config.load_kube_config(config_file=self.kubeconfig)
        except config.ConfigException:
            config.load_incluster_config()
        self.api = client.CoreV1Api()

    def _pending_pods(self):
        # filtra os Pods que SÃO meus pra resolver. tem que passar em tudo:
        assert self.api is not None
        pods = self.api.list_namespaced_pod(namespace=self.namespace).items
        result = []
        for pod in pods:
            if pod.metadata.deletion_timestamp:       # tá sendo deletado, ignora
                continue
            if pod.spec.node_name:                    # já tem node, alguém já agendou
                continue
            if pod.status.phase != "Pending":         # só me interessa quem tá esperando
                continue
            if pod.spec.scheduler_name != self.scheduler_name:  # não é pra mim, é do default
                continue
            result.append(pod)
        # ordena por nome pra dar previsibilidade na ordem de agendamento
        return sorted(result, key=lambda item: item.metadata.name)

    def _worker_states(self):
        # monta a foto atual dos workers: quanto cada um tem e quanto já tá usando.
        # somo o uso de TODOS os Pods do cluster (todos os namespaces) pra não estourar capacidade
        assert self.api is not None
        all_pods = self.api.list_pod_for_all_namespaces().items
        usage = aggregate_usage(all_pods)
        nodes = self.api.list_node().items
        workers = []
        for node in nodes:
            if node.spec.unschedulable:               # node cordoned, pula
                continue
            if not node_is_ready(node):               # node não tá pronto, pula
                continue
            if not node_is_worker(node, include_control_plane=self.include_control_plane):
                continue                              # é control-plane, pula (a não ser que eu force)
            workers.append(worker_state_from_node(node, usage))
        return workers

    def _schedule_one(self, pod):
        # o passo a passo de agendar UM Pod
        assert self.api is not None
        request = pod_request(pod)                  # converte o Pod do K8s pra ficha limpa
        workers = self._worker_states()             # foto atual dos workers
        ranking = rank_workers(request, workers, profile_weights=self.profile_weights)
        # pega o primeiro viável do ranking (já vem ordenado do melhor pro pior)
        selected = next((item for item in ranking if item.feasible), None)

        # nenhum worker coube: registra como não-agendado e desiste desse Pod
        if selected is None:
            self._print_decision(request.name, request, ranking, None)
            self._write_decision(pod, request, ranking, None, status="unscheduled")
            return

        try:
            self._bind_pod(pod, selected.worker.name)   # diz pro cluster onde colocar
            self._annotate_pod(pod, selected)           # marca o Pod com score/node escolhido
        except ApiException as exc:
            # 409 = conflito: outro processo agendou esse Pod antes de mim. sem problema, só ignoro
            if exc.status == 409:
                print(f"[scheduler] Pod {request.name} ja foi agendado por outro processo")
                return
            raise

        self.scheduled_count += 1
        self._print_decision(request.name, request, ranking, selected)
        self._write_decision(pod, request, ranking, selected, status="scheduled")

    def _bind_pod(self, pod, node_name):
        # ESSE é o momento que o agendamento vira real: um POST no endpoint /binding
        # é literalmente como o scheduler nativo do K8s prende um Pod a um Node.
        assert self.api is not None
        # uso a chamada "crua" (call_api) de propósito: a resposta do Binding às vezes
        # vem sem o campo `target` e o client tenta desserializar e quebra. assim eu evito isso
        self.api.api_client.call_api(
            "/api/v1/namespaces/{namespace}/pods/{name}/binding",
            "POST",
            path_params={"namespace": pod.metadata.namespace, "name": pod.metadata.name},
            header_params={"Accept": "application/json", "Content-Type": "application/json"},
            body={
                "apiVersion": "v1",
                "kind": "Binding",
                "metadata": {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                },
                "target": {
                    "apiVersion": "v1",
                    "kind": "Node",
                    "name": node_name,
                },
            },
            auth_settings=["BearerToken"],
            response_type=None,
            _return_http_data_only=True,
            _preload_content=False,
        )

    def _annotate_pod(self, pod, selected):
        # carimba o Pod com qual node ganhou, o score e a hora.
        # serve pra dar pra ver a decisão depois com kubectl describe pod
        assert self.api is not None
        annotations = {
            "scheduler.lab/selected-node": selected.worker.name,
            "scheduler.lab/selected-score": f"{selected.score:.4f}",
            "scheduler.lab/scheduled-at": datetime.now(timezone.utc).isoformat(),
        }
        self.api.patch_namespaced_pod(
            name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            body={"metadata": {"annotations": annotations}},
        )

    def _print_decision(self, pod_name, request, ranking, selected):
        # imprime a tabela de decisão no log do operator (o que aparece no kubectl logs)
        rows = []
        for item in ranking:
            rows.append(
                [
                    item.worker.name,
                    "sim" if item.feasible else "nao",
                    f"{item.score:.2f}" if item.feasible else "-",
                    f"{item.worker.cpu_free_m}m",
                    f"{item.worker.memory_free_mib}Mi",
                    f"{item.worker.disk_free_mib}Mi",
                    f"{item.worker.latency_ms:.0f}ms",
                    item.reason,
                ]
            )
        print()
        print(
            f"[scheduler] Pod {pod_name}: req cpu={request.cpu_m}m "
            f"mem={request.memory_mib}Mi disk={request.disk_mib}Mi profile={request.profile}"
        )
        print(render_table(["worker", "viavel", "score", "cpuLivre", "memLivre", "diskLivre", "lat", "motivo"], rows))
        if selected:
            print(f"[scheduler] escolhido: {selected.worker.name} ({selected.reason})")
        else:
            print("[scheduler] nenhum worker viavel encontrado")

    def _write_decision(self, pod, request, ranking, selected, status):
        # grava a decisão como uma linha JSON no .jsonl. é isso que os relatórios
        # e a comparação leem depois pra montar as estatísticas
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "namespace": pod.metadata.namespace,
            "pod": pod.metadata.name,
            "request": {
                "cpu_m": request.cpu_m,
                "memory_mib": request.memory_mib,
                "disk_mib": request.disk_mib,
                "profile": request.profile,
                "weights": request.weights,
            },
            "selected_node": selected.worker.name if selected else None,
            "selected_score": selected.score if selected else None,
            "scores": [self._score_to_dict(item) for item in ranking],
        }
        with self.report_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    @staticmethod
    def _score_to_dict(item):
        # achata um ScoreResult num dict bonitinho pro JSON. guardo capacidade,
        # uso e livre de cada worker pra conseguir reconstruir a decisão depois
        worker = item.worker
        return {
            "node": worker.name,
            "feasible": item.feasible,
            "score": item.score,
            "reason": item.reason,
            "components": item.components,
            "weights": item.weights,
            "capacity": {
                "cpu_m": worker.cpu_capacity_m,
                "memory_mib": worker.memory_capacity_mib,
                "disk_mib": worker.disk_capacity_mib,
                "latency_ms": worker.latency_ms,
            },
            "used": {
                "cpu_m": worker.cpu_used_m,
                "memory_mib": worker.memory_used_mib,
                "disk_mib": worker.disk_used_mib,
                "pods": worker.pod_count,
            },
            "free": {
                "cpu_m": worker.cpu_free_m,
                "memory_mib": worker.memory_free_mib,
                "disk_mib": worker.disk_free_mib,
            },
        }
