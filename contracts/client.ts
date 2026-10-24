/** Browser client owned by Person 4. No Gemini/CEN credentials belong here. */
export type ExecutionMode = "live" | "replay";
export type Options = { battery_policy?: "disabled" | "optimised"; allow_load_shedding?: boolean };
export type Metrics = { curtailed_energy_mwh: number; assumed_cost_usd: number; unserved_energy_mwh: number };
export type Run = {
  run_id: string; scenario_id: string; execution_mode: ExecutionMode;
  status: "queued" | "running" | "completed" | "failed";
  revision: number; approval_status: "unavailable" | "pending" | "approved" | "rejected";
  validation: { passed: boolean; violations: string[]; max_residual_mw: number };
  baseline: { valid: boolean; metrics: Metrics | null; solution: Record<string, unknown> } | null;
  candidate: { valid: boolean; metrics: Metrics | null; solution: Record<string, unknown> } | null;
  comparison: { curtailment_reduction_mwh: number; assumed_cost_delta_usd: number; unserved_energy_delta_mwh: number } | null;
  tool_trace: Array<{ tool: string; status: string; [key: string]: unknown }>;
  operator_report: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
  [key: string]: unknown;
};

export class ApiError extends Error {
  constructor(public status: number, public details: unknown) {
    super(`GridPilot API returned HTTP ${status}`);
  }
}

export function gridPilotClient(baseUrl: string, operatorToken = "") {
  const base = baseUrl.replace(/\/$/, "");
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body) headers.set("Content-Type", "application/json");
    if (operatorToken && init.method === "POST") headers.set("Authorization", `Bearer ${operatorToken}`);
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (init.signal?.aborted) abort();
    init.signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(abort, 10_000);
    try {
      const response = await fetch(base + path, { ...init, headers, signal: controller.signal });
      if (!response.ok) throw new ApiError(response.status, await response.json());
      return await response.json() as T;
    } finally {
      clearTimeout(timer);
      init.signal?.removeEventListener("abort", abort);
    }
  }
  return {
    health: () => request<Record<string, unknown>>("/api/health"),
    scenarios: () => request<{ schema_version: string; scenarios: Record<string, unknown>[] }>("/api/scenarios"),
    scenario: (id: string) => request<Record<string, unknown>>(`/api/scenario?scenario_id=${encodeURIComponent(id)}`),
    start: (scenarioId: string, executionMode: ExecutionMode, settings: Options = {}, idempotencyKey = crypto.randomUUID()) =>
      request<Run>("/api/agent/run", { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ scenario_id: scenarioId, execution_mode: executionMode, settings }) }),
    run: (id: string) => request<Run>(`/api/agent/runs/${encodeURIComponent(id)}`),
    decision: (run: Run, decision: "approved" | "rejected", operator: string, note = "") =>
      request<Run>(`/api/agent/runs/${encodeURIComponent(run.run_id)}/decision`, { method: "POST", body: JSON.stringify({ decision, operator, note, expected_revision: run.revision }) }),
    reportUrl: (id: string) => base + `/api/agent/runs/${encodeURIComponent(id)}/report`,
    /** Poll at 500–1000 ms in UI; stop on completed/failed and show errors explicitly. */
  };
}
