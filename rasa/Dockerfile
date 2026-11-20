FROM rasa/rasa:3.6.21-full

WORKDIR /app
ENV PYTHONPATH=/app
COPY --chown=1001:0 rasa/config.yml /app/config.yml
COPY --chown=1001:0 rasa/data /app/data
COPY --chown=1001:0 rasa/contextual_intent.py rasa/caller_acts.tsv /app/

RUN TF_NUM_INTRAOP_THREADS=4 TF_NUM_INTEROP_THREADS=2 OMP_NUM_THREADS=4 \
    rasa train nlu --config /app/config.yml --nlu /app/data/nlu.yml --out /app/models

EXPOSE 5005
CMD ["run", "--enable-api", "--model", "/app/models", "--port", "5005", "--interface", "0.0.0.0"]
