"""A simple controller using the public selection interface.

python examples/custom_controller.py
This controller keeps the fault isolated. It passes electrical checks but fails
the minimum restored-service requirement.
"""

import json

from gridsense.cases import PortableCase
from gridsense.regression import evaluate_case


class MaintenanceHold:
    id = "owner-maintenance-hold-v1"

    def select(self, view):
        return next(c.action for c in view.candidates if c.action.id == "hold")


if __name__ == "__main__":
    result = evaluate_case(PortableCase(), MaintenanceHold())
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("controller", "action", "electrical_pass", "service_pass", "passed")
            },
            indent=2,
        )
    )
