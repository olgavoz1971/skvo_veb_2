"""Tests for user-facing lightcurve upload error text."""

from skvo_veb.utils.lc_bridge import format_user_upload_error
from skvo_veb.utils.my_tools import PipeException


def test_pipe_exception_text_is_shown():
    """User-facing PipeException text is returned unchanged."""
    exc = PipeException(
        "Invalid .dat row at line 4: column 'mag' expects a numeric value, got 'x'.\n"
        "Offending line: 2459000.5 x 0.02"
    )
    assert format_user_upload_error(exc) == str(exc)


def test_short_value_error_is_shown():
    """Short ingest ValueError text is shown, not a generic gag line."""
    exc = ValueError("No time column found in the uploaded file.")
    assert format_user_upload_error(exc) == str(exc)


def test_empty_exception_uses_class_name():
    """An exception with empty ``str()`` falls back to the type name."""
    assert format_user_upload_error(ValueError()) == "ValueError"


def test_traceback_dump_is_truncated():
    """Traceback-like dumps keep the first line and point to the server log."""
    dump = (
        "not well-formed (invalid token): line 1, column 1\n"
        "Traceback (most recent call last):\n"
        '  File "astropy/io/votable/tree.py", line 1, in parse\n'
        "    raise ValueError('xml boom')\n"
        "ValueError: xml boom"
    )
    text = format_user_upload_error(ValueError(dump))
    assert text.startswith("not well-formed (invalid token): line 1, column 1")
    assert "Full details were logged on the server." in text
    assert "Traceback" not in text


def test_long_parser_dump_is_truncated():
    """Very long parser text is truncated to a short first-line reason."""
    first = "W49: Invalid XML content in VOTable header"
    dump = first + "\n" + ("x" * 500)
    text = format_user_upload_error(Exception(dump))
    assert text.startswith(first)
    assert "Full details were logged on the server." in text
    assert "x" * 50 not in text
