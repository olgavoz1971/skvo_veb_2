"""Tests for shared utility helpers in ``my_tools``."""

from __future__ import annotations

from skvo_veb.utils.my_tools import sanitize_filename


def test_sanitize_filename_removes_parentheses():
    """Parentheses are dropped rather than replaced with underscores."""
    assert sanitize_filename("AA And (ZTF r)") == "AA_And_ZTF_r"


def test_sanitize_filename_collapses_underscores():
    """Repeated underscores from spacing and punctuation collapse to one."""
    assert sanitize_filename("foo  (bar)  baz") == "foo_bar_baz"


def test_sanitize_filename_replaces_equals():
    """Equals signs in titles become underscores for export stems."""
    assert sanitize_filename("999 filter=g") == "999_filter_g"


def test_sanitize_filename_hyphen_separators_no_dangling_underscores():
    """Title separators like ' - ' must not leave '_-_' in export stems."""
    assert (
        sanitize_filename("AA And - 165243463579570976 filter=i")
        == "AA_And_165243463579570976_filter_i"
    )


def test_sanitize_filename_replaces_forbidden_characters():
    """Standard unsafe path characters become underscores."""
    assert sanitize_filename('a/b:c*d?') == "a_b_c_d_"
