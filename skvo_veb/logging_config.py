"""Central logging configuration for the skvo_veb application.

Configures the root logger once with mirrored file and console handlers so every
module-level ``logger = logging.getLogger(__name__)`` emits to ``APP_LOG`` and
the terminal without per-file ``basicConfig`` calls.
"""

from __future__ import annotations

import logging
import sys
import warnings
from contextlib import contextmanager
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


class LogWarningError(Exception):
    """Raised when a monitored logger emits at or above the configured level."""


class _RaiseOnLogHandler(logging.Handler):
    """Handler that aborts logging by raising ``LogWarningError``."""

    def emit(self, record: logging.LogRecord) -> None:
        """Raises ``LogWarningError`` with the formatted log message.

        Args:
            record (logging.LogRecord): Record being logged.
        """
        raise LogWarningError(self.format(record))


@contextmanager
def log_warnings_as_errors(*logger_names: str, level: int = logging.WARNING):
    """Turns WARNING (or higher) log records on named loggers into exceptions.

    Attach a temporary handler so ``logger.warning()`` in third-party code
    (e.g. Lightkurve) surfaces as ``LogWarningError`` instead of only appearing
    on stderr. Handlers are removed when the context exits.

    Args:
        *logger_names (str): Logger names to monitor (e.g. ``'lightkurve.periodogram'``).
        level (int): Minimum level that triggers an exception.

    Yields:
        None

    Raises:
        LogWarningError: If a monitored logger emits at ``level`` or above.
    """
    attached: list[tuple[logging.Logger, _RaiseOnLogHandler]] = []
    try:
        for name in logger_names:
            monitored = logging.getLogger(name)
            handler = _RaiseOnLogHandler()
            handler.setLevel(level)
            handler.setFormatter(logging.Formatter('%(message)s'))
            monitored.addHandler(handler)
            attached.append((monitored, handler))
        yield
    finally:
        for monitored, handler in attached:
            monitored.removeHandler(handler)


@contextmanager
def warnings_and_log_as_errors(*logger_names: str, log_level: int = logging.WARNING):
    """Combines ``warnings.simplefilter('error')`` with ``log_warnings_as_errors``.

    Args:
        *logger_names (str): Logger names passed to ``log_warnings_as_errors``.
        log_level (int): Minimum log level that triggers ``LogWarningError``.

    Yields:
        None
    """
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        with log_warnings_as_errors(*logger_names, level=log_level):
            yield
