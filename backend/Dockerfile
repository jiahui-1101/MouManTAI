FROM python:3.11-slim

WORKDIR /app
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir ".[dev]"
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY contracts ./contracts
COPY scripts ./scripts
RUN ln -s /app/contracts /contracts

ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
