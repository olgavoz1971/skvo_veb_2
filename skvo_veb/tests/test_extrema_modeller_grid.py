"""Extrema modeller live/review cards share one graphic configuration."""

from skvo_veb.components.extrema_modeller_appearance import (
    CARD_COL_WIDTH,
    CARD_ROWS_PER_PAGE,
    CARDS_PER_ROW,
    PAGE_SIZE,
    REVIEW_CARD_PLOT_HEIGHT,
)


def test_grid_divides_bootstrap_row():
    """Column width is derived from cards per row; page size is rows times columns."""
    assert CARDS_PER_ROW >= 1
    assert CARD_ROWS_PER_PAGE >= 1
    assert 12 % CARDS_PER_ROW == 0
    assert CARD_COL_WIDTH == 12 // CARDS_PER_ROW
    assert CARD_COL_WIDTH * CARDS_PER_ROW == 12
    assert PAGE_SIZE == CARDS_PER_ROW * CARD_ROWS_PER_PAGE


def test_review_card_plot_height_is_one_number():
    """Live and review card figures share one Plotly height."""
    assert REVIEW_CARD_PLOT_HEIGHT > 0


def test_photcal_fallback_is_not_a_gp_parameter():
    """Incomplete-upload zero points live on the lightcurve, not in GP config."""
    from skvo_veb.utils import gp as gp_pkg
    from skvo_veb.utils.lc_config import (
        DEFAULT_REFERENCE_MAG,
        DEFAULT_ZP_FLUX_DIMENSIONLESS,
    )

    assert DEFAULT_REFERENCE_MAG == 20.0
    assert DEFAULT_ZP_FLUX_DIMENSIONLESS == 1.0
    assert not hasattr(gp_pkg, "DEFAULT_REFERENCE_MAG")
    assert not hasattr(gp_pkg, "GP_ZP_FLUX_DIMENSIONLESS")
