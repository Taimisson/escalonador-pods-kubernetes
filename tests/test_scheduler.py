# testes do algoritmo, rodam sem precisar de cluster
# o objetivo é provar que a lógica de score e parsing funciona isolada
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scheduler_lab.quantity import parse_bytes, parse_cpu_millicores, parse_mib
from scheduler_lab.policy import load_profile_weights
from scheduler_lab.scoring import PodRequest, WorkerState, rank_workers


# conversão das quantidades do K8s (millicores e MiB)
class QuantityTest(unittest.TestCase):
    def test_parse_cpu(self):
        # "500m" continua 500, "2" CPUs viram 2000 millicores
        self.assertEqual(parse_cpu_millicores("500m"), 500)
        self.assertEqual(parse_cpu_millicores("2"), 2000)

    def test_parse_storage(self):
        self.assertEqual(parse_mib("512Mi"), 512)
        self.assertEqual(parse_bytes("1Gi"), 1024 * 1024 * 1024)


# o coração: prova que cada perfil escolhe o worker certo
class ScoringTest(unittest.TestCase):
    def test_storage_profile_prefers_more_disk(self):
        # perfil storage tem que preferir o worker com mais disco, mesmo com latência pior
        pod = PodRequest("storage", cpu_m=100, memory_mib=100, disk_mib=500, profile="storage")
        workers = [
            WorkerState("worker-a", 4000, 4096, 700, latency_ms=10),
            WorkerState("worker-b", 4000, 4096, 1600, latency_ms=40),
        ]

        ranked = rank_workers(pod, workers)

        self.assertTrue(ranked[0].feasible)
        self.assertEqual(ranked[0].worker.name, "worker-b")

    def test_latency_profile_prefers_lower_latency(self):
        # perfil latency tem que preferir o worker de menor latência, com disco igual
        pod = PodRequest("latency", cpu_m=100, memory_mib=100, disk_mib=100, profile="latency")
        workers = [
            WorkerState("worker-a", 4000, 4096, 1000, latency_ms=10),
            WorkerState("worker-b", 4000, 4096, 1000, latency_ms=80),
        ]

        ranked = rank_workers(pod, workers)

        self.assertEqual(ranked[0].worker.name, "worker-a")

    def test_infeasible_worker_goes_to_end(self):
        # worker que não comporta o Pod (CPU insuficiente) tem que ir pro fim da lista
        pod = PodRequest("large", cpu_m=5000, memory_mib=100, disk_mib=100)
        workers = [
            WorkerState("small", 1000, 4096, 1000, latency_ms=10),
            WorkerState("large", 8000, 4096, 1000, latency_ms=20),
        ]

        ranked = rank_workers(pod, workers)

        self.assertEqual(ranked[0].worker.name, "large")
        self.assertFalse(ranked[-1].feasible)


# carregamento dos pesos via ConfigMap
class PolicyTest(unittest.TestCase):
    def test_missing_policy_uses_defaults(self):
        # arquivo inexistente tem que cair nos pesos padrão sem quebrar
        weights = load_profile_weights("arquivo-inexistente.yaml")

        self.assertIn("balanced", weights)
        self.assertIn("latency", weights["balanced"])

    def test_loads_configmap_policy(self):
        # ConfigMap com pesos iguais (1,1,1,1) tem que normalizar pra 0.25 cada
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy-configmap.yaml"
            path.write_text(
                """
apiVersion: v1
kind: ConfigMap
data:
  policy.yaml: |
    profiles:
      balanced:
        cpu: 1
        memory: 1
        disk: 1
        latency: 1
""",
                encoding="utf-8",
            )

            weights = load_profile_weights(str(path))

        self.assertAlmostEqual(weights["balanced"]["cpu"], 0.25)
        self.assertAlmostEqual(weights["balanced"]["latency"], 0.25)


if __name__ == "__main__":
    unittest.main()
