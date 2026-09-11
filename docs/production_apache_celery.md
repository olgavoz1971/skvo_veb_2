# Production Apache, Redis, and Celery

This document describes how the IGEBC Dash application (`skvo_veb`) runs in production on Apache with Redis and Celery. It is the operational reference for the install under `/var/www/flask/skvo_veb_2`.

Application URL: `https://astronomy.science.upjs.sk/igebc/`

WordPress (unrelated to this stack) remains at `https://astronomy.science.upjs.sk/`.

## 1. Process layout

Three independent processes must be running:

| Process | Role | How it is started |
| :--- | :--- | :--- |
| Apache (`mod_wsgi`) | Serves HTTP for `/igebc/`. Runs the Dash/Flask WSGI application. | `systemctl` (`apache2`) |
| Redis | Queue and result store for background jobs. | `systemctl` (`redis-server` or `redis`) |
| Celery worker | Executes long-running Dash background callbacks. | `systemctl` (`celery-skvo-veb-2`) |

Apache never runs the long jobs itself. It only enqueues them. If Redis or Celery is down, pages still load, but TESS retrieves, Discovery search, and similar buttons hang or fail.

```text
Browser
   |
   v
Apache + mod_wsgi  (skvo_veb_2.wsgi -> Flask `server`)
   |
   |  background=True callback
   v
Redis  (broker db 0, backend db 1)
   |
   v
Celery worker  (same venv and .env as Apache)
   |
   v
Result stored in Redis; Dash polls and updates the page
```

## 2. On-disk layout

```text
/var/www/flask/
├── .env                      # production environment (shared by WSGI and Celery)
├── skvo_veb_2.wsgi           # Apache WSGI entry
└── skvo_veb_2/
    ├── .venv/                # Python virtualenv (python-home in Apache)
    ├── skvo_veb/             # application package
    ├── deployment/           # vhost, WSGI template, systemd unit, helper scripts
    └── log/                  # Apache, application, and Celery logs
```

The WSGI file (`deployment/skvo_veb_2.wsgi`) must be installed as `/var/www/flask/skvo_veb_2.wsgi`. It inserts `/var/www/flask/skvo_veb_2` on `sys.path` and loads `/var/www/flask/.env`.

Apache `python-home` must be `/var/www/flask/skvo_veb_2/.venv`. Do not activate the venv by hand; both Apache and the systemd unit use that interpreter path directly.

## 3. Environment file

Production reads `/var/www/flask/.env` (WSGI via `load_dotenv`, Celery via `EnvironmentFile=`).

Required for background callbacks:

```text
USE_REDIS=true
REDIS_BROKER=redis://localhost:6379/0
REDIS_BACKEND=redis://localhost:6379/1
```

Required so Dash URLs match Apache `WSGIScriptAlias /igebc` (omit on a local `main.py` run):

```text
BEHIND_WSGI_ALIAS=true
```

Also required (typical):

```text
SECRET_KEY=...
APP_LOG=/var/www/flask/skvo_veb_2/log/app.log
TESS_CACHE_DIR=...
ASASSN_CACHE_DIR=...
USER_CACHE_DIR=...
DISKCACHE_DIR=...
DB_HOST=...
DB_NAME=...
DB_USER=...
DB_PASS=...
```

Do not set `DEBUG_LOCAL` in production. That flag changes Gaia database routing.

Local development uses a project `.env` with `USE_REDIS=false` and `DiskcacheManager` instead of Celery. That path is for `main.py` on a workstation, not Apache.

## 4. Why Redis and Celery (background callbacks)

Dash callbacks marked `background=True` (TESS archive retrieve/stitch, Lightcurve Discovery search and fetch, long GP fits) would otherwise run inside the Apache WSGI process. That would block a worker thread for tens of seconds and often hit Apache timeouts.

`skvo_veb/config.py` selects the manager:

- `USE_REDIS=true`: `CeleryManager` wrapping a Celery app (`REDIS_BROKER`, `REDIS_BACKEND`).
- otherwise: `DiskcacheManager` on `DISKCACHE_DIR` (development only).

The Celery application object is created once with the Dash app in `skvo_veb/app.py`. `skvo_veb/__init__.py` exports it as `skvo_veb.celery_app` (`background_callback_manager.handle`) so the worker command can be:

```bash
celery -A skvo_veb.celery_app worker
```

Redis is the message broker (jobs in) and the result backend (jobs out). Celery is the process that performs the Python work. Both are required in production.

The worker must use the same virtualenv, `WorkingDirectory`, and `.env` as Apache. A worker from another install will consume jobs it cannot run.

Systemd unit: `deployment/celery-skvo-veb-2.service`, installed as `/etc/systemd/system/celery-skvo-veb-2.service`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now celery-skvo-veb-2
sudo systemctl status celery-skvo-veb-2
```

Manual worker (tests only; systemd is the normal method): `deployment/go_celery.sh`, run as `www-data`. Do not run the worker as root (cache files would be unwritable by Apache).

Health check (as `www-data`, from the app root, with `.env` loaded):

```bash
.venv/bin/celery -A skvo_veb.celery_app inspect ping
```

## 5. Apache

SSL vhost: `deployment/astronomy_igebc-le-ssl.conf`, installed under `/etc/apache2/sites-available/` and enabled with `a2ensite`.

Important directives:

- `DocumentRoot /opt/astronomy` : WordPress at `/`
- `WSGIScriptAlias /igebc /var/www/flask/skvo_veb_2.wsgi` : Dash at `/igebc`
- `WSGIDaemonProcess` with `python-home=/var/www/flask/skvo_veb_2/.venv`
- `WSGIApplicationGroup %{GLOBAL}` : required for some scientific C extensions

Dash URL prefixes are selected in `Config.dash_pathname_kwargs()` from `BEHIND_WSGI_ALIAS`:

- Production (this flag `true`): `requests_pathname_prefix='/igebc/'` only. Flask routes stay at `/` because `WSGIScriptAlias` already strips `/igebc`. Setting `url_base_pathname='/igebc/'` here yields HTTP 404 with no Python traceback.
- Local `python main.py` (flag unset): `url_base_pathname='/igebc/'`. Open `http://localhost:8051/igebc/`.

### Reload versus restart

| Command | Effect |
| :--- | :--- |
| `sudo apache2ctl configtest` | Syntax check. Run before any reload. |
| `sudo systemctl reload apache2` | Re-read vhosts and WSGI. Preferred after code or vhost edits. |
| `sudo systemctl restart apache2` | Full stop/start. Use if reload is not enough (stuck daemon, `python-home` change that did not apply). |

`WSGIScriptReloading On` reloads the Python application when the `.wsgi` file timestamp changes. Touching `/var/www/flask/skvo_veb_2.wsgi` is a light way to recycle the WSGI process after Python code updates:

```bash
sudo touch /var/www/flask/skvo_veb_2.wsgi
```

After changing the Celery unit or `.env` Redis settings, restart the Celery worker as well:

```bash
sudo systemctl restart celery-skvo-veb-2
```

Helper script (activate this stack and bounce Apache plus Celery):

```bash
sudo /var/www/flask/skvo_veb_2/deployment/restart-skvo-veb-2.sh
```

## 6. Logs

| Log | Path |
| :--- | :--- |
| Apache error / WSGI tracebacks | `/var/www/flask/skvo_veb_2/log/error.log` |
| Apache access | `/var/www/flask/skvo_veb_2/log/access.log` |
| Application (`APP_LOG`) | `/var/www/flask/skvo_veb_2/log/app.log` |
| Celery | `/var/www/flask/skvo_veb_2/log/celery.log` |

Directories must be writable by `www-data`.

## 7. Typical operations

**After deploying Python code**

```bash
sudo touch /var/www/flask/skvo_veb_2.wsgi
sudo systemctl restart celery-skvo-veb-2
```

**After editing the Apache vhost**

```bash
sudo apache2ctl configtest
sudo systemctl reload apache2
```

**After editing `/var/www/flask/.env`**

WSGI reads the environment at import, so recycle WSGI and restart Celery:

```bash
sudo touch /var/www/flask/skvo_veb_2.wsgi
sudo systemctl restart celery-skvo-veb-2
```

**Confirm Redis**

```bash
redis-cli ping
```

## 8. Dual install (legacy tree versus current tree)

This section applies only while two code trees exist on the same host. Remove it when the legacy tree is decommissioned.

Legacy tree: `/var/www/flask/skvo_veb`

Current tree: `/var/www/flask/skvo_veb_2`

Public URL is the same (`/igebc/`). Only one Apache vhost and only one Celery worker must be active. Both workers would share `REDIS_BROKER` / `REDIS_BACKEND` in `/var/www/flask/.env` and steal each other's jobs.

| Stack | Apache site (typical name) | Celery systemd unit |
| :--- | :--- | :--- |
| Current | `astronomy_igebc-le-ssl.conf` | `celery-skvo-veb-2` |
| Legacy | `astronomy_igebc-le-ssl_old.conf` | `celery` |

Confirm real site filenames with `ls /etc/apache2/sites-available/` and edit the variables at the top of the helper scripts if needed.

**Make the current stack live**

```bash
sudo /var/www/flask/skvo_veb_2/deployment/restart-skvo-veb-2.sh
```

**Return to the legacy stack**

```bash
sudo /var/www/flask/skvo_veb_2/deployment/rollback-to-skvo-veb.sh
```

First-time install of the current Celery unit:

```bash
sudo cp /var/www/flask/skvo_veb_2/deployment/celery-skvo-veb-2.service /etc/systemd/system/
sudo mkdir -p /var/www/flask/skvo_veb_2/log
sudo chown www-data:www-data /var/www/flask/skvo_veb_2/log
sudo systemctl daemon-reload
```

Keep the legacy `celery.service` file on disk; `disable` it while the current stack is live so it does not start on boot.
