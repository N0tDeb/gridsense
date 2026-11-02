"""Portable experiment inputs: expectations are separate from recorded outputs."""

from typing import Literal
from pydantic import Field, model_validator
from .domain import Record, Scenario


class ServiceContract(Record):
    minimum_restored_kw: float = Field(default=990, ge=0, le=20000)
    minimum_critical_kw: float = Field(default=395, ge=0, le=20000)


class PortableCase(Record):
    schema_version: Literal[1] = 1
    title: str = Field(default="Reduced stale-demand regression", min_length=1, max_length=100)
    feeder: Literal["teaching", "ieee13"] = "teaching"
    fault: str = "feed_a"
    scenario: Scenario = Field(
        default_factory=lambda: Scenario(load_b=1.15, reported_b=0.85, load_c=1, uncertainty_pct=40)
    )
    contract: ServiceContract = Field(default_factory=ServiceContract)
    origin: str = Field(default="Curated from the v0.2 reduced failure", max_length=300)

    @model_validator(mode="after")
    def compatible_fault(self):
        valid = {"teaching": {"feed_a", "seg_a"}, "ieee13": {"632670", "671692"}}
        if self.fault not in valid[self.feeder]:
            raise ValueError("Fault is not supported by this versioned feeder adapter")
        if (
            self.feeder == "ieee13"
            and self.scenario.telemetry_age_s == 0
            and self.scenario.load_a != self.scenario.reported_b
        ):
            raise ValueError(
                "IEEE13 fresh aggregate demand must equal its actual multiplier (load_a)"
            )
        return self


class RegressionInput(Record):
    case: PortableCase = Field(default_factory=PortableCase)
    baseline: Literal["nominal-v1", "guarded-v1", "hold-v1"] = "nominal-v1"
    candidate: Literal["nominal-v1", "guarded-v1", "hold-v1"] = "guarded-v1"


def case_from_incident(incident: dict) -> PortableCase:
    """Import inputs only. Never describe this as reproducing the old controller."""
    scenario = Scenario.model_validate(incident["scenario"])
    return PortableCase(
        title=scenario.title,
        scenario=scenario,
        contract=ServiceContract(
            minimum_restored_kw=990 * scenario.load_a, minimum_critical_kw=395 * scenario.load_a
        ),
        origin=f"Imported inputs from incident {incident['id']}; service contract is editable",
    )


def presets() -> list[dict]:
    return [
        PortableCase().model_dump(mode="json"),
        PortableCase(
            title="Fresh demand control",
            scenario=Scenario(
                load_b=0.7, reported_b=0.7, load_c=1.1, telemetry_age_s=0, uncertainty_pct=0
            ),
            origin="Negative control: no stale demand",
        ).model_dump(mode="json"),
        PortableCase(
            title="IEEE13 modified feeder · downstream fault",
            feeder="ieee13",
            fault="671692",
            scenario=Scenario(
                load_a=0.8,
                load_b=0.8,
                reported_b=0.8,
                load_c=1,
                telemetry_age_s=0,
                uncertainty_pct=0,
            ),
            contract=ServiceContract(minimum_restored_kw=750, minimum_critical_kw=380),
            origin="Published electrical model with documented experimental ties and ratings",
        ).model_dump(mode="json"),
    ]
