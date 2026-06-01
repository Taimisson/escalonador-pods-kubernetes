"""
Porta de entrada da aplicação (linha de comando).

Expõe 3 subcomandos que orquestram o resto do pacote:
- schedule: roda o scheduler customizado (o loop do k8s_scheduler)
- report:   tira o snapshot de uma bateria e mostra/salva as estatísticas
- compare:  compara os snapshots default x custom

É o que o Dockerfile chama no ENTRYPOINT e o que os scripts .ps1 invocam.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scheduler_lab.k8s_scheduler import KubernetesScheduler
from scheduler_lab.reports import KubernetesReporter, compare_snapshots, print_comparison


def main(argv=None):
    # monta o parser com os 3 subcomandos. cada um tem suas próprias flags
    parser = argparse.ArgumentParser(
        prog="sisop-scheduler",
        description="Scheduler customizado para Laboratorio de Sistemas Operacionais.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # subcomando schedule: liga o operator
    schedule = subparsers.add_parser("schedule", help="executa o scheduler customizado")
    schedule.add_argument("--namespace", default="scheduler-lab")
    schedule.add_argument("--scheduler-name", default="custom-scheduler")
    schedule.add_argument("--report", default="reports/custom-decisions.jsonl")
    schedule.add_argument("--interval", type=float, default=2.0)
    schedule.add_argument("--max-pods", type=int, default=None)
    schedule.add_argument("--idle-timeout", type=float, default=90.0)
    schedule.add_argument("--once", action="store_true")
    schedule.add_argument("--include-control-plane", action="store_true")
    schedule.add_argument("--kubeconfig", default=None)
    schedule.add_argument("--policy-file", default=None)

    # subcomando report: snapshot de uma bateria
    report = subparsers.add_parser("report", help="mostra recursos, alocacoes e estatisticas")
    report.add_argument("--namespace", default="scheduler-lab")
    report.add_argument("--batch", choices=["default", "custom"], required=True)
    report.add_argument("--decision-log", default=None)
    report.add_argument("--output-json", default=None)
    report.add_argument("--include-control-plane", action="store_true")
    report.add_argument("--kubeconfig", default=None)

    # subcomando compare: default x custom
    compare = subparsers.add_parser("compare", help="compara snapshots JSON")
    compare.add_argument("--baseline", default="reports/baseline-snapshot.json")
    compare.add_argument("--custom", default="reports/custom-snapshot.json")
    compare.add_argument("--output-json", default=None)

    args = parser.parse_args(argv)

    # despacha pro subcomando escolhido, repassando as flags
    if args.command == "schedule":
        scheduler = KubernetesScheduler(
            namespace=args.namespace,
            scheduler_name=args.scheduler_name,
            report_path=args.report,
            interval_seconds=args.interval,
            max_pods=args.max_pods,
            idle_timeout_seconds=args.idle_timeout,
            once=args.once,
            include_control_plane=args.include_control_plane,
            kubeconfig=args.kubeconfig,
            policy_file=args.policy_file,
        )
        return scheduler.run()

    if args.command == "report":
        reporter = KubernetesReporter(
            namespace=args.namespace,
            batch=args.batch,
            decision_log=args.decision_log,
            include_control_plane=args.include_control_plane,
            kubeconfig=args.kubeconfig,
        )
        snapshot = reporter.snapshot()
        reporter.print_snapshot(snapshot)
        # --output-json salva o snapshot em arquivo (é o que o compare lê depois)
        if args.output_json:
            path = Path(args.output_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
            print(f"\nSnapshot salvo em {path}")
        return 0

    if args.command == "compare":
        comparison = compare_snapshots(args.baseline, args.custom)
        print_comparison(comparison)
        if args.output_json:
            path = Path(args.output_json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(comparison, indent=2, ensure_ascii=True), encoding="utf-8")
            print(f"\nComparacao salva em {path}")
        return 0

    # subparser com required=True já barra comando inválido, mas deixo a rede de segurança
    parser.error("comando invalido")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
