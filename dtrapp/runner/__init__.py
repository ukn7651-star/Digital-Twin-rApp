"""Stage 6 - runner: snapshot loop, output writer, and CLI entry point."""

from dtrapp.runner.pipeline import run_simulation
from dtrapp.runner.output import write_outputs

__all__ = ["run_simulation", "write_outputs"]
