FROM rasa/rasa:3.6.21-full

WORKDIR /app
COPY --chown=1001:0 rasa/config.yml /app/config.yml
COPY --chown=1001:0 rasa/data /app/data

RUN rasa train nlu --config /app/config.yml --nlu /app/data/nlu.yml --out /app/models

EXPOSE 5005
CMD ["run", "--enable-api", "--model", "/app/models", "--port", "5005", "--host", "0.0.0.0"]
