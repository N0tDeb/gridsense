"""Small trusted-Python controller interface, independent of hidden plant truth.

A controller receives only candidate predictions from permitted measurements.
Implement select(view), then pass the instance to regression.evaluate_case.
Web requests select an allowlisted controller; they never execute uploaded code.
"""

from dataclasses import dataclass
from typing import Protocol
from .domain import Action, Candidate, Observation


@dataclass(frozen=True)
class PlanningView:
    observation: Observation
    candidates: tuple[Candidate, ...]


class Controller(Protocol):
    id: str

    def select(self, view: PlanningView) -> Action: ...


@dataclass(frozen=True)
class RankedController:
    id: str
    guarded: bool = False

    def select(self, view: PlanningView) -> Action:
        feasible = [
            c for c in view.candidates if (c.feasible if self.guarded else c.nominal.feasible)
        ]
        if not feasible:
            return next(c.action for c in view.candidates if c.action.id == "hold")
        winner = min(
            feasible,
            key=lambda c: (
                -round(c.nominal.critical_served_kw, 1),
                -round(c.nominal.served_kw, 1),
                len(c.action.operations),
                c.worst_loading_pct if self.guarded else c.nominal.max_loading_pct,
                c.action.id,
            ),
        )
        return winner.action


@dataclass(frozen=True)
class HoldController:
    id: str = "hold-v1"

    def select(self, view: PlanningView) -> Action:
        return next(c.action for c in view.candidates if c.action.id == "hold")


CONTROLLERS: dict[str, Controller] = {
    "nominal-v1": RankedController("nominal-v1"),
    "guarded-v1": RankedController("guarded-v1", guarded=True),
    "hold-v1": HoldController(),
}
