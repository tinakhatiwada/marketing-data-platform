# Image for the Cloud Run job. One container run = one pipeline run.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ADPULSE_HOME=/app \
    ADPULSE_TARGET=bigquery

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[bigquery]"

COPY dbt ./dbt
# Parse once at build time: catches broken models before deploy, speeds up startup.
RUN cd dbt && GCP_PROJECT=build-check dbt parse --profiles-dir . --target bigquery --quiet

RUN useradd --create-home runner && chown -R runner /app
USER runner

ENTRYPOINT ["adpulse"]
CMD ["run", "--json-logs"]
