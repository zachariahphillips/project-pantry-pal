# Phase 2C — production image for Fly.io.
#
# Single-stage build: app is small (Flask + SQLAlchemy + a handful of
# templates) so the wins from a multi-stage build wouldn't pay for the
# extra complexity. If we ever add native deps (Pillow for receipt OCR
# in Phase 4, e.g.), revisit.
#
# Image size with python:3.12-slim base is ~160 MB before site-packages,
# ~210 MB after our deps. Fine for Fly's free tier.

FROM python:3.12-slim

# Don't write .pyc files (the volume isn't writable by random workers anyway,
# and disk noise just slows the cold-start). Stream logs immediately so
# `fly logs` shows output in real time.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps in a separate layer so changes to app code don't bust the
# pip cache. `requirements.txt` also pulls in `pytest` (under "dev only"),
# which is harmless in prod — a few MB. Keeping the requirements file
# single-source-of-truth means there's no second list to drift.
COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

# Copy the rest of the source. `.dockerignore` excludes .venv, instance/,
# tests/, *.bak, .git, __pycache__, .pytest_cache so the build context
# is small and we don't ship local DB state.
COPY . /app

# Run as non-root. Fly's machines don't strictly require this, but it's
# best-practice + cheap insurance.
RUN useradd --create-home --uid 1000 pantrypal \
    && chown -R pantrypal:pantrypal /app
USER pantrypal

# Fly expects services on the port set in fly.toml [http_service]
# internal_port = 8080. Gunicorn listens on $PORT (also 8080) so the
# image is port-flexible if we ever change it.
ENV PORT=8080
EXPOSE 8080

# `--workers=1` is mandatory while we're on SQLite — concurrent writers
#   corrupt the file (well, get locked out, which becomes 500s under load).
#   When we move to Postgres, bump this to (2 * CPU) + 1.
# `--threads=4` gets us a little request-handling concurrency for I/O-bound
#   work (mostly OpenAI calls in Phase 3) without multi-processing.
# `--timeout=60` is generous for SQLite writes + slow OpenAI requests later.
# `--access-logfile -` streams access logs to stdout so `fly logs` shows them.
CMD gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 1 \
    --threads 4 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile - \
    "app:app"
