"""
Leitura externa dos pesos do scheduler.

O scoring.py tem uma tabela embutida mas a graça do Kubernetes é poder mudar config sem rebuildar imagem. Aqui é o leitor do ConfigMap que monta o policy.yaml dentro do Pod do operator. Se algo quebrar cai no default embutido, o scheduler nunca para por culpa do ConfigMap.
"""

from __future__ import annotations
from pathlib import Path

import yaml

from scheduler_lab.scoring import DEFAULT_PROFILE_WEIGHTS

# as 4 métricas obrigatórias, se faltar alguma a receita é descartada
EXPECTED_METRICS = {"cpu", "memory", "disk", "latency"}


def load_profile_weights(path):
    """Recebe o caminho do YAML e devolve o dicionário de pesos por perfil."""
    # sem caminho ou arquivo inexistente: cai no default embutido
    if not path:
        return DEFAULT_PROFILE_WEIGHTS
    
    policy_path = Path(path)
    if not policy_path.exists():
        return DEFAULT_PROFILE_WEIGHTS
    
    # lê o YAML (pode ser um ConfigMap inteiro ou só os profiles direto na raiz)
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    data = _unwrap_configmap(data)
    raw_profiles = data.get("profiles", {})

    if not isinstance(raw_profiles, dict):
        return DEFAULT_PROFILE_WEIGHTS
    
    # valida cada receita individualmente. as inválidas são descartadas
    profiles: dict[str, dict[str, float]] = {}
    for profile, weights in raw_profiles.items():
        parsed = _parse_weights(weights)
        if parsed:
            profiles[str(profile)] = parsed

    # garante que "balanced" sempre exista pq o resto do código usa ele como fallback
    if "balanced" not in profiles:
        profiles["balanced"] = DEFAULT_PROFILE_WEIGHTS["balanced"]

    # se sobrou alguma coisa devolve, senão volta pro default
    return profiles or DEFAULT_PROFILE_WEIGHTS


def _parse_weights(weights):
    # tem que ser um dict. qualquer outra coisa (lista, string, null) é jogada fora
    if not isinstance(weights, dict):
        return {}
    
    # exige as 4 métricas presentes e convertíveis pra float. se faltar uma só, descarta a receita inteira

    parsed: dict[str, float] = {}
    for metric in EXPECTED_METRICS:
        value = weights.get(metric)
        if value is None:
            return {}
        try:
            parsed[metric] = float(value)
        except (TypeError, ValueError):
            return {}
        
    # soma zero ou negativa não dá pra normalizar, então descarta
    total = sum(parsed.values())
    if total <= 0:
        return {}
    
    # normaliza pra somar 1.0 (mesma lógica do scoring.normalize_weights)
    return {metric: value / total for metric, value in parsed.items()}


def _unwrap_configmap(data):

    # se não for um dict, return vaazio pra cair no default
    if not isinstance(data, dict):
        return {}
    
    # se o YAML não é um ConfigMap, assume que já tem os profiles direto na raiz
    if data.get("kind") != "ConfigMap":
        return data
    
    # ConfigMap do Kubernetes guarda o conteúdo de verdade dentro de data.policy.yaml como string. então preciso dar yaml.safe_load mais uma vez pra desembrulhar

    raw_policy = (data.get("data") or {}).get("policy.yaml")
    if not raw_policy:
        return {}
    
    parsed = yaml.safe_load(raw_policy) or {}

    return parsed if isinstance(parsed, dict) else {}
