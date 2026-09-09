#!/bin/bash
# Restart the current IGEBC stack (skvo_veb_2) on the production server.
# See docs/production_apache_celery.md
set -euo pipefail
# What this does:
#   1. Stops the legacy Celery unit if it is running (same Redis queue; only one
#      worker may run).
#   2. Enables and restarts celery-skvo-veb-2.
#   3. Switches Apache to the skvo_veb_2 vhost (if a legacy vhost is still present).
#   4. Tests Apache syntax and reloads the web server.
#
# Usage (on the server, as root):
#   sudo /var/www/flask/skvo_veb_2/deployment/restart-skvo-veb-2.sh
#
# Edit the Apache site filenames below if they differ on this host.
# List them with:  ls /etc/apache2/sites-available/

# --- paths and unit names (server layout) ---
APP_ROOT="/var/www/flask/skvo_veb_2"
CELERY_UNIT="celery-skvo-veb-2"
LEGACY_CELERY_UNIT="celery"
NEW_APACHE_SITE="astronomy_igebc-le-ssl.conf"
LEGACY_APACHE_SITE="astronomy_igebc-old-le-ssl.conf"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script as root, e.g. sudo $0" >&2
    exit 1
fi

echo "==> Stopping legacy Celery (${LEGACY_CELERY_UNIT}) if it is active"
if systemctl list-unit-files "${LEGACY_CELERY_UNIT}.service" --no-legend | grep -q .; then
    systemctl stop "${LEGACY_CELERY_UNIT}" || true
    systemctl disable "${LEGACY_CELERY_UNIT}" || true
fi

echo "==> Enabling and restarting Celery (${CELERY_UNIT})"
systemctl enable "${CELERY_UNIT}"
systemctl restart "${CELERY_UNIT}"
systemctl --no-pager --full status "${CELERY_UNIT}" || true

echo "==> Switching Apache vhost to ${NEW_APACHE_SITE}"
if [[ -f "/etc/apache2/sites-available/${LEGACY_APACHE_SITE}" ]]; then
    a2dissite "${LEGACY_APACHE_SITE}" || true
fi
a2ensite "${NEW_APACHE_SITE}"

echo "==> Checking Apache configuration"
apache2ctl configtest

echo "==> Reloading Apache (keeps existing connections; picks up vhost and WSGI)"
systemctl reload apache2

echo "==> Done. Check https://astronomy.science.upjs.sk/igebc/"
echo "    Celery log: ${APP_ROOT}/log/celery.log"
echo "    Apache error log: ${APP_ROOT}/log/error.log"
