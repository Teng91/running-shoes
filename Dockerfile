# SPEC-134: pinned to one image digest so every build gets the same base; Dependabot's
# monthly docker update moves the pin (the tag keeps it readable).
FROM python:3.11-slim@sha256:61e01f72680f86a5279ad510818ab7b2ee9f049822589d4e34e33e044360356c
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY backend backend/
# appuser cannot write __pycache__ under /app; compile once so cold starts skip it.
RUN python -m compileall -q backend
COPY frontend frontend/
# SPEC-134: every documented rollback script ships with the image, so a production rollback
# needs no file transfer onto the machine.
COPY scripts/database_backup.py scripts/*.sql scripts/
RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data
ENV DB_DIR=/data
ENV ENVIRONMENT=production
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health/ready',timeout=4)" || exit 1
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
