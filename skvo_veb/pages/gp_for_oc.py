# --- Documentation Content ---
DOC_MARKDOWN = """

# Lightcurve Extrema Modeller

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
The model is controlled by a few parameters that define how “flexible” or “smooth” the curve is, 
and how much it trusts the data.

Internally, we use a kernel of the form:

`ConstantKernel (Amplitude) × [Matern(ν = 2.5) OR RBF]`

You do not need to work with this directly — the parameters below are the practical controls.

---

## Parameters

**GUESS_SIGMA**

If enabled, the model ignores provided uncertainties and estimates noise from the data scatter 
(MAD). Use this if errors are missing or clearly unreliable.

---

**NOISE_SCALE_DIVISOR**

A handy "trust factor" for measurement noise. This empirical divisor 
is applied to both guessed noise or provided observation errors.

- *Higher (>1.0)*: You trust the data more than the errors suggest. 
  Results in a more sensitive (wiggly) fit;
- *Lower (<1.0)*: You suspect the errors are underestimated. Results in a smoother fit.

Use this to tweak" the fit if the model is ignoring real structure or, conversely, over-fitting noise.

---

**LENGTH_SCALE (MIN / INIT / MAX)**

Controls the smoothness in time (x-axis).

- *INIT*: initial guess (≈ half of a typical feature width)  
- *MIN*: prevents the model from diving into individual noise spikes 
- *MAX*: prevents the model from becoming so stiff it misses the peak.

Practical tuning:
- Too wiggly --> increase values  
- Too smooth --> decrease values  

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

We hope, this approach naturally accounts for noise, sampling, and shape of the feature.

---

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
We draw three hundreds of these "valid" realisations from the model. 
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

import dash
# import diskcache
from dash import dcc, html, Input, Output, State, ALL, callback_context, callback, no_update
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

from skvo_veb.utils.lc_bridge import get_intervals_from_phase, phase_vrect_bounds_for_jd_interval

from skvo_veb.utils.gp import (
    GUESS_SIGMA, LEN_MIN,
    load_intervals, gp_peak_pipeline,
    NOISE_SCALE_DIVISOR,
    KERNEL_TYPE, EXTREMA_MODE, guess_length_scale,
    AMPLITUDE_INIT, AMPLITUDE_MIN, AMPLITUDE_MAX,
    DEFAULT_FLOAT_PARAMS,
    pack_uploaded_lightcurve,
    get_gp_flux_fragment,
    figure_from_gp_result,
    format_intervals_download,
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
from skvo_veb.utils.gp.config import GP_LIVE_PAGE_SIZE
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
from skvo_veb.utils.gp.plot_data import unpack_json_for_gp_plot, folding_metadata_from_transport
from skvo_veb.utils.lc_config import (
    DEFAULT_EPOCH_JD,
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
from skvo_veb.utils.lc_interaction import plot_x_to_jd

jd0 = DEFAULT_EPOCH_JD

logger = logging.getLogger(__name__)

_LIVE_SLOT_PROGRESS_OUTPUTS = [
    Output({"type": "gp-live-slot", "index": i}, "children")
    for i in range(GP_LIVE_PAGE_SIZE)
]
# Gaia Eclipsing Binary Catalog - IGEBC
dash.register_page(__name__, name='GP',
                   order=7,
                   title='Gaussian Process for O-C',
                   description='Determination of individual maxima timings in a light curve '
                               'using Gaussian Process Regression',
                   in_navbar=True,
                   path='/gp')

params_float = DEFAULT_FLOAT_PARAMS
# # Initialize diskcache for background callbacks
# cache = diskcache.Cache("./cache")
# background_callback_manager = DiskcacheManager(cache)


def _gp_click_help(help_id: str, title: str, body, *, placement: str = "bottom"):
    """Builds a click-triggered ``?`` control and its popover (GP page).

    Args:
        help_id (str): Short slug for unique component ids.
        title (str): Popover header text.
        body: Popover body as a string or sequence of Dash components.
        placement (str): Bootstrap popover placement.

    Returns:
        tuple: ``(help_button, popover)`` components.
    """
    btn_id = f"gp_page_help_{help_id}_btn"
    pop_id = f"gp_page_help_{help_id}_popover"
    if not isinstance(body, (list, tuple)):
        body = [html.P(body, className="mb-0")]
    button = html.Strong(
        "?",
        id=btn_id,
        role="button",
        tabIndex=0,
        className="lc-discovery-help-btn",
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


def _gp_upload_error_ui(
    filename: str,
    help_slug: str,
    popover_title: str,
    popover_body: str,
    *,
    icon_class: str = "bi-exclamation-triangle-fill",
) -> html.Div:
    """Upload error row with click ``?`` help instead of a hover tooltip.

    Args:
        filename (str): Uploaded file name shown in the row.
        help_slug (str): Unique slug for ``_gp_click_help`` ids.
        popover_title (str): Popover header.
        popover_body (str): Popover body (former tooltip text).
        icon_class (str): Bootstrap icon class suffix.

    Returns:
        html.Div: Error message and help control.
    """
    help_btn, help_pop = _gp_click_help(
        help_slug, popover_title, popover_body, placement="right"
    )
    return html.Div(
        [
            html.I(className=f"bi {icon_class} me-2", style={"color": "#dc3545"}),
            html.Span(
                [html.B("Error: "), filename],
                style={"color": "#dc3545", "fontSize": "0.85rem"},
            ),
            html.Div(help_btn, className="lc-discovery-field-help ms-1"),
            help_pop,
        ],
        className="d-flex align-items-center flex-wrap",
    )


(
    _add_interval_help_btn,
    _add_interval_help_pop,
) = _gp_click_help(
    "add_interval",
    "Add Interval",
    "Register selected JD interval as a target for extremum analysis",
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
    _noise_divisor_help_btn,
    _noise_divisor_help_pop,
) = _gp_click_help(
    "noise_divisor",
    "Noise divisor",
    "Empirical noise correction (↑ wiggly, ↓ smooth)"
    "Allows not quite fair to tweak uncertainties",
)
(
    _kernel_type_help_btn,
    _kernel_type_help_pop,
) = _gp_click_help(
    "kernel_type",
    "Kernel Smoothness Type",
    "Matern (nu=2.5): twice differentiable, physically realistic"
    "RBF (Radial Basis Function): infinitely differentiable, extremely smooth)",
)
(
    _length_scale_help_btn,
    _length_scale_help_pop,
) = _gp_click_help(
    "length_scale",
    "Length Scale (Min / Init / Max)",
    "GP smoothness (in days, as x-axis). Increase if fit is too wiggly, "
    "decrease if it misses structure.",
)
(
    _amplitude_help_btn,
    _amplitude_help_pop,
) = _gp_click_help(
    "signal_amplitude",
    "Signal Amplitude (Min / Init / Max)",
    "GP vertical scale (y-axis). Sets the 'headroom' for peak height. "
    "Since flux is normalised to 1.0, values between 0.1 and 10.0 are usually safe. "
    "Best left alone unless the model is failing to reach the top of your peak!",
)


def LegendItem(color, label, mode='line'):
    # mode can be: 'line', 'dashed', or 'circle'
    # Base style for the visual indicator
    style = {
        "display": "inline-block",
        "margin-right": "10px",
        "vertical-align": "middle",
    }

    if mode == 'circle':
        style.update({
            "background-color": color,
            "width": "10px",
            "height": "10px",
            "border-radius": "50%"
        })
    elif mode == 'line':
        style.update({
            "background-color": color,
            "width": "20px",
            "height": "3px",
            "border-radius": "0px"
        })
    elif mode == 'dashed':
        # For dashed, we use a border instead of background
        style.update({
            "width": "20px",
            "height": "0px",
            "border-top": f"3px dashed {color}",
            "background-color": "transparent"
        })

    return html.Div([
        html.Span(style=style),
        html.Span(label, style={"font-size": "0.85rem", "vertical-align": "middle"})
    ], style={"margin-bottom": "4px", "display": "flex", "align-items": "center"})


# ==================== Lightcurve GUI ==================

sidebar_lc = html.Div([
    # 1. PHASE FOLDING CONTROLS
    html.Label("Phase Folding", className="fw-bold", id="phase-folding-label"),
    dbc.Checklist(
        options=[{"label": "Fold", "value": 1}],  # type: ignore
        value=[],
        id="folding-switch",
        switch=True,
        className="mb-2"
    ),
    dbc.InputGroup([
        dbc.InputGroupText("P"),
        dbc.Input(id="input-period", type="number", placeholder="Period (days)"),
    ], size="sm", className="mb-1"),
    dbc.InputGroup([
        dbc.InputGroupText(f"Epoch-{DEFAULT_EPOCH_JD}"),
        dbc.Input(id="input-epoch", type="number", placeholder="MJD offset"),
    ], size="sm", className="mb-3"),

    html.Hr(),

    # 2. VIEW SETTINGS
    html.Label("View Settings", className="fw-bold", id="view-settings-label"),
    dbc.RadioItems(
        id="gp_time_axis_switch",
        options=[
            {"label": " MJD", "value": TIME_AXIS_MJD},
            {"label": " Date", "value": TIME_AXIS_DATE},
        ],
        value=TIME_AXIS_MJD,
        persistence=True,
        className="mb-2",
        inputStyle={"marginRight": "6px"},
        labelStyle={"marginRight": "12px", "fontSize": "0.9rem"},
    ),
    dbc.RadioItems(
        options=[  # type: ignore
            {"label": "Magnitudes", "value": "mag"},
            {"label": "Flux", "value": "flux"},
        ],
        value="mag",
        id="view-mode-radio",
        className="mb-3",
        style={"fontSize": "0.9rem"}
    ),

    html.Hr(),

    #  3. ACTION BUTTONS
    html.Div(
        [
            html.Label("Interval control", className="fw-bold mb-0"),
            html.Div(_add_interval_help_btn, className="lc-discovery-field-help ms-1"),
        ],
        className="d-flex align-items-center mb-2",
    ),
    dbc.Button(
        [html.I(className="bi bi-plus-circle me-2"), "Add Interval"],
        id="btn-add-interval", color="primary", className="w-100 mb-2"
    ),
    # CLEAR button
    dbc.Button(
        [html.I(className="bi bi-trash3 me-2"), "Clear All Intervals"],
        id="btn-clear-intervals", color="outline-danger",
        className="w-100", size="sm"
    ),

    html.Hr(),

    # 4. --- EXPORT ---
    html.Label("Export Settings", className="fw-bold"),
    # dbc.InputGroup([
    #     dbc.InputGroupText("Filename"),
    dbc.Input(
        id="export-intervals-filename",
        placeholder="intervals_export",
        type="text",
        value="my_intervals"  # Default value
    ),
    # dbc.InputGroupText(".intervals"),
    # ], size="sm", className="mb-2"),

    # DOWNLOAD button
    dbc.Button(
        [html.I(className="bi bi-download me-2"), "Download File"],
        id="btn-download-intervals",
        color="success",
        className="w-100 mb-2",
        size="sm"
    ),
    dcc.Download(id="download-intervals-file"),
    _add_interval_help_pop,
], className="p-3 bg-light border rounded shadow-sm")

graph_lc = html.Div([
    dcc.Graph(
        id='prep-graph',
        config={  # type: ignore
            'scrollZoom': True,
            'displaylogo': False,
            'modeBarButtonsToRemove': [
                'zoomIn2d',  # Hide Zoom In
                'zoomOut2d',  # Hide Zoom Out
                'lasso2d',  # Hide Lasso
                # 'select2d'  # Hide the default box-select (if you only want 'drawrect')
            ],
            'modeBarButtonsToAdd': ['drawrect', 'eraseshape'],
            # 'showAxisDragHandles': True,
            # 'showAxisRangeEntryBoxes': True,
        },
        # responsive=True,  # This tells Plotly to watch the container
        style={'height': '600px'}
    ),
    dbc.Alert(
        "Tip: Use the 'Box Select' tool to highlight a region for the GP fit.",
        color="info", className="mt-2 py-1 small"
    )
], className="border rounded p-2 bg-white")

intervals_registry = html.Div([
    html.H6("Selected Intervals", className="fw-bold mb-3"),
    html.Div(id='registry-list-container', children=[
        # We'll use a Dash Table or a List of Cards here
        html.P("No intervals selected.", className="text-muted small")
    ])
], className="p-3 border rounded bg-light", style={'height': '500px', 'overflowY': 'auto'})

registry_toggle_btn = dbc.Button(
    # region unfold
    html.I(className="bi bi-chevron-right", id="registry-toggle-icon"),
    id="btn-toggle-registry",
    color="light",
    size="sm",
    className="border shadow-sm p-1",
    style={
        "position": "absolute", "right": "0", "top": "50%",
        "zIndex": "1000", "transform": "translateX(50%)",
        "borderRadius": "50%", "width": "30px", "height": "30px"
    }
    # endregion
)
# ===================  GP GUI ===========================


sidebar_gp = html.Div([
    # 1. COLLAPSIBLE LEGEND
    dbc.Button(
        "Show Legend",
        id="toggle-legend-btn",
        color="link",
        # size="sm",
        className="p-0 mb-2 text-decoration-none"
    ),
    dbc.Collapse(
        html.Div([
            LegendItem("black", "Data Points", mode='circle'),
            LegendItem("rgb(31, 119, 180)", "GP Mean", mode='line'),
            LegendItem("rgba(31, 119, 180, 0.25)", "GP ±1σ Confidence", mode='line'),
            LegendItem("magenta", "Peak Estimate", mode='dashed'),
            LegendItem("orange", "Posterior Draws", mode='circle'),
            LegendItem("green", "Guess", mode='dashed'),
        ], className="p-2 border rounded bg-white mb-3 small"),
        id="legend-collapse",
        is_open=False
    ),

    # 2. PRIMARY ACTION BUTTONS
    dbc.Row([
        dbc.Col(dbc.Button("Run GP", id="run-btn", color="primary", className="w-100"), width=7),
        dbc.Col(dbc.Button("Stop", id="stop-btn", color="danger", outline=True, className="w-100"), width=5),
    ], className="g-2 mb-3"),

    # 3. GLOBAL MODEL SETTINGS
    dbc.Row([
        dbc.Col([
            dbc.Select(
                id="extrema-mode",
                options=[  # type: ignore
                    {"label": "Search Minima", "value": "min"},
                    {"label": "Search Maxima", "value": "max"},
                ],
                value=EXTREMA_MODE,
                size="sm",
            )
        ], width=12),

    ], className="g-2 mb-2"),

    dbc.Row([
        dbc.Col([
            html.Div(
                [
                    html.Label(
                        "Guess sigma", className="small fw-bold mb-0", id="guess-sigma-label"
                    ),
                    html.Div(_guess_sigma_help_btn, className="lc-discovery-field-help ms-1"),
                ],
                className="d-flex align-items-center",
            ),
        ], width=6),
        dbc.Col([
            html.Div(
                [
                    html.Label(
                        "Noise divisor", className="small fw-bold mb-0", id="noise-divisor-label"
                    ),
                    html.Div(_noise_divisor_help_btn, className="lc-discovery-field-help ms-1"),
                ],
                className="d-flex align-items-center",
            ),
        ], width=6),
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Checkbox(id="guess-sigma", value=GUESS_SIGMA, className="form-check-input"),
            dbc.Label("", html_for="guess-sigma", className="small ms-2"),
        ], width=6, className="d-flex align-items-center mb-3"),
        dbc.Col([
            dbc.Input(
                id={"type": "float-input", "index": "noise_scale_divisor"},
                type="number", size="sm", step=0.1,
                value=params_float["noise_scale_divisor"]
            ),
            # dbc.Tooltip("Noise Divisor", target={"type": "float-input", "index": "noise_scale_divisor"})
        ], width=6),
    ]),

    html.Hr(className="my-2"),

    # 4. KERNEL PARAMETERS (Compact Triples)
    # Kernel Selection
    html.Div(
        [
            html.Label(
                "Kernel Smoothness Type", className="small fw-bold mb-0", id="kernel-type-label"
            ),
            html.Div(_kernel_type_help_btn, className="lc-discovery-field-help ms-1"),
        ],
        className="d-flex align-items-center mb-1",
    ),
    dbc.RadioItems(
        id='kernel-type',
        options=[  # type: ignore
            {"label": "Matern 2.5", "value": "matern"},
            {"label": "RBF", "value": "rbf"},
        ],
        value=KERNEL_TYPE,
        inline=True,
        className="mb-3 small",
        style={"fontSize": "0.85rem"}
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
                "Length Scale (Min / Init / Max)", className="small fw-bold mb-0", id="ls-label"
            ),
            html.Div(_length_scale_help_btn, className="lc-discovery-field-help ms-1"),
        ],
        className="d-flex align-items-center mb-1",
    ),
    dbc.Row([
        dbc.Col(dbc.Input(
            id={'type': 'float-input', 'index': "length_scale_min"},
            size="sm",
            type="number", step="any",
            style={"backgroundColor": "rgba(70, 90, 230, 0.12)"},  # Violet, "too short"
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
            style={"backgroundColor": "rgba(220, 53, 69, 0.12)"},  # red, "too long"
            value=params_float["length_scale_max"]), width=4),
    ], className="g-1 mb-3"),

    html.Div(
        [
            html.Label(
                "Signal Amplitude (Min / Init / Max)",
                className="small fw-bold mb-0",
                id="amp-label",
            ),
            html.Div(_amplitude_help_btn, className="lc-discovery-field-help ms-1"),
        ],
        className="d-flex align-items-center mb-1",
    ),

    dbc.Row([
        dbc.Col(dbc.Input(
            id={'type': 'float-input', 'index': "amplitude_min"},
            size="sm",
            type="number", step="any",
            style={"backgroundColor": "rgba(70, 90, 230, 0.12)"},  # Violet, "too short"
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
            style={"backgroundColor": "rgba(220, 53, 69, 0.12)"},  # red, "too big"
            value=params_float["amplitude_max"]), width=4),
    ], className="g-1 mb-3"),

    dbc.Button("Reset Defaults", id="reset-btn", color="secondary", outline=True, size="sm", className="w-100 mt-2"),

    _guess_sigma_help_pop,
    _noise_divisor_help_pop,
    _kernel_type_help_pop,
    _length_scale_help_pop,
    _amplitude_help_pop,

], className="p-3 bg-light border rounded shadow-sm")


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
            html.H5("GP Processing View", className="fw-bold mb-0"),
            dbc.Badge("Waiting for Run", color="secondary", id='gp-view-badge', className="ms-2")
        ], className="d-flex align-items-center"),
    ], className="mb-1"),
    html.Div(id="gp-live-progress-label", className="small text-muted mb-3"),

    # 1. LIVE VIEW: fixed grid, updated per finished extremum
    _live_processing_layout(),

    # 3. FINAL REVIEW
    html.Div(id='final-review-container', style={'display': 'none'}, children=[
        html.Hr(className="my-4"),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.H6("Review and Export", className="mb-0 fw-bold"), width="auto"),
                    dbc.Col(dbc.Button("Select All", id="select-all-btn", size="sm", color="link"), width="auto"),
                    dbc.Col(dbc.Button("Unselect All", id="unselect-all-btn", size="sm", color="link"), width="auto"),

                    dbc.Col([
                        dbc.Button("Previous page", id="gp-review-prev", size="sm", outline=True, color="secondary"),
                        html.Span(id="gp-review-page-label", className="mx-2 small text-muted align-middle"),
                        dbc.Button("Next page", id="gp-review-next", size="sm", outline=True, color="secondary"),
                    ], width="auto", className="d-flex align-items-center"),

                    # Compact Filename + Download Group
                    dbc.Col([
                        dbc.InputGroup([
                            dbc.Input(id="export-filename", placeholder="results.dat", type="text", size="sm"),
                            dbc.Button([html.I(className="bi bi-download me-2"), "Download"],
                                       id="save-file-btn", color="success", size="sm"),
                        ], className="ms-auto", style={"width": "350px"})
                    ], width="auto", className="ms-auto"),
                ], className="align-items-center"),
            ], className="py-2")  # Thinner padding
        ], className="bg-light mb-3"),

        dbc.Row(id='graphs-container', className="g-2"),
    ]),

    dcc.Download(id="download-results"),
    dcc.Store(id='store-results-data')
], className="p-2")


def layout():
    return dbc.Container([
        # --- HEADER SECTION ---
        dbc.Row([
            dbc.Col([
                # html.H1("Astro-GP", className="display-4 text-primary mb-0"),
                # html.P("Lightcurves Extrema Modeller", className="lead text-muted")
                html.H1("Lightcurve Extrema Modeller (working draft)")  # , className="display-4 text-primary mb-0")
            ], width="auto"),
            dbc.Col(
                dbc.Button([html.I(className="bi bi-question-circle me-2"), "About"],
                           id="open-help", color="outline-secondary", className="mb-2"),
                width="auto", className="ms-auto d-flex align-items-end"
            ),
        ], className="mb-4 border-bottom pb-3"),

        # --- THE HELP MODAL ---
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Description")),
            dbc.ModalBody(
                dcc.Markdown(DOC_MARKDOWN, dangerously_allow_html=True),
                style={"maxHeight": "75vh", "overflowY": "auto"}
            ),
            dbc.ModalFooter(
                dbc.Button("Stop talking!", id="close-help", className="ms-auto", n_clicks=0)
            ),
        ], id="help-modal", size="xl", is_open=False),

        dcc.Store(id='store-lc-data'),
        dcc.Store(id='store-intervals-data'),
        dcc.Store(id='store-active-intervals-name', data="Drag or Select"),
        dcc.Store(id='scale-calc-trigger', data=0),  # A simple counter, trigger for scale recalculation

        # --- 2. GLOBAL DATA HUB

        dbc.Card([
            # dbc.CardHeader(html.B("Data Management")),
            dbc.CardBody([
                dbc.Row([
                    # Lightcurve Upload
                    dbc.Col([
                        html.Label("Lightcurve", className="small fw-bold"),
                        dcc.Upload(
                            id='upload-lc',
                            children=html.Div(['Drag or ', html.A('Select')], id='upload-lc-text'),
                            className="upload-box",  # We style this in the local style.css
                            style={'border': '1px dashed', 'padding': '5px', 'borderRadius': '5px',
                                   'textAlign': 'center'},
                        ),
                    ], width=6),

                    # Intervals Upload
                    dbc.Col([
                        html.Label("Intervals", className="small fw-bold"),
                        dcc.Upload(
                            id='upload-intervals',
                            children=html.Div(['Drag or ', html.A('Select')], id='upload-intervals-text'),
                            className="upload-box",  # We style this in the local style.css
                            style={'border': '1px dashed', 'padding': '5px', 'borderRadius': '5px',
                                   'textAlign': 'center'},
                        ),
                    ], width=6),

                    # # Global Summary Metrics
                    # dbc.Col([
                    #     html.Div([
                    #         html.P(id='data-summary-text', children="No data loaded.",
                    #                className="text-muted small mb-0")
                    #     ], className="p-2 border rounded bg-light", style={'height': '75px'})
                    # ], width=4),
                ])
            ])
        ], className="mb-4 shadow-sm"),

        # --- 3. THE WORKFLOW ACCORDION ---

        dbc.Accordion(
            [
                dbc.AccordionItem(
                    item_id="accordion-lc",
                    title="Lightcurve and Intervals",
                    children=[
                        dbc.Row([
                            # Sidebar (Column 1 - Fixed)
                            dbc.Col(sidebar_lc, width=3),

                            # Working Area (Column 2 & 3 combined into a Flex container)
                            dbc.Col([
                                html.Div([
                                    # Graph Area (Grows automatically)
                                    html.Div([
                                        graph_lc,
                                        registry_toggle_btn
                                    ],
                                        style={
                                            "flex": "1",
                                            "minWidth": "0",
                                            "position": "relative",
                                            "transition": "none",  # Kill the animation for instant speed
                                            # "transition": "flex 0.3s ease"
                                        }),

                                    # Registry Area (Collapses horizontally)
                                    dbc.Collapse(
                                        intervals_registry,
                                        id="registry-collapse",
                                        is_open=True,
                                        dimension="width",
                                        style={
                                            # "transition": "0.3s ease",
                                            "transition": "none",  # Kill the animation for instant speed
                                            "flexShrink": "0",
                                            # "minWidth": "0px"
                                        }
                                    )
                                ], style={
                                    "display": "flex",
                                    "flexDirection": "row",
                                    "flexWrap": "nowrap",
                                    "overflow": "hidden",
                                    "alignItems": "stretch"
                                })
                            ], width=9)
                            # dbc.Col(graph_lc, width=6),
                            # dbc.Col(intervals_registry, width=3),  # COLUMN 3: THE REGISTRY TABLE (intervals)
                        ]),
                    ]),

                # --- STEP 2: ANALYSIS (The "Monster") ---
                dbc.AccordionItem(
                    item_id="accordion-gp",
                    title="Gaussian Process",
                    children=[
                        dbc.Row([
                            dbc.Col(sidebar_gp, width=3),
                            dbc.Col(graph_gp, width=9),
                        ]),
                        html.Div(id="main-analysis-wrapper")
                    ],
                )
            ],
            id="main-workflow-accordion",
            always_open=True,  # Allows multiple items to stay open simultaneously
            active_item=["accordion-lc", "accordion-gp"],  # Opens both by default on load
        ),

    ], fluid=True)


# ===================== CALLBACKS ================================================

@callback(
    # region unfold
    Output("help-modal", "is_open"),
    [Input("open-help", "n_clicks"), Input("close-help", "n_clicks")],
    [State("help-modal", "is_open")],
    # endregion
)
def toggle_modal(n1, n2, is_open):
    if n1 or n2:
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
        return False, "Show Legend"
    return True, "Hide Legend"


# ------ lightcurve visualisation -------
@callback(
    # region unfold
    Output('prep-graph', 'figure'),
    Input('store-lc-data', 'data'),
    Input('store-intervals-data', 'data'),
    Input('folding-switch', 'value'),
    Input('view-mode-radio', 'value'),
    Input('gp_time_axis_switch', 'value'),
    State('input-period', 'value'),
    State('input-epoch', 'value'),
    # State('prep-graph', 'relayoutData')  # Optional?
    # endregion
)
def update_prep_graph(
    lc_json_string,
    intervals_data,
    folding_on,
    view_mode,
    time_axis_mode,
    period,
    epoch,
):
    if not lc_json_string:
        return go.Figure().update_layout(title="Upload data to see plot")

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
        return fig

    x_jd = np.asarray(lc['x'], dtype=float)
    y_data = lc['y']
    err_data = lc['err']

    # Error bars logic
    error_y_logic = None
    if err_data is not None:
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
        x_data = ((x_jd - t0_abs) / period) % 1.0
        t0_label = display_epoch_offset(t0_abs, jd0)
        x_label = f"Phase (P={period} d, Epoch-{jd0}={t0_label:.2f})"
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
        dragmode='zoom',
        selectdirection='h',
        # Using lc_json_string means zoom only resets when a NEW file is uploaded.
        # Adding an interval won't trigger a reset.
        # uirevision=[lc_json_string, view_mode],  # when we should update layout
        uirevision=f"{lc_json_string}_{view_mode}_{folding_on}_{axis_mode}",
        # ------------------------------
        newshape=dict(line_color='red', line_width=3, opacity=0.5),
    )

    apply_time_xaxis_format(fig, phase_view=phase_view, time_axis_mode=axis_mode)

    # Mark selected intervals (stored as absolute JD; display only in current axis)
    if intervals_data:
        if phase_view:
            t0_abs = absolute_jd_from_display_epoch(epoch, jd0)
            if t0_abs is None:
                t0_abs = float(np.nanmin(x_jd))
            for interval in intervals_data:
                for x0, x1 in phase_vrect_bounds_for_jd_interval(
                    interval[0], interval[1], t0_abs, float(period)
                ):
                    fig.add_vrect(
                        x0=x0,
                        x1=x1,
                        fillcolor="green",
                        opacity=0.15,
                        layer="below",
                        line_width=1,
                        line_color="green",
                    )
        else:
            ts = lc.get("timescale")
            for interval in intervals_data:
                x0, x1 = absolute_jd_to_plot_x(
                    [interval[0], interval[1]], axis_mode, jd0, timescale=ts
                )
                fig.add_vrect(
                    x0=x0, x1=x1,
                    fillcolor="green", opacity=0.15,
                    layer="below", line_width=1,
                    line_color="green",
                )

    return fig


# ------ Lightcurve ----

@callback(
    # region unfold me
    Output('store-lc-data', 'data'),
    Output('upload-lc-text', 'children'),
    Output('scale-calc-trigger', 'data', allow_duplicate=True),
    Output('input-period', 'value'),
    Output('input-epoch', 'value'),
    Output('view-mode-radio', 'value'),
    Input('upload-lc', 'contents'),
    State('upload-lc', 'filename'),
    State('scale-calc-trigger', 'data'),
    prevent_initial_call=True
    # endregion
)
def upload_lc(contents, filename, scale_calc_trigger_counter):
    logger.info("Uploading lightcurve: %s", filename)
    if contents is None:
        return (dash.no_update,) * 6
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)

        lc_json_string = pack_uploaded_lightcurve(decoded, filename)
        period, epoch_abs, active_domain = folding_metadata_from_transport(lc_json_string)
        epoch_display = (
            display_epoch_offset(epoch_abs, jd0) if epoch_abs is not None else None
        )

        new_label = html.Div([
            html.I(className="bi bi-check-circle-fill me-2", style={"color": "#28a745"}),
            html.Span(f"{filename}", style={"fontSize": "0.9rem", "fontWeight": "bold"})
        ])

        return (
            lc_json_string,
            new_label,
            scale_calc_trigger_counter + 1,
            period,
            epoch_display,
            active_domain,
        )

    except Exception as e:
        logger.error("Failed to process file: %s", filename)
        logger.error(traceback.format_exc())

        help_slug = "upload_lc_" + filename.replace(".", "-").replace(" ", "-")
        return (
            dash.no_update,
            _gp_upload_error_ui(
                filename,
                help_slug,
                "Upload error",
                f"Traceback: {str(e)}",
            ),
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
        )


# Callbacks for Intervals file upload/download/signs

@callback(
    Output('upload-intervals-text', 'children'),
    Input('store-active-intervals-name', 'data')
)
def update_global_intervals_label(stored_content):
    if not stored_content:
        return html.Div(['Drag or ', html.A('Select')])

    return stored_content
    # return html.Div([
    #     html.I(className="bi bi-check-circle-fill me-2", style={"color": "#28a745"}),
    #     html.B(active_name)
    # ])


@callback(
    # region unfold me
    Output('store-intervals-data', 'data'),
    Output('store-active-intervals-name', 'data', allow_duplicate=True),
    # Output('upload-intervals-text', 'children'),
    Input('upload-intervals', 'contents'),
    State('upload-intervals', 'filename'),
    prevent_initial_call=True
    # endregion
)
def upload_intervals(contents, filename):
    if contents is None:
        return dash.no_update, dash.no_update
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        # Convert bytes -> text -> StringIO
        text = decoded.decode('utf-8', errors='ignore')  # "ignore"  to prevent the whole app
        # from crashing over a single non-ASCII character.
        intervals_list = load_intervals(io.StringIO(text))
        success_ui = html.Div([
            html.I(className="bi bi-check-circle-fill me-2", style={"color": "#28a745"}),
            html.B(filename)
        ])
        return intervals_list, success_ui
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

        help_slug = "upload_int_" + filename.replace(".", "-").replace(" ", "-")
        error_ui = _gp_upload_error_ui(
            filename,
            help_slug,
            "Interval load error",
            f"Interval Load Error: {str(e)}",
            icon_class="bi-exclamation-octagon-fill",
        )
        return dash.no_update, error_ui
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
    Output("store-active-intervals-name", "data"),  # Store the "real" name here
    Input("btn-download-intervals", "n_clicks"),
    State("store-intervals-data", "data"),
    State("export-intervals-filename", "value"),
    prevent_initial_call=True,
    # endregion
)
def download_intervals(n_clicks, intervals, custom_name):
    if not n_clicks or not intervals:
        return dash.no_update, dash.no_update

    content = format_intervals_download(intervals)
    export_name = custom_name if custom_name else "my_intervals.dat"

    # --- DOWNLOAD SUCCESS UI ---
    download_ui = html.Div([
        html.I(className="bi bi-check-circle-fill me-2", style={"color": "#007bff"}),
        html.B(export_name)
    ])

    return dict(content=content, filename=export_name), download_ui
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
    Input('store-intervals-data', 'data'),
    Input('scale-calc-trigger', 'data'),  # Also triggered by Reset Button
    State('store-lc-data', 'data'),
    prevent_initial_call=True
    # endregion
)
def update_GP_scale(intervals, trigger_clicks, lc_json_string):
    if not lc_json_string or not intervals:
        return dash.no_update, dash.no_update, dash.no_update

    # di = json.loads(lc_json_string)
    # df_lc = pd.DataFrame(data=di['data'], columns=di['columns'])

    # Search for the first interval that actually contains enough data points
    for piece in intervals:
        jd_min, jd_max = piece[0], piece[1]
        frag = get_gp_flux_fragment(lc_json_string, jd_min, jd_max)

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
    Input('btn-add-interval', 'n_clicks'),
    State('prep-graph', 'selectedData'),
    State('store-intervals-data', 'data'),
    State('folding-switch', 'value'),  # we handle selection on a folded curve
    State('input-period', 'value'),  # we bring phase interval into jd-space
    State('input-epoch', 'value'),
    State('gp_time_axis_switch', 'value'),
    State('store-lc-data', 'data'),  # We need this to get JD span
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
):
    if not n_clicks or not selected_data or 'range' not in selected_data:
        return dash.no_update, dash.no_update

    x_min, x_max = selected_data['range']['x']
    updated_list = current_intervals or []
    # updated_list = current_intervals if current_intervals else []

    if folding_on:
        # --- phase to jd logic ---
        if not period or period <= 0:
            return dash.no_update, dash.no_update  # Need a valid period

        epoch_abs = absolute_jd_from_display_epoch(epoch, jd0)
        new_intervals = get_intervals_from_phase(
            lc_json, x_min, x_max, period, epoch_abs
        )
        for interval in new_intervals:
            if interval not in updated_list:
                updated_list.append(interval)

    else:
        # --- time selection (plot x → absolute JD) ---
        mode = time_axis_mode or TIME_AXIS_MJD
        left_jd = plot_x_to_jd(x_min, mode, jd0)
        right_jd = plot_x_to_jd(x_max, mode, jd0)
        new_interval = [round(left_jd, 6), round(right_jd, 6)]
        if new_interval not in updated_list:
            updated_list.append(new_interval)

    # Final cleanup
    updated_list.sort(key=lambda x: x[0])
    return updated_list, False  # force lightcurve unfolding


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
    Input('store-intervals-data', 'data')
)
def render_registry(intervals):
    if not intervals:
        return html.P("No intervals selected.", className="text-muted small italic")

    cards = []
    for i, interval in enumerate(intervals):
        cards.append(
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            # html.Small(f"Interval {i+1}", className="text-muted d-block"),
                            html.B(f"{interval[0]:.3f}", className="small"),
                            html.Span(" - ", className="mx-1"),
                            html.B(f"{interval[1]:.3f}", className="small"),
                        ], width=9),
                        dbc.Col([
                            dbc.Button(
                                html.I(className="bi bi-trash"),
                                id={'type': 'del-int', 'index': i},
                                color="link",  # Removes the button box entirely
                                className="text-danger p-0",  # "text-danger" keeps the icon red
                                style={"textDecoration": "none", "fontSize": "0.9rem"},
                                title="Delete"
                            )
                        ], width=3, className="text-end")
                    ], className="align-items-center")
                ], className="p-2")
            ], className="mb-2 shadow-sm")
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
            html.H5("GP Processing View", className="fw-bold mb-0"),
            dbc.Badge([
                html.I(className="bi bi-hourglass-split me-2"),
                "RUNNING - Modeling..."
            ], color="warning", className="ms-2")
        ], className="d-flex align-items-center mb-3")

    # 2. User clicks Stop (current fit finishes, then review partial results)
    if trigger_id == 'stop-btn' and stop_clicks > 0:
        return html.Div([
            html.H5("GP Processing View", className="fw-bold mb-0"),
            dbc.Badge([
                html.I(className="bi bi-pause-circle me-2"),
                "STOPPING - finishing current fit…"
            ], color="warning", className="ms-2")
        ], className="d-flex align-items-center mb-3")

    # 3. THE INTERMEDIATE: Plotting has started but isn't over
    if trigger_id == 'finished-signal' and signal_status == "WAITING":
        return html.Div([
            html.H5("GP Processing View", className="fw-bold mb-0"),
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
            html.H5("Results: Normalised flux vs JD", className="fw-bold mb-0"),
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
    badge_row = html.Div(badges, style={"textAlign": "center", "marginBottom": "2px"}) if badges else None

    # Checkbox logic for Review Mode
    checkbox = None
    if checkbox_id:
        checkbox = dbc.Checkbox(
            id=checkbox_id,
            value=not is_fail,
            disabled=is_fail,  # Can't keep a failure
            label="Keep Result" if not is_fail else "Fit Failed",
            className="mb-1 fw-bold"
        )

    return dbc.Col(
        html.Div([
            checkbox,
            badge_row,
            content
        ], style={
            "border": "1px solid #eee",
            "padding": "10px",
            "borderRadius": "5px",
            "backgroundColor": "#fdfdfd" if is_fail else "white"
        }),
        width=6, className="px-1 mb-2"
    )


@callback(
    # region unfold me
    Output('graphs-container', 'children', allow_duplicate=True),
    Output('finished-signal', 'children', allow_duplicate=True),  # Final signal
    Output('store-results-data', 'data'),  # Export metadata and include flags
    Output('gp-review-page-label', 'children'),
    Input('run-btn', 'n_clicks'),
    State('store-lc-data', 'data'),
    State('store-intervals-data', 'data'),
    State('guess-sigma', 'value'),
    State('extrema-mode', 'value'),
    State('kernel-type', 'value'),
    State({'type': 'float-input', 'index': ALL}, 'id'),  # Get the IDs
    State({'type': 'float-input', 'index': ALL}, 'value'),  # Get the values
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
           float_values):
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
    # print(f'{ids=}')
    # print(f'{float_values=}')
    # Use a safe conversion with a fallback to the default
    p = {}
    for val_id, val in zip(ids, float_values):
        key = val_id['index']
        try:
            # If val is None or empty, float(val) fails.
            # We fall back to the constant default.
            p[key] = float(val) if val is not None else params_float[key]
        except (ValueError, TypeError):
            p[key] = params_float[key]
    # p = {val_id['index']: float(val) for val_id, val in zip(ids, float_values)}
    # Add a standalone guess_sigma
    p['guess_sigma'] = guess_sigma
    p['extrema_mode'] = extrema_mode
    p['kernel_type'] = kernel_type
    logger.debug("GP params: %s", p)

    # 1. Validation: Ensure files are loaded
    if not lc_json_string or not intervals:
        error_alert = dbc.Alert("Please upload both lightcurve and intervals files.", color="warning")
        return error_alert, "FINISHED", None, ""
        # return dbc.Alert("Please upload both lightcurve and intervals files.", color="warning")
    # di = json.loads(lc_json_string)
    # df_lc = pd.DataFrame(data=di['data'], columns=di['columns'])

    work_items = []
    for piece in intervals:
        jd_min, jd_max = piece[0], piece[1]
        frag = get_gp_flux_fragment(lc_json_string, jd_min, jd_max)
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
        )

    # --- FINAL PHASE (Review): one page of cards; full list on server cache ---
    run_id = uuid.uuid4().hex
    save_gp_review_run(run_id, stored_entries)
    store_payload = build_review_store_payload(
        run_id, stored_entries, stopped_early=stopped_early
    )
    page_children = render_review_page(
        stored_entries, 0, store_payload["include"]
    )
    page_label = review_page_label(0, len(stored_entries))

    finish_signal = "FINISHED_STOPPED" if stopped_early else "FINISHED"
    return page_children, finish_signal, store_payload, page_label


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
def reset_params(n_clicks, ids, current_trigger):
    if n_clicks is None:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # 1. Reset floats from the dictionary
    float_resets = [str(params_float[val_id['index']]) for val_id in ids]
    # Create a list of return values based on the 'index' stored in the ID
    # This pulls directly from your global 'params_float' dictionary
    # 2. Reset the boolean to your default constant
    return float_resets, GUESS_SIGMA, KERNEL_TYPE, current_trigger + 1


# ---- Download results logic

@callback(
    Output('export-intervals-filename', 'value'),
    Input('upload-lc', 'filename'),
    prevent_initial_call=True
)
def update_intervals_output_filename(filename):
    if filename:
        # Strip the old extension and add '_intervals.dat'
        base = filename.rsplit('.', 1)[0]
        return f"{base}_intervals.dat"
    return "results_intervals.dat"


# Build GP output filename
@callback(
    Output('export-filename', 'value'),
    Input('upload-lc', 'filename'),
    prevent_initial_call=True
)
def update_default_filename(filename):
    if filename:
        # Strip the old extension and add '_maxima.dat'
        base = filename.rsplit('.', 1)[0]
        return f"{base}_extrema.dat"
    return "results_extrema.dat"


@callback(
    # region unfold me
    Output("download-results", "data"),
    Input("save-file-btn", "n_clicks"),
    State("export-filename", "value"),
    State('store-results-data', 'data'),
    State('extrema-mode', 'value'),
    prevent_initial_call=True
    # endregion
)
def trigger_download(n_clicks, filename_input, store, extrema_mode):
    logger.debug("GP download: filename=%s", filename_input)
    if not n_clicks or not store:
        return no_update

    rows = store.get("rows") or []
    include = store.get("include") or []
    if len(include) != len(rows):
        return no_update

    mode_label = "Minimum" if extrema_mode == 'min' else "Maximum"

    final_filename = filename_input if filename_input else f"gp_results_{extrema_mode}.dat"

    lines = [
        f"# GP {mode_label} Results\n",
        f"# JD_{mode_label}\tJD_Std\n"
    ]

    for is_selected, row in zip(include, rows):
        if is_selected and not row.get("is_fail"):
            lines.append(
                f"{row['jd_peak']:.6f}\t{row['jd_peak_std']:.6f}\n"
            )

    return dcc.send_string("".join(lines), final_filename)


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
