#!/bin/bash
# Roll the production IGEBC URL back to the legacy tree (/var/www/flask/skvo_veb).
#
# What this does:
#   1. Stops the current Celery unit (celery-skvo-veb-2).
#   2. Enables and restarts the legacy Celery unit (celery).
#   3. Disables the skvo_veb_2 Apache vhost and enables the legacy vhost.
#   4. Tests Apache syntax and reloads the web server.
#
# Usage (on the server, as root):
#   sudo /var/www/flask/skvo_veb_2/deployment/rollback-to-skvo-veb.sh
#
# Edit the Apache site filenames below if they differ on this host.
# List them with:  ls /etc/apache2/sites-available/

set -euo pipefail

# --- paths and unit names (server layout) ---
LEGACY_ROOT="/var/www/flask/skvo_veb"
CELERY_UNIT="celery-skvo-veb-2"
LEGACY_CELERY_UNIT="celery"
NEW_APACHE_SITE="astronomy_igebc-le-ssl.conf"
LEGACY_APACHE_SITE="astronomy_igebc-le-ssl_old.conf"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script as root, e.g. sudo $0" >&2
    exit 1
fi

echo "==> Stopping current Celery (${CELERY_UNIT})"
systemctl stop "${CELERY_UNIT}" || true
systemctl disable "${CELERY_UNIT}" || true

echo "==> Enabling and restarting legacy Celery (${LEGACY_CELERY_UNIT})"
systemctl enable "${LEGACY_CELERY_UNIT}"
systemctl restart "${LEGACY_CELERY_UNIT}"
systemctl --no-pager --full status "${LEGACY_CELERY_UNIT}" || true

echo "==> Switching Apache vhost to ${LEGACY_APACHE_SITE}"
a2dissite "${NEW_APACHE_SITE}" || true
a2ensite "${LEGACY_APACHE_SITE}"

echo "==> Checking Apache configuration"
apache2ctl configtest

echo "==> Reloading Apache"
systemctl reload apache2

echo "==> Rolled back to legacy IGEBC."
echo "    Celery log: ${LEGACY_ROOT}/log/celery.log"
echo "    Apache error log: ${LEGACY_ROOT}/log/error.log"
