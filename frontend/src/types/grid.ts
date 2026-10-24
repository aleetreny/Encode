export type NodeId =
  | 'n_norte_grande'
  | 'n_norte_chico'
  | 'n_centro'
  | 'n_centro_sur'
  | 'n_sur';

export type LineId = 'L1' | 'L2' | 'L3' | 'L4';

export type CandidateId =
  | 'baseline'
  | 'c1_battery_norte_grande'
  | 'c2_battery_sur'
  | 'c3_uprate_l2';

export type OperationMode = 'normal' | 'sudden_outage';

export type TimeGranularity = 'hourly' | '15min';

export interface GridNode {
  id: NodeId;
  label: string;
  shortName: string;
  regionCode: string;
  subtitle: string;
  lat: number;
  lon: number;
}

export interface GridLine {
  id: LineId;
  from: NodeId;
  to: NodeId;
  capacity_mw: number;
}

export interface GeneratorAsset {
  id: string;
  node_id: NodeId;
  technology: 'solar' | 'wind' | 'gas' | 'coal' | 'hydro' | 'diesel';
  capacity_mw: number;
  variable_cost_usd_per_mwh: number;
  ramp_rate_mw_per_h?: number;
}

export interface BatteryAsset {
  id: string;
  node_id: NodeId;
  power_capacity_mw: number;
  energy_capacity_mwh: number;
  min_soc_mwh: number;
  initial_soc_mwh: number;
  charge_efficiency: number;
  discharge_efficiency: number;
}

export interface BindingConstraint {
  type: string;
  id: string;
  hours: number[];
  detail: string;
}

export interface SolverSolution {
  status: 'optimal' | 'infeasible' | string;
  message: string | null;
  scenario_id: string;
  candidate_id: string;
  modifications: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  time_step_hours: number;
  timestamps_utc: string[];
  solver: {
    name: string;
    version: string;
    solve_time_s: number;
    solves: number;
  };
  objective: {
    total_usd: number;
    terms: {
      dispatchable_cost_usd: number;
      unserved_penalty_usd: number;
      curtailment_penalty_usd: number;
      battery_throughput_cost_usd: number;
      transmission_tiebreak_usd: number;
    };
  };
  assets: {
    batteries: BatteryAsset[];
    lines: GridLine[];
  };
  timeseries: {
    generation_mw: Record<string, number[]>;
    curtailment_mw: Record<string, number[]>;
    battery_charge_mw: Record<string, number[]>;
    battery_discharge_mw: Record<string, number[]>;
    battery_soc_mwh: Record<string, number[]>;
    line_flow_mw: Record<LineId, number[]>;
    unserved_mw: Record<NodeId, number[]>;
  };
  metrics: {
    curtailment_mwh: number;
    curtailment_mwh_by_generator: Record<string, number>;
    unserved_mwh: number;
    unserved_mwh_by_node: Record<NodeId, number>;
    renewable_used_mwh: number;
    dispatchable_mwh: number;
    demand_mwh: number;
    battery_charge_mwh: number;
    battery_discharge_mwh: number;
    battery_losses_mwh: number;
    assumed_cost_proxy_usd: number;
    line_hours_at_limit: Record<LineId, number>;
  };
  binding_constraints: BindingConstraint[];
}

export interface ValidationReport {
  passed: boolean;
  checks_run: string[];
  violations: Array<{
    check: string;
    id: string | null;
    hour: number | null;
    magnitude: number;
    detail: string;
  }>;
  violation_count: number;
  max_residual_mw: number;
}

export interface CandidateMenuOption {
  candidate_id: CandidateId;
  title: string;
  shortTitle: string;
  badge: string;
  description: string;
  locationLabel: string;
  regulatoryRef: string;
  modifications: Array<Record<string, unknown>>;
}
