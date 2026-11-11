"""Headless native snapshots: transformer trip, MV transfer, repair and reconnection.

Run from the project root: python examples/equipment_availability.py
These explicit state transitions are not a live clock or an automatic controller.
"""

import json

from gridsense.domain import Action, EquipmentOutage, Operation
from gridsense.electrical import ElectricalEngine
from gridsense.network import healthy_state, isolate_outage, repair_outage


def main():
    engine = ElectricalEngine()
    state = healthy_state({"a": 1, "b": 0.7, "c": 0.9})
    records = []

    def record(name):
        result = engine.solve(state)
        if not result.feasible:
            raise RuntimeError(f"{name}: {result.violations}")
        records.append(
            {"step": name, "state": state.model_dump(), "electrical": result.model_dump()}
        )

    record("Healthy supply")
    state = isolate_outage(
        state,
        EquipmentOutage(incident_id="medical-transformer", kind="transformer", equipment="tx_a1"),
    )
    record("Transformer unavailable and isolated")
    transfer = engine.execute(
        state,
        Action(
            id="transfer",
            label="Transfer MV supply",
            operations=(
                Operation(line="feed_a", closed=False),
                Operation(line="tie_c", closed=True),
            ),
        ),
    )
    if not transfer.result.feasible:
        raise RuntimeError("MV transfer failed an intermediate or final check")
    state = transfer.final_state
    record("MV transfer cannot bypass the unavailable LV transformer")
    state = repair_outage(state, "medical-transformer")
    record("Repair complete; transformer remains isolated")
    state = state.model_copy(update={"open_transformers": ()})
    record("Explicit transformer reconnection; supply checked")
    returned = engine.execute(
        state,
        Action(
            id="normal",
            label="Break before make",
            operations=(
                Operation(line="tie_c", closed=False),
                Operation(line="feed_a", closed=True),
            ),
        ),
    )
    if not returned.result.feasible:
        raise RuntimeError("Return-to-normal sequence failed an intermediate or final check")
    state = returned.final_state
    record("Normal feeder configuration")
    print(
        json.dumps(
            {
                "scope": "Steady-state snapshots with explicit trip/repair inputs; no transient or live-session claim",
                "steps": records,
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
