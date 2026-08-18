"""CLI entry point for O-C analysis studies."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_OC_DIR = Path(__file__).resolve().parent
_AUX = _OC_DIR.parent
_REPO = _AUX.parent
for _p in (_REPO, _AUX, _OC_DIR, _AUX / "template_timing"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from oc_config import load_oc_config
from oc_core import run_study

logger = logging.getLogger(__name__)


def main() -> None:
    """Run O-C tasks declared in a study YAML file."""
    parser = argparse.ArgumentParser(description="O-C analysis from YAML study config")
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        required=True,
        help="Path to oc_configs/*.yaml study file",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save figures only; do not call plt.show()",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

    cfg = load_oc_config(args.config.resolve())
    if args.no_show:
        cfg.show_plots = False

    run_study(cfg)
    logger.info("O-C study %r finished; outputs in %s", cfg.label, cfg.output_dir)


if __name__ == "__main__":
    main()
