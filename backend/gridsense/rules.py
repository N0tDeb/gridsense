"""Auditable sustained-limit rules over delivered rows, never simulator state."""

from pydantic import Field, model_validator

from .domain import Record
from .telemetry import Signal, fresh


class RuleSettings(Record):
    raise_samples: int = Field(default=2, ge=1, le=10, strict=True)
    clear_samples: int = Field(default=3, ge=1, le=10, strict=True)
    voltage_low_pu: float = Field(default=0.95, gt=0, lt=1)
    voltage_high_pu: float = Field(default=1.05, gt=1, le=1.5)
    voltage_reset_margin_pu: float = Field(default=0.01, gt=0, le=0.05)
    loading_limit_pct: float = Field(default=100, gt=0, le=100)
    loading_reset_margin_pct: float = Field(default=2, gt=0, le=20)

    @model_validator(mode="after")
    def reset_bands(self):
        if (
            self.voltage_low_pu + self.voltage_reset_margin_pu
            >= self.voltage_high_pu - self.voltage_reset_margin_pu
        ):
            raise ValueError("Voltage reset bands overlap")
        if self.loading_reset_margin_pct >= self.loading_limit_pct:
            raise ValueError("Loading reset margin must be below its limit")
        return self


class Alarm(Record):
    id: str
    rule: str
    equipment: str
    sensor_id: str
    raised_at_s: int
    explanation: str
    limit: float | bool
    reset_value: float | bool
    unit: str
    trigger_rows: tuple[Signal, ...]
    cleared_at_s: int | None = None
    clear_rows: tuple[Signal, ...] = ()


class RuleTrack(Record):
    last_sequence: int = -1
    violations: tuple[Signal, ...] = ()
    healthy: tuple[Signal, ...] = ()
    active_alarm: str | None = None


class RuleState(Record):
    tracks: dict[str, RuleTrack] = Field(default_factory=dict)
    alarms: dict[str, Alarm] = Field(default_factory=dict)


def definition(row, settings):
    if row.quantity == "voltage_min_pu":
        return (
            "low_voltage",
            settings.voltage_low_pu,
            settings.voltage_low_pu + settings.voltage_reset_margin_pu,
            "below",
            settings.raise_samples,
            settings.clear_samples,
            "Received minimum phase voltage is below the configured limit; this does not identify a physical fault cause.",
        )
    if row.quantity == "voltage_max_pu":
        return (
            "high_voltage",
            settings.voltage_high_pu,
            settings.voltage_high_pu - settings.voltage_reset_margin_pu,
            "above",
            settings.raise_samples,
            settings.clear_samples,
            "Received maximum phase voltage is above the configured limit; this does not identify a physical fault cause.",
        )
    if row.quantity == "loading_pct":
        return (
            "overload",
            settings.loading_limit_pct,
            settings.loading_limit_pct - settings.loading_reset_margin_pct,
            "above",
            settings.raise_samples,
            settings.clear_samples,
            "Received winding or line current loading exceeds the declared rating.",
        )
    if row.quantity in {"available", "energized"}:
        return (
            "equipment_unavailable" if row.quantity == "available" else "supply_interrupted",
            False,
            True,
            "false",
            1,
            1,
            "Received equipment status reports unavailable; repair and reconnection are separate."
            if row.quantity == "available"
            else "Received load status reports no supply; this alone does not diagnose its cause.",
        )
    return None


def update_rules(state, latest, received, at_s, policy, settings):
    tracks, alarms, changes = dict(state.tracks), dict(state.alarms), []
    for key, track in list(tracks.items()):
        row = latest.get(key)
        if row is None or not fresh(row, at_s, policy):
            tracks[key] = track.model_copy(update={"violations": (), "healthy": ()})
    for row in received:
        spec = definition(row, settings)
        if spec is None:
            continue
        key, track = row.sensor_id, tracks.get(row.sensor_id, RuleTrack())
        if row.sequence <= track.last_sequence:
            continue
        if not fresh(row, at_s, policy):
            tracks[key] = track.model_copy(
                update={"last_sequence": row.sequence, "violations": (), "healthy": ()}
            )
            continue
        name, limit, reset, comparison, raise_count, clear_count, explanation = spec
        violates = (
            row.value < limit
            if comparison == "below"
            else row.value > limit
            if comparison == "above"
            else row.value is False
        )
        healthy = (
            row.value >= reset
            if comparison == "below"
            else row.value <= reset
            if comparison == "above"
            else row.value is True
        )
        bad = (*track.violations, row)[-raise_count:] if violates else ()
        good = (*track.healthy, row)[-clear_count:] if healthy else ()
        active = track.active_alarm
        if active is None and len(bad) == raise_count:
            active = f"{key}@{row.sequence}"
            alarm = Alarm(
                id=active,
                rule=name,
                equipment=row.equipment,
                sensor_id=key,
                raised_at_s=at_s,
                explanation=explanation,
                limit=limit,
                reset_value=reset,
                unit=row.unit,
                trigger_rows=bad,
            )
            alarms[active] = alarm
            changes.append({"kind": "raised", "alarm": alarm.model_dump(mode="json")})
        elif active is not None and len(good) == clear_count:
            alarms[active] = alarms[active].model_copy(
                update={"cleared_at_s": at_s, "clear_rows": good}
            )
            changes.append({"kind": "cleared", "alarm": alarms[active].model_dump(mode="json")})
            active, bad, good = None, (), ()
        tracks[key] = RuleTrack(
            last_sequence=row.sequence, violations=bad, healthy=good, active_alarm=active
        )
    return RuleState(tracks=tracks, alarms=alarms), changes
