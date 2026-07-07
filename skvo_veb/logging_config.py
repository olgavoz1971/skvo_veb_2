"""Central logging configuration for the skvo_veb application.

Configures the root logger once with mirrored file and console handlers so every
module-level ``logger = logging.getLogger(__name__)`` emits to ``APP_LOG`` and
the terminal without per-file ``basicConfig`` calls.
"""

from __future__ import annotations

import logging
import sys
from os import getenv

_LOG_FORMAT = '%(asctime)s %(levelname)s [%(name)s] %(message)s'
_LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def _resolve_log_level(level: int | None) -> int:
    """Resolves the effective log level from explicit input or ``DEBUG_APP``.

    Args:
        level (int, optional): Explicit ``logging`` level constant.

    Returns:
        int: Resolved log level.
    """
    if level is not None:
        return level
    debug = getenv('DEBUG_APP', 'false').upper() in ('TRUE', '1')
    return logging.DEBUG if debug else logging.INFO


def configure_logging(level: int | None = None) -> None:
    """Initialises root logging with file and stream handlers (idempotent).

    When ``APP_LOG`` is set, log records are written to that path and duplicated
    on stderr. When unset, only the stream handler is attached (e.g. tests).

    Args:
        level (int, optional): ``logging`` level; defaults from ``DEBUG_APP``.
    """
    if getattr(configure_logging, '_configured', False):
        return

    root = logging.getLogger()
    if root.handlers:
        configure_logging._configured = True
        return

    resolved_level = _resolve_log_level(level)
    root.setLevel(resolved_level)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(resolved_level)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    app_log = getenv('APP_LOG')
    if app_log:
        try:
            file_handler = logging.FileHandler(app_log)
            file_handler.setLevel(resolved_level)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                'Could not open APP_LOG %r (%s); logging to stderr only.',
                app_log,
                exc,
            )

    configure_logging._configured = True
