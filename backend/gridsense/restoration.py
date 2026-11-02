"""Budgeted session planning from received load estimates and device status only."""

from copy import deepcopy
from itertools import product

from dss import DSSException
import networkx as nx
from pydantic import Field

from .domain import CircuitState, EquipmentOutage, Record
from .electrical import ElectricalEngine, InvalidSwitching
from .network import energized, graph_for, load_connected, load_network
from .switching import (
    SwitchOperation,
    change_position,
    device_positions,
    normal_positions,
    position_key,
)

OBJECTIVE = "Prioritize feasible terminal critical supply, then lower predicted critical and total unserved energy over the same window. Break ties by terminal total supply, fewer operations and lower peak tested loading. kW rounded to 0.1; deterministic operation-key ties."


class PlanningTiming(Record):
    """Public assumptions, independent of private actuator scenario events."""

    actuation_delay_s: int = Field(default=1, ge=1, le=10, strict=True)
    confirmation_delay_s: int = Field(default=0, ge=0, le=30, strict=True)
    energy_horizon_s: int = Field(default=10, ge=1, le=600, strict=True)

    @property
    def step_s(self):
        return self.actuation_delay_s + self.confirmation_delay_s


class PlanningView(Record):
    at_s: int
    state: CircuitState
    demand_kw: dict[str, float]
    bounds_kw: dict[str, tuple[float, float]]
    evidence: dict
    growth_pct_per_s: float = Field(default=0, ge=0, le=10)
    maximum_uncertainty_pct: float = Field(default=100, ge=0, le=100)
    remaining_horizon_s: int = Field(default=600, ge=0, le=600, strict=True)
    measured_overloads: tuple[dict, ...] = ()
    unsafe_exposures: tuple[dict, ...] = ()


def planning_view(observation, network=None):
    network = network or load_network()
    signals = {r["sensor_id"]: r for r in observation["signals"]}
    positions, outages, evidence = {}, [], {}
    template = CircuitState(load_factors={"a": 1, "b": 1, "c": 1}, closed_lines=(), locked_open=())
    for asset in sorted(device_positions(template, network)):
        rows = [signals.get(asset + "/" + q) for q in ("available", "closed")]
        if any(r is None or not r["fresh"] or type(r["value"]) is not bool for r in rows):
            raise ValueError("Fresh availability and position are required for " + asset)
        if rows[0]["measured_at_s"] != rows[1]["measured_at_s"]:
            raise ValueError("Availability and position timestamps disagree for " + asset)
        available, closed = (r["value"] for r in rows)
        if not available and closed:
            raise ValueError("Received unavailable equipment is reported closed: " + asset)
        positions[asset] = closed
        evidence[asset] = rows
        if not available:
            kind, name = asset.split(":", 1)
            outages.append(
                EquipmentOutage(incident_id="observed-" + asset, kind=kind, equipment=name)
            )
    demand, bounds = {}, {}
    estimates = {r["load_id"]: r for r in observation["demand_estimates"]}
    for load in network["loads"]:
        row = estimates.get(load["id"])
        if row is None or row["kw"] is None or row["kw"] <= 0:
            raise ValueError("A valid prior demand estimate is required for " + load["id"])
        demand[load["id"]] = row["kw"]
        bounds[load["id"]] = (row["lower_kw"], row["upper_kw"])
    state = template.model_copy(
        update={
            "closed_lines": tuple(
                sorted(
                    a.split(":", 1)[1]
                    for a, closed in positions.items()
                    if a.startswith("line:") and closed
                )
            ),
            "open_transformers": tuple(
                sorted(
                    a.split(":", 1)[1]
                    for a, closed in positions.items()
                    if a.startswith("transformer:") and not closed
                )
            ),
            "source_connected": positions["source:" + network["source_bus"]],
            "equipment_outages": tuple(outages),
        }
    )
    growth = observation.get("uncertainty_model", {"growth_pct_per_s": 0, "maximum_pct": 100})
    position_times = {row["measured_at_s"] for pair in evidence.values() for row in pair}
    overloads = tuple(
        {"equipment": row["equipment"], "limit_pct": 100, "row": row}
        for row in observation["signals"]
        if row["quantity"] == "loading_pct"
        and row["fresh"]
        and row["value"] > 100 + 1e-6
        and position_times == {row["measured_at_s"]}
    )
    return PlanningView(
        at_s=observation["at_s"],
        state=state,
        demand_kw=demand,
        bounds_kw=bounds,
        evidence={"device_rows": evidence, "demand_estimates": observation["demand_estimates"]},
        growth_pct_per_s=growth["growth_pct_per_s"],
        maximum_uncertainty_pct=growth["maximum_pct"],
        remaining_horizon_s=observation.get("remaining_horizon_s", 600),
        measured_overloads=overloads,
    )


def section_loads(state, asset, network):
    """Connected load groups whose supply path uses a modeled device."""
    live = energized(state, network)
    connected = {load["id"] for load in network["loads"] if load_connected(state, load, live)}
    if asset in {"transformer:main", "source:" + network["source_bus"]}:
        return connected
    if asset.startswith("transformer:tx_"):
        return connected & {asset.removeprefix("transformer:tx_")}
    if not asset.startswith("line:") or asset.removeprefix("line:") not in state.closed_lines:
        return set()
    line = next(row for row in network["lines"] if row["id"] == asset.removeprefix("line:"))
    graph = graph_for(state, network)
    graph.remove_edge(line["from_bus"], line["to_bus"])
    remaining = nx.node_connected_component(graph, network["distribution_bus"])
    return {
        load["id"]
        for load in network["loads"]
        if load["id"] in connected and load["bus"] not in remaining
    }


def correction_progress(view, changed, network):
    """A first correction must reduce measured exposure without increasing another."""
    reduced = False
    for overload in view.measured_overloads:
        before = section_loads(view.state, overload["equipment"], network)
        after = section_loads(changed, overload["equipment"], network)
        if not after <= before:
            return False
        reduced = reduced or after < before
    return reduced


def blocked_exposure(view, state, network):
    """Do not restore a known overloaded load set using unchanged received demand."""
    return any(
        section_loads(state, item["equipment"], network) >= set(item["load_ids"])
        for item in view.unsafe_exposures
    )


def projected_view(view, offset_s):
    """Age held bounds without assuming any future measurement will arrive."""
    if type(offset_s) is not int or offset_s < 0:
        raise ValueError("A nonnegative integer projection offset is required")
    bounds = {}
    for key, (low, high) in view.bounds_kw.items():
        mean = view.demand_kw[key]
        change = mean * view.growth_pct_per_s * offset_s / 100
        # Existing evidence may already be wider than the declared cap. Never
        # narrow it merely because time passed without a fresh measurement.
        floor = min(low, max(0, mean * (1 - view.maximum_uncertainty_pct / 100)))
        ceiling = max(high, mean * (1 + view.maximum_uncertainty_pct / 100))
        bounds[key] = (max(floor, low - change), min(ceiling, high + change))
    return view.model_copy(update={"at_s": view.at_s + offset_s, "bounds_kw": bounds})


def demand_samples(view, policy):
    samples = [dict(view.demand_kw)]
    if policy == "guarded":
        for key in sorted(view.demand_kw):
            for value in view.bounds_kw[key]:
                samples.append({**view.demand_kw, key: value})
        samples.extend(
            {key: value[index] for key, value in view.bounds_kw.items()} for index in (0, 1)
        )
    return list({tuple(sorted(s.items())): s for s in samples}.values())


class BudgetExhausted(Exception):
    pass


class Predictor:
    """Reuse exact native problems within one decision, including future stages."""

    def __init__(self, view, policy, budget, engine=None, network=None, samples=None):
        self.view = view
        self.policy = policy
        self.network = network or load_network()
        self.samples = demand_samples(view, policy) if samples is None else samples
        self.fixed_samples = samples
        self.budget, self.solves = budget, 0
        self.engine = engine or ElectricalEngine(self.network)
        self.cache = {}
        self.native_cache = {}
        self.cache_hits = 0

    def nominal(self, state):
        return self._solve(state, self.view.demand_kw)

    def _solve(self, state, demand):
        live = energized(state, self.network)
        connected = {
            load["id"] for load in self.network["loads"] if load_connected(state, load, live)
        }
        key = (
            state.model_dump_json(),
            tuple((name, value) for name, value in sorted(demand.items()) if name in connected),
        )
        if key in self.native_cache:
            self.cache_hits += 1
            return self._requested_demand(self.native_cache[key], state, demand)
        if self.solves >= self.budget:
            raise BudgetExhausted
        model = deepcopy(self.network)
        for load in model["loads"]:
            # Disabled loads cannot consume power. Keep their native model input
            # fixed; their requested demand is still counted separately below.
            load["kw"] = (
                demand[load["id"]] if load["id"] in connected else self.view.demand_kw[load["id"]]
            )
        previous = self.engine.network
        self.engine.network = model
        self.solves += 1
        try:
            result = self.engine.solve(state)
            outcome = {
                "feasible": result.feasible,
                "converged": result.converged,
                "critical_kw": result.critical_served_kw,
                "served_kw": result.served_kw,
                "requested_kw": result.requested_kw,
                "loading_pct": result.max_loading_pct,
                "min_voltage_pu": result.min_voltage_pu,
                "violations": [r.model_dump(mode="json") for r in result.violations],
            }
        except (InvalidSwitching, DSSException) as exc:
            outcome = {
                "feasible": False,
                "converged": False,
                "critical_kw": None,
                "served_kw": None,
                "requested_kw": None,
                "loading_pct": None,
                "min_voltage_pu": None,
                "violations": [{"kind": "model", "message": str(exc)}],
            }
        finally:
            self.engine.network = previous
        self.native_cache[key] = outcome
        return self._requested_demand(outcome, state, demand)

    def _requested_demand(self, outcome, state, demand):
        if outcome["requested_kw"] is None:
            return dict(outcome)
        return {
            **outcome,
            "requested_kw": sum(
                demand[load["id"]] * state.load_factors[load["feeder"]]
                for load in self.network["loads"]
            ),
        }

    def evaluate(self, state, offset_s=0):
        forecast = projected_view(self.view, offset_s)
        samples = (
            demand_samples(forecast, self.policy)
            if self.fixed_samples is None
            else self.fixed_samples
        )
        key = (state.model_dump_json(), offset_s)
        if key in self.cache:
            return self.cache[key]
        outcomes = []
        for demand in samples:
            outcomes.append(self._solve(state, demand))
            if not outcomes[-1]["feasible"]:
                break
        summary = {
            "nominal": outcomes[0],
            "feasible": all(r["feasible"] for r in outcomes) and len(outcomes) == len(samples),
            "samples_checked": len(outcomes),
            "samples_required": len(samples),
            "worst_loading_pct": max(
                (r["loading_pct"] for r in outcomes if r["loading_pct"] is not None), default=None
            ),
            "violations": [v for r in outcomes for v in r["violations"]],
            "at_offset_s": offset_s,
            "projected_bounds_kw": {k: list(v) for k, v in forecast.bounds_kw.items()},
        }
        self.cache[key] = summary
        return summary


def choices(state, network, used=(), blocked=()):
    unavailable = {o.kind + ":" + o.equipment for o in state.equipment_outages}
    result = []
    for asset, closed in sorted(device_positions(state, network).items()):
        if (
            asset in used
            or asset in unavailable
            or (closed and not asset.startswith(("line:", "transformer:tx_")))
        ):
            continue
        operation = SwitchOperation(equipment=asset, closed=not closed)
        if operation.key not in blocked:
            result.append(operation)
    return result


def rank(candidate):
    nominal = candidate["prediction"]["nominal"]
    energy = candidate["energy"]
    return (
        -round(nominal["critical_kw"], 1),
        round(energy["critical_unserved_kwh"], 8)
        if energy["critical_unserved_kwh"] is not None
        else float("inf"),
        round(energy["unserved_kwh"], 8) if energy["unserved_kwh"] is not None else float("inf"),
        -round(nominal["served_kw"], 1),
        len(candidate["operations"]),
        candidate["prediction"]["worst_loading_pct"],
        tuple(
            r["equipment"] + (":close" if r["closed"] else ":open") for r in candidate["operations"]
        ),
    )


def sequence_states(view, operations, network):
    states = [view.state]
    for operation in operations:
        states.append(change_position(states[-1], operation, network))
    return states


def forecast_sequence(predictor, operations, timing, *, forbidden=(), states=None):
    """Check arrivals and the last held tick before a following switch."""
    window = min(timing.energy_horizon_s, predictor.view.remaining_horizon_s)
    if len(operations) * timing.step_s > window:
        raise ValueError("Sequence cannot finish within the declared planning/session horizon")
    states = states or sequence_states(predictor.view, operations, predictor.network)
    forbidden = set(forbidden)
    steps, reason, checked = [], None, 0
    if predictor.view.measured_overloads and (
        not operations or not correction_progress(predictor.view, states[1], predictor.network)
    ):
        result = predictor.evaluate(states[0])
        return {
            "feasible": False,
            "reason": "The first switch must reduce the load exposure of fresh measured overloads",
            "steps": [{"operation": None, "offset_s": 0, "prediction": result}],
            "checked_operations": 0,
            "completion_offset_s": len(operations) * timing.step_s,
        }
    if not operations:
        result = predictor.evaluate(states[0])
        steps.append({"operation": None, "offset_s": 0, "prediction": result})
        if (
            not result["feasible"]
            or position_key(states[0], predictor.network) in forbidden
            or blocked_exposure(predictor.view, states[0], predictor.network)
        ):
            reason = "Holding is not feasible under the tested received evidence"
    for index, (operation, state) in enumerate(zip(operations, states[1:], strict=True)):
        arrival = index * timing.step_s + timing.actuation_delay_s
        confirmation = (index + 1) * timing.step_s
        last_held = (index + 1) * timing.step_s + timing.actuation_delay_s - 1
        end = last_held if index + 1 < len(operations) else confirmation
        valid = True
        for offset in sorted({arrival, end}):
            result = predictor.evaluate(state, offset)
            steps.append(
                {
                    "operation": operation.model_dump(mode="json"),
                    "offset_s": offset,
                    "prediction": result,
                }
            )
            if (
                not result["feasible"]
                or position_key(state, predictor.network) in forbidden
                or blocked_exposure(predictor.view, state, predictor.network)
            ):
                reason = (
                    "A future switching state fails sampled electrical or observed-safety checks"
                )
                valid = False
                break
        if not valid:
            break
        checked += 1
    return {
        "feasible": reason is None and checked == len(operations),
        "reason": reason,
        "steps": steps,
        "checked_operations": checked,
        "completion_offset_s": len(operations) * timing.step_s,
    }


def energy_prediction(predictor, states, timing):
    """Nominal service over one common window; terminal points have zero duration."""
    window = min(timing.energy_horizon_s, predictor.view.remaining_horizon_s)
    arrivals = [0, *(i * timing.step_s + timing.actuation_delay_s for i in range(len(states) - 1))]
    intervals, lost, critical_lost, known = [], 0.0, 0.0, True
    critical_demand = sum(
        predictor.view.demand_kw[load["id"]] * predictor.view.state.load_factors[load["feeder"]]
        for load in predictor.network["loads"]
        if load["critical"]
    )
    for index, state in enumerate(states):
        begin = arrivals[index]
        end = arrivals[index + 1] if index + 1 < len(arrivals) else window
        if end <= begin:
            continue
        result = predictor.nominal(state)
        valid = result["converged"] and all(
            result[k] is not None for k in ("requested_kw", "served_kw", "critical_kw")
        )
        unserved = max(0, result["requested_kw"] - result["served_kw"]) if valid else None
        critical = max(0, critical_demand - result["critical_kw"]) if valid else None
        known = known and valid
        if valid:
            lost += unserved * (end - begin) / 3600
            critical_lost += critical * (end - begin) / 3600
        intervals.append(
            {
                "start_offset_s": begin,
                "end_offset_s": end,
                "predicted_served_kw": result["served_kw"] if valid else None,
                "predicted_critical_kw": result["critical_kw"] if valid else None,
                "predicted_unserved_kw": unserved,
            }
        )
    return {
        "horizon_s": window,
        "completion_s": (len(states) - 1) * timing.step_s,
        "critical_unserved_kwh": critical_lost if known else None,
        "unserved_kwh": lost if known else None,
        "known": known,
        "intervals": intervals,
        "basis": "Held received means with assumed successful switching; future measurements, repairs and demand events are unknown",
    }


def combined_prediction(checked, nominal):
    predictions = [step["prediction"] for step in checked["steps"]]
    last = predictions[-1]
    return {
        **last,
        "nominal": nominal,
        "feasible": checked["feasible"],
        "samples_checked": sum(r["samples_checked"] for r in predictions),
        "samples_required": sum(r["samples_required"] for r in predictions),
        "worst_loading_pct": max(
            (r["worst_loading_pct"] for r in predictions if r["worst_loading_pct"] is not None),
            default=None,
        ),
        "violations": [v for r in predictions for v in r["violations"]],
    }


def structural_plans(view, network, max_operations, blocked):
    """Keep ordered paths: identical final positions can have different service loss."""
    paths, rejected = [], []
    transitions = {}
    stack = [(view.state, (), (view.state,))]
    while stack:
        state, operations, states = stack.pop()
        paths.append((state, operations, states))
        if len(operations) >= max_operations:
            continue
        for operation in reversed(
            choices(state, network, {o.equipment for o in operations}, blocked)
        ):
            key = (position_key(state, network), operation.key)
            try:
                if key not in transitions:
                    try:
                        transitions[key] = change_position(state, operation, network)
                    except ValueError as exc:
                        transitions[key] = str(exc)
                changed = transitions[key]
                if isinstance(changed, str):
                    raise ValueError(changed)
            except ValueError as exc:
                if len(rejected) < 24:
                    rejected.append(
                        {"operation": operation.model_dump(mode="json"), "reason": str(exc)}
                    )
                continue
            stack.append((changed, (*operations, operation), (*states, changed)))
    return paths, rejected


def service_upper_bound(view, state, network):
    """Connectivity bounds capped service; it never establishes electrical feasibility."""
    live = energized(state, network)
    critical, total = 0.0, 0.0
    for load in network["loads"]:
        if load_connected(state, load, live):
            demand = view.demand_kw[load["id"]] * state.load_factors[load["feeder"]]
            total += demand
            if load["critical"]:
                critical += demand
    return critical, total


def optimistic_rank(view, operations, states, timing, network, upper_cache=None):
    """Lower objective bound from connectivity and capped service, without a solve."""
    window = min(timing.energy_horizon_s, view.remaining_horizon_s)
    requested = sum(
        view.demand_kw[r["id"]] * view.state.load_factors[r["feeder"]] for r in network["loads"]
    )
    critical = sum(
        view.demand_kw[r["id"]] * view.state.load_factors[r["feeder"]]
        for r in network["loads"]
        if r["critical"]
    )
    times = [
        0,
        *(i * timing.step_s + timing.actuation_delay_s for i in range(len(operations))),
        window,
    ]
    critical_loss, total_loss = 0.0, 0.0
    upper_cache = {} if upper_cache is None else upper_cache
    for index, state in enumerate(states):
        key = position_key(state, network)
        if key not in upper_cache:
            upper_cache[key] = service_upper_bound(view, state, network)
        upper_critical, upper_total = upper_cache[key]
        duration = times[index + 1] - times[index]
        critical_loss += max(0, critical - upper_critical) * duration / 3600
        total_loss += max(0, requested - upper_total) * duration / 3600
    terminal_critical, terminal_total = upper_cache[position_key(states[-1], network)]
    return (
        -round(terminal_critical, 1),
        round(critical_loss, 8),
        round(total_loss, 8),
        -round(terminal_total, 1),
        len(operations),
        0.0,
        tuple(operation.key for operation in operations),
    )


def plan(
    view,
    policy,
    *,
    budget=2048,
    max_operations=3,
    engine=None,
    goal="restore",
    blocked=(),
    forbidden=(),
    timing=None,
):
    """Ordered bounded search, safe service-bound pruning and exact native reuse."""
    network = load_network()
    timing = timing or PlanningTiming()
    window = min(timing.energy_horizon_s, view.remaining_horizon_s)
    max_operations = min(max_operations, window // timing.step_s)
    predictor = Predictor(view, policy, budget, engine, network)
    paths, rejected = structural_plans(view, network, max_operations, blocked)
    sequence_count = len(paths)
    normal = tuple(sorted(normal_positions(network).items()))
    forbidden = set(forbidden)
    candidates, exhausted, best, hold, pruned = [], False, None, None, 0
    upper_cache = {}

    def assess(path):
        state, operations, states = path
        nominal = predictor.nominal(state)
        checked = forecast_sequence(
            predictor, operations, timing, forbidden=forbidden, states=states
        )
        predicted = combined_prediction(checked, nominal)
        energy = (
            energy_prediction(predictor, states, timing)
            if checked["feasible"]
            else {
                "horizon_s": window,
                "completion_s": len(operations) * timing.step_s,
                "critical_unserved_kwh": None,
                "unserved_kwh": None,
                "known": False,
                "intervals": [],
                "basis": "Inadmissible or incomplete sequence; no energy credit assigned",
            }
        )
        return {
            "operations": [o.model_dump(mode="json") for o in operations],
            "prediction": predicted,
            "energy": energy,
            "normal_configuration": position_key(state, network) == normal,
            "known_unsafe": position_key(state, network) in forbidden
            or blocked_exposure(view, state, network),
            "timeline": checked["steps"],
            "checked_operations": checked["checked_operations"],
            "completion_offset_s": checked["completion_offset_s"],
            "rejection_reason": checked["reason"],
        }

    try:
        hold = assess(paths[0])
        candidates.append(hold)
        if hold["prediction"]["feasible"] and (goal != "normal" or hold["normal_configuration"]):
            best = hold
        base = hold["prediction"]["nominal"]
        paths = sorted(
            paths[1:], key=lambda p: optimistic_rank(view, p[1], p[2], timing, network, upper_cache)
        )
        for path in paths:
            key = position_key(path[0], network)
            if goal == "normal" and key != normal:
                continue
            if best and optimistic_rank(
                view, path[1], path[2], timing, network, upper_cache
            ) > rank(best):
                pruned += 1
                continue
            candidate = assess(path)
            candidates.append(candidate)
            result = candidate["prediction"]["nominal"]
            if not candidate["prediction"]["feasible"]:
                continue
            if goal == "normal" and (
                result["critical_kw"] + 0.1 < (base["critical_kw"] or 0)
                or result["served_kw"] + 0.1 < (base["served_kw"] or 0)
            ):
                continue
            if best is None or rank(candidate) < rank(best):
                best = candidate
    except BudgetExhausted:
        exhausted = True
    selected, success = (best or hold), best is not None
    reason = (
        (
            "Checked return to normal; terminal service retained and transition loss compared"
            if goal == "normal"
            else "Critical supply prioritized; switching-delay and unserved-energy costs compared"
        )
        if success
        else "No checked plan satisfies the goal; hold and inspect constraints"
    )
    if exhausted:
        reason += "; native evaluation budget exhausted"
    return {
        "goal": goal,
        "policy": policy,
        "objective": OBJECTIVE,
        "reason": reason,
        "selected": selected,
        "feasible_choice": success,
        "candidates": candidates,
        "structural_rejections": rejected,
        "budget": budget,
        "native_evaluations": predictor.solves,
        "native_cache_hits": predictor.cache_hits,
        "budget_exhausted": exhausted,
        "max_operations": max_operations,
        "structural_sequences": sequence_count,
        "service_bound_pruned": pruned,
        "search_complete": not exhausted,
        "uncertainty_samples": predictor.samples,
        "timing": timing.model_dump(mode="json"),
        "energy_horizon_s": window,
        "forecast_assumption": "Held bounds age without future measurement refresh; sampled time points, not a continuous guarantee",
        "measured_overloads": list(view.measured_overloads),
        "unsafe_exposures": list(view.unsafe_exposures),
        "input": view.model_dump(mode="json"),
    }


def check_sequence(
    view, operations, policy, *, budget=2048, engine=None, forbidden=(), timing=None
):
    predictor = Predictor(view, policy, budget, engine)
    timing = timing or PlanningTiming()
    try:
        result = forecast_sequence(predictor, operations, timing, forbidden=forbidden)
    except (ValueError, BudgetExhausted) as exc:
        result = {
            "feasible": False,
            "reason": str(exc) or "Native evaluation budget exhausted during revalidation",
            "steps": [],
            "checked_operations": 0,
            "completion_offset_s": len(operations) * timing.step_s,
        }
    return {
        **result,
        "native_evaluations": predictor.solves,
        "timing": timing.model_dump(mode="json"),
    }


def dense_samples(view, levels=(0.0, 0.5, 1.0)):
    """Finite joint reference grid, not a proof over a continuous uncertainty box."""
    keys = sorted(view.bounds_kw)
    return [
        {
            k: view.bounds_kw[k][0] + fraction * (view.bounds_kw[k][1] - view.bounds_kw[k][0])
            for k, fraction in zip(keys, fractions, strict=True)
        }
        for fractions in product(levels, repeat=len(keys))
    ]
