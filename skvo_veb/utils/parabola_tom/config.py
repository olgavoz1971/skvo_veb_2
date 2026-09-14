"""Scientific defaults for local parabola ToM refinement."""

from __future__ import annotations

# Search troughs (eclipses) in the working photometry by default.
DEFAULT_EXTREMA_MODE = "min"

# Inverse-variance weights are off unless the user opts in.
DEFAULT_USE_WEIGHTS = False

# Empty / None: use the marked interval as-is. A positive value caps wide intervals.
DEFAULT_MAX_HALF_WIDTH_D = None

# Minimum raw points in an interval; fewer than 3 cannot define a parabola.
MIN_POINTS = 5
MIN_POINTS_ABSOLUTE = 3
