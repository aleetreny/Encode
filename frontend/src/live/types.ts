/**
 * Frozen GridPilot Live Ops Contract (`contracts/live.schema.json`).
 * Do NOT rename or remove any fields. Only optional additive fields may be added
 * and must be documented in `docs/live-contract-changelog.md`.
 */

export type Provenance = 'observed' | 'derived' | 'synthetic' | 'assumption';
export type GridState = 'normal' | 'alerta' | 'emergencia' | 'recuperacion';

export interface CatalogNode {
  id: string;
  name: string;
  lat: number;
  lon: number;
  households_total: number;
  households_per_mw: number;
}

export type GeneratorTechnology = 'solar' | 'wind' | 'hydro' | 'gas' | 'coal' | 'diesel';

export interface CatalogGenerator {
  id: string;
  name: string;
  node_id: string;
  technology: GeneratorTechnology;
  capacity_mw: number;
  disruptable: boolean;
}

export interface CatalogBattery {
  id: string;
  name: string;
  node_id: string;
  power_mw: number;
  energy_mwh: number;
  standby: boolean;
}

export interface CatalogLine {
  id: string;
  from: string;
  to: string;
  capacity_mw: number;
  disruptable: boolean;
}

export interface CatalogLever {
  type: string;
  label_es: string;
  description_es: string;
}

export interface CatalogDayProfile {
  source: string;
  date: string;
  method: 'synthetic' | 'scaled-observed-shape';
  scale_factor?: number;
  label_es: string;
}

export interface Catalog {
  nodes: CatalogNode[];
  generators: CatalogGenerator[];
  batteries: CatalogBattery[];
  lines: CatalogLine[];
  levers: CatalogLever[];
  provenance: Record<string, Provenance>;
  day_profile?: CatalogDayProfile;
}

export interface MonitorMetrics {
  demand_mw?: number;
  reserve_margin_pct?: number;
  max_line_loading_pct?: number;
  max_line_id?: string;
  curtailment_mw?: number;
  unserved_mw?: number;
  households_off?: number;
  net_load_ramp_mw_per_h?: number;
  storage_soc_pct?: number;
}

export interface ValidationSummary {
  passed: boolean;
  violations: string[];
  max_residual_mw: number;
}

export interface Solution {
  solution_id: string;
  generation_mw: Record<string, number[]>;
  available_mw: Record<string, number[]>;
  line_flow_mw: Record<string, number[]>;       // signo: + en dirección from→to
  line_capacity_mw: Record<string, number[]>;   // refleja emergency_rating
  battery_flow_mw: Record<string, number[]>;    // + descarga, − carga
  battery_soc_mwh: Record<string, number[]>;
  demand_mw: Record<string, number[]>;          // por nodo
  unserved_mw: Record<string, number[]>;        // por nodo
  demand_response_mw: Record<string, number[]>; // por nodo
  curtailment_mw: Record<string, number[]>;     // por generador
  households_off: Record<string, number[]>;     // por nodo = unserved_mw × households_per_mw
  cost_proxy_usd: number[];
  co2_t: number[];
  status: 'optimal' | 'infeasible' | 'error';
  validation: ValidationSummary;
}

export type DisruptionType = 'generator_outage' | 'line_outage' | 'battery_outage';
export type DisruptionSource = 'operator' | 'jury' | 'script';

export interface Disruption {
  event_id: string;
  type: DisruptionType;
  asset_id: string;
  from_hour: number;
  to_hour: number;
  source: DisruptionSource;
  jury_name?: string;
}

export type LeverType =
  | 'emergency_rating'
  | 'demand_response'
  | 'activate_reserve_bess'
  | 'hydro_reserve_release'
  | 'start_peaker'
  | 'add_battery'
  | 'uprate_line';

export interface Lever {
  type: LeverType;
  target_id: string;
  params: Record<string, number>;
  from_hour: number;
  to_hour: number;
}

export type TradeoffTag = 'max_hogares' | 'min_costo' | 'min_co2' | 'min_riesgo_red';

export interface OptionMetrics {
  households_reconnected: number;
  households_newly_off: number;
  unserved_mwh_avoided: number;
  cost_delta_usd: number;
  co2_delta_t: number;
  curtailment_delta_mwh: number;
  max_line_loading_pct: number;
  hours_to_zero_unserved: number | null;
}

export interface Option {
  option_id: string;
  title_es: string;               // título corto escrito por Gemini (sin dígitos)
  levers: Lever[];
  rationale_es: string;           // 1–2 frases de Gemini, sin dígitos
  tradeoff_tag: TradeoffTag;
  metrics: OptionMetrics;         // TODO calculado por código
  validation: ValidationSummary;
  solution: Solution;             // para previsualizar en el mapa al pasar el cursor
}

export interface ModelExecution {
  model: string;
  role: 'decider' | 'monitor';
  status: 'ok' | 'timeout' | 'error' | 'no_key' | 'stale';
  latency_ms: number;
  response_id?: string;
  cached: boolean;
  cached_at_utc?: string;
}

export interface LiveEventEnvelope {
  seq: number;
  session_id: string;
  hour: number;
  ts_utc: string;
}

export type LiveEventPayload =
  | {
      type: 'session.snapshot';
      catalog: Catalog;
      solution: Solution;
      grid_state: GridState;
      active_events: Disruption[];
      autonomy: boolean;
      clock: { hour: number; running: boolean; speed_s_per_hour: number };
    }
  | {
      type: 'clock.tick';
      running: boolean;
    }
  | {
      type: 'incident.detected';
      incident_id: string;
      disruption: Disruption;
      impact: {
        unserved_mw_peak: number;
        households_off_peak: number;
        nodes_affected: string[];
        lines_overloaded: string[];
      };
    }
  | {
      type: 'solution.updated';
      reason: 'incident' | 'plan_applied' | 'event_ended' | 'reset';
      solution: Solution;
      grid_state: GridState;
    }
  | {
      type: 'agent.thought';
      incident_id: string | null;
      delta: string;
    }
  | {
      type: 'agent.tool_call';
      incident_id: string;
      call_id: string;
      tool: string;
      args_summary_es: string;
      status: 'running' | 'pass' | 'fail' | 'infeasible';
      duration_ms?: number;
      result_summary?: Record<string, number | string | boolean>;
    }
  | {
      type: 'options.ready';
      incident_id: string;
      diagnosis_es: string;
      options: [Option, Option];
      recommended_id: string;
      candidates_evaluated: number;
      candidates_passed: number;
      model_execution: ModelExecution;
    }
  | {
      type: 'autonomy.countdown';
      incident_id: string;
      option_id: string;
      seconds_left: number;
    }
  | {
      type: 'plan.applied';
      incident_id: string;
      option_id: string;
      by: 'operator' | 'gemini_autonomous';
    }
  | {
      type: 'plan.vetoed';
      incident_id: string;
      option_id: string;
    }
  | {
      type: 'event.ended';
      event_id: string;
    }
  | {
      type: 'agent.note';
      text_es: string;
      kind?: 'periodic' | 'monitor';
      severity?: 'info' | 'watch' | 'alert';
      metrics?: MonitorMetrics;
      watch?: string[];
      model_execution?: ModelExecution;
    }
  | {
      type: 'error';
      code: string;
      message_es: string;
    };

export type LiveEvent = LiveEventEnvelope & LiveEventPayload;

// Command payloads
export interface CreateSessionRequest {
  scenario_id?: string;
  speed_s_per_hour?: number;
  start_hour?: number;
}

export interface CreateSessionResponse {
  session_id: string;
}

export interface ClockCommandRequest {
  action: 'play' | 'pause' | 'seek';
  hour?: number;
}

export interface DisruptCommandRequest {
  asset_id: string;
  duration_h?: number;
  source?: DisruptionSource;
}

export interface JuryDisruptCommandRequest {
  asset_id: string;
  jury_name?: string;
  device_id?: string;
  card_id?: string;
  action?: any;
}

export interface DecideCommandRequest {
  incident_id: string;
  option_id: string;
  decision: 'apply' | 'veto';
}

export interface AutonomyCommandRequest {
  enabled: boolean;
}

export interface ImpactPreviewAsset {
  asset_id: string;
  households_off_peak: number;
  unserved_mw_peak: number;
  absorbed: boolean;
}

export interface ImpactPreviewResponse {
  hour: number;
  assets: ImpactPreviewAsset[];
}

export interface LiveSessionState {
  sessionId: string | null;
  lastSeq: number;
  catalog: Catalog | null;
  grid_state: GridState;
  clock: {
    sim_hour: number;
    running: boolean;
    speed_hours_per_sec: number;
    autonomy_mode: boolean;
  };
  active_incidents: Disruption[];
  solution: Solution | null;
  validation: ValidationSummary | null;
  comparison: any | null;
  agent_status: {
    phase: 'idle' | 'analyzing' | 'awaiting_operator' | 'executing' | 'resolved';
    detail_es: string;
    started_at_utc: string | null;
  };
  thoughts: { text_es: string; ts_utc: string; sim_hour: number }[];
  tool_calls: Extract<LiveEvent, { type: 'agent.tool_call' }>[];
  options: [Option, Option] | null;
  model_execution?: ModelExecution | null;
  applied_by?: 'operator' | 'gemini_autonomous' | null;
  by?: 'operator' | 'gemini_autonomous' | null;
  countdown: { candidate_id: string; seconds_left: number; active: boolean } | null;
  notes: { text_es: string; ts_utc: string; sim_hour: number }[];
}

export interface LiveSessionActions {
  setClock(cmd: ClockCommandRequest): Promise<void>;
  injectEvent(cmd: DisruptCommandRequest): Promise<void>;
  submitJuryAction(cmd: JuryDisruptCommandRequest): Promise<Response>;
  submitOperatorDecision(cmd: DecideCommandRequest): Promise<void>;
  vetoCountdown(incidentId: string, optionId: string): Promise<void>;
  switchMode(mode: 'live' | 'offline'): void;
  replayOfflineDemo(): void;
  downloadReportUrl(): string;
}

export interface LiveSessionHook {
  state: LiveSessionState;
  catalog: Catalog | null;
  connected: boolean;
  connectionMode: 'live' | 'offline' | 'connecting';
  actions: LiveSessionActions;
  interpolatedSimHour: number;
}

