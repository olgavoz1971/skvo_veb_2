## File Structure & Architectural Separation

This repository strictly separates **Frontend (UI/Layout/Callbacks)** from **Backend (Scientific Math/Astropy/Data Processing)**. AI agents must respect this separation when creating or modifying files:

```text
my-dash-app/
├── app.py                     # App initialization (instantiates dash.Dash and exposes 'server')
├── index.py                   # Entry point for running the local development server
├── requirements.txt           # Python dependencies (e.g., astropy, scipy, dash)
├── AGENTS.md                  # System rules for AI coding assistants
│
├── assets/                    # Static UI elements (Custom CSS, favicon, images)
│   └── *.css                  # All layout styling and dark mode overrides go here
│
├── pages/                     # FRONTEND: Multi-page routing layout modules
│   ├── __init__.py
│   ├── home.py                # Home page layout and presentation logic
│   └── *.py                   # DYNAMIC: Any new frontend view or dashboard tab layout goes here
│
├── utils/                     # BACKEND: Pure scientific computations and math engine
│   ├── __init__.py
│   ├── data_processor.py      # Archive plate reading, parsing, and phase folding
│   └── *.py                   # DYNAMIC: Any new numerical, regression, or Astropy module goes here
│
# Deployment-specific targets (Maintain if present):
└── plotly-cloud.toml          # Plotly Cloud: Managed CLI deployment config profile

### Core Dependency Rules:
- **Do Not Alter Versions Blindly:** You are explicitly forbidden from rewriting or appending restrictive upper bounds (e.g., `dash<4`, `astropy<7`) to `requirements.txt` based on your internal training cuts.
- **Default to Loose Pinning:** If asked to add a *new* dependency to `requirements.txt`, append only the package name or use loose lower bounds (e.g., `package>=version`). Never set hard upper caps unless a specific code incompatibility has been explicitly verified in the workspace.
- **Do Not Call Pip Commands:** Never run `pip install` commands inside the integrated terminal layout unless explicitly ordered to fix a broken module import.
- **Trust the Live Documentation Context:** You are supplied with up-to-date documentation via MCP. Do not assume your internal pre-2025 knowledge of package major-versions is correct. If the workspace or provided documentation demonstrates the use of cutting-edge features, do not restrict the environment to older major release boundaries.

## General Architecture
- **Global Variables**: Never use global variables to store user-specific state. All mutable state must live in the client browser using `dcc.Store` or URL parameters.
- **Server Variable**: Make sure the app file always exposes a server variable: `server = app.server`
- **Dash Pages**: If Snapshot Engine is used, do not use Dash Pages; use callback routing instead to navigate between views. Otherwise, use `dash.page_registry`, keep all pages in a `pages/` directory, and register each page with `dash.register_page(__name__)`.
- **App IDs**: Prefer descriptive IDs like `"sales-filter-dropdown"` over `"dropdown-1"`. IDs must be unique across the entire app, including all pages.
- **Loading Data**: Load data inside callbacks, not at import time. Avoid `df = pd.read_csv(...)` at module level. Data loaded at startup won't refresh until the process restarts. Fetch or refresh data inside the callback that needs it, or use a layout function (`def serve_layout(): ...`) when the layout must be rebuilt on each page load.
- **Server-side Filtering**: Filter, aggregate, and paginate data in Python before passing it to graphs or `AgGrid`. Only send the rows or points needed for the current view to the client.
- **Pin Dependencies**: Specify minimum or exact versions for `dash`, `plotly`, and component libraries in `requirements.txt` to avoid breaking changes on deploy.

## Callbacks
- **Dataset Size**: Do not pass massive datasets through `dcc.Store` if they can be cached server-side. Use `dcc.Store` only for lightweight state (IDs, UI toggles, query filters) with a maximum of 5MB.
- **Caching**: For large datasets, expensive database queries, heavy computations, or API requests, implement server-side caching using `flask_caching`. Decorate data-fetching operations with the `@cache.memoize()` pattern. Ensure the cache key includes relevant query parameters.
- **Input IDs**: Every `Input`, `Output`, and `State` ID referenced in a callback must be present in the layout when the callback fires. For dynamic or multi-page layouts, set `suppress_callback_exceptions = True`.
- **Prevent Callback Firing**: Apply `prevent_initial_call=True` in callback decorators that should not run on page load (e.g., actions triggered only by a button click).
- **Prevent Unnecessary Updates**: When a callback should leave an output unchanged, return `dash.no_update` instead of re-fetching or re-computing data. Use `raise PreventUpdate` to skip updating the entire callback.
- **Keep Callbacks Focused**: One callback per user interaction when possible. Split large callbacks into smaller, composable ones rather than updating many outputs from a single function.
- **Loading Spinners**: Show a spinner while data is loading to improve perceived performance by wrapping components that may be slow to update with `dcc.Loading`.
- **Background Callbacks**: Use background callbacks for long-running work. For tasks that take more than a few seconds, use `background=True` in the callback decorator, along with the configured manager: `manager=background_callback_manager`.
- **Validate Callback Outputs**: Return strings for `children`, lists of component objects for `children` on containers, dicts for `figure`, and lists of dicts for `AgGrid` `rowData` and `columnDefs`.
- **dash.no_update vs raise PreventUpdate**: do not raise PreventUpdate after calling set_props in the callback, return dash.no_update in these cases

## Layout and Styling
- **Custom Style Sheets**: For external stylesheets and CSS files, put core layout styles, layout grids, and structural overrides into custom files inside the `assets/` directory.
- **Theme File**: Use a shared `theme.py` or `theme.js` containing color constants, spacing scales, and font definitions to pass values systematically.
- **Inline Styles**: Use inline Python dictionaries (`style={"marginRight": "10px"}`) only for highly dynamic, runtime-computed values (e.g., styling a component color based on a callback threshold). Avoid static inline styling blocks as much as possible.
- **Code Format**: Run `black` for Python formatting and Prettier for CSS formatting.

## Charts and Components
- **Graphing Library**: Use `plotly.express` for charts first—it is simpler and covers most use cases. Switch to `plotly.graph_objects` only when you need fine-grained control.
- **Component Libraries**: Prioritize component libraries in this order: Dash Design Kit (if you have access to it), then Dash Core Components combined with Dash HTML Components, then Dash Mantine Components, then Dash Bootstrap Components if required. Try to minimize the number of libraries required. 
- **Data Tables**: Do not use `dash.datatable`; use `dash.AgGrid` instead.
- **AgGrid Configs**: When instantiating `dag.AgGrid`, always set the following properties:
  - `dashGridOptions={"theme": "themeBalham", "animateRows": True, "pagination": True, "paginationPageSize": 10}`
  - `columnSize="responsiveSizeToFit"`
  - `defaultColDef={"filter": True, "sortable": True}`

## Avoid Hallucinations
- Never use `app.run_server`; only use `app.run`
- Never use obsolete patterns like `app.validation_layout`. Modern Dash handles dynamic layouts smoothly; just use `suppress_callback_exceptions=True` on app initialization if building dynamic layouts.
- Never import `dash.dependencies` items individually (from `dash.dependencies import Input`). Always use the modern syntax: `from dash import Input, Output, State, callback, clientside_callback, no_update, ALL, MATCH`.
- Never write blocking `time.sleep` loops inside a callback in production contexts; use `dcc.Interval` for asynchronous long-polling or integrate an external task queue (like Celery/Redis) if handling long-running computations.
- Never assign to callback `Input` values or mutate callback arguments in place.
- Never use `dash_table.DataTable`; use `dash.AgGrid()` instead.
- Never put secrets, API keys, or credentials in layout code or `dcc.Store`. Use environment variables and server-side logic only.

- **Preserve Callback Architecture:** NEVER convert a client-side callback (`app.clientside_callback`) into a server-side Python callback unless explicitly requested by the user. Maintaining low-latency, browser-executed frontend performance takes absolute precedence over refactoring conveniences.

- **Optimize State Boundaries & Data Transfer:** Prefer maintaining a clean separation between lightweight UI metadata and heavy application state to ensure high-performance network handling.
  - Avoid serializing large datasets or back-end cached collections (such as dataframes, tables, or complex arrays) into client-side components or `dcc.Store` objects whenever possible.
  - Standard browser-side `dcc.Store` targets are best reserved for lightweight UI tracking parameters, such as coordinate boundaries, range limits, configuration flags, or active tab UUIDs.
  - When slicing, filtering, or cropping data stored in server-side caches, prefer transmitting only the small configuration boundaries (`xmin`, `xmax`) to the backend. It is generally more efficient to execute heavy computations or dataframe slicing directly on the server layer before updating visual charts.

## Dependencies and Mathematical Implementation Hierarchy

When implementing physical formulas, statistical analysis, curve fitting, or coordinate transformations, you must follow this strict priority chain. **Never implement mathematical or astronomical algorithms from scratch.** Exhaust each level of the hierarchy before moving to the next:

1. **Level 1: Astronomical Core Libraries**
   - **VOTable Exception:** For VOTable reading, parsing, schema interpretation, and reporting, **GAVO utilities (`gavo.utils`, `gavo.votable`) are strictly preferred** over standard parsers.
   
   - **Astropy (`astropy.*`):** Must be used for all other core astronomical concepts: Time conversions, coordinate frames, cosmological calculations, modeling/fitting, and unit propagation.

   - *Example:* Use `astropy.modeling` for lightcurve/O-C curve fitting; use `astropy.time` for time scales (JD/MJD).

2. **Level 2: SciPy (`scipy.*`)**
   - Use ONLY if the specific scientific feature or mathematical optimization is completely absent in Astropy.
   - *Example:* Periodogram analysis (if not using `astropy.timeseries`), advanced integration (`scipy.integrate`), or signal processing filters.

3. **Level 3: NumPy (`numpy.*`)**
   - Use ONLY for raw array manipulations, basic linear algebra (e.g., matrix operations), and standard mathematical primitives ($\sin, \cos, \exp, \log$). 
   - Do not use NumPy for high-level statistical modeling or curve fitting (e.g., absolutely no `np.polyfit`).

4. **Level 4: Pure Python / Custom Logic**
   - Strictly prohibited for scientific equations. You are explicitly forbidden from writing custom mathematical functions, manual interpolation loops, or implementing mathematical equations from scratch if an open-source equivalent exists in the levels above.

### Enforcement Rules & Syntax Restrictions

- **Unit Safety:** Always enforce physical dimensions using `astropy.units`. Never drop units into raw floats unless explicitly feeding a plotting function that requires it.
- **No Reinventing the Wheel:** If asked to implement a known astrophysical formula, check `astropy` first. If you write a manual math loop for an existing library feature, the code will be rejected.

## Virtual observatories
- ALWAYS prioritise dedicated `pyvo` modules while querying virtual observatory services

## Language & Localization
- **Rule:** Use British English (UK) for all user-facing strings, page descriptions, button labels, and charts (e.g., "visualise", "colour", "behaviour").
- **Strict Exception:** Programming syntax, library functions, HTML attributes, and CSS properties/values MUST remain in their standard technical specifications (which use US spelling). 
  - *Never write:* `text-align: centre;` or `background-color: colour;`
  - *Always write:* `text-align: center;` and `background-color: color;`

## Server-Side Data Caching Engine (Shared Archive Cache)

When retrieving public astronomical data (e.g., TESS, Gaia, or archival photographic plate time-series), the application **MUST cache data centrally on the server side** so that multiple users requesting the same object hit our local server cache instead of hitting external data archives.

### 1. Architectural Strategy (Shared Disk/File Cache)
- **Thread-Safe Shared Cache:** You are explicitly forbidden from using raw, unprotected global Python dictionaries (e.g., `CACHE = {}`) for caching, as they fail under multi-threaded Flask workers.
- **Flask-Caching Integration:** Use `flask_caching` configured with a `FileSystemCache` or `DiskCache` backend. This ensures the data is stored safely in a designated server directory (`/cache/`) accessible by all user sessions.
- **Query Key Normalization:** Cache keys must be uniquely and deterministically generated based on the target astronomical object identifier (e.g., TIC ID, Gaia DR3 ID) and the requested data bounds to ensure shared hits.

### 2. Implementation Directive for AI Agents
- When the frontend callbacks request remote public data, they must pass through an isolated, server-cached utility wrapper.

## Core Architectural Principles: Modular & Decoupled Code

- To ensure the application remains maintainable, scalable, and easy to test, all code generated must strictly adhere to the following structural principles:

### 1. The "One Idea, One Callback" Rule
- **Single Responsibility Callbacks:** Every Dash callback must do exactly one conceptual job (e.g., updating a single graph, toggling a loading state, or saving data to a `dcc.Store`). 
- **No Monolithic Callbacks:** Do not bunch unrelated UI logic together into giant, multi-output callbacks unless they are completely dependent on the exact same user trigger and state.
- **Isolate Side Effects:** Keep logic linear. A callback should receive an input, call a clean utility function if computation is needed, and return the result straight to the layout target.

### 2. High Reuse of Backend Methods (Zero Logic Duplication)
- **Math & Parsing belong in `/utils/`:** All mathematical transformations, file parsers (VOTable/CSV), archival data queries, and statistical fits must live as standalone, pure functions inside the `/utils/` directory.
- **Never Mix Business Logic with UI:** Frontend layout files inside `/pages/` are forbidden from implementing equations or data parsing loops inline. If two different pages need to process data or format astronomical times, they must import and share the exact same utility function from `/utils/`.
- **Functions Return Data, Not Figures:** Utility methods must remain agnostic of the visual presentation layer. They must return clean data structures (DataFrames, dicts, primitives)—never Plotly figure dictionaries or UI components.

### 3. Clear Separation Blueprint

Keep this structural pipeline in mind for every interactive feature you build:

```text
  [ User Action ]  --> Triggered by a UI component in /pages/
         │
         ▼
  [ UI Callback ]  --> Captures input, performs ZERO math/parsing itself
         │
         ▼
  [ Utils Layer ]  --> Pure Python function in /utils/ handles data/physics/caching
         │
         ▼
  [ UI Callback ]  --> Receives clean data back, compiles and styles the Plotly Figure
         │
         ▼
  [ Screen Output] --> Renders the updated component to the user

## Logging Standards & Terminal Output

* **Central configuration:** Do not call ``logging.basicConfig`` in individual modules. Logging is initialised once via ``skvo_veb.logging_config.configure_logging()`` (invoked from ``skvo_veb/__init__.py`` on app import). Set ``APP_LOG`` for a mirrored file log; all records also go to stderr.
* **NO `print()` STATEMENTS:** Under no circumstances should the agent use the raw `print()` function for terminal logging, debugging, or status updates in application files.
* **Mandatory Logger Usage:** Every file contains an explicitly defined module-level logger (`logger = logging.getLogger(__name__)`). You MUST route all diagnostic output, errors, and informational messages through this identifier using the appropriate severity levels:
  * `logger.debug()` for fine-grained execution tracing.
  * `logger.info()` for general state changes and successful milestones.
  * `logger.warning()` / `logger.error()` for handled or unhandled exceptions.

# Documentation Directives
- Every new or modified Python function/method must include a clean Google-style docstring.
- The docstring must briefly state the purpose, expected inputs (with types), and return values.
- Write docstrings immediately during the code generation phase; do not skip them for later.

- **No Silent Fallbacks or Blind Failure Mitigation:** You are strictly forbidden from implementing *any* fallback mechanisms without explicit consultation with Developer
