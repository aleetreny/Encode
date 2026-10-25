"""Version 2: native numerical contract for interventions and crisis recovery."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.models import ID, Model, NonNegative, Positive


class Outage(Model):
    type: Literal["generator_outage", "line_outage"]
    id: ID
    from_hour: int = Field(ge=0, le=23)
    to_hour: int = Field(gt=0, le=24)
    mode: Literal["planned", "sudden"] = "sudden"

    @model_validator(mode="after")
    def interval(self):
        if self.to_hour <= self.from_hour:
            raise ValueError("outage must have a nonempty half-open interval")
        return self


class AddBattery(Model):
    type: Literal["add_battery"]
    node_id: ID
    power_mw: Positive
    energy_mwh: Positive


class UprateLine(Model):
    type: Literal["uprate_line"]
    line_id: ID
    new_capacity_mw: Positive


Modification = Annotated[AddBattery | UprateLine, Field(discriminator="type")]


class Candidate(Model):
    candidate_id: ID
    modifications: list[Modification] = Field(min_length=1, max_length=2)
    description: str = Field(default="", max_length=1000)


class NativeOptions(Model):
    allow_unserved: bool = True
    time_limit_s: Annotated[Positive, Field(le=60)] = 20


class HouseholdMapping(Model):
    households_per_mw: Annotated[Positive, Field(le=10000)] = 1000
    residential_share_by_node: dict[str, Annotated[NonNegative, Field(le=1)]]
    classification: Literal["synthetic_assumption"] = "synthetic_assumption"
    interpretation: str = (
        "Residential-equivalent load; not identified customers or actual feeder reconnections."
    )


class NativeScenario(Model):
    schema_version: Literal["2.0.0"] = "2.0.0"
    scenario_id: ID
    mode: Literal["synthetic", "historically_anchored_simulation"]
    time_step_hours: Annotated[Positive, Field(le=24)]
    timestamps_utc: list[datetime] = Field(min_length=1, max_length=24)
    display_timezone: Literal["America/Santiago"] = "America/Santiago"
    provenance: dict
    nodes: list[dict] = Field(min_length=2, max_length=6)
    lines: list[dict] = Field(min_length=1, max_length=7)
    generators: list[dict] = Field(min_length=1, max_length=12)
    batteries: list[dict] = Field(max_length=4)
    demand_mw_by_node: dict[str, list[NonNegative]]
    renewable_availability_mw_by_generator: dict[str, list[NonNegative]]
    objective: dict[str, NonNegative]
    events: list[Outage] = Field(default_factory=list, max_length=2)
    modification_limits: dict = Field(default_factory=dict)
    household_mapping: HouseholdMapping
    regulatory_framework: list[dict] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def check(self):
        for value in self.timestamps_utc:
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("timestamps must be UTC interval starts")
        for a, b in zip(self.timestamps_utc, self.timestamps_utc[1:]):
            if b - a != timedelta(hours=self.time_step_hours):
                raise ValueError("time axis must be contiguous")
        from optimisation.scenario import build_grid
        from backend.models import wire

        grid = build_grid(wire(self))
        if set(self.household_mapping.residential_share_by_node) != set(grid.node_ids):
            raise ValueError("residential shares must cover exactly the model nodes")
        return self


class NativeScenarioResponse(NativeScenario):
    modification_menu: dict


class NativeSolveRequest(Model):
    scenario_id: ID = "chile-sen-5node-demo"
    candidate: Candidate | None = None
    events: list[Outage] = Field(default_factory=list, max_length=2)
    options: NativeOptions = Field(default_factory=NativeOptions)


class NativeValidateRequest(Model):
    scenario_id: ID = "chile-sen-5node-demo"
    solution: dict
    candidate: Candidate | None = None
    events: list[Outage] | None = Field(default=None, max_length=2)
    options: NativeOptions | None = None


class NativeCompareRequest(Model):
    scenario_id: ID = "chile-sen-5node-demo"
    baseline: dict
    candidate: dict


class NativeSolution(Model):
    status: Literal["optimal", "infeasible", "error"]
    message: str | None
    scenario_id: str
    candidate_id: str
    modifications: list[dict]
    events: list[dict]
    options: dict
    time_step_hours: Positive | None
    timestamps_utc: list[str] | None
    solver: dict
    objective: dict | None
    assets: dict | None
    timeseries: dict | None
    metrics: dict | None
    binding_constraints: list[dict] | None
    validation: dict
    accepted: bool

    @model_validator(mode="after")
    def accepted_requires_validation(self):
        if self.accepted and (
            self.status != "optimal" or not self.validation.get("passed") or self.metrics is None
        ):
            raise ValueError("accepted native dispatch requires independent validation and metrics")
        return self


class InvestigationSettings(Model):
    candidates: list[Candidate] | None = Field(default=None, max_length=4)
    crisis_events: list[Outage] | None = Field(default=None, max_length=2)
    options: NativeOptions = Field(default_factory=NativeOptions)
    allow_cached_fallback: bool = True


class NativeRunRequest(Model):
    scenario_id: ID = "chile-sen-5node-demo"
    execution_mode: Literal["live", "replay", "deterministic"] = "live"
    governance_mode: Literal["operator_approval", "autonomous_sced_with_audit_gate"] = (
        "operator_approval"
    )
    settings: InvestigationSettings = Field(default_factory=InvestigationSettings)


class NativeRunDocument(Model):
    schema_version: Literal["2.0.0"]
    run_id: str
    scenario_id: ID
    execution_mode: Literal["live", "replay", "deterministic"]
    requested_execution_mode: str | None = None
    governance_mode: Literal["operator_approval", "autonomous_sced_with_audit_gate"]
    status: Literal["queued", "running", "completed", "failed", "infeasible"]
    created_at: datetime
    updated_at: datetime
    revision: int
    approval_status: Literal["unavailable", "pending", "approved", "rejected"]
    tool_trace: list[dict]
    baseline: dict | None
    candidate: dict | None
    comparison: dict | None
    crisis_analysis: dict | None = None
    candidate_evaluations: list[dict] = Field(default_factory=list)
    validation: dict
    operator_report: dict | None
    error: dict | None
    provenance: dict | None = None
    scenario_snapshot: dict | None = None
    historical_evidence: dict | None = None
    governance: dict | None = None
    decision: dict | None = None
    fallback: dict | None = None

    @model_validator(mode="after")
    def verified_completion(self):
        if self.status == "completed":
            if (
                not self.validation.get("passed")
                or not self.baseline
                or not self.candidate
                or not self.comparison
                or not self.crisis_analysis
            ):
                raise ValueError(
                    "completed crisis investigation requires verified normal and crisis outputs"
                )
            if self.approval_status == "unavailable" or not self.comparison.get("comparable"):
                raise ValueError(
                    "completed comparison must be comparable and available for a decision"
                )
        elif self.approval_status != "unavailable":
            raise ValueError("non-completed investigations cannot receive a decision")
        return self
