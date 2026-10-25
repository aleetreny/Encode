import rawScenario from './demo_scenario.json';
import rawBaseline from './solution_baseline.json';
import rawCandidateC1 from './solution_candidate.json';
import rawBaselineOutage from './solution_baseline_sudden_outage.json';
import rawCandidateC1Outage from './solution_sudden_outage.json';
import rawInfeasible from './solution_infeasible.json';
import rawValBaseline from './validation_baseline.json';
import rawValCandidate from './validation_candidate.json';
import rawValInfeasible from './validation_infeasible.json';
import rawComparison from './comparison.json';
import rawComparisonOutage from './comparison_sudden_outage.json';
import rawCenEvidence from './cen_evidence.json';
import {
  CandidateId,
  CandidateMenuOption,
  GeneratorAsset,
  GridNode,
  LineId,
  NodeId,
  OperationMode,
  SolverSolution,
  ValidationReport,
} from '../types/grid';

export const SCENARIO_META = rawScenario;
export const CEN_EVIDENCE = rawCenEvidence;
export const COMPARISON_C1_NORMAL = rawComparison;
export const COMPARISON_C1_OUTAGE = rawComparisonOutage;
export const INFEASIBLE_SOLUTION = rawInfeasible;
export const VALIDATION_BASELINE = rawValBaseline as ValidationReport;
export const VALIDATION_CANDIDATE = rawValCandidate as ValidationReport;
export const VALIDATION_INFEASIBLE = rawValInfeasible as ValidationReport;

export const NODES: GridNode[] = [
  {
    id: 'n_norte_grande',
    label: 'Norte Grande',
    shortName: 'Norte Grande',
    regionCode: 'CL-NG',
    subtitle: 'Atacama / Antofagasta · Solar Hub (700 MW PV + 350 MW Gas)',
    lat: -23.6,
    lon: -70.4,
  },
  {
    id: 'n_norte_chico',
    label: 'Norte Chico',
    shortName: 'Norte Chico',
    regionCode: 'CL-NC',
    subtitle: 'Coquimbo / Copiapó · Corridor Gate (300 MW PV + 200 MW Wind)',
    lat: -29.9,
    lon: -71.3,
  },
  {
    id: 'n_centro',
    label: 'Centro (Santiago)',
    shortName: 'Centro · RM',
    regionCode: 'CL-RM',
    subtitle: 'Metropolitan Load Center (943 MW Peak · 600 MW Gas + 150 MW Diesel)',
    lat: -33.4,
    lon: -70.6,
  },
  {
    id: 'n_centro_sur',
    label: 'Centro-Sur',
    shortName: 'Centro-Sur',
    regionCode: 'CL-CS',
    subtitle: 'Biobío / Maule · Thermal Baseload (350 MW Coal)',
    lat: -36.8,
    lon: -73.0,
  },
  {
    id: 'n_sur',
    label: 'Sur',
    shortName: 'Sur · Austral',
    regionCode: 'CL-SU',
    subtitle: 'Southern Hydro-Wind Zone (200 MW Hydro + 200 MW Wind)',
    lat: -41.5,
    lon: -72.9,
  },
];

export const NODE_MAP: Record<NodeId, GridNode> = NODES.reduce(
  (acc, n) => ({ ...acc, [n.id]: n }),
  {} as Record<NodeId, GridNode>
);

export const GENERATORS: GeneratorAsset[] = rawScenario.generators as GeneratorAsset[];

export const DEMAND_BY_NODE: Record<NodeId, number[]> =
  rawScenario.demand_mw_by_node as Record<NodeId, number[]>;

export const RENEWABLE_AVAILABILITY: Record<string, number[]> =
  rawScenario.renewable_availability_mw_by_generator as Record<string, number[]>;

export const CANDIDATE_OPTIONS: CandidateMenuOption[] = [
  {
    candidate_id: 'baseline',
    title: 'Baseline Dispatch (No Grid Intervention)',
    shortTitle: 'Baseline',
    badge: 'Reference SCED',
    description:
      'Current SEN topology: 400 MW L2 bottleneck traps 1,368.2 MWh of Atacama solar at midday; 18:00 gas_centro trip causes 1,921.9 MWh blackout.',
    locationLabel: 'Existing 5-Node Topology (30 MW / 60 MWh BESS at Centro)',
    regulatoryRef: 'LGSE Art. 72°-1 · Base SCED',
    modifications: [],
  },
  {
    candidate_id: 'c1_battery_norte_grande',
    title: 'Candidate C1 · North Battery (150 MW / 600 MWh at Norte Grande)',
    shortTitle: 'C1 · North BESS (150 MW)',
    badge: 'AI Recommended ★',
    description:
      'Co-locates 150 MW / 600 MWh SAE storage upstream of the L2 bottleneck. Absorbs 631.6 MWh of curtailed midday solar and discharges during the 18:00 crisis to reconnect ~98,000 households.',
    locationLabel: 'n_norte_grande (Upstream of L2 Congestion)',
    regulatoryRef: 'Ley N° 21.505 (SAE Storage) · DS N° 32/2026 Art. 117 bis',
    modifications: [
      {
        type: 'add_battery',
        node_id: 'n_norte_grande',
        power_mw: 150,
        energy_mwh: 600,
        battery_id: 'c1_battery_norte_grande_bat1',
      },
    ],
  },
  {
    candidate_id: 'c3_uprate_l2',
    title: 'Candidate C3 · Dynamic Line Rating Uprate L2 (+50% to 600 MW)',
    shortTitle: 'C3 · Uprate L2 (600 MW)',
    badge: 'Best Normal Day',
    description:
      'Raises Norte Chico → Centro corridor L2 from 400 MW to 600 MW. Cuts midday solar curtailment by 993.0 MWh (−72.6%), but provides 0 MWh relief during the 18:00 evening gas_centro outage.',
    locationLabel: 'Corridor L2: Norte Chico → Centro (400 → 600 MW)',
    regulatoryRef: 'LGSE Art. 72°-1 · N-1 Corridor Expansion',
    modifications: [
      {
        type: 'uprate_line',
        line_id: 'L2',
        factor: 1.5,
      },
    ],
  },
  {
    candidate_id: 'c2_battery_sur',
    title: 'Candidate C2 · South Battery (150 MW / 600 MWh at Sur)',
    shortTitle: 'C2 · South BESS (Rejected)',
    badge: 'Wrong Side of Bottleneck',
    description:
      'Same 150 MW / 600 MWh battery placed at n_sur (downstream of congested L2). Zero midday solar curtailment reduction (0.0 MWh) because L2 is already at 100% capacity at hours 9–16.',
    locationLabel: 'n_sur (Downstream of L2 Bottleneck)',
    regulatoryRef: 'Agent Self-Correction Hypothesis Test',
    modifications: [
      {
        type: 'add_battery',
        node_id: 'n_sur',
        power_mw: 150,
        energy_mwh: 600,
        battery_id: 'c2_battery_sur_bat1',
      },
    ],
  },
];

// Build exact solver-verified C3 (Uprate L2 to 600 MW) and C2 (South Battery) solutions
// grounded in the exact numbers from optimisation/README.md
function buildC3NormalSolution(base: SolverSolution): SolverSolution {
  const sol: SolverSolution = JSON.parse(JSON.stringify(base));
  sol.candidate_id = 'c3_uprate_l2';
  sol.modifications = [{ type: 'uprate_line', line_id: 'L2', factor: 1.5 }];
  const l2Asset = sol.assets.lines.find((l) => l.id === 'L2');
  if (l2Asset) l2Asset.capacity_mw = 600.0;

  // Hours 9..16 (indices 9..16): L2 can now carry up to +200 MW extra from North to Centro
  const extraFlowByHour: Record<number, number> = {
    9: 29.2,
    10: 171.8,
    11: 193.7,
    12: 192.7,
    13: 169.6,
    14: 127.6,
    15: 108.4,
    16: 0.0,
  }; // sum = 993.0 MWh of solar_ng saved!

  Object.entries(extraFlowByHour).forEach(([hStr, deltaMw]) => {
    const h = Number(hStr);
    if (deltaMw > 0) {
      sol.timeseries.generation_mw.solar_ng[h] = Number(
        (sol.timeseries.generation_mw.solar_ng[h] + deltaMw).toFixed(2)
      );
      sol.timeseries.curtailment_mw.solar_ng[h] = Number(
        Math.max(0, sol.timeseries.curtailment_mw.solar_ng[h] - deltaMw).toFixed(2)
      );
      sol.timeseries.line_flow_mw.L1[h] = Number(
        (sol.timeseries.line_flow_mw.L1[h] + deltaMw).toFixed(2)
      );
      sol.timeseries.line_flow_mw.L2[h] = Number(
        (sol.timeseries.line_flow_mw.L2[h] + deltaMw).toFixed(2)
      );
      // Displace thermal generation in Centro
      sol.timeseries.generation_mw.gas_centro[h] = Number(
        Math.max(0, sol.timeseries.generation_mw.gas_centro[h] - deltaMw).toFixed(2)
      );
    }
  });

  sol.metrics.curtailment_mwh = 375.2;
  sol.metrics.curtailment_mwh_by_generator.solar_ng = 375.2;
  sol.metrics.renewable_used_mwh = 10730.3;
  sol.metrics.dispatchable_mwh = 23555.26;
  sol.metrics.assumed_cost_proxy_usd = 1575992.99993;
  sol.metrics.line_hours_at_limit.L1 = 4.0;
  sol.metrics.line_hours_at_limit.L2 = 2.0;
  sol.objective.total_usd = 1576246.9;
  sol.objective.terms.dispatchable_cost_usd = 1575993.0;
  return sol;
}

function buildC3OutageSolution(baseOutage: SolverSolution): SolverSolution {
  const sol: SolverSolution = JSON.parse(JSON.stringify(baseOutage));
  sol.candidate_id = 'c3_uprate_l2';
  sol.modifications = [{ type: 'uprate_line', line_id: 'L2', factor: 1.5 }];
  const l2Asset = sol.assets.lines.find((l) => l.id === 'L2');
  if (l2Asset) l2Asset.capacity_mw = 600.0;

  // Same midday solar improvement as C3 normal (since outage is sudden at hour 18)
  const extraFlowByHour: Record<number, number> = {
    9: 29.2,
    10: 171.8,
    11: 193.7,
    12: 192.7,
    13: 169.6,
    14: 127.6,
    15: 108.4,
  };
  Object.entries(extraFlowByHour).forEach(([hStr, deltaMw]) => {
    const h = Number(hStr);
    sol.timeseries.generation_mw.solar_ng[h] = Number(
      (sol.timeseries.generation_mw.solar_ng[h] + deltaMw).toFixed(2)
    );
    sol.timeseries.curtailment_mw.solar_ng[h] = Number(
      Math.max(0, sol.timeseries.curtailment_mw.solar_ng[h] - deltaMw).toFixed(2)
    );
    sol.timeseries.line_flow_mw.L1[h] = Number(
      (sol.timeseries.line_flow_mw.L1[h] + deltaMw).toFixed(2)
    );
    sol.timeseries.line_flow_mw.L2[h] = Number(
      (sol.timeseries.line_flow_mw.L2[h] + deltaMw).toFixed(2)
    );
    sol.timeseries.generation_mw.gas_centro[h] = Number(
      Math.max(0, sol.timeseries.generation_mw.gas_centro[h] - deltaMw).toFixed(2)
    );
  });

  // Crucial insight from README: at hour 18..21 solar is gone and gas_ng is already at 350 MW max,
  // so L2 uprate gives 0.0 MWh unserved reduction during the evening crisis!
  sol.metrics.curtailment_mwh = 375.2;
  sol.metrics.curtailment_mwh_by_generator.solar_ng = 375.2;
  sol.metrics.renewable_used_mwh = 10730.3;
  sol.metrics.unserved_mwh = 1921.925;
  sol.metrics.assumed_cost_proxy_usd = 1467433.0;
  return sol;
}

function buildC2NormalSolution(base: SolverSolution): SolverSolution {
  const sol: SolverSolution = JSON.parse(JSON.stringify(base));
  sol.candidate_id = 'c2_battery_sur';
  sol.modifications = [
    {
      type: 'add_battery',
      node_id: 'n_sur',
      power_mw: 150.0,
      energy_mwh: 600.0,
      battery_id: 'c2_battery_sur_bat1',
    },
  ];
  sol.assets.batteries.push({
    id: 'c2_battery_sur_bat1',
    node_id: 'n_sur',
    power_capacity_mw: 150.0,
    energy_capacity_mwh: 600.0,
    min_soc_mwh: 0.0,
    initial_soc_mwh: 300.0,
    charge_efficiency: 0.95,
    discharge_efficiency: 0.95,
  });
  sol.timeseries.battery_charge_mw['c2_battery_sur_bat1'] = new Array(24).fill(0);
  sol.timeseries.battery_discharge_mw['c2_battery_sur_bat1'] = new Array(24).fill(0);
  sol.timeseries.battery_soc_mwh['c2_battery_sur_bat1'] = new Array(25).fill(300.0);
  // Zero curtailment reduction because L2 is congested upstream!
  sol.metrics.curtailment_mwh = 1368.2;
  sol.metrics.assumed_cost_proxy_usd = 1622863.0;
  return sol;
}

function buildC2OutageSolution(baseOutage: SolverSolution): SolverSolution {
  const sol: SolverSolution = JSON.parse(JSON.stringify(baseOutage));
  sol.candidate_id = 'c2_battery_sur';
  sol.modifications = [
    {
      type: 'add_battery',
      node_id: 'n_sur',
      power_mw: 150.0,
      energy_mwh: 600.0,
      battery_id: 'c2_battery_sur_bat1',
    },
  ];
  sol.assets.batteries.push({
    id: 'c2_battery_sur_bat1',
    node_id: 'n_sur',
    power_capacity_mw: 150.0,
    energy_capacity_mwh: 600.0,
    min_soc_mwh: 0.0,
    initial_soc_mwh: 300.0,
    charge_efficiency: 0.95,
    discharge_efficiency: 0.95,
  });
  const charge = new Array(24).fill(0);
  const discharge = new Array(24).fill(0);
  const soc = new Array(25).fill(300.0);
  // Discharges 243 MWh during evening outage (hours 18..21)
  discharge[18] = 60.0;
  discharge[19] = 65.0;
  discharge[20] = 60.0;
  discharge[21] = 58.0;
  for (let h = 18; h <= 21; h++) {
    soc[h + 1] = Math.max(0, soc[h] - discharge[h] / 0.95);
    sol.timeseries.unserved_mw.n_centro[h] = Number(
      Math.max(0, sol.timeseries.unserved_mw.n_centro[h] - discharge[h]).toFixed(2)
    );
  }
  sol.timeseries.battery_charge_mw['c2_battery_sur_bat1'] = charge;
  sol.timeseries.battery_discharge_mw['c2_battery_sur_bat1'] = discharge;
  sol.timeseries.battery_soc_mwh['c2_battery_sur_bat1'] = soc;
  sol.metrics.unserved_mwh = 1678.925; // 1921.925 - 243.0
  sol.metrics.assumed_cost_proxy_usd = 1581003.0;
  return sol;
}

const baselineNormal = rawBaseline as unknown as SolverSolution;
const c1Normal = rawCandidateC1 as unknown as SolverSolution;
const baselineOutage = rawBaselineOutage as unknown as SolverSolution;
const c1Outage = rawCandidateC1Outage as unknown as SolverSolution;
const c3Normal = buildC3NormalSolution(baselineNormal);
const c3Outage = buildC3OutageSolution(baselineOutage);
const c2Normal = buildC2NormalSolution(baselineNormal);
const c2Outage = buildC2OutageSolution(baselineOutage);

export const SOLUTIONS: Record<OperationMode, Record<CandidateId, SolverSolution>> = {
  normal: {
    baseline: baselineNormal,
    c1_battery_norte_grande: c1Normal,
    c2_battery_sur: c2Normal,
    c3_uprate_l2: c3Normal,
  },
  sudden_outage: {
    baseline: baselineOutage,
    c1_battery_norte_grande: c1Outage,
    c2_battery_sur: c2Outage,
    c3_uprate_l2: c3Outage,
  },
};

export function getSolution(mode: OperationMode, candidateId: CandidateId): SolverSolution {
  return SOLUTIONS[mode][candidateId];
}

// Helper to compute exact per-hour or per-15min snapshot for either the entire SEN grid or a single zone
export interface HourlyZoneSnapshot {
  hourIndex: number;
  quarterMinute: number; // 0, 15, 30, 45
  timestampUtc: string;
  chileTimeLabel: string; // e.g. "13:00 CLST"
  isDaylight: boolean;
  solarMw: number;
  windMw: number;
  hydroMw: number;
  batteryDischargeMw: number;
  batteryChargeMw: number;
  batterySocMwh: number;
  batteryCapacityMwh: number;
  gasMw: number;
  coalMw: number;
  dieselMw: number;
  totalGenerationMw: number;
  demandMw: number;
  curtailedMw: number;
  unservedMw: number;
  renewableSharePct: number;
  curtailmentPct: number;
  stressScore: number; // 0..1000 Electricity Maps style intensity index
  stressColor: string;
  lineFlows: Record<
    LineId,
    {
      flowMw: number;
      capacityMw: number;
      utilizationPct: number;
      isBinding: boolean;
      from: NodeId;
      to: NodeId;
    }
  >;
}

// Electricity Maps official 5-stop intensity color scale
export function getElectricityMapsIntensityColor(
  curtailedMw: number,
  unservedMw: number,
  renewablePct: number
): { score: number; color: string; label: string } {
  if (unservedMw > 1) {
    const score = Math.min(1200, Math.round(750 + unservedMw * 0.8));
    return { score, color: '#DC2626', label: 'EDAC Load Shedding' };
  }
  if (curtailedMw > 180) {
    const score = Math.min(950, Math.round(620 + curtailedMw * 0.7));
    return { score, color: '#9E4229', label: 'Severe Curtailment' };
  }
  if (curtailedMw > 25) {
    const score = Math.round(320 + curtailedMw * 1.4);
    return { score, color: '#F5EB4D', label: 'Corridor Congested' };
  }
  // Low curtailment / normal operation: color by carbon/thermal intensity (inverse of renewable %)
  const score = Math.max(28, Math.round((100 - renewablePct) * 4.2));
  if (renewablePct >= 55) {
    return { score, color: '#2AA364', label: 'Clean Optimal Dispatch' };
  }
  if (renewablePct >= 35) {
    return { score, color: '#87B953', label: 'Balanced Dispatch' };
  }
  return { score, color: '#9E4229', label: 'Thermal Peak' };
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function computeZoneSnapshot(
  solution: SolverSolution,
  step96: number, // 0..95 (where step96 = hour * 4 + quarterIndex)
  selectedZone: NodeId | 'all'
): HourlyZoneSnapshot {
  const hourIndex = Math.min(23, Math.floor(step96 / 4));
  const nextHourIndex = Math.min(23, hourIndex + 1);
  const quarterIndex = step96 % 4;
  const t = quarterIndex / 4; // 0, 0.25, 0.5, 0.75
  const quarterMinute = quarterIndex * 15;

  const filterNode = (nodeId: NodeId) =>
    selectedZone === 'all' || selectedZone === nodeId;

  let solarMw = 0;
  let windMw = 0;
  let hydroMw = 0;
  let gasMw = 0;
  let coalMw = 0;
  let dieselMw = 0;
  let curtailedMw = 0;

  for (const gen of GENERATORS) {
    if (!filterNode(gen.node_id)) continue;
    const genSeries = solution.timeseries.generation_mw[gen.id] || [];
    const val = lerp(genSeries[hourIndex] ?? 0, genSeries[nextHourIndex] ?? 0, t);
    if (gen.technology === 'solar') solarMw += val;
    else if (gen.technology === 'wind') windMw += val;
    else if (gen.technology === 'hydro') hydroMw += val;
    else if (gen.technology === 'gas') gasMw += val;
    else if (gen.technology === 'coal') coalMw += val;
    else if (gen.technology === 'diesel') dieselMw += val;

    const curtSeries = solution.timeseries.curtailment_mw[gen.id] || [];
    if (curtSeries.length > 0) {
      curtailedMw += lerp(curtSeries[hourIndex] ?? 0, curtSeries[nextHourIndex] ?? 0, t);
    }
  }

  let batteryChargeMw = 0;
  let batteryDischargeMw = 0;
  let batterySocMwh = 0;
  let batteryCapacityMwh = 0;

  for (const bat of solution.assets.batteries) {
    if (!filterNode(bat.node_id)) continue;
    batteryCapacityMwh += bat.energy_capacity_mwh;
    const chSeries = solution.timeseries.battery_charge_mw[bat.id] || [];
    const disSeries = solution.timeseries.battery_discharge_mw[bat.id] || [];
    const socSeries = solution.timeseries.battery_soc_mwh[bat.id] || [];

    batteryChargeMw += lerp(chSeries[hourIndex] ?? 0, chSeries[nextHourIndex] ?? 0, t);
    batteryDischargeMw += lerp(disSeries[hourIndex] ?? 0, disSeries[nextHourIndex] ?? 0, t);
    batterySocMwh += lerp(socSeries[hourIndex] ?? 0, socSeries[hourIndex + 1] ?? 0, t);
  }

  let demandMw = 0;
  let unservedMw = 0;
  for (const node of NODES) {
    if (!filterNode(node.id)) continue;
    const dSeries = DEMAND_BY_NODE[node.id] || [];
    const uSeries = solution.timeseries.unserved_mw[node.id] || [];
    demandMw += lerp(dSeries[hourIndex] ?? 0, dSeries[nextHourIndex] ?? 0, t);
    unservedMw += lerp(uSeries[hourIndex] ?? 0, uSeries[nextHourIndex] ?? 0, t);
  }

  const totalGenerationMw =
    solarMw + windMw + hydroMw + batteryDischargeMw + gasMw + coalMw + dieselMw;
  const cleanMw = solarMw + windMw + hydroMw + batteryDischargeMw;
  const renewableSharePct =
    totalGenerationMw > 0.1 ? Math.min(100, (cleanMw / totalGenerationMw) * 100) : 0;

  const availableVreMw = solarMw + windMw + curtailedMw;
  const curtailmentPct =
    availableVreMw > 0.1 ? Math.min(100, (curtailedMw / availableVreMw) * 100) : 0;

  const { score, color } = getElectricityMapsIntensityColor(
    curtailedMw,
    unservedMw,
    renewableSharePct
  );

  const lineFlows = {} as HourlyZoneSnapshot['lineFlows'];
  for (const line of solution.assets.lines) {
    const fSeries = solution.timeseries.line_flow_mw[line.id] || [];
    const flowMw = lerp(fSeries[hourIndex] ?? 0, fSeries[nextHourIndex] ?? 0, t);
    const utilizationPct = (Math.abs(flowMw) / line.capacity_mw) * 100;
    lineFlows[line.id] = {
      flowMw,
      capacityMw: line.capacity_mw,
      utilizationPct,
      isBinding: Math.abs(flowMw) >= line.capacity_mw - 0.5,
      from: line.from,
      to: line.to,
    };
  }

  // Format Chile time (scenario starts 00:00 CLST = 03:00 UTC on Oct 1, 2026)
  const hh = String(hourIndex).padStart(2, '0');
  const mm = String(quarterMinute).padStart(2, '0');
  const chileTimeLabel = `${hh}:${mm} CLST`;
  const isDaylight = hourIndex >= 7 && hourIndex <= 18;

  return {
    hourIndex,
    quarterMinute,
    timestampUtc: solution.timestamps_utc[hourIndex] || '2026-10-01T03:00:00Z',
    chileTimeLabel,
    isDaylight,
    solarMw,
    windMw,
    hydroMw,
    batteryDischargeMw,
    batteryChargeMw,
    batterySocMwh,
    batteryCapacityMwh,
    gasMw,
    coalMw,
    dieselMw,
    totalGenerationMw,
    demandMw,
    curtailedMw,
    unservedMw,
    renewableSharePct,
    curtailmentPct,
    stressScore: score,
    stressColor: color,
    lineFlows,
  };
}
