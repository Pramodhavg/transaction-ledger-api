FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer stays cached when only source code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown appuser:appuser /app
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8000

# Apply migrations, then `exec` so uvicorn replaces the shell and receives stop signals directly.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
