"""Shared Bootstrap alert helpers for LC pages.

``status_alert`` is the canonical factory (Ticket 4): dismissable always;
``info`` / ``success`` auto-clear; ``warning`` / ``danger`` stay until
dismiss or replacement. Legacy ``warning_alert`` / ``info_alert`` keep their
old undismissable shape for any remaining non-migrated callers.
"""

from __future__ import annotations

import logging
import uuid

import dash_bootstrap_components as dbc

# DEBUG_EXCEPTION = True
DEBUG_EXCEPTION = False

if DEBUG_EXCEPTION:
    import traceback

logger = logging.getLogger(__name__)

# dbc.Alert ``duration`` for info/success. Warning and danger stay until
# dismiss, a newer message, or a deliberate clear. Tweak this one value only.
STATUS_ALERT_DURATION_MS = 4000
_STATUS_ALERT_TIMED_COLORS = frozenset({"info", "success"})


def status_alert(message: str, color: str) -> dbc.Alert:
    """Builds a dismissable status alert with Processor timing rules.

    Every message is dismissable. Info and success use
    ``STATUS_ALERT_DURATION_MS`` via the ready-made ``dbc.Alert`` timer.
    Warning and danger omit ``duration`` and stay until dismiss, a newer
    message, or an explicit clear.

    Args:
        message (str): User-facing text.
        color (str): Bootstrap alert colour (e.g. ``info``, ``warning``).

    Returns:
        dash_bootstrap_components.Alert: Alert component for a feedback slot.
    """
    duration = (
        STATUS_ALERT_DURATION_MS if color in _STATUS_ALERT_TIMED_COLORS else None
    )
    return dbc.Alert(
        message,
        color=color,
        className="py-2 mb-0",
        dismissable=True,
        duration=duration,
        is_open=True,
        key=str(uuid.uuid4()),
    )


def warning_alert(arg: Exception | str):
    """Builds a Bootstrap warning alert from a string or exception.

    Upload catch sites should pass a pre-sanitised string from
    ``format_user_upload_error``; this helper does not hide exception text.

    Legacy helper for pages not yet on ``status_alert``. New call sites should
    use ``status_alert`` (dismissable; sticky warning).

    Args:
        arg (Exception | str): User-facing message, or an exception whose
            ``str()`` is shown (traceback when ``DEBUG_EXCEPTION`` is true).

    Returns:
        dbc.Alert: Warning-coloured alert with preserved newlines.
    """
    if not isinstance(arg, BaseException):
        message = arg
    elif DEBUG_EXCEPTION:
        message = traceback.format_exc()
    else:
        message = str(arg).strip() or arg.__class__.__name__
    return dbc.Alert(f'{message}', color='warning', style={'white-space': 'pre-wrap'})


def info_alert(message: str):
    """Builds a legacy undismissable info alert.

    New call sites should use ``status_alert(message, "info")``.

    Args:
        message (str): User-facing text.

    Returns:
        dbc.Alert: Info-coloured alert.
    """
    return dbc.Alert(f'{message}', color='info')
