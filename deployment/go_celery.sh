#!/bin/bash
# Production Celery worker for /var/www/flask/skvo_veb_2 (run as www-data).

# to fail early instead of silently continuing after errors:
set -euo pipefail

APP_ROOT="/var/www/flask/skvo_veb_2"
ENV_FILE="/var/www/flask/.env"

export $(grep -v '^#' "${ENV_FILE}" | xargs)
cd "${APP_ROOT}"
exec "${APP_ROOT}/.venv/bin/celery" -A skvo_veb.celery_app worker --loglevel=INFO
