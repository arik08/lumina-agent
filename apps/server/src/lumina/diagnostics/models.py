from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


DiagnosticStatus = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class DiagnosticStep:
    stage: str
    status: DiagnosticStatus
    message: str

    @property
    def ok(self) -> bool:
        return self.status != "failed"

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "status": self.status,
            "ok": self.ok,
            "message": self.message,
        }


@dataclass(slots=True)
class DiagnosticReport:
    steps: list[DiagnosticStep] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)

    def add(self, stage: str, status: DiagnosticStatus, message: str) -> None:
        self.steps.append(DiagnosticStep(stage, status, message))

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "steps": [step.as_dict() for step in self.steps],
        }
