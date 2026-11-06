FROM python:3.11-slim-bookworm@sha256:6cbe849bdc876ecd413a4a09a919a0d861d908589de9eba61e886c29af793a07 AS wheels
WORKDIR /build
COPY requirements.lock requirements-build.lock ./
RUN pip install --require-hashes --no-cache-dir -r requirements-build.lock && pip wheel --require-hashes --wheel-dir /wheels -r requirements.lock -r requirements-build.lock

FROM python:3.11-slim-bookworm@sha256:6cbe849bdc876ecd413a4a09a919a0d861d908589de9eba61e886c29af793a07 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --gid 10001 payflow && useradd --uid 10001 --gid payflow --no-create-home payflow
WORKDIR /app
COPY --from=wheels /wheels /wheels
COPY requirements.lock requirements-build.lock ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels --require-hashes -r requirements.lock -r requirements-build.lock && rm -rf /wheels
COPY *.py alembic.ini ./
COPY migrations/ ./migrations/
USER 10001:10001
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8001')+'/health/ready', timeout=3)"]
CMD ["python", "-m", "serve"]
