"""Stage 6 - runner: pipeline orchestration, output writer, and CLI entry point."""

from dtrapp.runner.pipeline import run_simulation
from dtrapp.runner.output import write_outputs

__all__ = ["run_simulation", "write_outputs"]
