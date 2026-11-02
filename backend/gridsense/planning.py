"""Bounded action enumeration, electrically evaluated on observed load scenarios."""

from .domain import Action, Candidate, CircuitState, Decision, Observation, Operation
from .electrical import ElectricalEngine
from .network import energized, load_network, restoration_baseline_kw, unavailable

OBJECTIVE = "Among feasible candidates: maximize critical kW, then total kW, then minimize switching operations, then maximum equipment loading. kW rounded to 0.1 for solver tolerance."


def candidate_actions(state: CircuitState, network: dict) -> tuple[Action, ...]:
    """Discover single backup ties and optional one-section load shedding.

    This is an intentionally bounded action space, not all possible switch plans.
    Sectionalizing operations precede tie closure (break before make).
    """
    live = energized(state, network)
    outage = {l["bus"] for l in network["loads"]} - live
    actions = [Action(id="hold", label="Keep section isolated", operations=())]
    for line in network["lines"]:
        if line["id"] in (
            set(state.closed_lines) | set(state.locked_open) | unavailable(state, "line")
        ):
            continue
        ends = {line["from_bus"], line["to_bus"]}
        if not (ends & live and ends & outage):
            continue
        close = Operation(line=line["id"], closed=True)
        label = "West" if line["id"] == "tie_b" else "East" if line["id"] == "tie_c" else line["id"]
        actions.append(
            Action(id=line["id"], label=f"{label} backup · full section", operations=(close,))
        )
        for section in network["lines"]:
            if section["id"] not in state.closed_lines:
                continue
            if not {section["from_bus"], section["to_bus"]}.issubset(outage):
                continue
            trial = set(state.closed_lines) - {section["id"]} | {line["id"]}
            changed = state.model_copy(update={"closed_lines": tuple(sorted(trial))})
            remaining = energized(changed, network)
            critical = {l["bus"] for l in network["loads"] if l["critical"]}
            if not critical.issubset(remaining):
                continue
            actions.append(
                Action(
                    id=f"{line['id']}_partial_{section['id']}",
                    label=f"{label} backup · critical only",
                    operations=(Operation(line=section["id"], closed=False), close),
                )
            )
    return tuple(actions)


def observation_samples(observation: Observation, guarded: bool) -> list[dict[str, float]]:
    nominal = dict(observation.load_factors)
    if not guarded or observation.age_s == 0 or observation.uncertainty_pct == 0:
        return [nominal]
    # Only west-feeder telemetry is stale in v1. The range is an explicit
    # experiment assumption, not a statistically calibrated interval.
    delta = observation.uncertainty_pct / 100
    return [{**nominal, "b": nominal["b"] * m} for m in (1 - delta, 1, 1 + delta)]


def choose_action(
    observation: Observation, state: CircuitState, policy: str, network: dict | None = None
) -> Decision:
    """State supplies disclosed device status; its load factors are never consulted."""
    if policy not in ("nominal", "guarded", "oracle"):
        raise ValueError("Unknown policy")
    network = network or load_network()
    controller_state = CircuitState(
        load_factors=dict(observation.load_factors),
        closed_lines=state.closed_lines,
        locked_open=state.locked_open,
        equipment_outages=state.equipment_outages,
        open_transformers=state.open_transformers,
        source_connected=state.source_connected,
    )
    engine = ElectricalEngine(
        network, restoration_baseline_kw=restoration_baseline_kw(controller_state, network)
    )
    candidates = []
    for action in candidate_actions(controller_state, network):
        nominal = engine.execute(controller_state, action).result
        outcomes = [nominal]
        for factors in observation_samples(observation, policy == "guarded"):
            if factors != observation.load_factors:
                sample_state = controller_state.model_copy(update={"load_factors": factors})
                outcomes.append(engine.execute(sample_state, action).result)
        reasons = tuple(dict.fromkeys(v.message for result in outcomes for v in result.violations))
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
                rejected_reasons=reasons,
            )
        )
    feasible = [c for c in candidates if c.feasible]
    if feasible:
        selected = min(
            feasible,
            key=lambda c: (
                -round(c.nominal.critical_served_kw, 1),
                -round(c.nominal.served_kw, 1),
                len(c.action.operations),
                c.worst_loading_pct,
                c.action.id,
            ),
        )
        rationale = (
            f"{selected.action.label} passes {selected.sample_count} tested load case(s). "
            f"It serves {selected.nominal.critical_served_kw:.0f} critical kW and restores "
            f"{selected.nominal.restored_kw:.0f} kW in the observation-based solve. "
            f"Worst tested equipment loading is {selected.worst_loading_pct:.1f}%."
        )
    else:
        selected = next(c for c in candidates if c.action.id == "hold")
        rationale = "No candidate passes every required electrical check. Keep the faulted section isolated and request engineering review; existing violations remain unresolved."
    if policy == "guarded" and observation.age_s > 0:
        rationale += (
            " This is a finite stress check, not a guarantee over the entire uncertainty interval."
        )
    return Decision(
        policy=policy,
        selected_action=selected.action,
        feasible_choice=bool(feasible),
        rationale=rationale,
        candidates=tuple(candidates),
        observation=observation,
        objective=OBJECTIVE,
    )
