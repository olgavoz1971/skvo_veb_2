"""Resolve pre-built Step 1 template artefacts (skip GP rebuild, no copy)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from manifest_config import PieceConfig

logger = logging.getLogger(__name__)

_TEMPLATE_FILES = ("template.npz", "template_meta.json")


def _require_template_files(source_dir: Path, *, context: str) -> None:
    """Ensure ``source_dir`` contains the Step 1 template bundle.

    Args:
        source_dir (Path): Directory expected to hold ``template.npz`` and meta.
        context (str): Label for error messages.

    Raises:
        FileNotFoundError: When a required file is missing.
    """
    for name in _TEMPLATE_FILES:
        if not (source_dir / name).is_file():
            raise FileNotFoundError(f"{context}: missing {source_dir / name}")


def resolve_piece_template_dir(
    piece: PieceConfig,
    *,
    run_dir: Path,
    pieces: list[PieceConfig],
) -> Path:
    """Return the directory holding ``template.npz`` for ``piece`` (read-only).

    Follows ``existing_template_dir`` and ``reuse_template_from`` chains without
    copying artefacts into ``pieces/<piece_id>/``.

    Args:
        piece (PieceConfig): Target piece.
        run_dir (Path): Manifest output root.
        pieces (list[PieceConfig]): Full manifest piece list (for reuse lookup).

    Returns:
        Path: Resolved template source directory.

    Raises:
        ValueError: When ``reuse_template_from`` references an unknown piece.
        FileNotFoundError: When the resolved directory lacks template files.
    """
    if piece.existing_template_dir is not None:
        source = piece.existing_template_dir.resolve()
        _require_template_files(
            source,
            context=f"piece {piece.piece_id} existing_template_dir",
        )
        return source

    if piece.reuse_template_from is not None:
        source_piece = next(
            (p for p in pieces if p.piece_id == piece.reuse_template_from),
            None,
        )
        if source_piece is None:
            raise ValueError(
                f"piece {piece.piece_id}: reuse_template_from unknown piece "
                f"{piece.reuse_template_from!r}"
            )
        source = resolve_piece_template_dir(
            source_piece, run_dir=run_dir, pieces=pieces
        )
        _require_template_files(
            source,
            context=(
                f"piece {piece.piece_id} reuse_template_from "
                f"{piece.reuse_template_from!r}"
            ),
        )
        return source

    piece_dir = (run_dir / "pieces" / piece.piece_id).resolve()
    _require_template_files(
        piece_dir,
        context=f"piece {piece.piece_id} built template",
    )
    return piece_dir


def bind_reused_template_dir(
    piece: PieceConfig,
    *,
    template_dirs: dict[str, Path],
) -> Path:
    """Resolve and register the read-only template directory for one piece.

    Args:
        piece (PieceConfig): Active piece (not skipped).
        template_dirs (dict[str, Path]): Already-resolved dirs for earlier pieces.

    Returns:
        Path: Template source directory for ``piece``.

    Raises:
        ValueError: When ``reuse_template_from`` precedes an unresolved source.
        FileNotFoundError: When template files are missing at the resolved path.
    """
    if piece.existing_template_dir is not None:
        source = piece.existing_template_dir.resolve()
        _require_template_files(
            source,
            context=f"piece {piece.piece_id} existing_template_dir",
        )
        logger.info(
            "Piece %s: reusing template from %s (read-only, no copy)",
            piece.piece_id,
            source,
        )
        return source

    if piece.reuse_template_from is not None:
        source_id = piece.reuse_template_from
        if source_id not in template_dirs:
            raise ValueError(
                f"piece {piece.piece_id}: reuse_template_from {source_id!r} "
                f"must appear earlier in the manifest run order"
            )
        source = template_dirs[source_id]
        _require_template_files(
            source,
            context=(
                f"piece {piece.piece_id} reuse_template_from {source_id!r}"
            ),
        )
        logger.info(
            "Piece %s: reusing template from piece %s at %s (read-only, no copy)",
            piece.piece_id,
            source_id,
            source,
        )
        return source

    raise ValueError(
        f"piece {piece.piece_id}: bind_reused_template_dir called without "
        f"existing_template_dir or reuse_template_from"
    )
