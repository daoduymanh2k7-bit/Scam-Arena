FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend:/app \
    HF_HOME=/models/huggingface \
    PIPER_VOICE_PATH=/app/voices/vi_VN-vais1000-medium.onnx \
    WHISPER_MODEL=base

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=app:app backend /app/backend
COPY --chown=app:app rasa/evaluation/dataset_workflow.py /app/rasa/evaluation/dataset_workflow.py
COPY --chown=app:app frontend /app/frontend
COPY --chown=app:app data /app/data
RUN mkdir -p /app/voices /models/huggingface && chown -R app:app /app /models

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
