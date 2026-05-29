"""
Algoritmo de score do scheduler customizado.

Pra cada Pod pendente, o scheduler precisa escolher um Worker.

Cada Pod tem um "perfil" (cpu, memory, storage, latency, balanced, light) que diz quais métricas pesam mais na hora de decidir. Os pesos saem do DEFAULT_PROFILE_WEIGHTS ou de um ConfigMap.

Worker que não tem CPU/memória/disco suficiente pro Pod é marcado como inviável (score = -1) e vai pro fim da lista.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# representa o pedido do Pod q é tipo um hóspede: quanto ele quer de cada recurso e qual perfil de pesos vai usar
@dataclass(frozen=True)
class PodRequest:
    name: str
    cpu_m: int          # CPU pedida em millicores
    memory_mib: int     # memória pedida em MiB
    disk_mib: int       # disco pedido em MiB
    profile: str = "balanced"
    # weights pode trazer overrides via annotation do Pod
    # (ex.: scheduler.lab/weight-cpu="0.55")
    # overrides são coisas que o Pod pode pedir individualmente, enquanto o profile é um pacote de pesos pré-definidos
    weights: dict[str, float] = field(default_factory=dict)


# representa o estado do Worker q seria o quarto do hospede: capacidade total, o que já tá ocupado e a latência simulada (vem do label scheduler.lab/latency-ms)
@dataclass(frozen=True)
class WorkerState:
    name: str
    cpu_capacity_m: int
    memory_capacity_mib: int
    disk_capacity_mib: int
    latency_ms: float
    cpu_used_m: int = 0
    memory_used_mib: int = 0
    disk_used_mib: int = 0
    pod_count: int = 0

    # as 3 properties abaixo devolvem quanto sobra pra alocar.
    # uso max(0, ...) pra nunca devolver negativo caso a soma dos pedidos passe da capacidade total (acontece em estados intermediários)
    @property
    def cpu_free_m(self):
        return max(0, self.cpu_capacity_m - self.cpu_used_m)

    @property
    def memory_free_mib(self):
        return max(0, self.memory_capacity_mib - self.memory_used_mib)

    @property
    def disk_free_mib(self):
        return max(0, self.disk_capacity_mib - self.disk_used_mib)


# resultado da avaliação de UM worker pra UM pod. carrega a nota, se é viável, a razão (string que vai pro log) e os componentes pra ajudar nos relatórios e na hora de debugar
@dataclass(frozen=True)
class ScoreResult:
    worker: WorkerState
    feasible: bool
    score: float
    reason: str
    components: dict[str, float]
    weights: dict[str, float]


# tabela de pesos por perfil. cada perfil prioriza uma métrica diferente: storage manda no disco, latency manda na rede, etc. os valores aqui não precisam somar 1 — a normalize_weights divide tudo pelo total na hora de aplicar
DEFAULT_PROFILE_WEIGHTS = {
    "light": {"cpu": 0.25, "memory": 0.25, "disk": 0.20, "latency": 0.30},
    "balanced": {"cpu": 0.30, "memory": 0.30, "disk": 0.25, "latency": 0.15},
    "cpu": {"cpu": 0.50, "memory": 0.20, "disk": 0.20, "latency": 0.10},
    "memory": {"cpu": 0.20, "memory": 0.50, "disk": 0.20, "latency": 0.10},
    "storage": {"cpu": 0.18, "memory": 0.17, "disk": 0.55, "latency": 0.10},
    "latency": {"cpu": 0.18, "memory": 0.17, "disk": 0.15, "latency": 0.50},
}


def normalize_weights(profile, custom_weights=None, profile_weights=None):
    # se veio um dict externo (do ConfigMap), uso ele ou cai no DEFAULT_PROFILE_WEIGHTS embutido aqui no código
    available_weights = profile_weights or DEFAULT_PROFILE_WEIGHTS
    # fallback: se o perfil pedido não existir, uso "balanced" como padrão
    default_weights = available_weights.get("balanced", DEFAULT_PROFILE_WEIGHTS["balanced"])
    weights = dict(available_weights.get(profile, default_weights))

    # se o Pod tiver overrides individuais (annotation scheduler.lab/weight-*), sobrescreve só as métricas válidas e ignora valores negativos
    for metric, value in (custom_weights or {}).items():
        if metric in weights and value >= 0:
            weights[metric] = float(value)

    # divide tudo pelo total pra somar 1.0. se algo der errado e a soma ficar zero ou negativa, devolvo o "balanced" puro como rede de segurança
    total = sum(weights.values())
    if total <= 0:
        return dict(DEFAULT_PROFILE_WEIGHTS["balanced"])

    return {metric: value / total for metric, value in weights.items()}


def score_worker(pod, worker, max_latency_ms, profile_weights=None):
    # primeiro o filtro: vê se o Worker tem CPU/memória/disco suficiente pro Pod e se faltar alguma coisa, ele já vai ser marcado inviável
    missing = []
    if pod.cpu_m > worker.cpu_free_m:
        missing.append(f"CPU livre {worker.cpu_free_m}m < pedido {pod.cpu_m}m")
    if pod.memory_mib > worker.memory_free_mib:
        missing.append(f"memoria livre {worker.memory_free_mib}Mi < pedido {pod.memory_mib}Mi")
    if pod.disk_mib > worker.disk_free_mib:
        missing.append(f"disco livre {worker.disk_free_mib}Mi < pedido {pod.disk_mib}Mi")

    # calcula os pesos finais (perfil + overrides do Pod, já normalizados)
    weights = normalize_weights(pod.profile, pod.weights, profile_weights=profile_weights)

    # se faltou recurso, devolve score -1 pra esse worker ir pro fim do ranking. mantenho os pesos no resultado pra ficar registrado no log mesmo quando o worker for descartado
    if missing:
        return ScoreResult(
            worker=worker,
            feasible=False,
            score=-1.0,
            reason="; ".join(missing),
            components={},
            weights=weights,
        )

    # quanto sobra de cada recurso DEPOIS de acomodar o Pod e é isso que vira nota, logo, mais recurso livre depois = melhor escolha
    cpu_after = worker.cpu_free_m - pod.cpu_m
    mem_after = worker.memory_free_mib - pod.memory_mib
    disk_after = worker.disk_free_mib - pod.disk_mib

    # normaliza cada métrica pra [0, 1].
    # latência é invertida (1 - ratio) porque menor latência tem que dar nota MAIOR, ao contrário das outras 3 onde mais livre = mais nota
    components = {
        "cpu": _ratio(cpu_after, worker.cpu_capacity_m),
        "memory": _ratio(mem_after, worker.memory_capacity_mib),
        "disk": _ratio(disk_after, worker.disk_capacity_mib),
        "latency": 1.0 - _ratio(worker.latency_ms, max(max_latency_ms, 1.0)),
    }
    # soma ponderada e multiplica por 100 só pra a nota sair entre
    # 0 e 100 em vez de 0 e 1 (fica mais legível no log)
    score = sum(weights[metric] * components[metric] for metric in weights) * 100
    reason = (
        f"score={score:.2f}; cpu={components['cpu']:.2f}; "
        f"mem={components['memory']:.2f}; disk={components['disk']:.2f}; "
        f"latency={components['latency']:.2f}"
    )
    return ScoreResult(
        worker=worker,
        feasible=True,
        score=score,
        reason=reason,
        components=components,
        weights=weights,
    )


def rank_workers(pod, workers, profile_weights=None):
    worker_list = list(workers)
    # pega a maior latência da rodada pra usar como denominador na normalização. default=1.0 pra não dividir por zero caso a lista esteja vazia
    max_latency = max((worker.latency_ms for worker in worker_list), default=1.0)
    results = [score_worker(pod, worker, max_latency, profile_weights=profile_weights) for worker in worker_list]
    # ordena assim:
    #   1) inviáveis vão pro fim (not feasible = True ordena depois)
    #   2) maior score primeiro (por isso o -item.score)
    #   3) desempate por menos pods alocados 
    #   4) desempate final em ordem alfabética
    return sorted(
        results,
        key=lambda item: (
            not item.feasible,
            -item.score,
            item.worker.pod_count,
            item.worker.name,
        ),
    )


def _ratio(numerator, denominator):
    # divide com proteção contra zero e prende o resultado entre 0 e 1. 
    # uso isso pra normalizar todas as métricas antes de aplicar os pesos
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, float(numerator) / float(denominator)))
