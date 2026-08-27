# --- Documentation Content ---
GP_HELP_MARKDOWN = """

# Lightcurve Extrema Modeller (Gaussian Process regression)

## What this tool does
This tool models a selected fragment of a light curve and determines the time of a minimum or maximum, 
together with its uncertainty.

Instead of fitting a fixed function (e.g. parabola), it builds a **smooth probabilistic model** 
of the data using a **Gaussian Process (GP)**.  
In practice, this means:
- the model adapts to the actual shape of the light curve,
- it handles uneven sampling and gaps naturally,
- it accounts for observational noise.

You can think of it as drawing a smooth curve through the data, while also estimating how uncertain that curve is.

---

## When to use it
This method is useful when:
- the extremum is not perfectly symmetric,
- the data are noisy,
- there are gaps or irregular cadence,
- simple polynomial fits give unstable or biased results.

---

## How the model behaves
The model is controlled by a few parameters that define how "flexible" or "smooth" the curve is, 
and how much it trusts the data.

Internally, we use a kernel of the form:

`ConstantKernel (Amplitude) × [Matern(ν = 2.5) OR RBF]`

You do not need to work with this directly — the parameters below are the practical controls.

---

## Parameters

**GUESS_SIGMA**

If enabled, the model ignores provided uncertainties and estimates noise from the data scatter (MAD). 
Use this if errors are missing or clearly unreliable. (TBD)

---

**ASSUMED_NOISE_SCALE**

A handy "trust factor" for measurement noise.
Encodes your own judgement about whether the provided (or guessed) errors are trustworthy. Applied as
a multiplier to both guessed noise and provided observation errors: `effective error = original error × ASSUMED_NOISE_SCALE`.

This is not a cosmetic dial — it's how you feed the model information it cannot get from the data alone.
Two visual symptoms tell you which way to move it:

- **Fit looks saw-toothed / chases individual points** → the assumed noise is too small for the model
  to trust its own smoothness. Increase the value — this raises the effective error and removes the
  wiggle by letting the fit lean on more points at once.

- **Fit looks blunt/shallow, doesn't reach the visible extremum, or the error-bar fence obscures the
  feature itself** → the assumed noise is too large. Decrease the value.

*Caveat:* if you find yourself needing extreme values to get a sane-looking fit, check first whether
`LENGTH_SCALE` bounds (below) are fighting this parameter for the same job -- the two are not
interchangeable and correcting one with the other can mask what's actually wrong.

---

**LENGTH_SCALE (MIN / INIT / MAX)**

Controls the smoothness in time (x-axis).

- *INIT*: initial guess (≈ half of a typical feature width)  
- *MIN*: prevents the model from diving into individual noise spikes 
- *MAX*: prevents the model from becoming so stiff it misses the peak.

Practical tuning:
- Fit is too wiggly --> increase values  
- Fit is too smooth --> decrease values

**On sparsely-covered features:** for extrema with too few points to constrain a scale on their own, 
we sometimes import a scale learned from well-covered cycles of the *same* light curve, narrowing 
MIN/MAX around it rather than fitting freely. With very few points, a freely-fit scale can lock onto 
a value that fits those points well but has nothing to do with the real shape of the feature. 
Borrowed shape information from the same star is usually more trustworthy than what a handful of points can tell you on their own.

The trade-off: the reported timing uncertainty for such an extremum reflects noise only, conditional on 
the imported shape — it does **not** include how much the answer would shift if that imported shape is 
itself slightly wrong for this particular cycle. **Any extremum where the fitted scale sits at (or 
against) its MIN/MAX bound is flagged in the output** as scale-constrained, precisely because its 
uncertainty is of this weaker, conditional kind rather than a locally-estimated one.

---

**SIGNAL AMPLITUDE (MIN / INIT / MAX)**

Controls the vertical "headroom" (y-axis).
Since we work with normalised flux, the amplitude represents how far the GP can swing from the baseline.

- *Too low*: The model may "clip" and fail to reach the true top of a sharp peak;
- *Too high*: The model might become unstable and create non-physical vertical swings.

---

**KERNEL TYPE**

- *Matern (ν=2.5)*: twice differentiable, physically realistic;
- *RBF*: (Radial Basis Function): infinitely smooth. Best for very rounded, geometric features, 
   but can sometimes be too stiff for real data.

---

**EXTREMA_MODE**

Select what to detect:
- `min` — minima (eclipses)  
- `max` — maxima (peaks)

---

## How the extremum and its uncertainty are computed

1. **Best estimate**  
   The extremum is taken from the smooth model curve (the GP mean).

2. **Uncertainty**  
   The model generates many possible light curves consistent with the data.  
   The extremum is measured for each of them.

3. **Final error**  
   The spread of these extrema gives the uncertainty in time.

4. **Constrained-scale flag**  
   If `LENGTH_SCALE` was imported/narrowed rather than freely fit (see above) and the optimiser sits at 
   its bound, the extremum is marked accordingly. Its quoted uncertainty should be read as noise-only, 
   not as including shape uncertainty.

We hope this approach naturally accounts for noise, sampling, and shape of the feature — and where it 
can't, we try to say so rather than hide it in a single number.

---

## If you are curious how it works

### What is a Gaussian Process

A Gaussian Process (GP) is a way to describe **a whole family of possible curves** that could pass 
through your data. (**Note:** It does not fit the data with a Gaussian-shaped function; 
the term "Gaussian" refers to the underlying use of the Normal distribution to calculate probabilities).

Instead of choosing a fixed formula (like parabola, spline, etc.), we assume:
> “The true lightcurve is one of many smooth functions consistent with the observations.”

The model does not try to find *the* curve.  
It assigns a **probability to every possible curve**, favouring those that:
- pass near the data points,
- remain reasonably smooth (determined by your **length scale**),
- respect the assumed noise level.

### Visualising the "Family of Curves"
To turn this abstract probability into a concrete measurement, we look at the "Posterior Samples".

<img src="assets/samples.png" style="width:100%; max-width:600px; display:block; margin:auto;"/>

As you can see in the image above, the GP isn't just one particular curve. 
We draw three hundred of these "valid" realisations from the model. 
Each one is a smooth function that fits your data but has a slightly different peak position 
(marked by the red dots).
The "Peak JD" you see in the results is the extremum of the Blue Mean Curve.
We calculate the Standard Deviation (σ) of all the sampled peak positions (the red dots). 

---

### Why “Gaussian”?
The term *Gaussian* refers to how uncertainties are described.

For any set of time points, the model assumes that the flux values follow a **multivariate normal distribution**.  
In simpler terms:
- each point has an uncertainty,
- nearby points are **correlated** (they tend to vary together),
- this correlation is described in a mathematically convenient way.

This assumption makes the problem tractable and stable, while still being flexible enough for real light curves.

---

### What is actually being modeled?
The key idea is not the curve itself, but **how points are related to each other**.

We define:
- how strongly two observations are connected depending on their time separation,
- how smooth the curve should be,
- how much noise is present.

From this, the GP builds a smooth curve that:
- follows large-scale structure,
- ignores random scatter,
- adapts to asymmetry and irregular sampling.

The result is:
- a most probable curve (the mean),
- and a full description of uncertainty around it.

---

### Implementation
This tool uses the `GaussianProcessRegressor` from the  
`sklearn.gaussian_process` module in Python.

---

## References
- **Pedregosa et al. (2011):** [Scikit-learn: Machine Learning in Python]
(https://jmlr.csail.mit.edu/papers/v12/pedregosa11a.html), JMLR 12, pp. 2825-2830. 
Specifically the `GaussianProcessRegressor` module.
- **Rasmussen & Williams (2006):** [Gaussian Processes for Machine Learning]
(http://www.gaussianprocess.org/gpml/), MIT Press. (The "Bible" of GPs).
"""

PAGE_ABOUT_MARKDOWN = """
# Lightcurve Extrema Modeller

This page times minima (or maxima) on a light curve and plots O-C against a trial ephemeris.

Work from the top: load the light curve and mark intervals; time each extremum with a Gaussian Process or with MAVKA and keep the measurements you trust; then plot O-C (observed minus calculated times) and apply cycle corrections if a cycle has slipped.

Use About for this overview. Each accordion has its own help for that step.

"""

LC_INTERVALS_HELP_MARKDOWN = """

## Supported lightcurve file formats

Upload uses the **same ingest path** as the TESS lightcurve page: VOTable (`.vot`), CSV, ECSV, and `.dat`.

### `.dat` comment headers (ASCII)

For **`.dat` files only**, you may include metadata in ``#`` comment lines (case-insensitive):

| Pattern | Meaning |
|---------|---------|
| ``JD0 = <value>`` | Time origin added to the time column to obtain absolute Julian Date (default **0** if omitted). |
| ``MAG0 = <value>`` | Reference magnitude for photometric calibration when converting to the normalised flux used internally by the GP (paired with a dimensionless instrumental zero point). |
| ``PERIOD = <value>`` | Folding period in days (populates the **P** field after upload). |
| ``EPOCH = <value>`` | Reference epoch in the same units and scale as the time column (populates **Epoch-2400000.5**; combined with ``JD0`` when forming absolute JD). |
| ``FILTER=`` / ``BAND=`` | Filter or band label stored in metadata. |

You may also put a **header comment** whose words match the column count (e.g. ``# jd mag mag_err``). Otherwise columns default to time, magnitude, and magnitude error by position.

The GP fit works on **normalised flux**; timing (JD) is what matters for O-C. The y-axis in fit panels is not labelled with physical flux units (Jy or e/s).

See also the project document ``docs/dat_lightcurve_comments.md``.
"""

MAVKA_HELP_MARKDOWN = """
## About the MAVKA minima-timing tool

The underlying method was developed by **I. L. Andronov**, together with co-authors, as a statistically optimal approach to determining the **phenomenological** parameters of light-curve extrema — that is, parameters describing the *shape* of an eclipse or minimum as observed, without assuming an underlying physical (geometric or radiative) model of the star system.

The light curve is fitted piecewise: a smooth central function covers the region around the extremum, and — where the shape requires it — separate "wing" functions cover the branches on either side, joined at one or two **knots** (transition points between the pieces). The knot positions are not fixed in advance; they are solved for as part of the fit, together with the timing and depth of the minimum.

Four fitting methods are available:

- **Asymptotic Parabola (AP)** - a single smooth, gently rounded curve for typical minima.
- **Wall-Supported Asymptotic Parabola (WSAP)** - for minima with a flat or near-flat base (e.g. total eclipses). The wings are modelled with a power-law exponent of **1.5**, which is not an arbitrary numerical choice: it is the theoretically expected rate at which the eclipsed area — and hence the flux — changes near the moment of first/last contact between two circular stellar disks (see 2, and 3). (In the special case of two stars of equal radius, the exponent at inner contact reduces to 1, i.e. a straight line.)
- **Wall-Supported Line (WSL)** - for minima with a genuinely flat base and steep, straight sides, using the same 1.5-power "wall."
- **Two-line fit (A)** — a simpler method for sparse or noisy data, approximating the branches as two straight lines meeting near the minimum.

The tool reports the time of minimum with its formal uncertainty, the magnitude (depth) at minimum, and — where applicable — the eclipse duration, together with a plot of the fit for visual verification.

## Acknowledgements

The MAVKA method was developed by Kateryna Andrych, Ivan Andronov, and Lidia Chinarova (and co-authors) for the statistically optimal determination of phenomenological parameters of light-curve extrema. This implementation builds on the open-source Python realisation of the method by Maxim Pyatnytskyy. We gratefully acknowledge the authors of both the original algorithm and its Python implementation.

**If you use results obtained with this tool, please cite** the original MAVKA method paper and, where the WSAP or WSL methods are used, the paper introducing the "wall-supported" functions. If you use this specific implementation, please also acknowledge the Python code.

## References

1. Marsakova, V. I., Andronov, I. L. 1996, *Odessa Astronomical Publications*, 9, 127.
2. Andronov, I. L. 2012, *Astrophysics*, 55, 536. DOI: [10.1007/s10511-012-9259-0](https://doi.org/10.1007/s10511-012-9259-0)
3. Andrych, K. D., Andronov, I. L., Chinarova, L. L. 2018, *Statistically Optimal Modeling of Flat Eclipses and Exoplanet Transitions. The "Wall-Supported Polynomial" (WSP) Algorithms*. arXiv: [1712.05030](https://arxiv.org/abs/1712.05030)
4. Andronov, I. L., Tkachenko, M. G. 2013, *Odessa Astronomical Publications*, 26, 204.
5. Andrych, K. D., Andronov, I. L., Chinarova, L. L. 2020, *MAVKA: Program of Statistically Optimal Determination of Phenomenological Parameters of Extrema. Parabolic Spline Algorithm and Analysis of Variability of the Semi-Regular Star Z UMa*, *Journal of Physical Studies*, 24, article 1902. DOI: [10.30970/jps.24.1902](https://doi.org/10.30970/jps.24.1902)
6. Pyatnytskyy, M. *lc_approx*: Python implementation of MAVKA light-curve approximation methods. [github.com/mpyat2/lc_approx](https://github.com/mpyat2/lc_approx)
"""

# One row per workflow accordion. The factory reads only these keys.
# Page-level About (PAGE_ABOUT_MARKDOWN) is a separate modal, not in this table.
_ACCORDION_HELP_SPECS = (
    {
        "index": "lc",
        "title": "Lightcurve and intervals",
        "modal_title": "Lightcurve and intervals",
        "markdown": LC_INTERVALS_HELP_MARKDOWN,
        "allow_html": False,
        "close_label": "Close",
        "size": "xl",
    },
    {
        "index": "gp",
        "title": "Gaussian Process",
        "modal_title": "Description",
        "markdown": GP_HELP_MARKDOWN,
        "allow_html": True,
        "close_label": "Stop talking!",
        "size": "xl",
    },
    {
        "index": "mavka",
        "title": "MAVKA",
        "modal_title": "MAVKA",
        "markdown": MAVKA_HELP_MARKDOWN,
        "allow_html": False,
        "close_label": "Close",
        "size": "xl",
    },
    {
        "index": "oc",
        "title": "O-C",
        "modal_title": "O-C",
        "markdown": "Help for O-C",
        "allow_html": False,
        "close_label": "Close",
        "size": "md",
    },
)
_ACCORDION_HELP_BY_INDEX = {spec["index"]: spec for spec in _ACCORDION_HELP_SPECS}
ACCORDION_LC_ITEM_ID = "accordion-lc"

import dash
# import diskcache
from dash import (
    dcc,
    html,
    Input,
    Output,
    State,
    ALL,
    MATCH,
    callback_context,
    callback,
    no_update,
    clientside_callback,
    ClientsideFunction,
)
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

import base64
import io
import json
import numpy as np

import traceback
import logging
import uuid

from skvo_veb.utils.lc_bridge import (
    curvedash_from_transport_json,
    export_curvedash,
    format_user_upload_error,
    get_intervals_from_phase,
)
from skvo_veb.utils.my_tools import PipeException
from skvo_veb.utils.gp.prep_phase_plot import (
    EXTENDED_PHASE_XMAX,
    EXTENDED_PHASE_XMIN,
    assert_phase_intervals_not_duplicates,
    build_extended_phase_plot_arrays,
    build_extended_phase_plot_arrays_from_phi,
    merge_overlapping_phase_segments,
    phase_vrect_bounds_extended,
    phase_vrect_bounds_extended_quadratic,
    validate_extended_phase_selection,
)
from skvo_veb.utils.gp.quadratic_fold import (
    FOLD_EPHEMERIS_CONSTANT,
    FOLD_EPHEMERIS_QUADRATIC_OC,
    get_intervals_from_phase_quadratic,
    phases_from_quadratic_oc,
)
from skvo_veb.utils.gp.prep_interval_bands import (
    build_unfolded_interval_pick_payload,
    interval_shape_name,
    intervals_without_marked_indices,
    prep_interval_band_shape,
)

from skvo_veb.utils.gp import (
    GUESS_SIGMA, LEN_MIN,
    load_intervals, gp_peak_pipeline,
    KERNEL_TYPE, EXTREMA_MODE, guess_length_scale,
    AMPLITUDE_INIT, AMPLITUDE_MIN, AMPLITUDE_MAX,
    DEFAULT_FLOAT_PARAMS,
    pack_uploaded_lightcurve,
    decode_gp_flux_arrays,
    slice_gp_flux_arrays,
    figure_from_gp_result,
    format_intervals_download,
)
from skvo_veb.utils.gp.export import (
    apply_prep_fold_ephemeris,
    export_stem_from_upload_filename,
    gp_compact_extrema_download_name,
    gp_extended_extrema_download_name,
    gp_extrema_export_stem,
    gp_intervals_export_download_name,
    gp_lc_export_download_name,
)
from skvo_veb.utils.gp.flux import empty_interval_indices
from skvo_veb.utils.gp.manual_detrend import apply_manual_linear_detrend
from skvo_veb.utils.gp.results_export import (
    build_extended_export_zip,
    format_compact_extrema_dat,
    scale_limit_flag,
)
from skvo_veb.utils.gp.review_cache import load_gp_review_run, save_gp_review_run
from skvo_veb.utils.gp.review_page import (
    badges_from_specs,
    build_review_store_payload,
    render_review_page,
    review_page_label,
    serialise_review_entry,
    success_badge_specs,
)
from skvo_veb.utils.gp.config import GP_LIVE_PAGE_SIZE, build_gp_float_params
from skvo_veb.utils.gp.run_control import (
    clear_gp_batch_stop,
    gp_batch_stop_requested,
    request_gp_batch_stop,
)
from skvo_veb.utils.gp.live_page import (
    build_live_page_slot_children,
    live_progress_label,
    live_slot_waiting,
    live_visible_page_for_done_count,
)
from skvo_veb.utils.mavka import (
    DEFAULT_EXTREMA_MODE,
    DEFAULT_METHOD,
    MAVKA_LIVE_PAGE_SIZE,
    MAXIMA_NOT_AVAILABLE,
    METHOD_OPTIONS,
    figure_from_mavka_result,
    fit_interval as mavka_fit_interval,
    slice_interval_photometry,
)
from skvo_veb.utils.mavka.config import MAVKA_PIECE_COLOURS, MAVKA_REVIEW_PAGE_SIZE
from skvo_veb.utils.mavka.export import (
    build_extended_export_zip as build_mavka_extended_export_zip,
    format_compact_extrema_dat as format_mavka_compact_extrema_dat,
    mavka_compact_extrema_download_name,
    mavka_extended_extrema_download_name,
    mavka_extrema_export_stem,
)
from skvo_veb.utils.mavka.live_page import (
    build_live_page_slot_children as build_mavka_live_page_slot_children,
    live_progress_label as mavka_live_progress_label,
    live_slot_waiting as mavka_live_slot_waiting,
    live_visible_page_for_done_count as mavka_live_visible_page_for_done_count,
)
from skvo_veb.utils.mavka.review_cache import (
    load_mavka_review_run,
    save_mavka_review_run,
)
from skvo_veb.utils.mavka.review_page import (
    build_review_store_payload as build_mavka_review_store_payload,
    render_review_page as render_mavka_review_page,
    review_entry_from_fit as mavka_review_entry_from_fit,
    review_page_label as mavka_review_page_label,
    serialise_review_entry as serialise_mavka_review_entry,
)
from skvo_veb.utils.mavka.run_control import (
    clear_mavka_batch_stop,
    mavka_batch_stop_requested,
    request_mavka_batch_stop,
)
from skvo_veb.utils.oc.compute import compute_step1_oc, cycle_shifts_from_store
from skvo_veb.utils.oc.export import (
    format_oc_dat,
    oc_default_export_stem,
    oc_export_download_name,
    oc_source_filename,
)
from skvo_veb.utils.oc.tom_io import (
    parse_compact_tom_dat,
    toms_from_review_store,
    uploaded_toms_from_store,
)
from skvo_veb.utils.gp.plot_data import (
    folding_metadata_from_transport,
    transport_revision_token,
    unpack_json_for_gp_plot,
)
from skvo_veb.utils.gp.intervals import (
    format_interval_display_pair,
    format_interval_display_pairs,
)
from skvo_veb.utils.gp.working_window import (
    WORKING_WINDOW_DISABLED,
    build_working_window_store,
    filter_plot_arrays_by_jd_window,
    interval_overlaps_jd_window,
    jd_bounds_from_visible_plot,
    normalize_working_window,
    observation_jd_bounds_tuple,
    transport_json_for_prep_export,
)
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
    DEFAULT_EXPORT_FORMAT,
    EXPORT_FORMAT_OPTIONS,
    TIME_AXIS_DATE,
    TIME_AXIS_MJD,
    absolute_jd_from_display_epoch,
    display_epoch_offset,
)
from skvo_veb.utils.lc_figure import (
    absolute_jd_to_plot_x,
    apply_time_xaxis_format,
    time_axis_xaxis_title,
)
from skvo_veb.utils.lc_interaction import (
    apply_plot_relayout_ranges_to_figure,
    plot_x_to_jd,
)

jd0 = DEFAULT_EPOCH_JD

logger = logging.getLogger(__name__)

_LIVE_SLOT_PROGRESS_OUTPUTS = [
    Output({"type": "gp-live-slot", "index": i}, "children")
    for i in range(GP_LIVE_PAGE_SIZE)
]
_MAVKA_LIVE_SLOT_PROGRESS_OUTPUTS = [
    Output({"type": "mavka-live-slot", "index": i}, "children")
    for i in range(MAVKA_LIVE_PAGE_SIZE)
]
# Gaia Eclipsing Binary Catalog - IGEBC
dash.register_page(__name__, name='O-C',
                   order=7,
                   title='Extrema modeller for O-C',
                   description='Determination of individual extrema timings in a light curve',
                   in_navbar=True,
                   path='/gp')

params_float = DEFAULT_FLOAT_PARAMS
# # Initialize diskcache for background callbacks
# cache = diskcache.Cache("./cache")
# background_callback_manager = DiskcacheManager(cache)


def _gp_click_help(
    help_id: str,
    title: str,
    body,
    *,
    placement: str = "bottom",
    label: str = "?",
    trigger_class_name: str = "lc-discovery-help-btn",
):
    """Builds a click-triggered help control and its popover (GP page).

    Args:
        help_id (str): Short slug for unique component ids.
        title (str): Popover header text.
        body: Popover body as a string or sequence of Dash components.
        placement (str): Bootstrap popover placement.
        label (str): Trigger text, ``?`` for a single control or e.g. ``TIPS``
            for a workflow guide.
        trigger_class_name (str): CSS classes on the help trigger element.

    Returns:
        tuple: ``(help_button, popover)`` components.
    """
    btn_id = f"gp_page_help_{help_id}_btn"
    pop_id = f"gp_page_help_{help_id}_popover"
    if not isinstance(body, (list, tuple)):
        body = [html.P(body, className="mb-0")]
    button = html.Strong(
        label,
        id=btn_id,
        role="button",
        tabIndex=0,
        className=trigger_class_name,
        **{"aria-label": f"Help: {title}"},
    )
    popover = dbc.Popover(
        [
            dbc.PopoverHeader(title),
            dbc.PopoverBody(body),
        ],
        id=pop_id,
        target=btn_id,
        trigger="legacy",
        placement=placement,
        className="lc-discovery-help-popover",
    )
    return button, popover


def _accordion_title_with_help(spec: dict) -> html.Div:
    """Builds an accordion header: title text and a right-aligned ``?``.

    The visible ``?`` is not a Dash target. Page JS opens the matching modal
    without toggling the accordion.

    Args:
        spec (dict): One row of ``_ACCORDION_HELP_SPECS``.

    Returns:
        dash.html.Div: Header row for ``dbc.AccordionItem.title``.
    """
    label = spec["title"]
    help_index = spec["index"]
    return html.Div(
        [
            html.Span(label, className="gp-accordion-title-text"),
            html.Span(
                "?",
                className=(
                    "lc-discovery-help-btn gp-accordion-help "
                    f"gp-accordion-help--{help_index}"
                ),
                role="button",
                tabIndex=0,
                **{
                    "data-gp-accordion-help": help_index,
                    "aria-label": f"Help: {label}",
                },
            ),
        ],
        className="gp-accordion-title-row",
    )


def _accordion_help_modal(spec: dict) -> dbc.Modal:
    """Builds the help modal for one accordion item from its spec row.

    Args:
        spec (dict): One row of ``_ACCORDION_HELP_SPECS``.

    Returns:
        dbc.Modal: Closed on load.
    """
    index = spec["index"]
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(spec["modal_title"])),
            dbc.ModalBody(
                dcc.Markdown(
                    spec["markdown"],
                    dangerously_allow_html=bool(spec["allow_html"]),
                )
            ),
            dbc.ModalFooter(
                dbc.Button(
                    spec["close_label"],
                    id={"type": "gp-accordion-help-close", "index": index},
                    color="secondary",
                    size="sm",
                    className="ms-auto",
                    n_clicks=0,
                )
            ),
        ],
        id={"type": "gp-accordion-help-modal", "index": index},
        size=spec["size"],
        is_open=False,
    )


def _accordion_help_proxies() -> html.Div:
    """Hidden buttons the header ``?`` clicks so Dash can open each modal.

    Returns:
        dash.html.Div: One proxy button per accordion help spec.
    """
    return html.Div(
        [
            html.Button(
                type="button",
                id={"type": "gp-accordion-help-open", "index": spec["index"]},
                className=f"gp-help-proxy--{spec['index']}",
                n_clicks=0,
                tabIndex=-1,
                **{
                    "data-gp-help-proxy": spec["index"],
                    "aria-hidden": "true",
                },
            )
            for spec in _ACCORDION_HELP_SPECS
        ],
        className="gp-accordion-help-proxies",
    )


def _active_items_opening_lc(active_item) -> list:
    """Returns the always-open accordion set with Lightcurve and intervals included.

    Args:
        active_item: Current ``active_item`` from ``main-workflow-accordion``
            (list, single id, or ``None``).

    Returns:
        list: Item ids that should be open, including ``ACCORDION_LC_ITEM_ID``.
    """
    if active_item is None:
        items = []
    elif isinstance(active_item, (list, tuple)):
        items = [item for item in active_item if item]
    else:
        items = [active_item]
    if ACCORDION_LC_ITEM_ID not in items:
        items.append(ACCORDION_LC_ITEM_ID)
    return items


GP_UPLOAD_STATUS_ICONS = {
    "ok": "bi-check-circle-fill text-success",
    "info": "bi-check-circle-fill text-primary",
    "error": "bi-exclamation-triangle-fill text-danger",
}


def _gp_upload_placeholder() -> html.Span:
    """Idle caption shown in a data-bar slot before a file is chosen.

    Returns:
        dash.html.Span: Muted hint for the ``upload-*-text`` slot.
    """
    return html.Span("Drag or select", className="gp-upload-name-text text-muted")


def _gp_upload_status(filename: str, *, tone: str) -> html.Div:
    """File name chip shown next to an upload button.

    Args:
        filename (str): File name to display; truncated at the front when long.
        tone (str): ``ok`` for a loaded file, ``info`` for an exported file,
            ``error`` for a file that failed to parse.

    Returns:
        dash.html.Div: Icon plus truncating file name for ``upload-*-text``.

    Raises:
        ValueError: If ``tone`` is not a known status tone.
    """
    if tone not in GP_UPLOAD_STATUS_ICONS:
        raise ValueError(f"Unknown upload status tone: {tone}")
    return html.Div(
        [
            html.I(className=f"bi {GP_UPLOAD_STATUS_ICONS[tone]} gp-upload-status-icon"),
            html.Span(filename, className="gp-upload-name-text", title=filename),
        ],
        className="gp-upload-status",
    )


def _gp_upload_failure_detail(title: str, body: str) -> html.Div:
    """Explanatory block revealed by the ``?`` button after a failed upload.

    Args:
        title (str): Short headline, e.g. ``Lightcurve upload failed``.
        body (str): User-facing error text (may span several lines).

    Returns:
        dash.html.Div: Content for a ``gp-upload-detail`` collapse.
    """
    return html.Div(
        [
            html.B(title),
            html.Pre(body, className="gp-upload-detail-body"),
        ]
    )


def _gp_upload_slot(upload_id: str, button_label: str, detail_index: str) -> html.Div:
    """Builds one data-bar slot: load button, file name and a detail toggle.

    Clicking anywhere in the target opens the file dialogue; the dashed outline
    appears only while a file is dragged over it.

    Args:
        upload_id (str): Id for the ``dcc.Upload``; the file name area gets
            ``<upload_id>-text``.
        button_label (str): Sentence-case button label, e.g. ``Load lightcurve``.
        detail_index (str): ``index`` of the matching detail collapse components.

    Returns:
        dash.html.Div: Slot ready to place in the data bar.
    """
    return html.Div(
        [
            dcc.Upload(
                id=upload_id,
                children=html.Div(
                    [
                        dbc.Button(
                            button_label,
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                        html.Div(
                            _gp_upload_placeholder(),
                            id=f"{upload_id}-text",
                            className="gp-upload-name",
                        ),
                    ],
                    className="gp-upload-target-inner",
                ),
                className="gp-upload-target",
                className_active="gp-upload-target gp-upload-target-active",
                className_reject="gp-upload-target gp-upload-target-reject",
            ),
            dbc.Button(
                html.I(className="bi bi-question-circle"),
                id={"type": "gp-upload-detail-btn", "index": detail_index},
                color="link",
                size="sm",
                className="gp-upload-detail-btn d-none",
            ),
        ],
        className="gp-data-slot",
    )


def _gp_upload_detail_row(detail_index: str) -> dbc.Collapse:
    """Full-width collapse holding the failure explanation for one slot.

    Args:
        detail_index (str): ``index`` shared with the slot's ``?`` button.

    Returns:
        dash_bootstrap_components.Collapse: Closed collapse with an empty body.
    """
    return dbc.Collapse(
        html.Div(
            id={"type": "gp-upload-detail", "index": detail_index},
            className="gp-upload-detail",
        ),
        id={"type": "gp-upload-detail-collapse", "index": detail_index},
        is_open=False,
    )


(
    _add_interval_help_btn,
    _add_interval_help_pop,
) = _gp_click_help(
    "add_interval",
    "Add interval",
    "Unfolded: box-select a time range. Folded: box-select on the extended phase axis "
    "(−0.5 to 1.5); width must not exceed 1 phase. Re-adding the same window is "
    "rejected. See TIPS under the plot for the full workflow.",
)
# Workflow guide under the plot: longer than a per-control ? and opened on demand
(
    _prep_tips_btn,
    _prep_tips_pop,
) = _gp_click_help(
    "prep_tips",
    "Tips: selecting and removing intervals",
    [
        html.P(
            "Unfolded curve: box-select a time range on the plot and press "
            "Add interval.",
            className="mb-2",
        ),
        html.P(
            "If the period is known, add every cycle at once: switch on Fold, "
            "box-select on the extended phase axis (−0.5 to 1.5, box width ≤ 1) and "
            "press Add interval. Matching intervals from all cycles are added "
            "automatically, and you can unfold the curve afterwards.",
            className="mb-2",
        ),
        html.P(
            "To drop intervals, unfold the curve, switch on Mark bands, and click "
            "inside a green vertical strip (anywhere in its time range, not only "
            "the outline). It turns rose; click again to unmark. Then press "
            "Remove marked. Do not use the Plotly pan/zoom tools for this. "
            "Marking is unavailable while the curve is folded.",
            className="mb-2",
        ),
        html.P(
            "Marking is unavailable on a folded curve, because one interval maps to "
            "several phase rectangles. Existing marks are kept and reappear when you "
            "unfold.",
            className="mb-2",
        ),
        html.P(
            "Mark bands and Remove trend both use the pointer on the plot, so only "
            "one of them can be active at a time.",
            className="mb-2",
        ),
        html.P(
            "After trend removal, use Download light curve under Export settings "
            "to save the current stored light curve.",
            className="mb-0",
        ),
    ],
    placement="top",
    label="TIPS",
    trigger_class_name="lc-discovery-help-btn gp-prep-tips-btn",
)
(
    _prep_errorbars_help_btn,
    _prep_errorbars_help_pop,
) = _gp_click_help(
    "prep_errorbars",
    "Show error bars",
    "Draws uncertainty bars on the prep plot. This increases data sent to the browser "
    "and can slow pan/zoom and selection on long light curves.",
)
(
    _remove_trend_help_btn,
    _remove_trend_help_pop,
) = _gp_click_help(
    "remove_trend",
    "Remove trend",
    "Unfolded prep plot only. Switch on and click once: a horizontal dashed line "
    "appears at that level (four-fifths of the visible width) and the Apply and "
    "Clear buttons appear beside this switch. Drag the handles to adjust, then "
    "Apply trend removal, which also switches this off. Uses the current "
    "Magnitudes/Flux view. Reload the light curve to undo.",
)
(
    _guess_sigma_help_btn,
    _guess_sigma_help_pop,
) = _gp_click_help(
    "guess_sigma",
    "Guess sigma",
    "Auto-estimate noise (ignore provided uncertainties)",
)
(
    _noise_scale_help_btn,
    _noise_scale_help_pop,
) = _gp_click_help(
    "noise_scale",
    "Noise scale",
    "Assumed noise scale: empirical correction (↑ smooth, ↓ wiggly). "
    "Allows not quite fair to tweak uncertainties",
)
(
    _kernel_type_help_btn,
    _kernel_type_help_pop,
) = _gp_click_help(
    "kernel_type",
    "Kernel smoothness type",
    "Matern (nu=2.5): twice differentiable, physically realistic"
    "RBF (Radial Basis Function): infinitely differentiable, extremely smooth)",
)
(
    _length_scale_help_btn,
    _length_scale_help_pop,
) = _gp_click_help(
    "length_scale",
    "Length scale (min / init / max)",
    "GP smoothness (in days, as x-axis). Increase if fit is too wiggly, "
    "decrease if it misses structure.",
)
(
    _amplitude_help_btn,
    _amplitude_help_pop,
) = _gp_click_help(
    "signal_amplitude",
    "Signal amplitude (min / init / max)",
    "GP vertical scale (y-axis). Sets the 'headroom' for peak height. "
    "Since flux is normalised to 1.0, values between 0.1 and 10.0 are usually safe. "
    "Best left alone unless the model is failing to reach the top of your peak!",
)
(
    _mavka_method_help_btn,
    _mavka_method_help_pop,
) = _gp_click_help(
    "mavka_method",
    "Approximation method",
    [
        html.P(
            "AP: asymptotic parabola with a tilted core. TOM is the vertex, "
            "kept only if it lies between the junction times C4 and C5.",
            className="mb-2",
        ),
        html.P(
            "WSAP (default): wall-supported asymptotic parabola. TOM is the "
            "midpoint of C4 and C5.",
            className="mb-2",
        ),
        html.P(
            "WSL: wall-supported flat bottom. TOM is the midpoint of the flat part.",
            className="mb-2",
        ),
        html.P(
            "A: broken linear model; two slopes meet at C4.",
            className="mb-2",
        ),
        html.P(
            "Fits ignore photometric uncertainties; σ(TOM) comes from the "
            "parameter covariance. One method is fitted at a time.",
            className="mb-0",
        ),
    ],
)
(
    _mavka_extrema_help_btn,
    _mavka_extrema_help_pop,
) = _gp_click_help(
    "mavka_extrema",
    "Search extrema",
    "Times a trough in the current Magnitudes/Flux view from accordion 1. "
    "Search maxima is listed to match the GP control; it is not implemented "
    "in this version.",
)
(
    _oc_source_help_btn,
    _oc_source_help_pop,
) = _gp_click_help(
    "oc_source",
    "ToM source",
    "Gaussian Process and MAVKA use Keep-marked successes from those "
    "accordions. Upload reads a compact ToM .dat exported from GP or MAVKA "
    "(JD and σ in days, # comments skipped).",
)
(
    _oc_ephemeris_help_btn,
    _oc_ephemeris_help_pop,
) = _gp_click_help(
    "oc_ephemeris",
    "Trial ephemeris",
    "P and Epoch are independent of accordion 1. Take from lightcurve copies "
    "the current folding P and Epoch into these fields and overwrites them.",
)
(
    _oc_shift_help_btn,
    _oc_shift_help_pop,
) = _gp_click_help(
    "oc_cycle_shift",
    "Cycle corrections",
    "For every ToM at or after the given time (display MJD, same scale as "
    "Epoch), add integer ΔE to the rounded cycle. Several rows accumulate. "
    "Use +1 or −1 to fix a cycle slip.",
)


GP_CHECKLIST_SWITCH_ON = 1


def gp_mark_mode_checklist_options(*, disabled: bool = False) -> list[dict]:
    """Builds ``dbc.Checklist`` options for the prep-plot Mark bands switch.

    Args:
        disabled (bool): When ``True``, the switch cannot be turned on (folded LC).

    Returns:
        list[dict]: Single-option checklist payload for ``gp-interval-mark-mode``.
    """
    return [
        {
            "label": "Mark bands",
            "value": GP_CHECKLIST_SWITCH_ON,
            "disabled": disabled,
        }
    ]


def gp_trend_mode_checklist_options(*, disabled: bool = False) -> list[dict]:
    """Builds ``dbc.Checklist`` options for the prep-plot Remove trend switch.

    Args:
        disabled (bool): When ``True``, the switch cannot be turned on (folded LC).

    Returns:
        list[dict]: Single-option checklist payload for ``gp-prep-trend-mode``.
    """
    return [
        {
            "label": "Remove trend",
            "value": GP_CHECKLIST_SWITCH_ON,
            "disabled": disabled,
        }
    ]


def gp_checklist_switch_is_on(value) -> bool:
    """Returns whether a sidebar checklist switch (Fold, Remove trend, etc.) is on.

    Args:
        value: ``dbc.Checklist`` value (list of selected option values).

    Returns:
        bool: ``True`` when switch option ``1`` is selected.
    """
    return isinstance(value, list) and GP_CHECKLIST_SWITCH_ON in value


def gp_parse_oc_coefficient(value) -> float:
    """Parses one quadratic O-C coefficient from a sidebar number input.

    Args:
        value: Raw ``dbc.Input`` value (number or empty).

    Returns:
        float: Parsed coefficient, or ``0.0`` when empty.
    """
    if value is None or value == "":
        return 0.0
    return float(value)


def LegendItem(color, label, mode='line'):
    """Builds one legend row: a colour swatch plus its caption.

    Args:
        color (str): Any CSS colour taken from the corresponding plot trace.
        label (str): Caption shown next to the swatch.
        mode (str): Swatch shape, ``line``, ``dashed`` or ``circle``.

    Returns:
        dash.html.Div: Legend row component.

    Raises:
        ValueError: If ``mode`` is not a supported swatch shape.
    """
    if mode not in ("line", "dashed", "circle"):
        raise ValueError(f"Unsupported legend swatch mode: {mode}")

    # Geometry lives in gp_for_oc.css; only the trace colour is data-driven.
    swatch_style = (
        {"borderTopColor": color} if mode == "dashed" else {"backgroundColor": color}
    )
    return html.Div(
        [
            html.Span(
                className=f"gp-legend-swatch gp-legend-swatch-{mode}",
                style=swatch_style,
            ),
            html.Span(label),
        ],
        className="gp-legend-item",
    )


# ==================== Lightcurve GUI ==================

sidebar_lc = html.Div([
    # 1. PHASE FOLDING CONTROLS
    html.Div(
        [
            html.Label("Phase folding", className="gp-section-label"),
            dbc.Checklist(
                options=[{"label": "Fold", "value": GP_CHECKLIST_SWITCH_ON}],  # type: ignore
                value=[],
                id="folding-switch",
                switch=True,
            ),
            dbc.InputGroup([
                dbc.InputGroupText("P"),
                dbc.Input(id="input-period", type="number", placeholder="Period (days)"),
            ], size="sm"),
            dbc.InputGroup([
                dbc.InputGroupText(f"Epoch-{DEFAULT_EPOCH_JD}"),
                dbc.Input(id="input-epoch", type="number", placeholder="MJD offset"),
            ], size="sm"),
            dbc.RadioItems(
                id="gp-fold-ephemeris-mode",
                options=[
                    {"label": " Constant period", "value": FOLD_EPHEMERIS_CONSTANT},
                    {"label": " Quadratic O-C", "value": FOLD_EPHEMERIS_QUADRATIC_OC},
                ],
                value=FOLD_EPHEMERIS_CONSTANT,
                inputStyle={"marginRight": "6px"},
                labelStyle={"display": "block", "marginBottom": "0.25rem"},
            ),
            html.Div(
                [
                    dbc.InputGroup(
                        [
                            dbc.InputGroupText("a"),
                            dbc.Input(
                                id="input-oc-a",
                                type="number",
                                placeholder="0",
                                value=0,
                            ),
                        ],
                        size="sm",
                    ),
                    dbc.InputGroup(
                        [
                            dbc.InputGroupText("b"),
                            dbc.Input(
                                id="input-oc-b",
                                type="number",
                                placeholder="0",
                                value=0,
                            ),
                        ],
                        size="sm",
                    ),
                    dbc.InputGroup(
                        [
                            dbc.InputGroupText("c"),
                            dbc.Input(
                                id="input-oc-c",
                                type="number",
                                placeholder="0",
                                value=0,
                            ),
                        ],
                        size="sm",
                    ),
                    html.Div(
                        "O-C (days) = aE² + bE + c",
                        className="small text-muted",
                    ),
                ],
                id="gp-quadratic-oc-fields",
                className="gp-sidebar-btn-stack d-none",
            ),
        ],
        className="gp-sidebar-block",
    ),

    html.Hr(),

    # 2. VIEW SETTINGS
    html.Div(
        [
            html.Label("View settings", className="gp-section-label"),
            dbc.RadioItems(
                id="gp_time_axis_switch",
                options=[
                    {"label": " MJD", "value": TIME_AXIS_MJD},
                    {"label": " Date", "value": TIME_AXIS_DATE},
                ],
                value=TIME_AXIS_MJD,
                persistence=True,
                inputStyle={"marginRight": "6px"},
                labelStyle={"marginRight": "12px"},
            ),
            dbc.RadioItems(
                options=[  # type: ignore
                    {"label": "Magnitudes", "value": "mag"},
                    {"label": "Flux", "value": "flux"},
                ],
                value="mag",
                id="view-mode-radio",
            ),
            html.Div(
                [
                    dbc.Switch(
                        id="gp-prep-show-errorbars",
                        label="Show error bars",
                        value=False,
                    ),
                    html.Div(_prep_errorbars_help_btn, className="lc-discovery-field-help"),
                ],
                className="gp-sidebar-switch-row",
            ),
            html.Label("Working range", className="gp-export-sublabel"),
            html.Div(
                id="gp-prep-working-window-status",
                className="small text-muted",
            ),
            html.Div(
                [
                    dbc.Button(
                        "Use visible range",
                        id="btn-use-visible-range",
                        color="primary",
                        size="sm",
                    ),
                    dbc.Button(
                        "Restore full light curve",
                        id="btn-restore-full-lc",
                        color="secondary",
                        outline=True,
                        size="sm",
                        disabled=True,
                    ),
                ],
                className="gp-sidebar-btn-stack",
            ),
            html.Div(id="gp-prep-working-window-feedback", className="gp-export-feedback"),
        ],
        className="gp-sidebar-block",
    ),
    _prep_errorbars_help_pop,

    html.Hr(),

    # 3. --- EXPORT ---
    html.Div(
        [
            html.Label("Export settings", className="gp-section-label"),
            html.Div(
                [
                    html.Label("Intervals", className="gp-export-sublabel"),
                    dbc.InputGroup(
                        [
                            dbc.Input(
                                id="export-intervals-filename",
                                placeholder="intervals_export",
                                type="text",
                                value="",
                            ),
                            dbc.Button(
                                "Download",
                                id="btn-download-intervals",
                                color="primary",
                            ),
                        ],
                        size="sm",
                    ),
                ],
                className="gp-export-block",
            ),
            html.Div(
                [
                    html.Label("Light curve", className="gp-export-sublabel"),
                    dbc.Select(
                        options=EXPORT_FORMAT_OPTIONS,  # type: ignore[arg-type]
                        value=DEFAULT_EXPORT_FORMAT,
                        id="gp-lc-export-format",
                        size="sm",
                    ),
                    dbc.InputGroup(
                        [
                            dbc.Input(
                                id="export-lc-filename",
                                placeholder="lightcurve_export",
                                type="text",
                                value="gp_lightcurve",
                            ),
                            dbc.Button(
                                "Download",
                                id="btn-download-lc",
                                color="primary",
                                disabled=True,
                            ),
                        ],
                        size="sm",
                        className="gp-lc-export-actions",
                    ),
                    html.Div(id="gp-lc-export-feedback", className="gp-export-feedback"),
                ],
                className="gp-export-block",
            ),
            dcc.Download(id="download-intervals-file"),
            dcc.Download(id="download-lc-file"),
        ],
        className="gp-sidebar-block gp-export-stack",
    ),
], className="gp-sidebar bg-light border rounded shadow-sm")

# Actions that operate on the plot itself live above it, not in the sidebar: the
# marking and trend gestures happen on the graph, and the two modes compete for the
# same click, which is only obvious when their switches sit side by side.
prep_plot_toolbar = html.Div(
    [
        html.Div(
            [
                dbc.Button(
                    "Add interval",
                    id="btn-add-interval",
                    color="primary",
                    size="sm",
                ),
                html.Div(_add_interval_help_btn, className="lc-discovery-field-help"),
            ],
            className="gp-plot-toolbar-cluster",
        ),
        html.Div(
            [
                dbc.Checklist(
                    options=gp_mark_mode_checklist_options(disabled=False),  # type: ignore
                    value=[],
                    id="gp-interval-mark-mode",
                    switch=True,
                ),
                dbc.Button(
                    "Remove marked",
                    id="btn-remove-marked-intervals",
                    color="primary",
                    size="sm",
                    disabled=True,
                ),
                dbc.Button(
                    "Clear marks",
                    id="btn-clear-interval-marks",
                    color="secondary",
                    outline=True,
                    size="sm",
                    disabled=True,
                ),
            ],
            className="gp-plot-toolbar-cluster",
        ),
        html.Div(
            [
                dbc.Checklist(
                    options=gp_trend_mode_checklist_options(disabled=False),  # type: ignore
                    value=[],
                    id="gp-prep-trend-mode",
                    switch=True,
                ),
                html.Div(_remove_trend_help_btn, className="lc-discovery-field-help"),
                html.Div(
                    [
                        dbc.Button(
                            "Apply",
                            id="btn-apply-prep-trend",
                            color="primary",
                            size="sm",
                        ),
                        dbc.Button(
                            "Clear trend line",
                            id="btn-clear-prep-trend",
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                    ],
                    id="gp-trend-actions",
                    className="gp-plot-toolbar-actions d-none",
                ),
            ],
            className="gp-plot-toolbar-cluster",
        ),
        html.Div(
            [
                html.Div(id="gp-interval-add-feedback"),
                html.Div(id="gp-trend-feedback"),
            ],
            className="gp-plot-toolbar-feedback",
        ),
        _add_interval_help_pop,
        _remove_trend_help_pop,
    ],
    className="gp-plot-toolbar",
)

graph_lc = html.Div([
    prep_plot_toolbar,
    html.Div(
        dcc.Graph(
            id='prep-graph',
            config={  # type: ignore
                'scrollZoom': True,
                'displaylogo': False,
                'doubleClick': False,
                # Interval bands stay non-editable; trend line editing is toggled in JS
                'edits': {'shapePosition': False},
                # No shape-drawing tools: intervals come from box-select and the
                # trend line is placed by clicking, so drawn shapes would only be junk.
                'modeBarButtonsToRemove': ['zoomIn2d', 'zoomOut2d', 'lasso2d'],
            },
            className="gp-prep-graph",
        ),
        id="prep-graph-shell",
    ),
    html.Div([_prep_tips_btn, _prep_tips_pop], className="mt-2"),
], className="border rounded p-2 bg-white")

# List maintenance belongs to the list: these two act on the registry, not the plot.
intervals_registry = html.Div([
    html.Div(
        [
            html.H6("Selected intervals", className="gp-card-title"),
            html.Div(
                [
                    dbc.Button(
                        "Clear empty",
                        id="btn-remove-empty-intervals",
                        color="link",
                        size="sm",
                        disabled=True,
                        className="gp-registry-action gp-registry-action-caution",
                    ),
                    dbc.Button(
                        "Clear all",
                        id="btn-clear-intervals",
                        color="link",
                        size="sm",
                        disabled=True,
                        className="gp-registry-action text-danger",
                    ),
                ],
                className="gp-registry-header-actions",
            ),
        ],
        className="gp-registry-header",
    ),
    html.Div(id='registry-list-container', children=[
        # We'll use a Dash Table or a List of Cards here
        html.P("No intervals selected.", className="text-muted small")
    ])
], className="gp-registry-panel border rounded bg-light")

registry_toggle_btn = dbc.Button(
    # region unfold
    html.I(className="bi bi-chevron-right", id="registry-toggle-icon"),
    id="btn-toggle-registry",
    color="light",
    size="sm",
    className="gp-registry-toggle border shadow-sm p-1",
    # endregion
)
# ===================  GP GUI ===========================


sidebar_gp = html.Div([
    # 1. COLLAPSIBLE LEGEND
    dbc.Button(
        "Show legend",
        id="toggle-legend-btn",
        color="link",
        size="sm",
        className="p-0 text-decoration-none",
    ),
    dbc.Collapse(
        html.Div([
            LegendItem("black", "Data points", mode='circle'),
            LegendItem("rgb(31, 119, 180)", "GP mean", mode='line'),
            LegendItem("rgba(31, 119, 180, 0.25)", "GP ±1σ confidence", mode='line'),
            LegendItem("magenta", "Peak estimate", mode='dashed'),
            LegendItem("orange", "Posterior draws", mode='circle'),
            LegendItem("green", "Guess", mode='dashed'),
        ], className="p-2 border rounded bg-white"),
        id="legend-collapse",
        is_open=False,
        className="gp-sidebar-group",
    ),

    # 2. PRIMARY ACTION BUTTONS
    dbc.Row([
        dbc.Col(
            dbc.Button("Run GP", id="run-btn", color="primary", className="w-100", size="sm"),
            width=7,
        ),
        dbc.Col(
            dbc.Button("Stop", id="stop-btn", color="danger", outline=True, className="w-100", size="sm"),
            width=5,
        ),
    ], className="g-2 gp-sidebar-group"),

    # 3. GLOBAL MODEL SETTINGS
    dbc.Row([
        dbc.Col([
            dbc.Select(
                id="extrema-mode",
                options=[  # type: ignore
                    {"label": "Search minima", "value": "min"},
                    {"label": "Search maxima", "value": "max"},
                ],
                value=EXTREMA_MODE,
                size="sm",
            )
        ], width=12),

    ], className="g-2 gp-sidebar-group"),

    # Two noise settings share one row; labels sit above so the columns line up
    dbc.Row(
        [
            dbc.Col(
                [
                    html.Div(
                        [
                            html.Label("Guess sigma", className="gp-section-label mb-0"),
                            html.Div(
                                _guess_sigma_help_btn,
                                className="lc-discovery-field-help",
                            ),
                        ],
                        className="gp-sidebar-heading-row",
                    ),
                    html.Div(
                        dbc.Switch(id="guess-sigma", value=GUESS_SIGMA),
                        className="gp-field-switch",
                    ),
                ],
                width=6,
            ),
            dbc.Col(
                [
                    html.Div(
                        [
                            html.Label("Noise scale", className="gp-section-label mb-0"),
                            html.Div(
                                _noise_scale_help_btn,
                                className="lc-discovery-field-help",
                            ),
                        ],
                        className="gp-sidebar-heading-row",
                    ),
                    dbc.Input(
                        id={"type": "float-input", "index": "noise_scale"},
                        type="number", size="sm", step="any",
                        value=params_float["noise_scale"],
                    ),
                ],
                width=6,
            ),
        ],
        className="g-2 gp-sidebar-group",
    ),

    html.Hr(),

    # 4. KERNEL PARAMETERS (Compact Triples)
    # Kernel Selection
    html.Div(
        [
            html.Label(
                "Kernel smoothness type", className="gp-section-label mb-0"
            ),
            html.Div(_kernel_type_help_btn, className="lc-discovery-field-help"),
        ],
        className="gp-sidebar-heading-row",
    ),
    dbc.RadioItems(
        id='kernel-type',
        options=[  # type: ignore
            {"label": "Matern 2.5", "value": "matern"},
            {"label": "RBF", "value": "rbf"},
        ],
        value=KERNEL_TYPE,
        inline=True,
        className="gp-sidebar-group",
    ),

    # html.Label("White Kernel (Min / Val /  Max)", className="small fw-bold", id='wk-label'),
    # dbc.Tooltip("Extra noise allowance", target='wk-label'),
    # dbc.Row([
    #     dbc.Col(dbc.Input(
    #         id={'type': 'float-input', 'index': "white_noise_level_min"},
    #         size="sm",
    #         type="number", step=0.001,
    #         value=params_float["white_noise_level_min"]), width=4),
    #     dbc.Col(dbc.Input(
    #         id={'type': 'float-input', 'index': "white_noise_level_init"},
    #         size="sm",
    #         type="number", step=0.001,
    #         value=params_float["white_noise_level_init"]), width=4),
    #     dbc.Col(dbc.Input(
    #         id={'type': 'float-input', 'index': "white_noise_level_max"},
    #         size="sm",
    #         type="number", step=0.001,
    #         value=params_float["white_noise_level_max"]), width=4),
    # ]),

    # Length Scale Inputs
    html.Div(
        [
            html.Label(
                "Length scale (min / init / max)", className="gp-section-label mb-0"
            ),
            html.Div(_length_scale_help_btn, className="lc-discovery-field-help"),
        ],
        className="gp-sidebar-heading-row",
    ),
    dbc.Row([
        dbc.Col(dbc.Input(
            id={'type': 'float-input', 'index': "length_scale_min"},
            size="sm",
            type="number", step="any",
            className="gp-limit-min",
            value=params_float["length_scale_min"]), width=4),
        dbc.Col(dbc.Input(
            size="sm",
            id={'type': 'float-input', 'index': "length_scale_init"},
            type="number",
            # step=0.001,
            step="any",
            value=params_float["length_scale_init"]), width=4),
        dbc.Col(dbc.Input(
            size="sm",
            id={'type': 'float-input', 'index': "length_scale_max"},
            type="number", step="any",
            className="gp-limit-max",
            value=params_float["length_scale_max"]), width=4),
    ], className="g-1 gp-sidebar-group"),

    html.Div(
        [
            html.Label(
                "Signal amplitude (min / init / max)",
                className="gp-section-label mb-0",
            ),
            html.Div(_amplitude_help_btn, className="lc-discovery-field-help"),
        ],
        className="gp-sidebar-heading-row",
    ),

    dbc.Row([
        dbc.Col(dbc.Input(
            id={'type': 'float-input', 'index': "amplitude_min"},
            size="sm",
            type="number", step="any",
            className="gp-limit-min",
            value=params_float["amplitude_min"]), width=4),
        dbc.Col(dbc.Input(
            size="sm",
            id={'type': 'float-input', 'index': "amplitude_init"},
            type="number",
            # step=0.001,
            step="any",
            value=params_float["amplitude_init"]), width=4),
        dbc.Col(dbc.Input(
            size="sm",
            id={'type': 'float-input', 'index': "amplitude_max"},
            type="number", step="any",
            className="gp-limit-max",
            value=params_float["amplitude_max"]), width=4),
    ], className="g-1 gp-sidebar-group"),

    dbc.Button(
        "Guess parameters",
        id="reset-btn",
        color="primary",
        size="sm",
        className="w-100",
    ),

    _guess_sigma_help_pop,
    _noise_scale_help_pop,
    _kernel_type_help_pop,
    _length_scale_help_pop,
    _amplitude_help_pop,

], className="gp-sidebar bg-light border rounded shadow-sm")


def _live_processing_layout():
    """Fixed-slot grid for GP Processing View (see ``GP_LIVE_PAGE_SIZE``)."""
    return dbc.Row(
        [
            dbc.Col(
                html.Div(
                    id={"type": "gp-live-slot", "index": slot_idx},
                    children=live_slot_waiting(),
                ),
                width=6,
                className="px-1 mb-2",
            )
            for slot_idx in range(GP_LIVE_PAGE_SIZE)
        ],
        id="live-graphs-container",
        className="g-2",
    )


# =====================  LAYOUT ==================================================
graph_gp = html.Div([
    html.Div(id='finished-signal', style={'display': 'none'}),
    # signal for gp status, Allowed: "WAITING" and "FINISHED"

    # 1. DYNAMIC HEADER: title row + live progress (progress does not sit in the grid)
    html.Div(id='gp-header-area', children=[
        html.Div([
            html.H6("GP processing view", className="gp-card-title"),
            dbc.Badge("Waiting for run", color="secondary", id='gp-view-badge', className="ms-2")
        ], className="d-flex align-items-center"),
    ], className="mb-1"),
    html.Div(id="gp-live-progress-label", className="small text-muted mb-3"),

    # 1. LIVE VIEW: fixed grid, updated per finished extremum
    _live_processing_layout(),

    # 3. FINAL REVIEW
    html.Div(id='final-review-container', style={'display': 'none'}, children=[
        html.Hr(className="my-4"),
        dbc.Card([
            dbc.CardBody(
                html.Div(
                    [
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.H6(
                                        "Review and export",
                                        className="gp-card-title",
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        "Select all",
                                        id="select-all-btn",
                                        size="sm",
                                        color="secondary",
                                        outline=True,
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        "Unselect all",
                                        id="unselect-all-btn",
                                        size="sm",
                                        color="secondary",
                                        outline=True,
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    [
                                        dbc.Button(
                                            "Previous page",
                                            id="gp-review-prev",
                                            size="sm",
                                            outline=True,
                                            color="secondary",
                                        ),
                                        html.Span(
                                            id="gp-review-page-label",
                                            className="gp-review-page-caption",
                                        ),
                                        dbc.Button(
                                            "Next page",
                                            id="gp-review-next",
                                            size="sm",
                                            outline=True,
                                            color="secondary",
                                        ),
                                    ],
                                    width="auto",
                                    className="gp-review-pager",
                                ),
                            ],
                            className="align-items-center g-2",
                        ),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Switch(
                                        id="gp-extended-export",
                                        value=False,
                                        label="Extended export",
                                    ),
                                    width="auto",
                                ),
                                dbc.Col(
                                    dbc.InputGroup(
                                        [
                                            dbc.Input(
                                                id="export-filename",
                                                placeholder="results_extrema",
                                                type="text",
                                                size="sm",
                                            ),
                                            dbc.Button(
                                                "Download",
                                                id="save-file-btn",
                                                color="primary",
                                                size="sm",
                                            ),
                                        ],
                                        className="gp-export-group",
                                    ),
                                    width="auto",
                                ),
                            ],
                            className="align-items-center g-2 justify-content-end",
                        ),
                    ],
                    className="gp-review-toolbar",
                ),
                className="gp-review-toolbar-body",
            )
        ], className="bg-light mb-3"),

        dbc.Row(id='graphs-container', className="g-2"),
    ]),

    dcc.Download(id="download-results"),
    dcc.Store(id='store-results-data')
], className="p-2")


sidebar_mavka = html.Div(
    [
        dbc.Button(
            "Show legend",
            id="toggle-mavka-legend-btn",
            color="link",
            size="sm",
            className="p-0 text-decoration-none",
        ),
        dbc.Collapse(
            html.Div(
                [
                    LegendItem("black", "Data points", mode="circle"),
                    LegendItem(MAVKA_PIECE_COLOURS["left"], "Left wing", mode="line"),
                    LegendItem(MAVKA_PIECE_COLOURS["core"], "Core", mode="line"),
                    LegendItem(MAVKA_PIECE_COLOURS["right"], "Right wing", mode="line"),
                    LegendItem("magenta", "TOM estimate", mode="dashed"),
                    LegendItem("maroon", "C4 / C5 junctions", mode="dashed"),
                ],
                className="p-2 border rounded bg-white",
            ),
            id="mavka-legend-collapse",
            is_open=False,
            className="gp-sidebar-group",
        ),
        dbc.Row(
            [
                dbc.Col(
                    dbc.Button(
                        "Run MAVKA",
                        id="mavka-run-btn",
                        color="primary",
                        className="w-100",
                        size="sm",
                    ),
                    width=7,
                ),
                dbc.Col(
                    dbc.Button(
                        "Stop",
                        id="mavka-stop-btn",
                        color="danger",
                        outline=True,
                        className="w-100",
                        size="sm",
                    ),
                    width=5,
                ),
            ],
            className="g-2 gp-sidebar-group",
        ),
        html.Div(
            [
                html.Label("Search extrema", className="gp-section-label mb-0"),
                html.Div(
                    _mavka_extrema_help_btn, className="lc-discovery-field-help"
                ),
            ],
            className="gp-sidebar-heading-row",
        ),
        dbc.Select(
            id="mavka-extrema-mode",
            options=[  # type: ignore
                {"label": "Search minima", "value": "min"},
                {"label": "Search maxima", "value": "max"},
            ],
            value=DEFAULT_EXTREMA_MODE,
            size="sm",
            className="gp-sidebar-group",
        ),
        html.Div(
            [
                html.Label("Approximation method", className="gp-section-label mb-0"),
                html.Div(
                    _mavka_method_help_btn, className="lc-discovery-field-help"
                ),
            ],
            className="gp-sidebar-heading-row",
        ),
        dbc.Select(
            id="mavka-method",
            options=list(METHOD_OPTIONS),  # type: ignore
            value=DEFAULT_METHOD,
            size="sm",
            className="gp-sidebar-group",
        ),
        _mavka_method_help_pop,
        _mavka_extrema_help_pop,
    ],
    className="gp-sidebar bg-light border rounded shadow-sm",
)


def _mavka_live_processing_layout():
    """Fixed-slot grid for MAVKA processing view."""
    return dbc.Row(
        [
            dbc.Col(
                html.Div(
                    id={"type": "mavka-live-slot", "index": slot_idx},
                    children=mavka_live_slot_waiting(),
                ),
                width=6,
                className="px-1 mb-2",
            )
            for slot_idx in range(MAVKA_LIVE_PAGE_SIZE)
        ],
        id="mavka-live-graphs-container",
        className="g-2",
    )


graph_mavka = html.Div(
    [
        html.Div(id="mavka-finished-signal", style={"display": "none"}),
        html.Div(
            id="mavka-header-area",
            children=[
                html.Div(
                    [
                        html.H6("MAVKA processing view", className="gp-card-title"),
                        dbc.Badge(
                            "Waiting for run",
                            color="secondary",
                            id="mavka-view-badge",
                            className="ms-2",
                        ),
                    ],
                    className="d-flex align-items-center",
                ),
            ],
            className="mb-1",
        ),
        html.Div(id="mavka-live-progress-label", className="small text-muted mb-3"),
        _mavka_live_processing_layout(),
        html.Div(
            id="mavka-final-review-container",
            style={"display": "none"},
            children=[
                html.Hr(className="my-4"),
                dbc.Card(
                    [
                        dbc.CardBody(
                            html.Div(
                                [
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.H6(
                                                    "Review and export",
                                                    className="gp-card-title",
                                                ),
                                                width="auto",
                                            ),
                                            dbc.Col(
                                                dbc.Button(
                                                    "Select all",
                                                    id="mavka-select-all-btn",
                                                    size="sm",
                                                    color="secondary",
                                                    outline=True,
                                                ),
                                                width="auto",
                                            ),
                                            dbc.Col(
                                                dbc.Button(
                                                    "Unselect all",
                                                    id="mavka-unselect-all-btn",
                                                    size="sm",
                                                    color="secondary",
                                                    outline=True,
                                                ),
                                                width="auto",
                                            ),
                                            dbc.Col(
                                                [
                                                    dbc.Button(
                                                        "Previous page",
                                                        id="mavka-review-prev",
                                                        size="sm",
                                                        outline=True,
                                                        color="secondary",
                                                    ),
                                                    html.Span(
                                                        id="mavka-review-page-label",
                                                        className="gp-review-page-caption",
                                                    ),
                                                    dbc.Button(
                                                        "Next page",
                                                        id="mavka-review-next",
                                                        size="sm",
                                                        outline=True,
                                                        color="secondary",
                                                    ),
                                                ],
                                                width="auto",
                                                className="gp-review-pager",
                                            ),
                                        ],
                                        className="align-items-center g-2",
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                dbc.Switch(
                                                    id="mavka-extended-export",
                                                    value=False,
                                                    label="Extended export",
                                                ),
                                                width="auto",
                                            ),
                                            dbc.Col(
                                                dbc.InputGroup(
                                                    [
                                                        dbc.Input(
                                                            id="mavka-export-filename",
                                                            placeholder="results_mavka",
                                                            type="text",
                                                            size="sm",
                                                        ),
                                                        dbc.Button(
                                                            "Download",
                                                            id="mavka-save-file-btn",
                                                            color="primary",
                                                            size="sm",
                                                        ),
                                                    ],
                                                    className="gp-export-group",
                                                ),
                                                width="auto",
                                            ),
                                        ],
                                        className="align-items-center g-2 justify-content-end",
                                    ),
                                ],
                                className="gp-review-toolbar",
                            ),
                            className="gp-review-toolbar-body",
                        )
                    ],
                    className="bg-light mb-3",
                ),
                dbc.Row(id="mavka-graphs-container", className="g-2"),
            ],
        ),
        dcc.Download(id="mavka-download-results"),
        dcc.Store(id="store-mavka-results-data"),
    ],
    className="p-2",
)


def _oc_empty_figure() -> go.Figure:
    """Returns a blank O-C axes figure before the first Plot."""
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        xaxis_title="Cycle number E",
        yaxis_title="O-C (days)",
        xaxis2=dict(
            overlaying="x",
            side="top",
            title="Calculated JD (T0 + E × P0)",
        ),
        margin=dict(l=50, r=20, t=60, b=50),
        showlegend=False,
    )
    return fig


def _build_oc_figure(payload: dict) -> go.Figure:
    """Builds the O-C Plotly figure from a ``compute_step1_oc`` payload.

    Args:
        payload (dict): Arrays and ephemeris metadata from the utils layer.

    Returns:
        plotly.graph_objects.Figure: O-C vs E with calculated-JD top axis.
    """
    cycle_e = np.asarray(payload["E"], dtype=float)
    oc_days = np.asarray(payload["OC"], dtype=float)
    jd_obs = np.asarray(payload["jd_ext"], dtype=float)
    jd_calc = np.asarray(payload["jd_calc"], dtype=float)
    sigma_jd = np.asarray(payload["sigma_jd"], dtype=float)
    custom = np.column_stack(
        [
            oc_days * 86400.0,
            jd_obs,
            jd_calc,
            sigma_jd,
            sigma_jd * 86400.0,
        ]
    )
    hover = (
        "E: %{x:.0f}<br>"
        "O-C: %{y:.6f} d (%{customdata[0]:.1f} s)<br>"
        "jd_obs: %{customdata[1]:.6f}<br>"
        "jd_calc: %{customdata[2]:.6f}<br>"
        "σ: %{customdata[3]:.8f} d (%{customdata[4]:.1f} s)"
        "<extra></extra>"
    )
    fig = go.Figure()
    finite = np.isfinite(sigma_jd)
    if np.any(finite):
        fig.add_trace(
            go.Scatter(
                x=cycle_e[finite],
                y=oc_days[finite],
                mode="markers",
                marker=dict(size=8),
                error_y=dict(
                    type="data",
                    array=sigma_jd[finite],
                    visible=True,
                    thickness=1,
                    width=3,
                    color="grey",
                ),
                customdata=custom[finite],
                hovertemplate=hover,
                name="O-C",
            )
        )
    if np.any(~finite):
        fig.add_trace(
            go.Scatter(
                x=cycle_e[~finite],
                y=oc_days[~finite],
                mode="markers",
                marker=dict(size=8, color="#fd7e14"),
                customdata=custom[~finite],
                hovertemplate=hover,
                name="O-C (no σ)",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=cycle_e,
            y=oc_days,
            xaxis="x2",
            visible=False,
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_hline(y=0.0, line_dash="dash", line_color="grey", line_width=1)
    e_min = float(np.min(cycle_e))
    e_max = float(np.max(cycle_e))
    tick_e = (
        np.array([e_min])
        if e_min == e_max
        else np.linspace(e_min, e_max, 6)
    )
    t0_jd = float(payload["t0_jd"])
    p0 = float(payload["p0"])
    tick_jd = t0_jd + tick_e * p0
    source_label = {"gp": "GP", "mavka": "MAVKA", "upload": "Upload"}.get(
        str(payload.get("source")), str(payload.get("source"))
    )
    fig.update_layout(
        title=dict(
            text=(
                f"O-C [{source_label}] "
                f"(T0={t0_jd:.5f} JD, P0={p0:.8f} d)"
            ),
            font=dict(size=14),
        ),
        xaxis=dict(title="Cycle number E"),
        xaxis2=dict(
            overlaying="x",
            side="top",
            title="Calculated JD (T0 + E × P0)",
            tickmode="array",
            tickvals=tick_e.tolist(),
            ticktext=[f"{value:.2f}" for value in tick_jd],
        ),
        yaxis_title="O-C (days)",
        template="plotly_white",
        showlegend=False,
        margin=dict(l=50, r=20, t=70, b=50),
        annotations=[
            dict(
                text=(
                    f"N={payload['n']}  RMS={payload['rms_d']:.5f} d "
                    f"({payload['rms_s']:.1f} s)"
                ),
                xref="paper",
                yref="paper",
                x=0.98,
                y=0.02,
                showarrow=False,
                xanchor="right",
                yanchor="bottom",
            )
        ],
    )
    return fig


def _render_oc_shift_list(rows: list | None) -> list:
    """Builds sidebar rows for stored cycle corrections.

    Args:
        rows (list | None): ``{at_mjd, delta_e}`` dicts.

    Returns:
        list: Dash children for ``oc-cycle-shift-list``.
    """
    if not rows:
        return [html.P("No cycle corrections.", className="text-muted small mb-0")]
    items = []
    for index, row in enumerate(rows):
        delta = int(row["delta_e"])
        sign = f"+{delta}" if delta >= 0 else str(delta)
        items.append(
            html.Div(
                [
                    html.Span(f"at ≥ {float(row['at_mjd']):.2f}, ΔE = {sign}"),
                    dbc.Button(
                        "Remove",
                        id={"type": "oc-shift-remove", "index": index},
                        color="link",
                        size="sm",
                    ),
                ],
                className="gp-sidebar-heading-row",
            )
        )
    return items


sidebar_oc = html.Div(
    [
        html.Div(
            [
                html.Label("ToM source", className="gp-section-label mb-0"),
                html.Div(_oc_source_help_btn, className="lc-discovery-field-help"),
            ],
            className="gp-sidebar-heading-row",
        ),
        dbc.RadioItems(
            id="oc-tom-source",
            options=[
                {"label": "Gaussian Process", "value": "gp"},
                {"label": "MAVKA", "value": "mavka"},
                {"label": "Upload", "value": "upload"},
            ],
            value="gp",
            className="gp-sidebar-group",
        ),
        html.Div(
            [
                _gp_upload_slot("upload-oc-toms", "Load timings", "oc-toms"),
                _gp_upload_detail_row("oc-toms"),
            ],
            className="gp-sidebar-group",
        ),
        html.Div(
            [
                html.Label("Trial ephemeris", className="gp-section-label mb-0"),
                html.Div(_oc_ephemeris_help_btn, className="lc-discovery-field-help"),
            ],
            className="gp-sidebar-heading-row",
        ),
        dbc.InputGroup(
            [
                dbc.InputGroupText("P"),
                dbc.Input(
                    id="oc-input-period",
                    type="number",
                    placeholder="Period (days)",
                ),
            ],
            size="sm",
            className="gp-sidebar-group",
        ),
        dbc.InputGroup(
            [
                dbc.InputGroupText(f"Epoch-{DEFAULT_EPOCH_JD}"),
                dbc.Input(
                    id="oc-input-epoch",
                    type="number",
                    placeholder="MJD offset",
                ),
            ],
            size="sm",
            className="gp-sidebar-group",
        ),
        dbc.Button(
            "Take from lightcurve",
            id="oc-take-from-lc-btn",
            color="secondary",
            outline=True,
            size="sm",
            className="gp-sidebar-group",
        ),
        html.Div(
            [
                html.Label("Cycle corrections", className="gp-section-label mb-0"),
                html.Div(_oc_shift_help_btn, className="lc-discovery-field-help"),
            ],
            className="gp-sidebar-heading-row",
        ),
        dbc.InputGroup(
            [
                dbc.InputGroupText("At ≥"),
                dbc.Input(
                    id="oc-shift-at-time",
                    type="number",
                    placeholder="MJD",
                ),
            ],
            size="sm",
            className="gp-sidebar-group",
        ),
        dbc.InputGroup(
            [
                dbc.InputGroupText("ΔE"),
                dbc.Input(
                    id="oc-shift-delta-e",
                    type="number",
                    step=1,
                    placeholder="±1",
                ),
            ],
            size="sm",
            className="gp-sidebar-group",
        ),
        dbc.Button(
            "Add",
            id="oc-shift-add-btn",
            color="primary",
            size="sm",
            className="gp-sidebar-group",
        ),
        html.Div(id="oc-cycle-shift-list", className="gp-sidebar-group"),
        html.Div(id="oc-sidebar-feedback", className="gp-export-feedback"),
        dbc.Button(
            "Plot",
            id="oc-plot-btn",
            color="primary",
            size="sm",
            className="w-100 gp-sidebar-group",
        ),
        html.Div(
            [
                html.Label("Export", className="gp-section-label"),
                dbc.InputGroup(
                    [
                        dbc.Input(
                            id="oc-export-filename",
                            placeholder="results_oc",
                            type="text",
                            value="results_oc",
                        ),
                        dbc.Button(
                            "Download",
                            id="oc-download-btn",
                            color="primary",
                            size="sm",
                        ),
                    ],
                    size="sm",
                    className="gp-export-group",
                ),
            ],
            className="gp-sidebar-block gp-export-stack",
        ),
        _oc_source_help_pop,
        _oc_ephemeris_help_pop,
        _oc_shift_help_pop,
        dcc.Download(id="oc-download-results"),
        dcc.Store(id="store-oc-uploaded-toms"),
        dcc.Store(id="store-oc-cycle-shifts", data=[]),
        dcc.Store(id="store-oc-plot-data"),
    ],
    className="gp-sidebar bg-light border rounded shadow-sm",
)


graph_oc = html.Div(
    [
        html.Div(
            [
                html.H6("O-C view", className="gp-card-title"),
            ],
            className="mb-1",
        ),
        html.Div(id="oc-plot-feedback", className="gp-export-feedback"),
        dcc.Graph(
            id="oc-graph",
            figure=_oc_empty_figure(),
            className="gp-prep-graph",
            config={"displaylogo": False},
        ),
    ],
    className="p-2",
)


def layout():
    return dbc.Container([
        # --- HEADER SECTION ---
        dbc.Row(
            [
                dbc.Col(
                    html.H1(
                        "Lightcurve Extrema Modeller",
                        className="gp-page-title",
                    ),
                    width="auto",
                ),
                dbc.Col(
                    dbc.Button(
                        [
                            html.I(className="bi bi-question-circle me-2"),
                            "About",
                        ],
                        id="open-help",
                        color="secondary",
                        outline=True,
                        className="gp-page-about-btn",
                    ),
                    width="auto",
                    className="ms-auto d-flex align-items-center",
                ),
            ],
            className="gp-page-header align-items-center",
        ),

        # --- PAGE ABOUT + ACCORDION HELP ---
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("About")),
            dbc.ModalBody(dcc.Markdown(PAGE_ABOUT_MARKDOWN)),
            dbc.ModalFooter(
                dbc.Button(
                    "Close", id="close-help",
                    color="secondary", size="sm", className="ms-auto", n_clicks=0,
                )
            ),
        ], id="help-modal", size="lg", is_open=False),
        *[ _accordion_help_modal(spec) for spec in _ACCORDION_HELP_SPECS ],
        _accordion_help_proxies(),

        dcc.Store(id='store-lc-data'),
        dcc.Store(id='store-gp-prep-working-window', data=WORKING_WINDOW_DISABLED),
        dcc.Store(id='store-intervals-data'),
        dcc.Store(id='store-gp-interval-pick-bands'),
        dcc.Store(id='store-gp-intervals-marked', data=[]),
        dcc.Store(id='store-gp-prep-mark-selection'),
        # Short token bumped on every prep replot. Clientside binders listen to
        # this instead of 'prep-graph.figure' so they are not handed the whole
        # figure (about 0.9 MB folded) on every redraw.
        dcc.Store(id='store-gp-prep-render-token', data=''),
        dcc.Store(id='store-gp-trend-click'),
        dcc.Store(id='store-gp-trend-line'),
        dcc.Store(id='store-active-intervals-name'),
        dcc.Store(id='scale-calc-trigger', data=0),  # Incremented by Guess parameters only

        # --- 2. GLOBAL DATA HUB

        html.Div(
            [
                html.Div(
                    [
                        _gp_upload_slot('upload-lc', "Load lightcurve", "lc"),
                        _gp_upload_slot('upload-intervals', "Load intervals", "intervals"),
                    ],
                    className="gp-data-bar",
                ),
                _gp_upload_detail_row("lc"),
                _gp_upload_detail_row("intervals"),
            ],
            className="gp-data-hub",
        ),

        # --- 3. THE WORKFLOW ACCORDION ---

        dbc.Accordion(
            [
                dbc.AccordionItem(
                    item_id=ACCORDION_LC_ITEM_ID,
                    title=_accordion_title_with_help(
                        _ACCORDION_HELP_BY_INDEX["lc"]
                    ),
                    children=[
                        dbc.Row([
                            # Sidebar (Column 1 - Fixed)
                            dbc.Col(sidebar_lc, width=3),

                            # Working Area (Column 2 & 3 combined into a Flex container)
                            dbc.Col([
                                html.Div([
                                    # Graph Area (Grows automatically)
                                    html.Div(
                                        [graph_lc, registry_toggle_btn],
                                        className="gp-prep-workspace-plot",
                                    ),

                                    # Registry Area (Collapses horizontally)
                                    dbc.Collapse(
                                        intervals_registry,
                                        id="registry-collapse",
                                        is_open=True,
                                        dimension="width",
                                        className="gp-registry-collapse",
                                    )
                                ], className="gp-prep-workspace")
                            ], width=9)
                            # dbc.Col(graph_lc, width=6),
                            # dbc.Col(intervals_registry, width=3),  # COLUMN 3: THE REGISTRY TABLE (intervals)
                        ]),
                    ]),

                # --- STEP 2: ANALYSIS (The "Monster") ---
                dbc.AccordionItem(
                    item_id="accordion-gp",
                    title=_accordion_title_with_help(
                        _ACCORDION_HELP_BY_INDEX["gp"]
                    ),
                    children=[
                        dbc.Row([
                            dbc.Col(sidebar_gp, width=3),
                            dbc.Col(graph_gp, width=9),
                        ]),
                        html.Div(id="main-analysis-wrapper")
                    ],
                ),
                dbc.AccordionItem(
                    item_id="accordion-mavka",
                    title=_accordion_title_with_help(
                        _ACCORDION_HELP_BY_INDEX["mavka"]
                    ),
                    children=[
                        dbc.Row([
                            dbc.Col(sidebar_mavka, width=3),
                            dbc.Col(graph_mavka, width=9),
                        ]),
                    ],
                ),
                dbc.AccordionItem(
                    item_id="accordion-oc",
                    title=_accordion_title_with_help(
                        _ACCORDION_HELP_BY_INDEX["oc"]
                    ),
                    children=[
                        dbc.Row([
                            dbc.Col(sidebar_oc, width=3),
                            dbc.Col(graph_oc, width=9),
                        ]),
                    ],
                ),
            ],
            id="main-workflow-accordion",
            always_open=True,  # Allows multiple items to stay open simultaneously
            active_item=[ACCORDION_LC_ITEM_ID],
        ),

    ], fluid=True, className="gp-page")


# ===================== CALLBACKS ================================================

@callback(
    # region unfold
    Output("help-modal", "is_open"),
    [Input("open-help", "n_clicks"), Input("close-help", "n_clicks")],
    [State("help-modal", "is_open")],
    # endregion
)
def toggle_modal(n1, n2, is_open):
    """Opens or closes the page-level About modal.

    Args:
        n1: Clicks on the header About button.
        n2: Clicks on the modal Close button.
        is_open: Current modal state.

    Returns:
        bool: Toggled open state.
    """
    if n1 or n2:
        return not is_open
    return is_open


@callback(
    Output({"type": "gp-accordion-help-modal", "index": MATCH}, "is_open"),
    Input({"type": "gp-accordion-help-open", "index": MATCH}, "n_clicks"),
    Input({"type": "gp-accordion-help-close", "index": MATCH}, "n_clicks"),
    State({"type": "gp-accordion-help-modal", "index": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def toggle_accordion_help_modal(n_open, n_close, is_open):
    """Opens or closes the help modal for one accordion item.

    Args:
        n_open: Clicks on the hidden proxy fired by the header ``?``.
        n_close: Clicks on the modal Close / Stop talking! button.
        is_open: Current modal state.

    Returns:
        bool: Toggled open state.
    """
    if n_open or n_close:
        return not is_open
    return is_open


# --- Open/Close registry
@callback(
    # region unfold
    Output("registry-collapse", "is_open"),
    Output("registry-toggle-icon", "className"),
    Input("btn-toggle-registry", "n_clicks"),
    State("registry-collapse", "is_open"),
    prevent_initial_call=True
    # endregion
)
def toggle_registry(n_clicks, is_open):
    if is_open:
        # Closing: return is_open=False and the Left arrow icon
        return False, "bi bi-chevron-left"
    else:
        # Opening: return is_open=True and the Right arrow icon
        return True, "bi bi-chevron-right"


@callback(
    # region unfold
    Output("legend-collapse", "is_open"),
    Output("toggle-legend-btn", "children"),
    Input("toggle-legend-btn", "n_clicks"),
    State("legend-collapse", "is_open"),
    prevent_initial_call=True
    # endregion
)
def toggle_gp_legend(n_clicks, is_open):
    if is_open:
        return False, "Show legend"
    return True, "Hide legend"


@callback(
    Output("mavka-legend-collapse", "is_open"),
    Output("toggle-mavka-legend-btn", "children"),
    Input("toggle-mavka-legend-btn", "n_clicks"),
    State("mavka-legend-collapse", "is_open"),
    prevent_initial_call=True,
)
def toggle_mavka_legend(n_clicks, is_open):
    """Shows or hides the MAVKA fit legend in the sidebar."""
    if is_open:
        return False, "Show legend"
    return True, "Hide legend"


# ------ lightcurve visualisation -------
@callback(
    # region unfold
    Output('prep-graph', 'figure'),
    Output('store-gp-interval-pick-bands', 'data'),
    Output('store-gp-intervals-marked', 'data'),
    Output('store-gp-prep-render-token', 'data'),
    Input('store-lc-data', 'data'),
    Input('store-intervals-data', 'data'),
    Input('folding-switch', 'value'),
    Input('view-mode-radio', 'value'),
    Input('gp_time_axis_switch', 'value'),
    Input('gp-prep-show-errorbars', 'value'),
    Input('store-gp-prep-working-window', 'data'),
    # Marking is applied clientside by recolouring the band shapes in place, so
    # a mark must never trigger a replot. State, not Input.
    State('store-gp-intervals-marked', 'data'),
    Input('gp-fold-ephemeris-mode', 'value'),
    State('input-period', 'value'),
    State('input-epoch', 'value'),
    State('input-oc-a', 'value'),
    State('input-oc-b', 'value'),
    State('input-oc-c', 'value'),
    State('prep-graph', 'relayoutData'),
    # endregion
)
def update_prep_graph(
    lc_json_string,
    intervals_data,
    folding_on,
    view_mode,
    time_axis_mode,
    show_prep_errorbars,
    working_window_store,
    marked_indices,
    fold_ephemeris_mode,
    period,
    epoch,
    oc_a,
    oc_b,
    oc_c,
    prep_relayout_data,
):
    # Bumped on every replot so the clientside binders can rebind their Plotly
    # listeners without being handed the figure itself.
    render_token = uuid.uuid4().hex[:8]

    if not lc_json_string:
        return (
            go.Figure().update_layout(title="Upload data to see plot"),
            {"enabled": False, "axis": TIME_AXIS_MJD, "bands": []},
            [],
            render_token,
        )

    axis_mode = time_axis_mode or TIME_AXIS_MJD
    phase_view = bool(folding_on) and period and period > 0

    try:
        lc = unpack_json_for_gp_plot(lc_json_string, view_mode=view_mode)
    except Exception as e:
        logger.exception("Prep plot failed")
        fig = go.Figure()
        fig.update_layout(
            title=f"Could not plot lightcurve: {e}",
            template="plotly_white",
            margin=dict(l=40, r=20, t=60, b=40),
        )
        return (
            fig,
            {"enabled": False, "axis": axis_mode, "bands": []},
            [],
            render_token,
        )

    x_jd = np.asarray(lc['x'], dtype=float)
    y_data = lc['y']
    err_data = lc['err']

    working_window = normalize_working_window(working_window_store)
    if working_window is not None:
        try:
            x_jd, y_data, err_data = filter_plot_arrays_by_jd_window(
                x_jd,
                y_data,
                err_data,
                working_window["jd_min"],
                working_window["jd_max"],
            )
        except PipeException as exc:
            fig = go.Figure()
            fig.update_layout(
                title=str(exc),
                template="plotly_white",
                margin=dict(l=40, r=20, t=60, b=40),
            )
            return (
                fig,
                {"enabled": False, "axis": axis_mode, "bands": []},
                [],
                render_token,
            )

    # Error bars logic (off by default; large LC + triple phase copies is slow)
    error_y_logic = None
    if err_data is not None and show_prep_errorbars:
        error_y_logic = dict(
            type='data',
            array=err_data,
            visible=True,
            thickness=1,
            width=0,
            color='rgba(100, 100, 100, 0.3)'  # Subtle grey
        )

    if phase_view:
        t0_abs = absolute_jd_from_display_epoch(epoch, jd0)
        if t0_abs is None:
            t0_abs = float(np.nanmin(x_jd))
        fold_mode = fold_ephemeris_mode or FOLD_EPHEMERIS_CONSTANT
        oc_a_val = gp_parse_oc_coefficient(oc_a)
        oc_b_val = gp_parse_oc_coefficient(oc_b)
        oc_c_val = gp_parse_oc_coefficient(oc_c)
        try:
            if fold_mode == FOLD_EPHEMERIS_QUADRATIC_OC:
                phi = phases_from_quadratic_oc(
                    x_jd,
                    float(period),
                    t0_abs,
                    oc_a_val,
                    oc_b_val,
                    oc_c_val,
                )
                x_plot, y_plot, err_plot = build_extended_phase_plot_arrays_from_phi(
                    phi,
                    y_data,
                    err_data if show_prep_errorbars else None,
                )
                t0_label = display_epoch_offset(t0_abs, jd0)
                x_label = (
                    f"Phase (quadratic O-C; P={period} d, Epoch-{jd0}={t0_label:.2f}; "
                    f"a={oc_a_val:g}, b={oc_b_val:g}, c={oc_c_val:g}; "
                    f"extended {EXTENDED_PHASE_XMIN}–{EXTENDED_PHASE_XMAX})"
                )
            else:
                x_plot, y_plot, err_plot = build_extended_phase_plot_arrays(
                    x_jd,
                    y_data,
                    err_data if show_prep_errorbars else None,
                    t0_abs,
                    float(period),
                )
                t0_label = display_epoch_offset(t0_abs, jd0)
                x_label = (
                    f"Phase (P={period} d, Epoch-{jd0}={t0_label:.2f}; "
                    f"extended {EXTENDED_PHASE_XMIN}–{EXTENDED_PHASE_XMAX})"
                )
        except PipeException as exc:
            fig = go.Figure()
            fig.update_layout(
                title=str(exc),
                template="plotly_white",
                margin=dict(l=40, r=20, t=60, b=40),
            )
            return (
                fig,
                {"enabled": False, "axis": axis_mode, "bands": []},
                [],
                render_token,
            )
        if err_plot is not None and show_prep_errorbars:
            error_y_logic = dict(
                type='data',
                array=err_plot,
                visible=True,
                thickness=1,
                width=0,
                color='rgba(100, 100, 100, 0.3)',
            )
        else:
            error_y_logic = None
        x_data = x_plot
        y_data = y_plot
    else:
        ts = lc.get("timescale")
        ref = lc.get("refposition")
        x_data = absolute_jd_to_plot_x(
            x_jd, axis_mode, jd0, timescale=ts
        )
        x_label = time_axis_xaxis_title(axis_mode, ts, ref)

    fig = go.Figure()  # todo: use px.* stuff instead

    # Main data trace with error bars
    fig.add_trace(go.Scattergl(  # go.Scattergl (uses users GPU) is much faster and responsive than go.Scatter
        x=x_data, y=y_data,
        mode='markers',
        selectedpoints=None,
        # Define how points look when they AREN'T in a box (prevents dimming)
        unselected=dict(marker=dict(opacity=0.7, color='blue')),
        # Define how they look when they ARE in a box (while dragging)
        selected=dict(marker=dict(opacity=1.0, color='green')),
        # todo: add an user-option -- draw error bars or not (no error bars for TESS data please!)
        error_y=error_y_logic,  # <--- Error bars added here  this is very heavy thing to send to and from
        hoverinfo='none',
        marker=dict(
            size=4,
            color='blue',
            opacity=0.7,
            line=dict(width=0.5, color='White')
        ),
        name="Data"
    ))

    # Layout with UI Revision
    fig.update_layout(
        xaxis_title=x_label,
        yaxis_title=lc['y_label'],
        yaxis_autorange='reversed' if lc['is_mag'] else True,
        # xaxis_title=x_label,
        # yaxis_title="Magnitude" if view_mode == 'mag' else "Flux",
        # yaxis_autorange='reversed' if view_mode == 'mag' else True,
        margin=dict(l=10, r=10, t=20, b=40),
        template="plotly_white",
        # dragmode='pan',
        dragmode='select',
        selectdirection='h',
        # A digest of the light curve means zoom only resets when a NEW file is
        # uploaded; adding an interval won't trigger a reset. The digest keeps the
        # transport string itself out of the figure payload.
        uirevision=(
            f"{transport_revision_token(lc_json_string)}_{view_mode}_{folding_on}_"
            f"{axis_mode}_{show_prep_errorbars}_{working_window_store}_"
            f"{fold_ephemeris_mode}_{oc_a}_{oc_b}_{oc_c}"
        ),
        # ------------------------------
        newshape=dict(line_color='red', line_width=3, opacity=0.5),
    )

    apply_time_xaxis_format(fig, phase_view=phase_view, time_axis_mode=axis_mode)
    if phase_view:
        fig.update_xaxes(range=[EXTENDED_PHASE_XMIN, EXTENDED_PHASE_XMAX])

    # Mark selected intervals (stored as absolute JD; display only in current axis)
    pick_bands = {"enabled": False, "axis": axis_mode, "bands": []}
    if intervals_data:
        # Bands are collected and assigned in one go: fig.add_shape/add_vrect
        # re-validate the whole shapes tuple per call, which is quadratic.
        band_shapes: list[dict] = []
        jd_window = None
        if working_window is not None:
            jd_window = (
                working_window["jd_min"],
                working_window["jd_max"],
            )
        if phase_view:
            # Folded bands carry no name and no marked styling: one interval maps
            # to several phase rectangles, so a mark cannot be shown. All mark
            # work is skipped here and 'pick_bands' stays disabled. Overlapping
            # phase copies are merged so stacked minima become a handful of SVG
            # rectangles, not one per interval. The marked set itself is left
            # untouched in its store and reappears on unfolding.
            t0_abs = absolute_jd_from_display_epoch(epoch, jd0)
            if t0_abs is None:
                t0_abs = float(np.nanmin(x_jd))
            fold_mode = fold_ephemeris_mode or FOLD_EPHEMERIS_CONSTANT
            oc_a_val = gp_parse_oc_coefficient(oc_a)
            oc_b_val = gp_parse_oc_coefficient(oc_b)
            oc_c_val = gp_parse_oc_coefficient(oc_c)
            phase_segments: list[tuple[float, float]] = []
            for interval in intervals_data:
                if jd_window is not None and not interval_overlaps_jd_window(
                    interval, jd_window[0], jd_window[1]
                ):
                    continue
                if fold_mode == FOLD_EPHEMERIS_QUADRATIC_OC:
                    vrect_bounds = phase_vrect_bounds_extended_quadratic(
                        interval[0],
                        interval[1],
                        float(period),
                        t0_abs,
                        oc_a_val,
                        oc_b_val,
                        oc_c_val,
                    )
                else:
                    vrect_bounds = phase_vrect_bounds_extended(
                        interval[0], interval[1], t0_abs, float(period)
                    )
                phase_segments.extend(vrect_bounds)
            for x0, x1 in merge_overlapping_phase_segments(phase_segments):
                band_shapes.append(prep_interval_band_shape(x0, x1))
        else:
            ts = lc.get("timescale")
            pick_bands = build_unfolded_interval_pick_payload(
                intervals_data,
                time_axis_mode=axis_mode,
                display_epoch=jd0,
                timescale=ts,
                jd_window=jd_window,
            )
            marked_set = {
                int(i)
                for i in (marked_indices if isinstance(marked_indices, list) else [])
                if 0 <= int(i) < len(intervals_data)
            }
            for index, interval in enumerate(intervals_data):
                if jd_window is not None and not interval_overlaps_jd_window(
                    interval, jd_window[0], jd_window[1]
                ):
                    continue
                x0, x1 = absolute_jd_to_plot_x(
                    [interval[0], interval[1]], axis_mode, jd0, timescale=ts
                )
                band_shapes.append(
                    prep_interval_band_shape(
                        x0,
                        x1,
                        name=interval_shape_name(index),
                        marked=index in marked_set,
                    )
                )
        fig.update_layout(shapes=band_shapes)

    triggered = callback_context.triggered
    if triggered:
        trigger_id = triggered[0]['prop_id'].split('.')[0]
        if trigger_id == 'store-intervals-data':
            if working_window is None:
                apply_plot_relayout_ranges_to_figure(
                    fig,
                    prep_relayout_data,
                    preserve_x=not phase_view,
                )

    if working_window is not None and not phase_view:
        ts = lc.get("timescale")
        wx0, wx1 = absolute_jd_to_plot_x(
            [working_window["jd_min"], working_window["jd_max"]],
            axis_mode,
            jd0,
            timescale=ts,
        )
        fig.update_xaxes(range=[wx0, wx1], autorange=False)

    return fig, pick_bands, no_update, render_token


clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="applyIntervalMarkMode"),
    Output("prep-graph", "figure", allow_duplicate=True),
    Input("gp-interval-mark-mode", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="syncPrepGraphConfig"),
    Output("prep-graph", "config"),
    Input("gp-interval-mark-mode", "value"),
    Input("gp-prep-trend-mode", "value"),
)

# Mark-band actions stay disabled until at least one band is marked
clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="reflectMarkedIntervalCount"),
    Output("btn-remove-marked-intervals", "disabled"),
    Output("btn-clear-interval-marks", "disabled"),
    Input("store-gp-intervals-marked", "data"),
)

# The trend actions are meaningless while the mode is off
clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="toggleTrendActions"),
    Output("gp-trend-actions", "className"),
    Input("gp-prep-trend-mode", "value"),
)


@callback(
    Output("btn-remove-empty-intervals", "disabled"),
    Output("btn-clear-intervals", "disabled"),
    Input("store-intervals-data", "data"),
)
def reflect_registry_interval_count(intervals):
    """Enables list actions when at least one interval is registered.

    Args:
        intervals (list | None): Interval registry from ``store-intervals-data``.

    Returns:
        tuple: ``(remove_empty_disabled, clear_all_disabled)``.
    """
    count = len(intervals) if intervals else 0
    return count == 0, count == 0


@callback(
    Output("btn-restore-full-lc", "disabled"),
    Input("store-gp-prep-working-window", "data"),
)
def gate_restore_full_lightcurve(working_window_store):
    """Disables restore until a working range is active.

    Args:
        working_window_store: ``store-gp-prep-working-window`` payload.

    Returns:
        bool: ``True`` when restore should stay disabled.
    """
    return normalize_working_window(working_window_store) is None


@callback(
    Output("gp-prep-working-window-status", "children"),
    Input("store-gp-prep-working-window", "data"),
    Input("gp_time_axis_switch", "value"),
    State("store-lc-data", "data"),
)
def describe_working_window(working_window_store, time_axis_mode, lc_json_string):
    """Shows whether prep uses the full light curve or a working JD window.

    Args:
        working_window_store: Working range store payload.
        time_axis_mode: Active prep plot time axis.
        lc_json_string: Full light curve transport JSON.

    Returns:
        str: Sentence-case status for the sidebar.
    """
    window = normalize_working_window(working_window_store)
    if window is None:
        return "Full light curve (zoom changes the view only)."
    timescale = None
    if lc_json_string:
        try:
            import json as _json

            meta = _json.loads(lc_json_string).get("meta") or {}
            timescale = meta.get("timescale")
        except (TypeError, ValueError, _json.JSONDecodeError):
            timescale = None
    start_label, end_label = format_interval_display_pair(
        window["jd_min"],
        window["jd_max"],
        time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
        display_epoch=jd0,
        timescale=timescale,
    )
    return f"Working range: {start_label} – {end_label}"


@callback(
    Output("store-gp-prep-working-window", "data"),
    Output("gp-prep-working-window-feedback", "children"),
    Input("btn-use-visible-range", "n_clicks"),
    State("prep-graph", "relayoutData"),
    State("gp_time_axis_switch", "value"),
    State("folding-switch", "value"),
    State("store-lc-data", "data"),
    prevent_initial_call=True,
)
def apply_visible_range_as_working_window(
    n_clicks,
    relayout_data,
    time_axis_mode,
    folding_on,
    lc_json_string,
):
    """Sets the prep working window from the current plot zoom.

    Args:
        n_clicks: Button click count.
        relayout_data: Latest prep graph relayout payload.
        time_axis_mode: Active time axis mode.
        folding_on: Phase folding checklist value.
        lc_json_string: Full light curve transport JSON.

    Returns:
        tuple: Updated working window store and optional feedback alert.
    """
    if not n_clicks or not lc_json_string:
        return dash.no_update, dash.no_update

    if gp_checklist_switch_is_on(folding_on):
        return (
            dash.no_update,
            dbc.Alert(
                "Unfold the light curve before setting a working range from zoom.",
                color="warning",
                className="py-2 small mb-0",
            ),
        )

    try:
        mode = time_axis_mode or TIME_AXIS_MJD
        jd_min, jd_max = jd_bounds_from_visible_plot(
            relayout_data,
            time_axis_mode=mode,
            display_epoch=jd0,
        )
        store_payload = build_working_window_store(jd_min, jd_max, lc_json_string)
    except PipeException as exc:
        return dash.no_update, dbc.Alert(
            str(exc),
            color="warning",
            className="py-2 small mb-0",
        )

    if store_payload.get("enabled"):
        message = dbc.Alert(
            "Prep plot and folding now use this time range only.",
            color="success",
            className="py-2 small mb-0",
        )
    else:
        message = dbc.Alert(
            "Visible range covers the full light curve; working range cleared.",
            color="info",
            className="py-2 small mb-0",
        )
    return store_payload, message


@callback(
    Output("store-gp-prep-working-window", "data", allow_duplicate=True),
    Output("gp-prep-working-window-feedback", "children", allow_duplicate=True),
    Input("btn-restore-full-lc", "n_clicks"),
    prevent_initial_call=True,
)
def restore_full_lightcurve_working_window(n_clicks):
    """Clears the prep working window so the full light curve is used again.

    Args:
        n_clicks: Restore button click count.

    Returns:
        tuple: Disabled working window store and success feedback.
    """
    if not n_clicks:
        return dash.no_update, dash.no_update
    return (
        WORKING_WINDOW_DISABLED,
        dbc.Alert(
            "Full light curve restored for prep and folding.",
            color="success",
            className="py-2 small mb-0",
        ),
    )


clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="bindPrepGraphMarkSelect"),
    Output("store-gp-prep-mark-selection", "data", allow_duplicate=True),
    Input("store-gp-prep-render-token", "data"),
    prevent_initial_call="initial_duplicate",
)

# Click or drag on the green rectangles themselves. Recolour is clientside;
# no replot occurs until Remove marked.
clientside_callback(
    ClientsideFunction(
        namespace="gpOc", function_name="toggleIntervalMarksFromSelection"
    ),
    Output("store-gp-intervals-marked", "data", allow_duplicate=True),
    Input("store-gp-prep-mark-selection", "data"),
    State("store-gp-interval-pick-bands", "data"),
    State("store-gp-intervals-marked", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="clearIntervalMarks"),
    Output("store-gp-intervals-marked", "data", allow_duplicate=True),
    Input("btn-clear-interval-marks", "n_clicks"),
    State("store-gp-interval-pick-bands", "data"),
    State("store-gp-intervals-marked", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="applyTrendMode"),
    Output("prep-graph", "figure", allow_duplicate=True),
    Input("gp-prep-trend-mode", "value"),
    Input("folding-switch", "value"),
    prevent_initial_call="initial_duplicate",
)

clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="bindPrepGraphTrend"),
    Output("store-gp-trend-click", "data", allow_duplicate=True),
    Input("store-gp-prep-render-token", "data"),
    prevent_initial_call="initial_duplicate",
)

clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="processTrendClick"),
    Output("store-gp-trend-line", "data"),
    Input("store-gp-trend-click", "data"),
    State("gp-prep-trend-mode", "value"),
    State("folding-switch", "value"),
    State("store-gp-trend-line", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="clearTrendLine"),
    Output("store-gp-trend-line", "data", allow_duplicate=True),
    Input("btn-clear-prep-trend", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="gpOc", function_name="restoreTrendPreviewFromStore"),
    Output("prep-graph", "figure", allow_duplicate=True),
    Input("store-gp-prep-render-token", "data"),
    State("store-gp-trend-line", "data"),
    State("gp-prep-trend-mode", "value"),
    prevent_initial_call="initial_duplicate",
)


@callback(
    Output("store-intervals-data", "data", allow_duplicate=True),
    Output("store-gp-intervals-marked", "data", allow_duplicate=True),
    Input("btn-remove-marked-intervals", "n_clicks"),
    State("store-intervals-data", "data"),
    State("store-gp-intervals-marked", "data"),
    prevent_initial_call=True,
)
def commit_remove_marked_intervals(n_clicks, intervals, marked):
    """Removes intervals marked on the prep plot (single server round-trip)."""
    if not n_clicks or not intervals or not marked:
        raise PreventUpdate
    return intervals_without_marked_indices(intervals, marked), []


@callback(
    Output("store-intervals-data", "data", allow_duplicate=True),
    Input("btn-remove-empty-intervals", "n_clicks"),
    State("store-intervals-data", "data"),
    State("store-lc-data", "data"),
    prevent_initial_call=True,
)
def commit_remove_empty_intervals(n_clicks, intervals, lc_json_string):
    """Drops all point-free intervals in one store update (one prep replot)."""
    if not n_clicks or not intervals or not lc_json_string:
        raise PreventUpdate
    drop = empty_interval_indices(intervals, lc_json_string)
    if not drop:
        raise PreventUpdate
    return intervals_without_marked_indices(intervals, drop)


@callback(
    Output("gp-quadratic-oc-fields", "className"),
    Input("gp-fold-ephemeris-mode", "value"),
)
def toggle_quadratic_oc_fields(fold_ephemeris_mode):
    """Shows O-C coefficient inputs only for quadratic fold mode.

    Args:
        fold_ephemeris_mode (str): ``constant`` or ``quadratic_oc``.

    Returns:
        str: CSS classes for the coefficient block.
    """
    base = "gp-sidebar-btn-stack"
    if fold_ephemeris_mode == FOLD_EPHEMERIS_QUADRATIC_OC:
        return base
    return f"{base} d-none"


@callback(
    Output("gp-interval-mark-mode", "value"),
    Output("gp-interval-mark-mode", "options"),
    Output("gp-prep-trend-mode", "value"),
    Output("gp-prep-trend-mode", "options"),
    Input("folding-switch", "value"),
)
def disable_prep_interaction_modes_when_folded(folding_on):
    """Clear mark/trend modes when folded; both switches are unfolded-only."""
    if gp_checklist_switch_is_on(folding_on):
        return (
            [],
            gp_mark_mode_checklist_options(disabled=True),
            [],
            gp_trend_mode_checklist_options(disabled=True),
        )
    return (
        no_update,
        gp_mark_mode_checklist_options(disabled=False),
        no_update,
        gp_trend_mode_checklist_options(disabled=False),
    )


@callback(
    Output("store-lc-data", "data", allow_duplicate=True),
    Output("gp-trend-feedback", "children"),
    Output("store-gp-trend-line", "data", allow_duplicate=True),
    Output("gp-prep-trend-mode", "value", allow_duplicate=True),
    Input("btn-apply-prep-trend", "n_clicks"),
    State("store-lc-data", "data"),
    State("store-gp-trend-line", "data"),
    State("view-mode-radio", "value"),
    State("gp_time_axis_switch", "value"),
    State("folding-switch", "value"),
    State("store-gp-prep-working-window", "data"),
    prevent_initial_call=True,
)
def commit_prep_linear_detrend(
    n_clicks,
    lc_json_string,
    trend_line,
    view_mode,
    time_axis_mode,
    folding_on,
    working_window_store,
):
    """Applies the user trend line to the stored light curve."""
    if not n_clicks or not lc_json_string:
        raise PreventUpdate
    if gp_checklist_switch_is_on(folding_on):
        return (
            no_update,
            dbc.Alert(
                "Trend removal is only available on the unfolded light curve.",
                color="warning",
                className="py-2 small mb-0",
            ),
            no_update,
            no_update,
        )
    if not trend_line or not trend_line.get("ready"):
        return (
            no_update,
            dbc.Alert(
                "Click the prep plot once to place a trend line, then Apply.",
                color="warning",
                className="py-2 small mb-0",
            ),
            no_update,
            no_update,
        )
    try:
        window = normalize_working_window(working_window_store)
        jd_bounds = observation_jd_bounds_tuple(window)
        updated = apply_manual_linear_detrend(
            lc_json_string,
            view_mode=view_mode or "mag",
            anchor_a=(trend_line["x0"], trend_line["y0"]),
            anchor_b=(trend_line["x1"], trend_line["y1"]),
            time_axis_mode=time_axis_mode or TIME_AXIS_MJD,
            display_epoch=jd0,
            jd_bounds=jd_bounds,
        )
    except PipeException as exc:
        return (
            no_update,
            dbc.Alert(str(exc), color="warning", className="py-2 small mb-0"),
            no_update,
            no_update,
        )
    except Exception as exc:
        logger.exception("Prep trend removal failed")
        return (
            no_update,
            dbc.Alert(
                f"Could not apply trend removal: {exc}",
                color="danger",
                className="py-2 small mb-0",
            ),
            no_update,
            no_update,
        )
    return (
        updated,
        dbc.Alert(
            "Trend removed from the working range."
            if jd_bounds
            else "Trend removed from the working light curve.",
            color="success",
            className="py-2 small mb-0",
        ),
        None,
        [],
    )


# ------ Lightcurve ----

@callback(
    Output('store-lc-data', 'data'),
    Output('upload-lc-text', 'children'),
    Output({"type": "gp-upload-detail", "index": "lc"}, 'children'),
    Output('input-period', 'value'),
    Output('input-epoch', 'value'),
    Output('view-mode-radio', 'value'),
    Output('store-gp-prep-working-window', 'data', allow_duplicate=True),
    Output("gp-trend-feedback", "children", allow_duplicate=True),
    Output("gp-prep-working-window-feedback", "children", allow_duplicate=True),
    Output("main-workflow-accordion", "active_item", allow_duplicate=True),
    Input('upload-lc', 'contents'),
    State('upload-lc', 'filename'),
    State("main-workflow-accordion", "active_item"),
    prevent_initial_call=True
    # endregion
)
def upload_lc(contents, filename, accordion_active):
    """Ingests a light-curve file and opens Lightcurve and intervals on success.

    Args:
        contents: ``dcc.Upload`` file payload.
        filename: Original upload filename.
        accordion_active: Current workflow accordion ``active_item``.

    Returns:
        tuple: Store, upload chip, folding fields, working-window reset, and
        accordion open set. Failures leave the accordion unchanged.
    """
    logger.info("Uploading lightcurve: %s", filename)
    if contents is None:
        return (dash.no_update,) * 10
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)

        lc_json_string = pack_uploaded_lightcurve(decoded, filename)
        period, epoch_abs, active_domain = folding_metadata_from_transport(lc_json_string)
        epoch_display = (
            display_epoch_offset(epoch_abs, jd0) if epoch_abs is not None else None
        )

        return (
            lc_json_string,
            _gp_upload_status(filename, tone="ok"),
            None,
            period,
            epoch_display,
            active_domain,
            WORKING_WINDOW_DISABLED,
            None,
            None,
            _active_items_opening_lc(accordion_active),
        )

    except Exception as e:
        logger.error("Failed to process file: %s", filename)
        logger.error(traceback.format_exc())

        return (
            dash.no_update,
            _gp_upload_status(filename, tone="error"),
            _gp_upload_failure_detail(
                "Lightcurve upload failed",
                format_user_upload_error(e),
            ),
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
        )


@callback(
    Output({"type": "gp-upload-detail-btn", "index": MATCH}, "className"),
    Output({"type": "gp-upload-detail-collapse", "index": MATCH}, "is_open"),
    Input({"type": "gp-upload-detail", "index": MATCH}, "children"),
)
def reflect_upload_failure_detail(detail):
    """Shows the ``?`` toggle only while a slot has an explanation to give.

    Args:
        detail: Children of the slot's detail container (``None`` when the last
            upload succeeded).

    Returns:
        tuple: ``(button_class_name, collapse_is_open)``; the collapse always
        starts closed so a new upload never leaves stale text open.
    """
    base = "gp-upload-detail-btn"
    return (base if detail else f"{base} d-none"), False


@callback(
    Output(
        {"type": "gp-upload-detail-collapse", "index": MATCH},
        "is_open",
        allow_duplicate=True,
    ),
    Input({"type": "gp-upload-detail-btn", "index": MATCH}, "n_clicks"),
    State({"type": "gp-upload-detail-collapse", "index": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def toggle_upload_failure_detail(n_clicks, is_open):
    """Expands or hides the failure explanation under the data bar.

    Args:
        n_clicks (int | None): Clicks on the slot's ``?`` button.
        is_open (bool): Current collapse state.

    Returns:
        bool: Requested collapse state.
    """
    if not n_clicks:
        raise PreventUpdate
    return not is_open


# Callbacks for Intervals file upload/download/signs

@callback(
    Output('upload-intervals-text', 'children'),
    Input('store-active-intervals-name', 'data')
)
def update_global_intervals_label(stored_status):
    """Renders the intervals file name chip from the shared status store.

    Args:
        stored_status (dict | None): ``{"name": str, "tone": str}`` written by the
            interval upload and download callbacks.

    Returns:
        dash development component: Placeholder when no file is active, otherwise
        the file name chip.
    """
    if not stored_status:
        return _gp_upload_placeholder()

    return _gp_upload_status(stored_status["name"], tone=stored_status["tone"])


@callback(
    # region unfold me
    Output('store-intervals-data', 'data'),
    Output('store-active-intervals-name', 'data'),
    Output({"type": "gp-upload-detail", "index": "intervals"}, 'children'),
    Output("main-workflow-accordion", "active_item", allow_duplicate=True),
    Input('upload-intervals', 'contents'),
    State('upload-intervals', 'filename'),
    State("main-workflow-accordion", "active_item"),
    prevent_initial_call=True
    # endregion
)
def upload_intervals(contents, filename, accordion_active):
    """Ingests an intervals file and opens Lightcurve and intervals on success.

    Args:
        contents: ``dcc.Upload`` file payload.
        filename: Original upload filename.
        accordion_active: Current workflow accordion ``active_item``.

    Returns:
        tuple: Intervals store, file-name chip, detail slot, and accordion open
        set. Failures leave the accordion unchanged.
    """
    if contents is None:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        # Convert bytes -> text -> StringIO
        text = decoded.decode('utf-8', errors='ignore')  # "ignore"  to prevent the whole app
        # from crashing over a single non-ASCII character.
        intervals_list = load_intervals(io.StringIO(text))
        return (
            intervals_list,
            {"name": filename, "tone": "ok"},
            None,
            _active_items_opening_lc(accordion_active),
        )
        # --- Success UI ---
        # return intervals_list, filename
        # return intervals_list, html.Div([
        #     html.I(className="bi bi-check-circle-fill me-2", style={"color": "#28a745"}),
        #     html.B(filename)
        # ])
    except Exception as e:
        # 1. Log full traceback for terminal
        logging.error(f"Error processing interval file {filename}:")
        logging.error(traceback.format_exc())

        return (
            dash.no_update,
            {"name": filename, "tone": "error"},
            _gp_upload_failure_detail(
                "Intervals upload failed",
                format_user_upload_error(e),
            ),
            dash.no_update,
        )
        # return dash.no_update, html.Div([
        #     html.I(className="bi bi-exclamation-octagon-fill me-2", style={"color": "#dc3545"}),
        #     html.Span(
        #         [html.B("Error: "), filename],
        #         id=safe_id,
        #         style={"color": "#dc3545", "fontSize": "0.85rem", "cursor": "help"}
        #     ),
        #     dbc.Tooltip(
        #         f"Interval Load Error: {str(e)}",
        #         target=safe_id,
        #         placement="right",
        #         style={"fontSize": "0.75rem"}
        #     )
        # ])

    # content_type, content_string = contents.split(',')
    # decoded = base64.b64decode(content_string)
    #
    # # convert bytes -> text -> StringIO
    # text = decoded.decode('utf-8')
    # intervals_list = load_intervals(io.StringIO(text))
    # return intervals_list


@callback(
    # region infold
    Output("download-intervals-file", "data"),
    Output("store-active-intervals-name", "data", allow_duplicate=True),
    Output(
        {"type": "gp-upload-detail", "index": "intervals"},
        "children",
        allow_duplicate=True,
    ),
    Input("btn-download-intervals", "n_clicks"),
    State("store-intervals-data", "data"),
    State("export-intervals-filename", "value"),
    prevent_initial_call=True,
    # endregion
)
def download_intervals(n_clicks, intervals, custom_name):
    if not n_clicks or not intervals:
        return dash.no_update, dash.no_update, dash.no_update

    content = format_intervals_download(intervals)
    export_name = gp_intervals_export_download_name(custom_name)

    return (
        dict(content=content, filename=export_name),
        {"name": export_name, "tone": "info"},
        None,
    )
    # return dict(content=content, filename=export_name), export_name


@callback(
    # region unfold
    Output('store-intervals-data', 'data', allow_duplicate=True),
    Input('btn-clear-intervals', 'n_clicks'),
    prevent_initial_call=True
    # endregion
)
def clear_all_intervals(n_clicks):
    if n_clicks:
        return []  # Return empty list to the store
    return dash.no_update


@callback(
    # region unfold
    Output({'type': 'float-input', 'index': 'length_scale_min'}, 'value', allow_duplicate=True),
    Output({'type': 'float-input', 'index': 'length_scale_init'}, 'value', allow_duplicate=True),
    Output({'type': 'float-input', 'index': 'length_scale_max'}, 'value', allow_duplicate=True),
    Input('scale-calc-trigger', 'data'),
    State('store-intervals-data', 'data'),
    State('store-lc-data', 'data'),
    prevent_initial_call=True
    # endregion
)
def update_GP_scale(trigger_clicks, intervals, lc_json_string):
    """Fills length-scale bounds from data when the user clicks Guess parameters."""
    if not trigger_clicks or not lc_json_string or not intervals:
        return dash.no_update, dash.no_update, dash.no_update

    # di = json.loads(lc_json_string)
    # df_lc = pd.DataFrame(data=di['data'], columns=di['columns'])

    # Search for the first interval that actually contains enough data points
    lc_arrays = decode_gp_flux_arrays(lc_json_string)
    for piece in intervals:
        jd_min, jd_max = piece[0], piece[1]
        frag = slice_gp_flux_arrays(lc_arrays, jd_min, jd_max)

        if len(frag) >= LEN_MIN:
            scale = guess_length_scale(frag)
            return (
                round(scale['length_scale_min'], 6),  # round here is purely for UI aesthetics
                round(scale['length_scale_init'], 6),
                round(scale['length_scale_max'], 6)
            )
    return dash.no_update, dash.no_update, dash.no_update


@callback(
    # region unfold
    Output('store-intervals-data', 'data', allow_duplicate=True),
    Output('folding-switch', 'value'),
    Output('gp-interval-add-feedback', 'children'),
    Input('btn-add-interval', 'n_clicks'),
    State('prep-graph', 'selectedData'),
    State('store-intervals-data', 'data'),
    State('folding-switch', 'value'),  # we handle selection on a folded curve
    State('input-period', 'value'),  # we bring phase interval into jd-space
    State('input-epoch', 'value'),
    State('gp_time_axis_switch', 'value'),
    State('store-lc-data', 'data'),  # We need this to get JD span
    State('store-gp-prep-working-window', 'data'),
    State('gp-fold-ephemeris-mode', 'value'),
    State('input-oc-a', 'value'),
    State('input-oc-b', 'value'),
    State('input-oc-c', 'value'),
    State('gp-prep-trend-mode', 'value'),
    prevent_initial_call=True
    # endregion
)
def add_selection_to_registry(
    n_clicks,
    selected_data,
    current_intervals,
    folding_on,
    period,
    epoch,
    time_axis_mode,
    lc_json,
    working_window_store,
    fold_ephemeris_mode,
    oc_a,
    oc_b,
    oc_c,
    trend_mode_on,
):
    if not n_clicks or not selected_data or 'range' not in selected_data:
        return dash.no_update, dash.no_update, dash.no_update

    if gp_checklist_switch_is_on(trend_mode_on):
        return (
            dash.no_update,
            dash.no_update,
            dbc.Alert(
                "Turn off Remove trend before adding intervals from a box selection.",
                color="warning",
                className="py-2 small mb-0",
            ),
        )

    x_min, x_max = selected_data['range']['x']
    updated_list = list(current_intervals or [])

    try:
        if folding_on:
            if not period or period <= 0:
                raise PipeException("Set a valid period before adding intervals on the folded curve.")
            if not lc_json:
                raise PipeException("Upload a light curve before adding intervals.")

            phi_lo, phi_hi = validate_extended_phase_selection(x_min, x_max)
            epoch_abs = absolute_jd_from_display_epoch(epoch, jd0)
            obs_bounds = observation_jd_bounds_tuple(
                normalize_working_window(working_window_store)
            )
            fold_mode = fold_ephemeris_mode or FOLD_EPHEMERIS_CONSTANT
            if fold_mode == FOLD_EPHEMERIS_QUADRATIC_OC:
                new_intervals = get_intervals_from_phase_quadratic(
                    lc_json,
                    phi_lo,
                    phi_hi,
                    period,
                    epoch_abs,
                    gp_parse_oc_coefficient(oc_a),
                    gp_parse_oc_coefficient(oc_b),
                    gp_parse_oc_coefficient(oc_c),
                    observation_jd_bounds=obs_bounds,
                )
            else:
                new_intervals = get_intervals_from_phase(
                    lc_json,
                    phi_lo,
                    phi_hi,
                    period,
                    epoch_abs,
                    observation_jd_bounds=obs_bounds,
                )
            if not new_intervals:
                raise PipeException(
                    "No intervals fall inside the working time range for this phase selection."
                )
            assert_phase_intervals_not_duplicates(new_intervals, updated_list)
            updated_list.extend(new_intervals)
        else:
            mode = time_axis_mode or TIME_AXIS_MJD
            left_jd = plot_x_to_jd(x_min, mode, jd0)
            right_jd = plot_x_to_jd(x_max, mode, jd0)
            new_interval = [round(left_jd, 6), round(right_jd, 6)]
            assert_phase_intervals_not_duplicates([new_interval], updated_list)
            updated_list.append(new_interval)

        updated_list.sort(key=lambda x: x[0])
        fold_out = (
            []
            if gp_checklist_switch_is_on(folding_on)
            else dash.no_update
        )
        return updated_list, fold_out, None

    except PipeException as exc:
        return (
            dash.no_update,
            dash.no_update,
            dbc.Alert(str(exc), color="warning", className="py-2 small mb-0"),
        )


# @callback(
#     # region infold
#     Output('store-intervals-data', 'data', allow_duplicate=True),
#     Input('btn-add-interval', 'n_clicks'),
#     State('prep-graph', 'selectedData'),
#     State('store-intervals-data', 'data'),
#     State('folding-switch', 'value'),  # We need to know if we are in Phase or JD!
#     prevent_initial_call=True
#     # endregion
# )
# def add_selection_to_registry_back(n_clicks, selected_data, current_intervals, folding_on):
#     if not n_clicks or not selected_data:
#         return dash.no_update
#
#     # 1. Extract the X-range from the selection
#     # SelectedData contains 'range': {'x': [min, max]}
#     if 'range' in selected_data:
#         x_min, x_max = selected_data['range']['x']
#
#         # BETA-TESTER WARNING:
#         # If folding is ON, x_min/max are PHASES (0-1).
#         # If folding is OFF, they are JD.
#         # For now, let's assume the user selects in JD (unfolded) mode.
#         if folding_on:
#             # We might want to warn the user or handle phase-to-jd conversion later
#             return dash.no_update
#
#             # 2. Append to our list
#         new_interval = [round(x_min, 6), round(x_max, 6)]
#
#         # current_intervals is usually a list of lists: [[start1, end1], [start2, end2]]
#         updated_list = current_intervals if current_intervals else []
#
#         # Prevent exact duplicates
#         if new_interval not in updated_list:
#             updated_list.append(new_interval)
#             # Sort by JD start time
#             updated_list.sort(key=lambda x: x[0])
#
#         return updated_list
#
#     return dash.no_update


# ------- interval registry stuff ----
@callback(
    Output('registry-list-container', 'children'),
    Input('store-intervals-data', 'data'),
    Input('gp_time_axis_switch', 'value'),
    Input('store-gp-prep-working-window', 'data'),
    State('store-lc-data', 'data'),
)
def render_registry(intervals, time_axis_mode, working_window_store, lc_json_string):
    """Renders interval cards using the same time axis as the prep plot."""
    if not intervals:
        return html.P("No intervals selected.", className="text-muted small italic")

    axis_mode = time_axis_mode or TIME_AXIS_MJD
    timescale = None
    if lc_json_string:
        try:
            import json as _json

            meta = _json.loads(lc_json_string).get("meta") or {}
            timescale = meta.get("timescale")
        except (TypeError, ValueError, _json.JSONDecodeError):
            timescale = None

    working_window = normalize_working_window(working_window_store)
    labels = format_interval_display_pairs(
        intervals,
        time_axis_mode=axis_mode,
        display_epoch=jd0,
        timescale=timescale,
    )
    cards = []
    for i, interval in enumerate(intervals):
        start_label, end_label = labels[i]
        outside = working_window is not None and not interval_overlaps_jd_window(
            interval,
            working_window["jd_min"],
            working_window["jd_max"],
        )
        row_class = "gp-registry-item"
        if outside:
            row_class = "gp-registry-item gp-registry-item-outside"
        cards.append(
            dbc.Card([
                dbc.CardBody([
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.B(start_label),
                                    html.Span(" - "),
                                    html.B(end_label),
                                ],
                                className="small gp-registry-item-values",
                            ),
                            dbc.Button(
                                html.I(className="bi bi-trash"),
                                id={'type': 'del-int', 'index': i},
                                color="link",
                                size="sm",
                                className="gp-registry-action text-danger",
                                title="Delete",
                            ),
                        ],
                        className=row_class,
                    )
                ])
            ], className="shadow-sm")
        )
    return cards


# --------  Delete individual interval ----------
@callback(
    # region unfold
    Output('store-intervals-data', 'data', allow_duplicate=True),
    Input({'type': 'del-int', 'index': ALL}, 'n_clicks'),
    State('store-intervals-data', 'data'),
    prevent_initial_call=True
    # endregion
)
def delete_interval(n_clicks_list, current_intervals):
    # Check if any button was actually clicked
    if not any(n_clicks_list):
        return dash.no_update

    # Find which button index was triggered
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    # Extract the index from the triggered ID string
    # e.g., '{"index":2,"type":"del-int"}.n_clicks' -> 2
    import json
    triggered_id = json.loads(ctx.triggered[0]['prop_id'].split('.')[0])
    idx_to_remove = triggered_id['index']

    # Remove the item and return the new list
    if current_intervals and idx_to_remove < len(current_intervals):
        new_list = [item for i, item in enumerate(current_intervals) if i != idx_to_remove]
        return new_list

    return dash.no_update


# ================= GP callbacks ===================

@callback(
    Input("stop-btn", "n_clicks"),
    prevent_initial_call=True,
)
def gp_request_batch_stop(_n_clicks):
    """Cooperative stop: finish the current fit, then exit the batch loop."""
    request_gp_batch_stop()


@callback(
    # region unfold
    Output('gp-header-area', 'children'),
    Input('run-btn', 'n_clicks'),  # User clicks Run
    Input('stop-btn', 'n_clicks'),
    Input('finished-signal', 'children'),  # The Monster finishes
    prevent_initial_call=True
    # endregion
)
def update_gp_status_ui(run_clicks, stop_clicks, signal_status):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # 1. THE START: User clicks Run
    if trigger_id == 'run-btn' and run_clicks > 0:
        return html.Div([
            html.H6("GP processing view", className="gp-card-title"),
            dbc.Badge([
                html.I(className="bi bi-hourglass-split me-2"),
                "RUNNING - Modeling..."
            ], color="warning", className="ms-2")
        ], className="d-flex align-items-center mb-3")

    # 2. User clicks Stop (current fit finishes, then review partial results)
    if trigger_id == 'stop-btn' and stop_clicks > 0:
        return html.Div([
            html.H6("GP processing view", className="gp-card-title"),
            dbc.Badge([
                html.I(className="bi bi-pause-circle me-2"),
                "STOPPING - finishing current fit…"
            ], color="warning", className="ms-2")
        ], className="d-flex align-items-center mb-3")

    # 3. THE INTERMEDIATE: Plotting has started but isn't over
    if trigger_id == 'finished-signal' and signal_status == "WAITING":
        return html.Div([
            html.H6("GP processing view", className="gp-card-title"),
            dbc.Badge([
                html.I(className="bi bi-gear-wide-connected me-2"),
                "GENERATING PLOTS..."
            ], color="info", className="ms-2")
        ], className="d-flex align-items-center mb-3")

    # 4. THE END: Only show the "Finished" badge for the explicit final signal
    if trigger_id == 'finished-signal' and signal_status in ("FINISHED", "FINISHED_STOPPED"):
        stopped = signal_status == "FINISHED_STOPPED"
        badge_text = (
            "STOPPED - review completed fits"
            if stopped
            else "FINISHED"
        )
        badge_color = "warning" if stopped else "success"
        return html.Div([
            html.H6("Results: Normalised flux vs JD", className="gp-card-title"),
            dbc.Badge([
                html.I(className="bi bi-check-all me-2"),
                badge_text
            ], color=badge_color, className="ms-2")
        ], className="d-flex align-items-center mb-3")

    return dash.no_update


def create_interval_card(content, badges=None, is_fail=False, checkbox_id=None):
    """
    Wraps a graph or an alert into a standardized card with badges and checkboxes.
    """
    badge_row = html.Div(badges, className="gp-review-badges") if badges else None

    # Checkbox logic for Review Mode
    checkbox = None
    if checkbox_id:
        checkbox = dbc.Checkbox(
            id=checkbox_id,
            value=not is_fail,
            disabled=is_fail,  # Can't keep a failure
            label="Keep result" if not is_fail else "Fit failed",
            className="mb-1 fw-bold"
        )

    return dbc.Col(
        html.Div(
            [checkbox, badge_row, content],
            className="gp-review-card gp-review-card-fail" if is_fail else "gp-review-card",
        ),
        width=6, className="px-1 mb-2"
    )


@callback(
    # region unfold me
    Output('graphs-container', 'children', allow_duplicate=True),
    Output('finished-signal', 'children', allow_duplicate=True),  # Final signal
    Output('store-results-data', 'data'),  # Export metadata and include flags
    Output('gp-review-page-label', 'children'),
    Output("oc-export-filename", "value", allow_duplicate=True),
    Input('run-btn', 'n_clicks'),
    State('store-lc-data', 'data'),
    State('store-intervals-data', 'data'),
    State('guess-sigma', 'value'),
    State('extrema-mode', 'value'),
    State('kernel-type', 'value'),
    State({'type': 'float-input', 'index': ALL}, 'id'),  # Get the IDs
    State({'type': 'float-input', 'index': ALL}, 'value'),  # Get the values
    State("upload-lc", "filename"),
    State("oc-tom-source", "value"),
    background=True,
    running=[
        (Output("run-btn", "disabled"), True, False),
        (Output("stop-btn", "disabled"), False, True),
    ],
    progress=[
        Output("gp-live-progress-label", "children"),
        *_LIVE_SLOT_PROGRESS_OUTPUTS,
        Output("finished-signal", "children"),
    ],
    # this is why we place set_progress between input arguments
    prevent_initial_call=True
    # endregion
)
def run_gp(set_progress, n_clicks, lc_json_string, intervals, guess_sigma, extrema_mode, kernel_type, ids,
           float_values, lc_filename, oc_source):
    def _push_live(stored_entries: list, total_work: int) -> None:
        done = len(stored_entries)
        visible_page = live_visible_page_for_done_count(done)
        slots = build_live_page_slot_children(stored_entries, visible_page)
        label = live_progress_label(done, total_work)
        set_progress((label, *slots, "WAITING"))

    empty_slots = build_live_page_slot_children([], 0)
    set_progress((live_progress_label(0, 0), *empty_slots, "WAITING"))
    clear_gp_batch_stop()
    logger.debug("run_gp started")
    try:
        p = build_gp_float_params(ids, float_values)
    except ValueError as exc:
        error_alert = dbc.Alert(
            str(exc), color="warning", className="py-2 small mb-0"
        )
        return error_alert, "FINISHED", None, "", no_update
    # Add a standalone guess_sigma
    p['guess_sigma'] = guess_sigma
    p['extrema_mode'] = extrema_mode
    p['kernel_type'] = kernel_type
    logger.debug("GP params: %s", p)

    # 1. Validation: Ensure files are loaded
    if not lc_json_string or not intervals:
        error_alert = dbc.Alert("Please upload both lightcurve and intervals files.", color="warning")
        return error_alert, "FINISHED", None, "", no_update
        # return dbc.Alert("Please upload both lightcurve and intervals files.", color="warning")
    # di = json.loads(lc_json_string)
    # df_lc = pd.DataFrame(data=di['data'], columns=di['columns'])

    # Decode the light curve once, then slice per interval: decoding is the
    # expensive half and does not depend on the interval.
    lc_arrays = decode_gp_flux_arrays(lc_json_string)
    work_items = []
    for piece in intervals:
        jd_min, jd_max = piece[0], piece[1]
        frag = slice_gp_flux_arrays(lc_arrays, jd_min, jd_max)
        if len(frag) >= LEN_MIN:
            work_items.append((jd_min, jd_max, frag))

    total_work = len(work_items)
    _push_live([], total_work)

    stored_entries: list[dict] = []
    stopped_early = False

    for jd_min, jd_max, frag in work_items:
        if gp_batch_stop_requested():
            stopped_early = True
            logger.info("GP batch stopped before extremum (%s done)", len(stored_entries))
            break

        logging.info(f'{len(frag)=}')

        res_entry = {'jd_min': jd_min, 'jd_max': jd_max, 'is_fail': False}

        try:
            gp_res = gp_peak_pipeline(frag, params=p)
            fig = figure_from_gp_result(gp_res, display_epoch=jd0)

            # Extract kernel params for badges
            # optimized_params = gp_res['gp'].kernel_.get_params()
            k_obj = gp_res['gp'].kernel_
            # k1 is ConstantKernel, k2 is Matern/RBF
            opt_ampl = k_obj.k1.constant_value
            opt_l = k_obj.k2.length_scale

            # opt_l = optimized_params.get('k1__k2__length_scale', 0.0)
            # opt_w = optimized_params.get('k2__noise_level', 0.0)

            # Colour logic for Length Scale
            if opt_l <= p['length_scale_min'] * 1.01:
                l_color = "indigo"  # too short
            elif opt_l >= p['length_scale_max'] * 0.99:
                l_color = "danger"  # red, too long
            else:
                l_color = "success"

            # Amplitude badge (Replaces White Noise)
            # If amplitude hits the "Goldilocks" bounds,
            # maybe colour it yellow to warn the user
            amp_color = "info" if (0.01 < opt_ampl < 10.0) else "warning"

            badge_specs = success_badge_specs(
                kernel_type, opt_l, l_color, opt_ampl, amp_color, gp_res["jd_peak_std"]
            )
            badges = badges_from_specs(badge_specs)

            res_entry.update({
                'jd_peak': gp_res["jd_peak"],
                'jd_peak_std': gp_res["jd_peak_std"],
                'badge_specs': badge_specs,
                'kernel_type': kernel_type,
                'length_scale': float(opt_l),
                'amplitude': float(opt_ampl),
                'scale_limit_flag': scale_limit_flag(
                    float(opt_l),
                    float(p["length_scale_min"]),
                    float(p["length_scale_max"]),
                ),
            })

        except Exception as e:
            res_entry.update({
                'is_fail': True,
                'error': str(e),
                'badge_specs': [{"label": "FAILED", "color": "danger"}],
            })

        figure_json = None
        if not res_entry["is_fail"]:
            figure_json = fig.to_plotly_json()
        stored_entries.append(
            serialise_review_entry(res_entry, figure_json=figure_json)
        )
        _push_live(stored_entries, total_work)

        if gp_batch_stop_requested():
            stopped_early = True
            logger.info("GP batch stopped after %s fits", len(stored_entries))
            break

    if not stored_entries:
        msg = (
            "No fits completed before stop."
            if stopped_early
            else "No fits to review."
        )
        return (
            dbc.Alert(msg, color="warning"),
            "FINISHED_STOPPED" if stopped_early else "FINISHED",
            None,
            "",
            no_update,
        )

    # --- FINAL PHASE (Review): one page of cards; full list on server cache ---
    run_id = uuid.uuid4().hex
    save_gp_review_run(run_id, stored_entries)
    store_payload = build_review_store_payload(
        run_id,
        stored_entries,
        stopped_early=stopped_early,
        source_filename=lc_filename,
    )
    page_children = render_review_page(
        stored_entries, 0, store_payload["include"]
    )
    page_label = review_page_label(0, len(stored_entries))

    finish_signal = "FINISHED_STOPPED" if stopped_early else "FINISHED"
    oc_name = no_update
    if (oc_source or "gp") == "gp":
        oc_name = oc_default_export_stem(lc_filename)
    return page_children, finish_signal, store_payload, page_label, oc_name


@callback(
    # region unfold me
    Output({'type': 'float-input', 'index': ALL}, 'value'),
    Output('guess-sigma', 'value'),
    Output('kernel-type', 'value'),
    Output('scale-calc-trigger', 'data'),  # Trigger scale recalculation
    Input('reset-btn', 'n_clicks'),
    State({'type': 'float-input', 'index': ALL}, 'id'),
    State('scale-calc-trigger', 'data'),
    prevent_initial_call=True
    # endregion
)
def guess_gp_parameters(n_clicks, ids, current_trigger):
    """Applies default amplitude/noise guesses and data-driven length-scale bounds."""
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    float_resets = [str(params_float[val_id['index']]) for val_id in ids]
    return float_resets, GUESS_SIGMA, KERNEL_TYPE, current_trigger + 1


# ---- Download results logic

@callback(
    Output('export-intervals-filename', 'value'),
    Input('upload-intervals', 'filename'),
    Input('upload-lc', 'filename'),
    prevent_initial_call=True,
)
def update_intervals_output_filename(intervals_filename, lc_filename):
    """Default interval export stem from intervals upload, else light curve basename."""
    intervals_stem = export_stem_from_upload_filename(intervals_filename)
    if intervals_stem:
        return intervals_stem
    return export_stem_from_upload_filename(lc_filename)


@callback(
    Output("export-lc-filename", "value"),
    Input("upload-lc", "filename"),
    prevent_initial_call=True,
)
def update_lc_export_default_filename(filename):
    """Default light curve export stem from the uploaded file name."""
    if filename:
        base = filename.rsplit(".", 1)[0]
        return f"{base}_lc"
    return "gp_lightcurve"


@callback(
    Output("btn-download-lc", "disabled"),
    Input("store-lc-data", "data"),
)
def gate_lc_export_button(lc_json_string):
    """Light curve export is available whenever prep data is loaded."""
    return not lc_json_string


@callback(
    Output("download-lc-file", "data"),
    Output("gp-lc-export-feedback", "children"),
    Input("btn-download-lc", "n_clicks"),
    State("store-lc-data", "data"),
    State("gp-lc-export-format", "value"),
    State("export-lc-filename", "value"),
    State("upload-lc", "filename"),
    State("store-gp-prep-working-window", "data"),
    State("input-period", "value"),
    State("input-epoch", "value"),
    prevent_initial_call=True,
)
def download_gp_prep_lightcurve(
    n_clicks,
    lc_json_string,
    table_format,
    filename_stem,
    upload_filename,
    working_window_store,
    period,
    epoch,
):
    """Exports the stored prep light curve (including manual detrend) via lc_bridge."""
    if not n_clicks or not lc_json_string:
        raise PreventUpdate
    fmt = table_format or DEFAULT_EXPORT_FORMAT
    try:
        export_json = transport_json_for_prep_export(
            lc_json_string,
            working_window_store,
        )
        lcd = curvedash_from_transport_json(
            export_json,
            source_name=upload_filename,
        )
        apply_prep_fold_ephemeris(
            lcd,
            period,
            epoch,
            display_epoch=jd0,
        )
        file_bytes = export_curvedash(lcd, fmt)
        outfile = gp_lc_export_download_name(filename_stem, fmt)
        return dcc.send_bytes(file_bytes, outfile), None
    except PipeException as exc:
        logger.warning("GP light curve export failed: %s", exc)
        return no_update, dbc.Alert(
            str(exc),
            color="warning",
            className="py-2 small mb-0",
        )
    except Exception as exc:
        logger.exception("GP light curve export failed")
        return no_update, dbc.Alert(
            f"Could not export light curve: {exc}",
            color="danger",
            className="py-2 small mb-0",
        )


# Build GP output filename
@callback(
    Output('export-filename', 'value'),
    Input('upload-lc', 'filename'),
    prevent_initial_call=True
)
def update_default_filename(filename):
    if filename:
        base = filename.rsplit('.', 1)[0]
        return f"{base}_extrema"
    return "results_extrema"


@callback(
    # region unfold me
    Output("download-results", "data"),
    Input("save-file-btn", "n_clicks"),
    State("export-filename", "value"),
    State('store-results-data', 'data'),
    State('extrema-mode', 'value'),
    State("gp-extended-export", "value"),
    prevent_initial_call=True
    # endregion
)
def trigger_download(n_clicks, filename_input, store, extrema_mode, extended_export):
    logger.debug(
        "GP download: filename=%s extended=%s",
        filename_input,
        extended_export,
    )
    if not n_clicks or not store:
        return no_update

    rows = store.get("rows") or []
    include = store.get("include") or []
    if len(include) != len(rows):
        return no_update

    if extended_export:
        run_id = store.get("run_id")
        if not run_id:
            return no_update
        try:
            entries = load_gp_review_run(run_id)
        except KeyError as exc:
            raise PreventUpdate from exc
        if len(entries) != len(include):
            return no_update
        bundle_folder = gp_extrema_export_stem(filename_input)
        zip_bytes = build_extended_export_zip(
            entries,
            include,
            bundle_folder=bundle_folder,
            display_epoch=jd0,
            extrema_mode=extrema_mode or "max",
        )
        outfile = gp_extended_extrema_download_name(filename_input)
        return dcc.send_bytes(zip_bytes, outfile)

    body = format_compact_extrema_dat(
        rows,
        include,
        extrema_mode=extrema_mode or "max",
    )
    outfile = gp_compact_extrema_download_name(filename_input)
    return dcc.send_string(body, outfile)


@callback(
    Output('graphs-container', 'children', allow_duplicate=True),
    Output('store-results-data', 'data', allow_duplicate=True),
    Output('gp-review-page-label', 'children', allow_duplicate=True),
    Input('gp-review-prev', 'n_clicks'),
    Input('gp-review-next', 'n_clicks'),
    State('store-results-data', 'data'),
    prevent_initial_call=True,
)
def change_gp_review_page(prev_clicks, next_clicks, store):
    """Shows the previous or next page of fit cards in Review and Export."""
    if not store or not store.get("run_id"):
        raise PreventUpdate

    triggered = callback_context.triggered_id
    if triggered not in ("gp-review-prev", "gp-review-next"):
        raise PreventUpdate

    page = int(store.get("page", 0))
    total = len(store.get("include") or [])
    if total == 0:
        raise PreventUpdate

    from skvo_veb.utils.gp.config import GP_REVIEW_PAGE_SIZE
    import math

    total_pages = max(1, math.ceil(total / GP_REVIEW_PAGE_SIZE))
    if triggered == "gp-review-prev":
        page = max(0, page - 1)
    else:
        page = min(total_pages - 1, page + 1)

    entries = load_gp_review_run(store["run_id"])
    children = render_review_page(entries, page, store["include"])
    label = review_page_label(page, total)
    new_store = {**store, "page": page}
    return children, new_store, label


@callback(
    Output('store-results-data', 'data', allow_duplicate=True),
    Output('graphs-container', 'children', allow_duplicate=True),
    Input('select-all-btn', 'n_clicks'),
    Input('unselect-all-btn', 'n_clicks'),
    State('store-results-data', 'data'),
    prevent_initial_call=True,
)
def gp_review_select_all(select_clicks, unselect_clicks, store):
    """Toggles include-in-export flags for every fit, then refreshes the current page."""
    if not store or not store.get("run_id"):
        raise PreventUpdate

    triggered = callback_context.triggered_id
    rows = store.get("rows") or []
    n = len(rows)
    if n == 0:
        raise PreventUpdate

    if triggered == "unselect-all-btn":
        include = [False] * n
    else:
        include = [not row.get("is_fail") for row in rows]

    page = int(store.get("page", 0))
    entries = load_gp_review_run(store["run_id"])
    children = render_review_page(entries, page, include)
    return {**store, "include": include}, children


@callback(
    Output('store-results-data', 'data', allow_duplicate=True),
    Input({'type': 'fit-selector', 'index': ALL}, 'value'),
    State({'type': 'fit-selector', 'index': ALL}, 'id'),
    State('store-results-data', 'data'),
    prevent_initial_call=True,
)
def gp_review_sync_include_checkbox(values, ids, store):
    """Persists include-in-export toggles for fits on the visible review page."""
    if not store or not ids:
        raise PreventUpdate

    include = list(store.get("include") or [])
    for val, comp_id in zip(values, ids):
        idx = comp_id["index"]
        if 0 <= idx < len(include):
            include[idx] = bool(val)
    return {**store, "include": include}


# -------------- Graphs with fits ---- two containers: Working and Final -----

@callback(
    # region unfold me
    Output('final-review-container', 'style'),
    Output('live-graphs-container', 'style'),
    Output('gp-live-progress-label', 'style'),
    Input('finished-signal', 'children'),  # this is a swithch-modes-trigger
    prevent_initial_call=True
    # endregion
)
def switch_modes(signal):
    logger.debug("switch_modes signal=%s", signal)
    # helper callback to toggle the visibility working and review modes (once run_gp finishes).
    if signal in ("FINISHED", "FINISHED_STOPPED"):
        return {'display': 'block'}, {'display': 'none'}, {'display': 'none'}
    return {'display': 'none'}, {'display': 'flex'}, {'display': 'block'}


# ================= MAVKA callbacks ===================

@callback(
    Input("mavka-stop-btn", "n_clicks"),
    prevent_initial_call=True,
)
def mavka_request_batch_stop(_n_clicks):
    """Cooperative stop: finish the current fit, then exit the MAVKA batch loop."""
    request_mavka_batch_stop()


@callback(
    Output("mavka-header-area", "children"),
    Input("mavka-run-btn", "n_clicks"),
    Input("mavka-stop-btn", "n_clicks"),
    Input("mavka-finished-signal", "children"),
    prevent_initial_call=True,
)
def update_mavka_status_ui(run_clicks, stop_clicks, signal_status):
    """Updates the MAVKA working-area header badge for run, stop, and finish."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "mavka-run-btn" and run_clicks > 0:
        return html.Div(
            [
                html.H6("MAVKA processing view", className="gp-card-title"),
                dbc.Badge(
                    [
                        html.I(className="bi bi-hourglass-split me-2"),
                        "RUNNING - Modelling...",
                    ],
                    color="warning",
                    className="ms-2",
                ),
            ],
            className="d-flex align-items-center mb-3",
        )

    if trigger_id == "mavka-stop-btn" and stop_clicks > 0:
        return html.Div(
            [
                html.H6("MAVKA processing view", className="gp-card-title"),
                dbc.Badge(
                    [
                        html.I(className="bi bi-pause-circle me-2"),
                        "STOPPING - finishing current fit…",
                    ],
                    color="warning",
                    className="ms-2",
                ),
            ],
            className="d-flex align-items-center mb-3",
        )

    if trigger_id == "mavka-finished-signal" and signal_status == "WAITING":
        return html.Div(
            [
                html.H6("MAVKA processing view", className="gp-card-title"),
                dbc.Badge(
                    [
                        html.I(className="bi bi-gear-wide-connected me-2"),
                        "GENERATING PLOTS...",
                    ],
                    color="info",
                    className="ms-2",
                ),
            ],
            className="d-flex align-items-center mb-3",
        )

    if trigger_id == "mavka-finished-signal" and signal_status in (
        "FINISHED",
        "FINISHED_STOPPED",
    ):
        stopped = signal_status == "FINISHED_STOPPED"
        badge_text = (
            "STOPPED - review completed fits" if stopped else "FINISHED"
        )
        badge_color = "warning" if stopped else "success"
        return html.Div(
            [
                html.H6("Results: photometry vs JD", className="gp-card-title"),
                dbc.Badge(
                    [
                        html.I(className="bi bi-check-all me-2"),
                        badge_text,
                    ],
                    color=badge_color,
                    className="ms-2",
                ),
            ],
            className="d-flex align-items-center mb-3",
        )

    return dash.no_update


@callback(
    Output("mavka-graphs-container", "children", allow_duplicate=True),
    Output("mavka-finished-signal", "children", allow_duplicate=True),
    Output("store-mavka-results-data", "data"),
    Output("mavka-review-page-label", "children"),
    Output("oc-export-filename", "value", allow_duplicate=True),
    Input("mavka-run-btn", "n_clicks"),
    State("store-lc-data", "data"),
    State("store-intervals-data", "data"),
    State("view-mode-radio", "value"),
    State("mavka-extrema-mode", "value"),
    State("mavka-method", "value"),
    State("upload-lc", "filename"),
    State("oc-tom-source", "value"),
    background=True,
    running=[
        (Output("mavka-run-btn", "disabled"), True, False),
        (Output("mavka-stop-btn", "disabled"), False, True),
    ],
    progress=[
        Output("mavka-live-progress-label", "children"),
        *_MAVKA_LIVE_SLOT_PROGRESS_OUTPUTS,
        Output("mavka-finished-signal", "children"),
    ],
    prevent_initial_call=True,
)
def run_mavka(
    set_progress,
    n_clicks,
    lc_json_string,
    intervals,
    view_mode,
    extrema_mode,
    method,
    lc_filename,
    oc_source,
):
    """Fits one MAVKA method on every interval; sparse and failed windows become cards."""

    def _push_live(stored_entries: list, total_work: int) -> None:
        done = len(stored_entries)
        visible_page = mavka_live_visible_page_for_done_count(done)
        slots = build_mavka_live_page_slot_children(stored_entries, visible_page)
        label = mavka_live_progress_label(done, total_work)
        set_progress((label, *slots, "WAITING"))

    empty_slots = build_mavka_live_page_slot_children([], 0)
    set_progress((mavka_live_progress_label(0, 0), *empty_slots, "WAITING"))
    clear_mavka_batch_stop()
    logger.debug("run_mavka started")

    if extrema_mode != "min":
        error_alert = dbc.Alert(MAXIMA_NOT_AVAILABLE, color="warning")
        return error_alert, "FINISHED", None, "", no_update

    if not method:
        error_alert = dbc.Alert(
            "Select an approximation method.", color="warning", className="py-2 small mb-0"
        )
        return error_alert, "FINISHED", None, "", no_update

    if not lc_json_string or not intervals:
        error_alert = dbc.Alert(
            "Please upload both lightcurve and intervals files.", color="warning"
        )
        return error_alert, "FINISHED", None, "", no_update

    view_mode = view_mode or "mag"
    try:
        lc = unpack_json_for_gp_plot(lc_json_string, view_mode=view_mode)
    except Exception as exc:
        logger.exception("MAVKA light curve unpack failed")
        error_alert = dbc.Alert(str(exc), color="danger")
        return error_alert, "FINISHED", None, "", no_update

    invert_y = bool(lc.get("is_mag"))
    y_label = lc.get("y_label") or ("Magnitude" if invert_y else "Flux")
    times_jd = np.asarray(lc["x"], dtype=float)
    photometry = np.asarray(lc["y"], dtype=float)

    total_work = len(intervals)
    _push_live([], total_work)

    stored_entries: list[dict] = []
    stopped_early = False

    for piece in intervals:
        if mavka_batch_stop_requested():
            stopped_early = True
            logger.info(
                "MAVKA batch stopped before interval (%s done)", len(stored_entries)
            )
            break

        jd_min, jd_max = piece[0], piece[1]
        t_obs, y_obs = slice_interval_photometry(times_jd, photometry, jd_min, jd_max)

        fig = None
        try:
            fit = mavka_fit_interval(
                method, t_obs, y_obs, extrema_mode=extrema_mode
            )
            res_entry = mavka_review_entry_from_fit(fit, jd_min, jd_max)
        except Exception as exc:
            logger.warning("MAVKA interval %s–%s failed: %s", jd_min, jd_max, exc)
            res_entry = {
                "jd_min": jd_min,
                "jd_max": jd_max,
                "is_fail": True,
                "error": str(exc),
                "badge_specs": [{"label": "FAILED", "color": "danger"}],
                "method": method,
            }
        else:
            if not res_entry["is_fail"]:
                try:
                    fig = figure_from_mavka_result(
                        t_obs,
                        y_obs,
                        fit,
                        display_epoch=jd0,
                        invert_y=invert_y,
                        y_label=y_label,
                    )
                except Exception as exc:
                    logger.warning(
                        "MAVKA plot failed for interval %s–%s: %s",
                        jd_min,
                        jd_max,
                        exc,
                    )
                    res_entry["is_fail"] = True
                    res_entry["error"] = (
                        f"Fit succeeded (TOM={fit.t_ext}) but plot failed: {exc}"
                    )
                    res_entry["badge_specs"] = [
                        {"label": "FAILED", "color": "danger"}
                    ]

        figure_json = None
        if not res_entry["is_fail"]:
            if fig is None:
                res_entry["is_fail"] = True
                res_entry["error"] = "Missing plot for a successful MAVKA fit"
                res_entry["badge_specs"] = [{"label": "FAILED", "color": "danger"}]
            else:
                figure_json = fig.to_plotly_json()
        stored_entries.append(
            serialise_mavka_review_entry(res_entry, figure_json=figure_json)
        )
        _push_live(stored_entries, total_work)

        if mavka_batch_stop_requested():
            stopped_early = True
            logger.info("MAVKA batch stopped after %s fits", len(stored_entries))
            break

    if not stored_entries:
        msg = (
            "No fits completed before stop."
            if stopped_early
            else "No fits to review."
        )
        return (
            dbc.Alert(msg, color="warning"),
            "FINISHED_STOPPED" if stopped_early else "FINISHED",
            None,
            "",
            no_update,
        )

    run_id = uuid.uuid4().hex
    save_mavka_review_run(run_id, stored_entries)
    store_payload = build_mavka_review_store_payload(
        run_id,
        stored_entries,
        stopped_early=stopped_early,
        source_filename=lc_filename,
    )
    page_children = render_mavka_review_page(
        stored_entries, 0, store_payload["include"]
    )
    page_label = mavka_review_page_label(0, len(stored_entries))
    finish_signal = "FINISHED_STOPPED" if stopped_early else "FINISHED"
    oc_name = no_update
    if oc_source == "mavka":
        oc_name = oc_default_export_stem(lc_filename)
    return page_children, finish_signal, store_payload, page_label, oc_name


@callback(
    Output("mavka-export-filename", "value"),
    Input("upload-lc", "filename"),
    prevent_initial_call=True,
)
def update_mavka_default_filename(filename):
    """Default MAVKA export stem from the uploaded light curve name."""
    if filename:
        base = filename.rsplit(".", 1)[0]
        return f"{base}_mavka"
    return "results_mavka"


@callback(
    Output("mavka-download-results", "data"),
    Input("mavka-save-file-btn", "n_clicks"),
    State("mavka-export-filename", "value"),
    State("store-mavka-results-data", "data"),
    State("mavka-extrema-mode", "value"),
    State("mavka-extended-export", "value"),
    State("input-period", "value"),
    State("input-epoch", "value"),
    prevent_initial_call=True,
)
def trigger_mavka_download(
    n_clicks,
    filename_input,
    store,
    extrema_mode,
    extended_export,
    period,
    epoch,
):
    """Downloads compact selected TOMs or an extended ZIP of the MAVKA run."""
    logger.debug(
        "MAVKA download: filename=%s extended=%s",
        filename_input,
        extended_export,
    )
    if not n_clicks or not store:
        return no_update

    rows = store.get("rows") or []
    include = store.get("include") or []
    if len(include) != len(rows):
        return no_update

    if extended_export:
        run_id = store.get("run_id")
        if not run_id:
            return no_update
        try:
            entries = load_mavka_review_run(run_id)
        except KeyError as exc:
            raise PreventUpdate from exc
        if len(entries) != len(include):
            return no_update
        bundle_folder = mavka_extrema_export_stem(filename_input)
        zip_bytes = build_mavka_extended_export_zip(
            entries,
            include,
            bundle_folder=bundle_folder,
            display_epoch=jd0,
            extrema_mode=extrema_mode or "min",
            period=None if period in (None, "") else str(period),
            epoch=None if epoch in (None, "") else str(epoch),
        )
        outfile = mavka_extended_extrema_download_name(filename_input)
        return dcc.send_bytes(zip_bytes, outfile)

    body = format_mavka_compact_extrema_dat(
        rows,
        include,
        extrema_mode=extrema_mode or "min",
        period=None if period in (None, "") else str(period),
        epoch=None if epoch in (None, "") else str(epoch),
    )
    outfile = mavka_compact_extrema_download_name(filename_input)
    return dcc.send_string(body, outfile)


@callback(
    Output("mavka-graphs-container", "children", allow_duplicate=True),
    Output("store-mavka-results-data", "data", allow_duplicate=True),
    Output("mavka-review-page-label", "children", allow_duplicate=True),
    Input("mavka-review-prev", "n_clicks"),
    Input("mavka-review-next", "n_clicks"),
    State("store-mavka-results-data", "data"),
    prevent_initial_call=True,
)
def change_mavka_review_page(prev_clicks, next_clicks, store):
    """Shows the previous or next page of MAVKA fit cards in Review and Export."""
    if not store or not store.get("run_id"):
        raise PreventUpdate

    triggered = callback_context.triggered_id
    if triggered not in ("mavka-review-prev", "mavka-review-next"):
        raise PreventUpdate

    page = int(store.get("page", 0))
    total = len(store.get("include") or [])
    if total == 0:
        raise PreventUpdate

    import math

    total_pages = max(1, math.ceil(total / MAVKA_REVIEW_PAGE_SIZE))
    if triggered == "mavka-review-prev":
        page = max(0, page - 1)
    else:
        page = min(total_pages - 1, page + 1)

    entries = load_mavka_review_run(store["run_id"])
    children = render_mavka_review_page(entries, page, store["include"])
    label = mavka_review_page_label(page, total)
    new_store = {**store, "page": page}
    return children, new_store, label


@callback(
    Output("store-mavka-results-data", "data", allow_duplicate=True),
    Output("mavka-graphs-container", "children", allow_duplicate=True),
    Input("mavka-select-all-btn", "n_clicks"),
    Input("mavka-unselect-all-btn", "n_clicks"),
    State("store-mavka-results-data", "data"),
    prevent_initial_call=True,
)
def mavka_review_select_all(select_clicks, unselect_clicks, store):
    """Toggles include-in-export flags for every MAVKA fit, then refreshes the page."""
    if not store or not store.get("run_id"):
        raise PreventUpdate

    triggered = callback_context.triggered_id
    rows = store.get("rows") or []
    n = len(rows)
    if n == 0:
        raise PreventUpdate

    if triggered == "mavka-unselect-all-btn":
        include = [False] * n
    else:
        include = [not row.get("is_fail") for row in rows]

    page = int(store.get("page", 0))
    entries = load_mavka_review_run(store["run_id"])
    children = render_mavka_review_page(entries, page, include)
    return {**store, "include": include}, children


@callback(
    Output("store-mavka-results-data", "data", allow_duplicate=True),
    Input({"type": "mavka-fit-selector", "index": ALL}, "value"),
    State({"type": "mavka-fit-selector", "index": ALL}, "id"),
    State("store-mavka-results-data", "data"),
    prevent_initial_call=True,
)
def mavka_review_sync_include_checkbox(values, ids, store):
    """Persists include-in-export toggles for MAVKA fits on the visible review page."""
    if not store or not ids:
        raise PreventUpdate

    include = list(store.get("include") or [])
    for val, comp_id in zip(values, ids):
        idx = comp_id["index"]
        if 0 <= idx < len(include):
            include[idx] = bool(val)
    return {**store, "include": include}


@callback(
    Output("mavka-final-review-container", "style"),
    Output("mavka-live-graphs-container", "style"),
    Output("mavka-live-progress-label", "style"),
    Input("mavka-finished-signal", "children"),
    prevent_initial_call=True,
)
def switch_mavka_modes(signal):
    """Toggles MAVKA live grid versus review once the batch finishes or stops."""
    logger.debug("switch_mavka_modes signal=%s", signal)
    if signal in ("FINISHED", "FINISHED_STOPPED"):
        return {"display": "block"}, {"display": "none"}, {"display": "none"}
    return {"display": "none"}, {"display": "flex"}, {"display": "block"}


def _oc_parse_delta_e(value) -> int:
    """Parses a cycle-shift ΔE from the sidebar number input.

    Args:
        value: Raw ``oc-shift-delta-e`` value.

    Returns:
        int: Integer cycle offset.

    Raises:
        ValueError: If the value is missing or not an integer.
    """
    if value is None or value == "":
        raise ValueError("Set ΔE to an integer (for example +1 or −1).")
    as_float = float(value)
    as_int = int(as_float)
    if as_int != as_float:
        raise ValueError("ΔE must be an integer.")
    return as_int


@callback(
    Output("oc-input-period", "value"),
    Output("oc-input-epoch", "value"),
    Input("oc-take-from-lc-btn", "n_clicks"),
    State("input-period", "value"),
    State("input-epoch", "value"),
    prevent_initial_call=True,
)
def oc_take_from_lightcurve(n_clicks, period, epoch):
    """Copies accordion 1 P and Epoch into the O-C fields, overwriting them."""
    if not n_clicks:
        raise PreventUpdate
    return period, epoch


@callback(
    Output("oc-export-filename", "value"),
    Input("oc-tom-source", "value"),
    State("store-results-data", "data"),
    State("store-mavka-results-data", "data"),
    State("store-oc-uploaded-toms", "data"),
    prevent_initial_call=True,
)
def update_oc_export_filename(source, gp_store, mavka_store, uploaded):
    """Sets the O-C export stem from the ToM source that is currently selected.

    Args:
        source: Radio value ``gp``, ``mavka``, or ``upload``.
        gp_store: GP review store (filename stamped at GP run time).
        mavka_store: MAVKA review store (filename stamped at MAVKA run time).
        uploaded: Compact ToM upload payload.

    Returns:
        str: Default ``{stem}_oc`` (or ``results_oc``).
    """
    return oc_default_export_stem(
        oc_source_filename(
            source or "gp",
            gp_store=gp_store,
            mavka_store=mavka_store,
            uploaded=uploaded,
        )
    )


@callback(
    Output("store-oc-uploaded-toms", "data"),
    Output("upload-oc-toms-text", "children"),
    Output({"type": "gp-upload-detail", "index": "oc-toms"}, "children"),
    Output("oc-tom-source", "value"),
    Output("oc-export-filename", "value", allow_duplicate=True),
    Input("upload-oc-toms", "contents"),
    State("upload-oc-toms", "filename"),
    prevent_initial_call=True,
)
def upload_oc_toms(contents, filename):
    """Parses a compact GP/MAVKA ToM file and selects the Upload source."""
    if contents is None:
        raise PreventUpdate
    try:
        _content_type, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
        text = decoded.decode("utf-8")
        records = parse_compact_tom_dat(text)
        logger.info("O-C timings upload: %s (%s ToMs)", filename, len(records))
        return (
            {"filename": filename, "records": records},
            _gp_upload_status(filename or "timings.dat", tone="ok"),
            None,
            "upload",
            oc_default_export_stem(filename),
        )
    except Exception as exc:
        logger.error("O-C timings upload failed: %s", filename)
        logger.error(traceback.format_exc())
        return (
            no_update,
            _gp_upload_status(filename or "timings.dat", tone="error"),
            _gp_upload_failure_detail(
                "Timings upload failed",
                str(exc),
            ),
            no_update,
            no_update,
        )


@callback(
    Output("store-oc-cycle-shifts", "data"),
    Output("oc-sidebar-feedback", "children"),
    Input("oc-shift-add-btn", "n_clicks"),
    State("oc-shift-at-time", "value"),
    State("oc-shift-delta-e", "value"),
    State("store-oc-cycle-shifts", "data"),
    prevent_initial_call=True,
)
def oc_add_cycle_shift(n_clicks, at_time, delta_e, rows):
    """Appends one cycle correction from the sidebar fields."""
    if not n_clicks:
        raise PreventUpdate
    try:
        if at_time is None or at_time == "":
            raise ValueError("Set the at-time (display MJD).")
        at_mjd = float(at_time)
        if not np.isfinite(at_mjd):
            raise ValueError("At-time must be a finite MJD.")
        delta = _oc_parse_delta_e(delta_e)
    except (TypeError, ValueError) as exc:
        return no_update, dbc.Alert(str(exc), color="warning", className="py-2 small mb-0")
    stored = list(rows or [])
    stored.append({"at_mjd": at_mjd, "delta_e": delta})
    return stored, None


@callback(
    Output("store-oc-cycle-shifts", "data", allow_duplicate=True),
    Input({"type": "oc-shift-remove", "index": ALL}, "n_clicks"),
    State("store-oc-cycle-shifts", "data"),
    prevent_initial_call=True,
)
def oc_remove_cycle_shift(n_clicks, rows):
    """Removes one cycle correction from the stored list."""
    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict) or not rows:
        raise PreventUpdate
    if not n_clicks or not any(n_clicks):
        raise PreventUpdate
    index = triggered.get("index")
    stored = list(rows)
    if not isinstance(index, int) or index < 0 or index >= len(stored):
        raise PreventUpdate
    stored.pop(index)
    return stored


@callback(
    Output("oc-cycle-shift-list", "children"),
    Input("store-oc-cycle-shifts", "data"),
)
def oc_render_cycle_shift_list(rows):
    """Redraws the cycle-correction list from the store."""
    return _render_oc_shift_list(rows)


@callback(
    Output("oc-graph", "figure"),
    Output("store-oc-plot-data", "data"),
    Output("oc-plot-feedback", "children"),
    Input("oc-plot-btn", "n_clicks"),
    State("oc-tom-source", "value"),
    State("oc-input-period", "value"),
    State("oc-input-epoch", "value"),
    State("store-oc-cycle-shifts", "data"),
    State("store-results-data", "data"),
    State("store-mavka-results-data", "data"),
    State("store-oc-uploaded-toms", "data"),
    prevent_initial_call=True,
)
def oc_plot(
    n_clicks,
    source,
    period,
    epoch,
    shift_rows,
    gp_store,
    mavka_store,
    uploaded,
):
    """Computes Step 1 O-C for the selected ToM source and draws the figure."""
    if not n_clicks:
        raise PreventUpdate
    try:
        t0_jd = absolute_jd_from_display_epoch(epoch, jd0)
        if t0_jd is None:
            raise ValueError("Set the O-C epoch (display MJD).")
        if period is None or period == "":
            raise ValueError("Set the O-C period P (days).")
        p0 = float(period)
        source_key = source or "gp"
        if source_key == "gp":
            records = toms_from_review_store(gp_store)
        elif source_key == "mavka":
            records = toms_from_review_store(mavka_store)
        elif source_key == "upload":
            records = uploaded_toms_from_store(uploaded)
        else:
            raise ValueError(f"Unknown ToM source: {source_key!r}.")
        shifts = cycle_shifts_from_store(shift_rows, display_epoch=jd0)
        payload = compute_step1_oc(
            records,
            t0_jd=t0_jd,
            p0=p0,
            cycle_shifts=shifts or None,
            source=source_key,
        )
        figure = _build_oc_figure(payload)
        return figure, payload, None
    except Exception as exc:
        logger.error("O-C plot failed: %s", exc)
        return (
            no_update,
            no_update,
            dbc.Alert(str(exc), color="warning", className="py-2 small mb-0"),
        )


@callback(
    Output("oc-download-results", "data"),
    Output("oc-plot-feedback", "children", allow_duplicate=True),
    Input("oc-download-btn", "n_clicks"),
    State("oc-export-filename", "value"),
    State("store-oc-plot-data", "data"),
    prevent_initial_call=True,
)
def oc_download(n_clicks, filename_input, payload):
    """Downloads the last plotted O-C table as an xmgrace ``.dat``."""
    if not n_clicks:
        raise PreventUpdate
    if not payload:
        return no_update, dbc.Alert(
            "Plot O-C first, then download.",
            color="warning",
            className="py-2 small mb-0",
        )
    try:
        body = format_oc_dat(payload)
        outfile = oc_export_download_name(filename_input)
        return dcc.send_string(body, outfile), None
    except Exception as exc:
        logger.error("O-C export failed: %s", exc)
        return no_update, dbc.Alert(
            str(exc), color="danger", className="py-2 small mb-0"
        )
