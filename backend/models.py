"""Version 1 wire contracts. Numbers are finite; unknown fields are rejected."""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

SCHEMA_VERSION = "1.0.0"
ID = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
NonNegative = Annotated[FiniteFloat, Field(ge=0)]
Positive = Annotated[FiniteFloat, Field(gt=0)]
Series = Annotated[list[NonNegative], Field(min_length=1, max_length=24)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


class Provenance(Model):
    observed_source_urls: list[str] = []
    observed_fields: list[str] = []
    derived_fields: list[str] = []
    synthetic_fields: list[str] = []
    historical_event_date: str | None = None
    source_timezone: str = "America/Santiago"
    notes: str
    evidence_id: ID | None = None
    gaps: list[str] = []


class Node(Model):
    id: ID
    label: str = Field(max_length=160)


class Line(Model):
    id: ID
    from_node: ID = Field(alias="from")
    to: ID
    capacity_mw: Positive


class Generator(Model):
    id: ID
    node_id: ID
    technology: Literal["solar", "wind", "thermal", "hydro"]
    capacity_mw: Positive
    variable_cost_usd_per_mwh: NonNegative


class Battery(Model):
    id: ID
    node_id: ID
    power_capacity_mw: Positive
    energy_capacity_mwh: Positive
    initial_soc_mwh: NonNegative
    final_soc_mwh: NonNegative
    final_soc_policy: Literal["equal", "at_least"] = "equal"
    round_trip_efficiency: Annotated[FiniteFloat, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def capacity(self):
        if max(self.initial_soc_mwh, self.final_soc_mwh) > self.energy_capacity_mwh:
            raise ValueError("SOC exceeds battery energy capacity")
        return self


class Scenario(Model):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    scenario_id: ID
    mode: Literal["synthetic", "historically_anchored_simulation"]
    network_model: Literal["transport"] = "transport"
    time_step_hours: Annotated[FiniteFloat, Field(gt=0, le=24)]
    timestamps_utc: list[datetime] = Field(min_length=1, max_length=24)
    provenance: Provenance
    nodes: list[Node] = Field(min_length=2, max_length=6)
    lines: list[Line] = Field(min_length=1, max_length=7)
    generators: list[Generator] = Field(min_length=1, max_length=6)
    batteries: list[Battery] = Field(max_length=2)
    demand_mw_by_node: dict[str, Series]
    renewable_availability_mw_by_generator: dict[str, Series]
    curtailment_penalty_usd_per_mwh: NonNegative = 1
    battery_throughput_cost_usd_per_mwh: NonNegative = 0
    load_shedding_penalty_usd_per_mwh: Positive = 10000

    @model_validator(mode="after")
    def consistency(self):
        n = len(self.timestamps_utc)
        for t in self.timestamps_utc:
            if t.tzinfo is None or t.utcoffset() != timedelta(0):
                raise ValueError("timestamps_utc must have UTC offset")
        for a, b in zip(self.timestamps_utc, self.timestamps_utc[1:]):
            if b - a != timedelta(hours=self.time_step_hours):
                raise ValueError("timestamps must be contiguous interval starts")
        for assets in (self.nodes, self.lines, self.generators, self.batteries):
            if len({x.id for x in assets}) != len(assets):
                raise ValueError("duplicate asset ID")
        nodes = {x.id for x in self.nodes}
        if set(self.demand_mw_by_node) != nodes:
            raise ValueError("demand must cover exactly the scenario nodes")
        for line in self.lines:
            if line.from_node not in nodes or line.to not in nodes or line.from_node == line.to:
                raise ValueError("invalid line endpoints")
        for asset in [*self.generators, *self.batteries]:
            if asset.node_id not in nodes:
                raise ValueError("asset references unknown node")
        renewables = {g.id: g for g in self.generators if g.technology in ("solar", "wind")}
        if set(self.renewable_availability_mw_by_generator) != set(renewables):
            raise ValueError("availability must cover exactly solar/wind generators")
        for key, values in self.renewable_availability_mw_by_generator.items():
            if any(v > renewables[key].capacity_mw for v in values):
                raise ValueError("renewable availability exceeds rated capacity")
        for values in [
            *self.demand_mw_by_node.values(),
            *self.renewable_availability_mw_by_generator.values(),
        ]:
            if len(values) != n:
                raise ValueError("time series length does not match horizon")
        if self.mode == "historically_anchored_simulation" and not self.provenance.evidence_id:
            raise ValueError("historical context requires an evidence ID")
        groups = [
            set(self.provenance.observed_fields),
            set(self.provenance.derived_fields),
            set(self.provenance.synthetic_fields),
        ]
        if any(groups[i] & groups[j] for i in range(3) for j in range(i)):
            raise ValueError("field provenance categories must not overlap")
        return self


class Options(Model):
    battery_policy: Literal["disabled", "optimised"] = "optimised"
    allow_load_shedding: bool = False


class RunRequest(Model):
    scenario_id: ID
    execution_mode: Literal["live", "replay"] = "live"
    settings: Options = Field(default_factory=Options)


class SolveRequest(Model):
    scenario_id: ID
    options: Options = Field(default_factory=Options)


class Solution(Model):
    status: Literal["optimal", "infeasible", "failed"]
    generation_mw_by_generator: dict[str, list[FiniteFloat]] = {}
    curtailment_mw_by_generator: dict[str, list[FiniteFloat]] = {}
    line_flows_mw_by_line: dict[str, list[FiniteFloat]] = {}
    charge_mw_by_battery: dict[str, list[FiniteFloat]] = {}
    discharge_mw_by_battery: dict[str, list[FiniteFloat]] = {}
    soc_mwh_by_battery: dict[str, list[FiniteFloat]] = {}
    load_shedding_mw_by_node: dict[str, list[FiniteFloat]] = {}
    reason: str | None = Field(default=None, max_length=1000)
    native_result: dict | None = None


class ValidateRequest(SolveRequest):
    solution: Solution


class Metrics(Model):
    curtailed_energy_mwh: NonNegative
    assumed_cost_usd: NonNegative
    unserved_energy_mwh: NonNegative


class Validation(Model):
    passed: bool
    violations: list[str]
    max_residual_mw: NonNegative
    metrics: Metrics | None = None

    @model_validator(mode="after")
    def honest(self):
        if self.passed and (self.violations or self.metrics is None):
            raise ValueError("passed validation requires metrics and no violations")
        return self


class ToolEvent(Model):
    tool: str = Field(min_length=1, max_length=100)
    status: Literal["started", "success", "failed", "retry"]
    timestamp_utc: datetime | None = None
    execution_mode: Literal["live", "replay"] | None = None
    live_gemini: bool | None = None
    note: str | None = Field(default=None, max_length=2000)
    scope: str | None = Field(default=None, max_length=200)
    input_summary: str | None = Field(default=None, max_length=2000)
    output_summary: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def utc_timestamp(self):
        if self.timestamp_utc is not None and (
            self.timestamp_utc.tzinfo is None or self.timestamp_utc.utcoffset() != timedelta(0)
        ):
            raise ValueError("tool timestamp must be UTC")
        return self


class OperatorReport(Model):
    summary: str = Field(max_length=6000)
    sources: list[str] = Field(max_length=30)
    assumptions: list[str] = Field(max_length=30)
    limitations: list[str] = Field(max_length=30)


class ModelExecution(Model):
    provider: Literal["google"]
    model: str = Field(min_length=1, max_length=100)
    response_id: str = Field(min_length=1, max_length=200)


class AgentResult(Model):
    """Agent output is untrusted until backend independently validates both solutions."""

    baseline: Solution
    candidate: Solution
    tool_trace: list[ToolEvent] = Field(min_length=1, max_length=100)
    operator_report: OperatorReport
    model_execution: ModelExecution | None = None


class Decision(Model):
    decision: Literal["approved", "rejected"]
    expected_revision: int = Field(ge=0)
    operator: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=1000)


class DispatchResult(Model):
    solution: Solution
    valid: bool
    metrics: Metrics | None

    @model_validator(mode="after")
    def coherent_validation(self):
        if self.valid and (self.solution.status != "optimal" or self.metrics is None):
            raise ValueError("valid dispatch requires an optimal solution and verified metrics")
        if not self.valid and self.metrics is not None:
            raise ValueError("invalid dispatch cannot expose accepted metrics")
        return self


class Comparison(Model):
    curtailment_reduction_mwh: FiniteFloat
    assumed_cost_delta_usd: FiniteFloat
    unserved_energy_delta_mwh: FiniteFloat


class RunValidation(Model):
    passed: bool
    violations: list[str]
    max_residual_mw: NonNegative
    baseline: Validation | None = None
    candidate: Validation | None = None


class SolveResponse(Model):
    status: Literal["optimal", "infeasible", "failed"]
    solution: Solution
    validation: Validation


class ScenarioList(Model):
    schema_version: Literal["1.0.0"]
    scenarios: list[Scenario]


class RunDocument(Model):
    schema_version: Literal["1.0.0"]
    run_id: str
    scenario_id: ID
    execution_mode: Literal["live", "replay"]
    status: Literal["queued", "running", "completed", "failed"]
    created_at: datetime
    updated_at: datetime
    revision: int
    approval_status: Literal["unavailable", "pending", "approved", "rejected"]
    tool_trace: list[ToolEvent]
    baseline: DispatchResult | None
    candidate: DispatchResult | None
    comparison: Comparison | None
    validation: RunValidation
    operator_report: dict | None
    error: dict | None
    provenance: dict | None = None
    scenario_snapshot: Scenario | None = None
    historical_evidence: dict | None = None
    decision: dict | None = None

    @model_validator(mode="after")
    def completed_requires_verified_outputs(self):
        if self.status == "completed":
            if (
                not self.validation.passed
                or self.validation.violations
                or self.baseline is None
                or self.candidate is None
                or not self.baseline.valid
                or not self.candidate.valid
                or self.baseline.metrics is None
                or self.candidate.metrics is None
                or self.comparison is None
                or self.approval_status == "unavailable"
            ):
                raise ValueError(
                    "completed run requires verified baseline, candidate and comparison"
                )
        elif self.approval_status != "unavailable":
            raise ValueError("non-completed runs cannot receive approval")
        return self


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def wire(model: BaseModel):
    return model.model_dump(mode="json", by_alias=True)
