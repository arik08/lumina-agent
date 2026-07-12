"""Installation and operator diagnostics with explicit network opt-in."""

from .models import DiagnosticReport, DiagnosticStep
from .service import run_diagnostics

__all__ = ["DiagnosticReport", "DiagnosticStep", "run_diagnostics"]
