FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY README.md pyproject.toml alembic.ini ./
COPY masterly ./masterly
RUN pip install --no-cache-dir . \
    && groupadd --system masterly \
    && useradd --system --gid masterly --create-home masterly \
    && install -d -o masterly -g masterly /app/data

USER masterly
EXPOSE 8000
CMD ["uvicorn", "masterly.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
