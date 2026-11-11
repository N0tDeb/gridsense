"""Fixed-horizon physical outcomes; unknown intervals never count as service."""

from .domain import Record


class EpisodeMetrics(Record):
    known_seconds: int = 0
    unknown_seconds: int = 0
    requested_kwh: float = 0
    served_kwh: float = 0
    critical_served_kwh: float = 0
    feasible_served_kwh: float = 0
    feasible_critical_served_kwh: float = 0
    unserved_kwh: float = 0
    violation_ticks: int = 0
    first_interruption_s: int | None = None
    first_full_recovery_s: int | None = None
    actuation_attempts: int = 0
    position_changes: int = 0

    @property
    def first_recovery_delay_s(self):
        if self.first_interruption_s is None or self.first_full_recovery_s is None:
            return None
        return self.first_full_recovery_s - self.first_interruption_s


def integrate_interval(metrics, previous):
    """Previous solved state is held over [t-1,t); final sample has zero duration."""
    if previous is None:
        return metrics.model_copy(update={"unknown_seconds": metrics.unknown_seconds + 1})
    fields = {
        "requested_kwh": "requested_kw",
        "served_kwh": "served_kw",
        "critical_served_kwh": "critical_served_kw",
        "unserved_kwh": "unserved_kw",
    }
    changes = {
        key: getattr(metrics, key) + previous[source] / 3600 for key, source in fields.items()
    }
    changes["known_seconds"] = metrics.known_seconds + 1
    # This is deliberately a whole-state compliance metric, not a claim that
    # every supplied customer is unsafe when one line is overloaded.
    if previous["feasible"]:
        changes["feasible_served_kwh"] = metrics.feasible_served_kwh + previous["served_kw"] / 3600
        changes["feasible_critical_served_kwh"] = (
            metrics.feasible_critical_served_kwh + previous["critical_served_kw"] / 3600
        )
    return metrics.model_copy(update=changes)


def observe_outcome(metrics, electrical, at_s):
    if electrical is None:
        return metrics
    changes = {"violation_ticks": metrics.violation_ticks + int(not electrical["feasible"])}
    interrupted = electrical["unserved_kw"] > 0.1 or not electrical["feasible"]
    if interrupted and metrics.first_interruption_s is None:
        changes["first_interruption_s"] = at_s
    if (
        not interrupted
        and metrics.first_interruption_s is not None
        and metrics.first_full_recovery_s is None
    ):
        changes["first_full_recovery_s"] = at_s
    return metrics.model_copy(update=changes)
