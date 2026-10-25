/** v2 control-room client: raw native numerical envelopes and two-stage investigations. */
import { ApiError } from "./client";

export type Outage = {type: "generator_outage" | "line_outage"; id: string; from_hour: number; to_hour: number; mode: "planned" | "sudden"};
export type Candidate = {candidate_id: string; modifications: Array<
  {type: "add_battery"; node_id: string; power_mw: number; energy_mwh: number} |
  {type: "uprate_line"; line_id: string; new_capacity_mw: number}
>; description?: string};
export type NativeOptions = {allow_unserved?: boolean; time_limit_s?: number};
export type NativeSolution = {
  status: "optimal" | "infeasible" | "error"; accepted: boolean;
  scenario_id: string; candidate_id: string; message: string | null;
  timeseries: Record<string, Record<string, number[]>> | null;
  metrics: Record<string, unknown> | null; objective: {total_usd: number; terms: Record<string, number>} | null;
  binding_constraints: Array<Record<string, unknown>> | null;
  validation: {passed: boolean; violations: Array<Record<string, unknown>>; max_residual_mw: number; checks_run: string[]};
  [key: string]: unknown;
};
export type NativeRun = {
  schema_version: "2.0.0"; run_id: string; scenario_id: string; revision: number;
  execution_mode: "live" | "replay" | "deterministic"; requested_execution_mode?: string;
  status: "queued" | "running" | "completed" | "failed" | "infeasible";
  approval_status: "unavailable" | "pending" | "approved" | "rejected";
  baseline: NativeSolution | null; candidate: NativeSolution | null;
  comparison: Record<string, unknown> | null; crisis_analysis: Record<string, unknown> | null;
  validation: {passed: boolean; violations: unknown[]; max_residual_mw: number};
  governance: Record<string, unknown> | null; fallback: Record<string, unknown> | null;
  provenance: {live_gemini: boolean; execution_mode: string; [key: string]: unknown} | null;
  tool_trace: Array<Record<string, unknown>>; [key: string]: unknown;
};
export type InvestigationSettings = {candidates?: Candidate[]; crisis_events?: Outage[]; options?: NativeOptions; allow_cached_fallback?: boolean};

export function nativeGridPilotClient(baseUrl: string, operatorToken = "") {
  const base = baseUrl.replace(/\/$/, "");
  async function request<T>(path: string, body?: unknown, extra: Record<string,string> = {}): Promise<T> {
    const headers = new Headers(extra);
    if (body !== undefined) {
      headers.set("Content-Type", "application/json");
      if (operatorToken) headers.set("Authorization", `Bearer ${operatorToken}`);
    }
    const response = await fetch(base + path, {method: body === undefined ? "GET" : "POST", headers,
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(100_000)});
    if (!response.ok) throw new ApiError(response.status, await response.json());
    return await response.json() as T;
  }
  return {
    scenario: (id = "chile-sen-5node-demo") => request<Record<string,unknown>>(`/api/scenario?scenario_id=${encodeURIComponent(id)}`),
    scenarios: () => request<Record<string,unknown>>("/api/scenarios"),
    optimise: (scenarioId: string, candidate: Candidate | null = null, events: Outage[] = [], options: NativeOptions = {}) =>
      request<NativeSolution>("/api/optimise", {scenario_id:scenarioId,candidate,events,options}),
    validate: (scenarioId: string, solution: NativeSolution) => request<NativeSolution["validation"]>("/api/validate", {scenario_id:scenarioId,solution}),
    compare: (scenarioId: string, baseline: NativeSolution, candidate: NativeSolution) => request<Record<string,unknown>>("/api/compare", {scenario_id:scenarioId,baseline,candidate}),
    start: (executionMode: "live" | "replay" | "deterministic", settings: InvestigationSettings = {}, governanceMode = "operator_approval", scenarioId = "chile-sen-5node-demo", key = crypto.randomUUID()) =>
      request<NativeRun>("/api/agent/run", {scenario_id:scenarioId,execution_mode:executionMode,settings,governance_mode:governanceMode}, {"Idempotency-Key":key}),
    run: (id: string) => request<NativeRun>(`/api/agent/runs/${encodeURIComponent(id)}`),
    decision: (run: NativeRun, decision: "approved" | "rejected", operator: string, note = "") =>
      request<NativeRun>(`/api/agent/runs/${encodeURIComponent(run.run_id)}/decision`, {decision,operator,note,expected_revision:run.revision}),
    reportUrl: (id: string) => base + `/api/agent/runs/${encodeURIComponent(id)}/report`,
  };
}
