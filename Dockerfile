FROM python:3.11-slim-bookworm

ENV AIRFLOW_HOME=/opt/airflow \
    HOME=/opt/airflow \
    PYTHONUNBUFFERED=1
WORKDIR /opt/road-safety
COPY --chown=50000:0 . .

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 50000 --gid 0 --home-dir "$AIRFLOW_HOME" --no-create-home airflow \
    && mkdir -p "$AIRFLOW_HOME/results" \
    && chown -R 50000:0 "$AIRFLOW_HOME"

USER 50000:0
