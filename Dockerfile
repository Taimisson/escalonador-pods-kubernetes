# empacota o operator numa imagem. essa imagem é carregada no kind e roda como o Deployment. slim pra ficar leve, já que só preciso de python + 2 libs.
FROM python:3.13-slim

# não gera .pyc e não bufferiza stdout (assim o kubectl logs mostra na hora)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# copia só o necessário pra instalar o pacote
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# roda como usuário não-root (65532 = nonroot), bate com o securityContext do Deployment
USER 65532:65532

# por padrão a imagem já sobe o scheduler. idle-timeout 0 = roda pra sempre (operator de verdade).
# e os caminhos batem com o volume do ConfigMap e a pasta /tmp pras decisões.
ENTRYPOINT ["python", "-m", "scheduler_lab.cli"]
CMD ["schedule", "--namespace", "scheduler-lab", "--scheduler-name", "custom-scheduler", "--idle-timeout", "0", "--policy-file", "/etc/custom-scheduler/policy.yaml", "--report", "/tmp/custom-decisions.jsonl"]
