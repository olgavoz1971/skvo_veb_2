"""Shared Julian Date scale conversion for auxiliary pipelines."""

from __future__ import annotations

from dataclasses import dataclass

from skvo_veb.utils.lc_config import JD_TO_MJD

TIME_SCALES = frozenset({"jd", "mjd", "jd_offset"})


@dataclass(frozen=True)
class TimeScaleConfig:
    """Input time coordinates before conversion to absolute Julian Date."""

    scale: str
    zero: float | None = None
    shift: float = 0.0

    def __post_init__(self) -> None:
        if self.scale not in TIME_SCALES:
            raise ValueError(
                f"time scale must be one of {sorted(TIME_SCALES)}, got {self.scale!r}"
            )
        if self.scale == "jd_offset" and self.zero is None:
            raise ValueError("zero is required when scale is jd_offset")
        if self.scale != "jd_offset" and self.zero is not None:
            raise ValueError(
                f"zero must be omitted unless scale is jd_offset "
                f"(got scale={self.scale!r})"
            )

    def to_absolute_jd(self, value: float) -> float:
        """Convert a file or manifest time value to absolute Julian Date (days)."""
        if self.scale == "jd":
            base = float(value)
        elif self.scale == "mjd":
            base = float(value) + JD_TO_MJD
        else:
            assert self.zero is not None
            base = float(value) + float(self.zero)
        return base + float(self.shift)


def parse_time_scale_block(
    raw: dict,
    *,
    block_name: str,
    require_scale: bool = True,
) -> TimeScaleConfig:
    """Parse a YAML mapping with ``scale``, optional ``zero``, optional ``shift``."""
    if not isinstance(raw, dict):
        raise ValueError(f"{block_name} must be a mapping")
    if require_scale and "scale" not in raw:
        raise ValueError(f"{block_name}.scale required (jd | mjd | jd_offset)")
    scale = str(raw["scale"])
    zero_raw = raw.get("zero")
    zero = None if zero_raw is None else float(zero_raw)
    shift = float(raw.get("shift", 0.0))
    try:
        return TimeScaleConfig(scale=scale, zero=zero, shift=shift)
    except ValueError as exc:
        raise ValueError(f"{block_name}: {exc}") from exc
