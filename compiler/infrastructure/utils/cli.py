"""Resolve the compiler input and output directories."""

import argparse
from pathlib import Path

from infrastructure.shared.project.provenance import resolve_workspace


def resolve_directories(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve CLI paths and keep requirements, compiler, and outputs separate."""
    return resolve_workspace(args.input, args.output)
