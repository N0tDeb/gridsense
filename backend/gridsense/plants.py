"""Adapter boundary for the teaching circuit and the native unbalanced feeder."""

from .cases import PortableCase
from .domain import Candidate, CircuitState, Observation
from .electrical import ElectricalEngine
from .network import initial_state, load_network, restoration_baseline_kw
from .planning import candidate_actions, observation_samples
from .service import observations
from .controllers import PlanningView


class TeachingPlant:
    def __init__(self, case: PortableCase):
        self.case = case
        self.network = load_network()
        self.network["faulted_line"] = case.fault
        s = case.scenario
        self.truth = initial_state({"a": s.load_a, "b": s.load_b, "c": s.load_c}, self.network)
        self.engine = ElectricalEngine(
            self.network, restoration_baseline_kw=restoration_baseline_kw(self.truth, self.network)
        )

    def observation(self, at: str) -> Observation:
        return observations(self.case.scenario, at, self.network)

    def observed_state(self, observation: Observation) -> CircuitState:
        return self.truth.model_copy(update={"load_factors": dict(observation.load_factors)})

    def actions(self, state):
        return candidate_actions(state, self.network)

    def samples(self, observation):
        return observation_samples(observation, True)

    def solve(self, state):
        return self.engine.solve(state)

    def execute(self, state, action):
        return self.engine.execute(state, action)

    @property
    def version(self):
        return self.engine.version


def plant_for(case: PortableCase):
    if case.feeder == "teaching":
        return TeachingPlant(case)
    from .ieee13 import IEEE13Plant

    return IEEE13Plant(case)


def planning_view(plant, at: str) -> PlanningView:
    observation = plant.observation(at)
    state = plant.observed_state(observation)
    candidates = []
    for action in plant.actions(state):
        nominal = plant.execute(state, action).result
        outcomes = [nominal]
        for factors in plant.samples(observation):
            if factors != observation.load_factors:
                outcomes.append(
                    plant.execute(state.model_copy(update={"load_factors": factors}), action).result
                )
        candidates.append(
            Candidate(
                action=action,
                nominal=nominal,
                feasible=all(r.feasible for r in outcomes),
                sample_count=len(outcomes),
                worst_loading_pct=max(r.max_loading_pct for r in outcomes),
                worst_voltage_pu=min(
                    (r.min_voltage_pu for r in outcomes if r.min_voltage_pu is not None),
                    default=None,
                ),
                rejected_reasons=tuple(
                    dict.fromkeys(v.message for r in outcomes for v in r.violations)
                ),
            )
        )
    return PlanningView(observation, tuple(candidates))
