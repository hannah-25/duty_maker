FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY api ./api
COPY core ./core
COPY frontend ./frontend
COPY templates ./templates
RUN mkdir -p data && chown -R app:app /app

USER app

CMD exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT}"
