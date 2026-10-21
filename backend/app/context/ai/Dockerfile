# Build context: repository root. No deployment/resource creation in this file.
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime@sha256:c16f4c749e2d9e96878875cdf6cc45cddda1d1a36fddd371dd6f2360f1b6e2a2
WORKDIR /opt/p1
COPY backend/app/context/ai/requirements-gpu.txt /opt/p1/requirements-gpu.txt
RUN python -m pip install --no-cache-dir -r /opt/p1/requirements-gpu.txt && python -m pip check
COPY backend/app/__init__.py /opt/p1/backend/app/__init__.py
COPY backend/app/context/__init__.py /opt/p1/backend/app/context/__init__.py
COPY backend/app/context/ai/ /opt/p1/backend/app/context/ai/
ENV PYTHONPATH=/opt/p1/backend HF_HOME=/tmp/p1-models HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
CMD ["python", "-m", "app.context.ai.worker"]
