"""Small-case permutation reference for session plans.

Candidate construction, prefix checks and ranking are separate from production
search. The electrical adapter, observation model and uncertainty samples are
shared; agreement is not independent validation of the feeder physics.
"""

from itertools import permutations

import networkx as nx

from .network import load_network
from .restoration import PlanningTiming, Predictor, section_loads


def enumerate_plans(view, policy, *, max_operations=3, engine=None, goal="restore", timing=None):
    network = load_network()
    timing = timing or PlanningTiming()
    window = min(timing.energy_horizon_s, view.remaining_horizon_s)
    max_operations = min(max_operations, window // timing.step_s)
    lines = {r["id"]: r for r in network["lines"]}
    transformers = {"main", *("tx_" + r["id"] for r in network["loads"])}
    unavailable = {r.kind + ":" + r.equipment for r in view.state.equipment_outages}
    initial = {
        **{"line:" + name: name in view.state.closed_lines for name in lines},
        **{
            "transformer:" + name: name not in view.state.open_transformers for name in transformers
        },
        "source:" + network["source_bus"]: view.state.source_connected,
    }
    normal = {
        **{"line:" + name: not row["normally_open"] for name, row in lines.items()},
        **{"transformer:" + name: True for name in transformers},
        "source:" + network["source_bus"]: True,
    }
    options = sorted(
        asset
        for asset in initial
        if asset not in unavailable
        and (asset.startswith(("line:", "transformer:tx_")) or not initial[asset])
    )
    predictor = Predictor(view, policy, float("inf"), engine, network)
    hold = predictor.evaluate(view.state)
    candidates, sequences, rejected = [], 0, 0
    for length in range(max_operations + 1):
        for sequence in permutations(options, length):
            sequences += 1
            positions, valid, states, steps = dict(initial), True, [view.state], []
            for index, asset in enumerate(sequence):
                positions[asset] = not positions[asset]
                graph = nx.Graph()
                graph.add_nodes_from(row["id"] for row in network["buses"])
                graph.add_edges_from(
                    (row["from_bus"], row["to_bus"])
                    for name, row in lines.items()
                    if positions["line:" + name]
                )
                if not nx.is_forest(graph) or any(
                    positions.get("line:" + name) for name in view.state.locked_open
                ):
                    valid = False
                    break
                state = view.state.model_copy(
                    update={
                        "closed_lines": tuple(
                            sorted(name for name in lines if positions["line:" + name])
                        ),
                        "open_transformers": tuple(
                            sorted(
                                name
                                for name in transformers
                                if not positions["transformer:" + name]
                            )
                        ),
                        "source_connected": positions["source:" + network["source_bus"]],
                    }
                )
                states.append(state)
                if index == 0 and view.measured_overloads:
                    pairs = [
                        (
                            section_loads(view.state, row["equipment"], network),
                            section_loads(state, row["equipment"], network),
                        )
                        for row in view.measured_overloads
                    ]
                    if not all(after <= before for before, after in pairs) or not any(
                        after < before for before, after in pairs
                    ):
                        valid = False
                        break
                if any(
                    section_loads(state, item["equipment"], network) >= set(item["load_ids"])
                    for item in view.unsafe_exposures
                ):
                    valid = False
                    break
                arrival = index * timing.step_s + timing.actuation_delay_s
                end = (
                    (index + 1) * timing.step_s + timing.actuation_delay_s - 1
                    if index + 1 < length
                    else (index + 1) * timing.step_s
                )
                operation = {"equipment": asset, "closed": not initial[asset]}
                for offset in sorted({arrival, end}):
                    result = predictor.evaluate(state, offset)
                    steps.append({"operation": operation, "offset_s": offset, "prediction": result})
                    if not result["feasible"]:
                        valid = False
                        break
                if not valid:
                    break
            if not sequence:
                steps = [{"operation": None, "offset_s": 0, "prediction": hold}]
                valid = (
                    hold["feasible"]
                    and not view.measured_overloads
                    and not any(
                        section_loads(view.state, item["equipment"], network)
                        >= set(item["load_ids"])
                        for item in view.unsafe_exposures
                    )
                )
            if not valid:
                rejected += 1
                continue
            nominal = predictor.nominal(states[-1])
            if goal == "normal" and (
                positions != normal
                or nominal["critical_kw"] + 0.1 < (hold["nominal"]["critical_kw"] or 0)
                or nominal["served_kw"] + 0.1 < (hold["nominal"]["served_kw"] or 0)
            ):
                continue
            predictions = [r["prediction"] for r in steps]
            result = {
                **predictions[-1],
                "nominal": nominal,
                "feasible": True,
                "samples_checked": sum(r["samples_checked"] for r in predictions),
                "samples_required": sum(r["samples_required"] for r in predictions),
                "worst_loading_pct": max(r["worst_loading_pct"] for r in predictions),
                "violations": [v for r in predictions for v in r["violations"]],
            }
            # Independent interval calculation and ranking. Candidate generation
            # does not call production search, pruning, energy or ranking helpers.
            critical_demand = sum(
                view.demand_kw[r["id"]] * view.state.load_factors[r["feeder"]]
                for r in network["loads"]
                if r["critical"]
            )
            lost, critical_lost, known = 0.0, 0.0, True
            times = [
                0,
                *(i * timing.step_s + timing.actuation_delay_s for i in range(length)),
                window,
            ]
            for index, state in enumerate(states):
                seconds = times[index + 1] - times[index]
                if seconds <= 0:
                    continue
                received = predictor.nominal(state)
                if not received["converged"]:
                    known = False
                    continue
                lost += max(0, received["requested_kw"] - received["served_kw"]) * seconds / 3600
                critical_lost += max(0, critical_demand - received["critical_kw"]) * seconds / 3600
            operations = [{"equipment": asset, "closed": not initial[asset]} for asset in sequence]
            score = (
                -round(nominal["critical_kw"], 1),
                round(critical_lost, 8) if known else float("inf"),
                round(lost, 8) if known else float("inf"),
                -round(nominal["served_kw"], 1),
                length,
                result["worst_loading_pct"],
                tuple(asset + (":open" if initial[asset] else ":close") for asset in sequence),
            )
            candidates.append((score, operations, result))
    selected = min(candidates, key=lambda r: r[0]) if candidates else None
    return {
        "operations": selected[1] if selected else [],
        "prediction": selected[2] if selected else hold,
        "feasible_choice": selected is not None,
        "sequences_tried": sequences,
        "rejected_sequences": rejected,
        "native_evaluations": predictor.solves,
        "max_operations": max_operations,
        "goal": goal,
        "timing": timing.model_dump(mode="json"),
        "energy_horizon_s": window,
    }
