"""Full-demand-key reference for native reuse experiments.

Every demand value participates in the cache key, including disabled loads.
This retains the reference calculation for comparison; it is not a controller option.
"""

from copy import deepcopy

from dss import DSSException

from gridsense.electrical import InvalidSwitching
from gridsense.restoration import BudgetExhausted, Predictor


class FullDemandPredictor(Predictor):
    def _solve(self, state, demand):
        key = (state.model_dump_json(), tuple(sorted(demand.items())))
        if key in self.native_cache:
            self.cache_hits += 1
            return self.native_cache[key]
        if self.solves >= self.budget:
            raise BudgetExhausted
        model = deepcopy(self.network)
        for load in model["loads"]:
            load["kw"] = demand[load["id"]]
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
        return outcome
