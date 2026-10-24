import React, { useState } from 'react';
import {
  Sun,
  Wind,
  Droplets,
  BatteryCharging,
  Flame,
  Factory,
  Fuel,
  AlertTriangle,
  Sparkles,
  CheckCircle2,
  Home,
  DollarSign,
  Database,
  ArrowDownRight,
} from 'lucide-react';
import {
  CandidateId,
  NodeId,
  OperationMode,
  SolverSolution,
} from '../types/grid';
import {
  CANDIDATE_OPTIONS,
  computeZoneSnapshot,
  NODES,
} from '../data/scenarioData';
import { GlassContainer } from './GlassContainer';
import { CircularGauge, IntensitySquare } from './CircularGauge';

interface LeftPanelProps {
  baselineSolution: SolverSolution;
  activeSolution: SolverSolution;
  step96: number;
  onChangeStep96: (step: number) => void;
  selectedZone: NodeId | 'all';
  onSelectZone: (zone: NodeId | 'all') => void;
  candidateId: CandidateId;
  onSelectCandidate: (id: CandidateId) => void;
  operationMode: OperationMode;
  onOpenEvidence: () => void;
}

export const LeftPanel: React.FC<LeftPanelProps> = ({
  baselineSolution,
  activeSolution,
  step96,
  onChangeStep96,
  selectedZone,
  onSelectZone,
  candidateId,
  onSelectCandidate,
  operationMode,
  onOpenEvidence,
}) => {
  const [chartTab, setChartTab] = useState<'curtailment' | 'corridors' | 'battery'>('curtailment');

  const snap = computeZoneSnapshot(activeSolution, step96, selectedZone);
  const baseSnap = computeZoneSnapshot(baselineSolution, step96, selectedZone);
  const selectedNodeMeta =
    selectedZone === 'all' ? null : NODES.find((n) => n.id === selectedZone) || null;

  // Daily 24h verified metrics from Solver JSON
  const baseCurtailmentMwh = baselineSolution.metrics.curtailment_mwh;
  const activeCurtailmentMwh = activeSolution.metrics.curtailment_mwh;
  const curtailmentDeltaMwh = activeCurtailmentMwh - baseCurtailmentMwh;

  const baseUnservedMwh = baselineSolution.metrics.unserved_mwh;
  const activeUnservedMwh = activeSolution.metrics.unserved_mwh;
  const unservedDeltaMwh = activeUnservedMwh - baseUnservedMwh;
  const householdsReconnected = Math.round(Math.max(0, -unservedDeltaMwh) * 250); // ~97,969 household-hours (~1,000 households/MW over 4h)

  const baseCostUsd = baselineSolution.metrics.assumed_cost_proxy_usd;
  const activeCostUsd = activeSolution.metrics.assumed_cost_proxy_usd;
  const costDeltaUsd = activeCostUsd - baseCostUsd;

  // Production breakdown rows modeled after Electricity Maps' BarBreakdownChart
  const maxBarMw = Math.max(850, snap.demandMw, snap.totalGenerationMw + snap.curtailedMw);
  const productionRows = [
    {
      key: 'solar',
      label: 'Solar PV',
      mw: snap.solarMw,
      baseMw: baseSnap.solarMw,
      color: '#FFC700',
      icon: Sun,
    },
    {
      key: 'wind',
      label: 'Wind',
      mw: snap.windMw,
      baseMw: baseSnap.windMw,
      color: '#69D6F8',
      icon: Wind,
    },
    {
      key: 'battery',
      label:
        snap.batteryChargeMw > 0.5
          ? `Battery (Charging −${Math.round(snap.batteryChargeMw)} MW)`
          : 'Battery Storage (SAE)',
      mw: snap.batteryDischargeMw,
      baseMw: baseSnap.batteryDischargeMw,
      color: '#1DA484',
      icon: BatteryCharging,
      extraPill:
        snap.batteryCapacityMwh > 0
          ? `SOC ${Math.round(snap.batterySocMwh)}/${Math.round(snap.batteryCapacityMwh)} MWh`
          : undefined,
    },
    {
      key: 'hydro',
      label: 'Hydro Reservoir',
      mw: snap.hydroMw,
      baseMw: baseSnap.hydroMw,
      color: '#1878EA',
      icon: Droplets,
    },
    {
      key: 'gas',
      label: 'Natural Gas',
      mw: snap.gasMw,
      baseMw: baseSnap.gasMw,
      color: '#AAA189',
      icon: Flame,
    },
    {
      key: 'coal',
      label: 'Coal Baseload',
      mw: snap.coalMw,
      baseMw: baseSnap.coalMw,
      color: '#545454',
      icon: Factory,
    },
    {
      key: 'diesel',
      label: 'Diesel Peaker',
      mw: snap.dieselMw,
      baseMw: baseSnap.dieselMw,
      color: '#8B5E3C',
      icon: Fuel,
    },
  ];

  // Hourly 24h arrays for SVG mini-charts
  const hours24 = Array.from({ length: 24 }, (_, i) => i);
  const baseHourlyCurtailment = hours24.map((h) =>
    Object.values(baselineSolution.timeseries.curtailment_mw).reduce(
      (s, arr) => s + (arr[h] || 0),
      0
    )
  );
  const activeHourlyCurtailment = hours24.map((h) =>
    Object.values(activeSolution.timeseries.curtailment_mw).reduce(
      (s, arr) => s + (arr[h] || 0),
      0
    )
  );
  const activeHourlyL2Flow = hours24.map(
    (h) => activeSolution.timeseries.line_flow_mw.L2[h] || 0
  );
  const baseHourlyL2Flow = hours24.map(
    (h) => baselineSolution.timeseries.line_flow_mw.L2[h] || 0
  );
  const activeHourlySoc = hours24.map((h) =>
    Object.values(activeSolution.timeseries.battery_soc_mwh).reduce(
      (s, arr) => s + (arr[h] || 0),
      0
    )
  );
  const activeHourlyUnserved = hours24.map((h) =>
    Object.values(activeSolution.timeseries.unserved_mw).reduce(
      (s, arr) => s + (arr[h] || 0),
      0
    )
  );
  const baseHourlyUnserved = hours24.map((h) =>
    Object.values(baselineSolution.timeseries.unserved_mw).reduce(
      (s, arr) => s + (arr[h] || 0),
      0
    )
  );

  const activeCandidateMeta = CANDIDATE_OPTIONS.find((c) => c.candidate_id === candidateId)!;

  return (
    <div className="fixed left-[75px] top-3 bottom-[132px] z-30 w-[428px] flex flex-col pointer-events-none">
      <GlassContainer className="pointer-events-auto flex h-full flex-col overflow-hidden">
        {/* 1. ZoneHeader (Exact Electricity Maps Header Layout) */}
        <div className="border-b border-neutral-800/80 px-4 pt-3.5 pb-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2.5">
              {/* Chile Flag SVG */}
              <div className="h-7 w-10 shrink-0 overflow-hidden rounded-md border border-neutral-700 shadow-sm">
                <svg viewBox="0 0 30 20" className="h-full w-full">
                  <rect width="30" height="10" fill="#FFFFFF" />
                  <rect y="10" width="30" height="10" fill="#D52B1E" />
                  <rect width="10" height="10" fill="#0039A6" />
                  <polygon
                    points="5,2.2 5.8,4.5 8.2,4.5 6.3,5.9 7,8.2 5,6.8 3,8.2 3.7,5.9 1.8,4.5 4.2,4.5"
                    fill="#FFFFFF"
                  />
                </svg>
              </div>
              <div>
                <h1 className="font-poppins text-[15px] font-semibold leading-tight text-white">
                  {selectedNodeMeta ? selectedNodeMeta.label : 'Chile · SEN National Grid'}
                </h1>
                <p className="text-[11px] text-neutral-400 line-clamp-1">
                  {selectedNodeMeta
                    ? selectedNodeMeta.subtitle
                    : '5-Zone Illustrative Corridor · 9 Generators · L1–L4'}
                </p>
              </div>
            </div>

            {/* Provenance Hygiene Pill (Observed vs Simulated) */}
            <button
              type="button"
              onClick={onOpenEvidence}
              className="shrink-0 inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-950/60 px-2 py-0.5 text-[10px] font-medium text-sky-300 hover:bg-sky-900/70 transition-colors"
              title="Click to inspect real Observed CEN Curtailment Evidence vs Synthetic 5-Node Simulation"
            >
              <Database className="h-2.5 w-2.5" />
              <span>Simulated · CEN Grounded</span>
            </button>
          </div>

          {/* 5-Zone Pill Filter Bar */}
          <div className="mt-2.5 flex items-center gap-1 overflow-x-auto pb-0.5">
            <button
              type="button"
              onClick={() => onSelectZone('all')}
              className={`rounded-lg px-2 py-1 text-[11px] font-medium transition-colors ${
                selectedZone === 'all'
                  ? 'bg-neutral-100 text-neutral-950 font-semibold'
                  : 'bg-neutral-800/80 text-neutral-400 hover:text-neutral-200'
              }`}
            >
              All SEN
            </button>
            {NODES.map((n) => (
              <button
                key={n.id}
                type="button"
                onClick={() => onSelectZone(n.id)}
                className={`rounded-lg px-2 py-1 text-[11px] font-medium whitespace-nowrap transition-colors ${
                  selectedZone === n.id
                    ? 'bg-emerald-500 text-neutral-950 font-semibold'
                    : 'bg-neutral-800/80 text-neutral-400 hover:text-neutral-200'
                }`}
              >
                {n.shortName.replace(' · RM', '').replace(' · Araucanía/Lagos', '')}
              </button>
            ))}
          </div>
        </div>

        {/* Scrollable Inner Body */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3.5">
          {/* 2. Electricity Maps Signature 3-Gauge Row (ZoneGaugesWithCO2Square) */}
          <div className="grid grid-cols-3 gap-2 rounded-xl border border-neutral-800/90 bg-neutral-950/60 p-2.5">
            <IntensitySquare
              score={snap.stressScore}
              unit={snap.unservedMw > 1 ? 'CRISIS' : 'STRESS'}
              label={
                snap.unservedMw > 1
                  ? 'EDAC Deficit'
                  : snap.curtailedMw > 25
                  ? 'Curtailed'
                  : 'Optimal'
              }
              bgColor={snap.stressColor}
            />
            <CircularGauge
              percentage={snap.renewableSharePct}
              label="Renewable"
              sublabel={`${Math.round(snap.solarMw + snap.windMw + snap.hydroMw + snap.batteryDischargeMw)} MW`}
              color="#2AA364"
            />
            <CircularGauge
              percentage={
                selectedZone === 'all' || selectedZone === 'n_norte_chico'
                  ? snap.lineFlows.L2.utilizationPct
                  : 100 - snap.curtailmentPct
              }
              label={
                selectedZone === 'all' || selectedZone === 'n_norte_chico'
                  ? 'Corridor L2'
                  : 'VRE Used'
              }
              sublabel={
                selectedZone === 'all' || selectedZone === 'n_norte_chico'
                  ? `${Math.round(Math.abs(snap.lineFlows.L2.flowMw))}/${snap.lineFlows.L2.capacityMw} MW`
                  : `${Math.round(snap.curtailedMw)} MW lost`
              }
              color={snap.lineFlows.L2.isBinding ? '#F59E0B' : '#69D6F8'}
            />
          </div>

          {/* 3. One-Glance Daily Impact Comparison Card (Baseline vs Active Candidate) */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-950/75 p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
                <span className="font-poppins text-xs font-semibold text-neutral-100">
                  24h Solver Impact ({activeCandidateMeta.shortTitle})
                </span>
              </div>
              <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-400">
                {activeCandidateMeta.badge}
              </span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {/* Metric 1: Solar/Wind Curtailment */}
              <div className="rounded-lg bg-neutral-900/90 p-2 border border-neutral-800/80">
                <span className="text-[10px] text-neutral-400 block">Solar Curtailed</span>
                <span className="font-mono text-sm font-bold text-white tabular-nums">
                  {activeCurtailmentMwh.toFixed(0)} <span className="text-[10px] font-normal text-neutral-400">MWh</span>
                </span>
                <div
                  className={`mt-0.5 flex items-center gap-0.5 font-mono text-[10px] font-semibold ${
                    curtailmentDeltaMwh < -1
                      ? 'text-emerald-400'
                      : 'text-amber-400'
                  }`}
                >
                  {curtailmentDeltaMwh < -1 ? (
                    <>
                      <ArrowDownRight className="h-3 w-3" />
                      <span>{curtailmentDeltaMwh.toFixed(1)} MWh</span>
                    </>
                  ) : candidateId === 'baseline' ? (
                    <span>L2 Bottleneck</span>
                  ) : (
                    <span>0.0 MWh saved</span>
                  )}
                </div>
              </div>

              {/* Metric 2: Crisis Unserved Energy & Households Reconnected */}
              <div className="rounded-lg bg-neutral-900/90 p-2 border border-neutral-800/80">
                <span className="text-[10px] text-neutral-400 block">
                  {operationMode === 'sudden_outage' ? 'Crisis Blackout' : 'Unserved Load'}
                </span>
                <span
                  className={`font-mono text-sm font-bold tabular-nums ${
                    activeUnservedMwh > 0 ? 'text-red-400' : 'text-emerald-400'
                  }`}
                >
                  {activeUnservedMwh.toFixed(0)}{' '}
                  <span className="text-[10px] font-normal text-neutral-400">MWh</span>
                </span>
                <div className="mt-0.5 font-mono text-[10px] font-semibold text-emerald-400">
                  {operationMode === 'sudden_outage' && unservedDeltaMwh < -1 ? (
                    <span className="inline-flex items-center gap-0.5 text-emerald-400">
                      <Home className="h-2.5 w-2.5" />
                      +{(householdsReconnected / 1000).toFixed(1)}k hh saved
                    </span>
                  ) : operationMode === 'sudden_outage' ? (
                    <span className="text-red-400">0 hh relief</span>
                  ) : (
                    <span className="text-neutral-400">100% Served</span>
                  )}
                </div>
              </div>

              {/* Metric 3: Dispatch Cost Proxy */}
              <div className="rounded-lg bg-neutral-900/90 p-2 border border-neutral-800/80">
                <span className="text-[10px] text-neutral-400 block">24h Dispatch Cost</span>
                <span className="font-mono text-sm font-bold text-white tabular-nums">
                  ${(activeCostUsd / 1_000_000).toFixed(2)}M
                </span>
                <div
                  className={`mt-0.5 flex items-center font-mono text-[10px] font-semibold ${
                    costDeltaUsd < -100 ? 'text-emerald-400' : 'text-neutral-400'
                  }`}
                >
                  {costDeltaUsd < -100 ? (
                    <span>−${Math.round(Math.abs(costDeltaUsd) / 1000)}k/day</span>
                  ) : (
                    <span>Reference</span>
                  )}
                </div>
              </div>
            </div>

            {/* Key Trade-Off Explanation Line */}
            <p className="mt-2 text-[11px] leading-snug text-neutral-300">
              {candidateId === 'c1_battery_norte_grande' ? (
                <>
                  <strong className="text-emerald-400">Why C1 wins:</strong> Stores{' '}
                  <span className="font-mono text-white">631.6 MWh</span> of trapped Atacama solar
                  upstream of L2 and discharges at 18:00 to save{' '}
                  <span className="font-mono text-emerald-300">~98,000 households</span> during the{' '}
                  <code className="text-red-300">gas_centro</code> outage.
                </>
              ) : candidateId === 'c3_uprate_l2' ? (
                <>
                  <strong className="text-amber-300">Trade-off alert:</strong> Uprating L2 to 600 MW
                  saves the most midday solar (<span className="font-mono text-white">−993 MWh</span>
                  ), but gives <strong className="text-red-400">0 MWh relief</strong> during the
                  18:00 evening outage when solar is zero.
                </>
              ) : candidateId === 'c2_battery_sur' ? (
                <>
                  <strong className="text-red-400">Rejected by Validator:</strong> Placing the
                  battery at <code className="text-neutral-200">n_sur</code> (south of congested L2)
                  yields <strong className="text-red-400">0.0 MWh</strong> midday curtailment
                  reduction.
                </>
              ) : (
                <>
                  <strong className="text-amber-300">Baseline Bottleneck:</strong> Corridor{' '}
                  <code className="text-amber-200">L2 (Norte Chico → Centro)</code> saturates at{' '}
                  <span className="font-mono text-white">400 MW</span> for 8 hours (09:00–16:00),
                  wasting <span className="font-mono text-amber-300">1,368.2 MWh</span> of free solar.
                </>
              )}
            </p>
          </div>

          {/* 4. Electricity Production & Curtailment Breakdown (Electricity Maps BarBreakdownChart) */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-poppins text-xs font-semibold uppercase tracking-wider text-neutral-300">
                Electricity Dispatch at {snap.chileTimeLabel}
              </h2>
              <span className="font-mono text-[11px] text-neutral-400 tabular-nums">
                Load: <strong className="text-white">{Math.round(snap.demandMw)} MW</strong>
              </span>
            </div>

            <div className="space-y-1.5">
              {productionRows.map((row) => {
                const Icon = row.icon;
                const widthPct = Math.min(100, (row.mw / maxBarMw) * 100);
                const deltaMw = row.mw - row.baseMw;

                return (
                  <div key={row.key} className="group">
                    <div className="flex items-center justify-between text-xs mb-0.5">
                      <div className="flex items-center gap-1.5 text-neutral-200">
                        <Icon className="h-3.5 w-3.5 shrink-0" style={{ color: row.color }} />
                        <span className="font-medium">{row.label}</span>
                        {row.extraPill && (
                          <span className="rounded bg-neutral-800 px-1.5 py-0.2 font-mono text-[9.5px] text-emerald-300">
                            {row.extraPill}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 font-mono text-xs tabular-nums">
                        {candidateId !== 'baseline' && Math.abs(deltaMw) >= 1 && (
                          <span
                            className={`text-[10px] ${
                              deltaMw > 0 ? 'text-emerald-400' : 'text-amber-400'
                            }`}
                          >
                            {deltaMw > 0 ? `+${Math.round(deltaMw)}` : Math.round(deltaMw)} MW
                          </span>
                        )}
                        <span className="font-semibold text-white">{Math.round(row.mw)} MW</span>
                      </div>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-neutral-800/90">
                      <div
                        className="h-full rounded-full transition-all duration-300"
                        style={{
                          width: `${Math.max(row.mw > 0.5 ? 2 : 0, widthPct)}%`,
                          backgroundColor: row.color,
                        }}
                      />
                    </div>
                  </div>
                );
              })}

              {/* Highlighted Curtailed Solar/Wind Bar */}
              {(snap.curtailedMw > 0.5 || baseSnap.curtailedMw > 0.5) && (
                <div className="pt-1">
                  <div className="flex items-center justify-between text-xs mb-0.5">
                    <div className="flex items-center gap-1.5 text-amber-300">
                      <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                      <span className="font-semibold">Curtailed Solar/Wind (Wasted)</span>
                    </div>
                    <div className="flex items-center gap-1.5 font-mono text-xs tabular-nums">
                      {candidateId !== 'baseline' &&
                        Math.abs(snap.curtailedMw - baseSnap.curtailedMw) >= 1 && (
                          <span className="text-[10px] font-semibold text-emerald-400">
                            {Math.round(snap.curtailedMw - baseSnap.curtailedMw)} MW saved
                          </span>
                        )}
                      <span className="font-bold text-amber-300">
                        {Math.round(snap.curtailedMw)} MW
                      </span>
                    </div>
                  </div>
                  <div className="h-2.5 w-full overflow-hidden rounded-full bg-neutral-800">
                    <div
                      className="h-full rounded-full bg-curtailed-stripes transition-all duration-300"
                      style={{
                        width: `${Math.min(100, (snap.curtailedMw / maxBarMw) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              )}

              {/* Highlighted Unserved Demand (EDAC Load Shedding) Bar */}
              {(snap.unservedMw > 0.5 || baseSnap.unservedMw > 0.5) && (
                <div className="pt-1">
                  <div className="flex items-center justify-between text-xs mb-0.5">
                    <div className="flex items-center gap-1.5 text-red-400">
                      <AlertTriangle className="h-3.5 w-3.5 text-red-500 animate-pulse" />
                      <span className="font-bold">Unserved Demand (EDAC Blackout)</span>
                    </div>
                    <div className="flex items-center gap-1.5 font-mono text-xs tabular-nums">
                      {candidateId !== 'baseline' &&
                        Math.abs(snap.unservedMw - baseSnap.unservedMw) >= 1 && (
                          <span className="text-[10px] font-semibold text-emerald-400">
                            {Math.round(snap.unservedMw - baseSnap.unservedMw)} MW restored
                          </span>
                        )}
                      <span className="font-bold text-red-400">
                        {Math.round(snap.unservedMw)} MW
                      </span>
                    </div>
                  </div>
                  <div className="h-2.5 w-full overflow-hidden rounded-full bg-neutral-800">
                    <div
                      className="h-full rounded-full bg-red-600 transition-all duration-300"
                      style={{
                        width: `${Math.min(100, (snap.unservedMw / maxBarMw) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 5. 24-Hour Interactive AreaGraphContainer (Click any hour bar to scrub time) */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-1 rounded-lg bg-neutral-900 p-0.5 border border-neutral-800">
                <button
                  type="button"
                  onClick={() => setChartTab('curtailment')}
                  className={`rounded-md px-2 py-0.5 text-[10.5px] font-medium transition-colors ${
                    chartTab === 'curtailment'
                      ? 'bg-neutral-700 text-white'
                      : 'text-neutral-400 hover:text-neutral-200'
                  }`}
                >
                  24h Curtailment
                </button>
                <button
                  type="button"
                  onClick={() => setChartTab('corridors')}
                  className={`rounded-md px-2 py-0.5 text-[10.5px] font-medium transition-colors ${
                    chartTab === 'corridors'
                      ? 'bg-neutral-700 text-white'
                      : 'text-neutral-400 hover:text-neutral-200'
                  }`}
                >
                  L2 Corridor Flow
                </button>
                <button
                  type="button"
                  onClick={() => setChartTab('battery')}
                  className={`rounded-md px-2 py-0.5 text-[10.5px] font-medium transition-colors ${
                    chartTab === 'battery'
                      ? 'bg-neutral-700 text-white'
                      : 'text-neutral-400 hover:text-neutral-200'
                  }`}
                >
                  {operationMode === 'sudden_outage' ? 'Crisis & BESS' : 'Battery SOC'}
                </button>
              </div>
              <span className="text-[10px] text-neutral-400">Click bar to jump</span>
            </div>

            {/* Interactive 24-Bar Comparative Chart */}
            <div className="relative h-24 w-full flex items-end gap-[3px] pt-3">
              {hours24.map((h) => {
                const isCurrentHour = snap.hourIndex === h;
                let baseVal = 0;
                let activeVal = 0;
                let maxScale = 300;
                let barColor = '#10B981';

                if (chartTab === 'curtailment') {
                  baseVal = baseHourlyCurtailment[h];
                  activeVal = activeHourlyCurtailment[h];
                  maxScale = 290;
                  barColor = activeVal > 10 ? '#F59E0B' : '#2AA364';
                } else if (chartTab === 'corridors') {
                  baseVal = Math.abs(baseHourlyL2Flow[h]);
                  activeVal = Math.abs(activeHourlyL2Flow[h]);
                  maxScale = 620;
                  barColor =
                    activeVal >= activeSolution.assets.lines[1].capacity_mw - 1
                      ? '#EF4444'
                      : '#69D6F8';
                } else {
                  if (operationMode === 'sudden_outage' && h >= 18 && h <= 21) {
                    baseVal = baseHourlyUnserved[h];
                    activeVal = activeHourlyUnserved[h];
                    maxScale = 580;
                    barColor = '#EF4444';
                  } else {
                    baseVal = 60;
                    activeVal = activeHourlySoc[h];
                    maxScale = 680;
                    barColor = '#1DA484';
                  }
                }

                const baseHeightPct = Math.min(100, (baseVal / maxScale) * 100);
                const activeHeightPct = Math.min(100, (activeVal / maxScale) * 100);

                return (
                  <div
                    key={h}
                    onClick={() => onChangeStep96(h * 4)}
                    className={`group relative flex-1 h-full flex items-end cursor-pointer rounded-t ${
                      isCurrentHour ? 'bg-white/10 ring-1 ring-white/40' : 'hover:bg-white/5'
                    }`}
                    title={`Hour ${String(h).padStart(2, '0')}:00 CLST · Active: ${activeVal.toFixed(1)} · Baseline: ${baseVal.toFixed(1)}`}
                  >
                    {/* Baseline Ghost Bar */}
                    {candidateId !== 'baseline' && (
                      <div
                        className="absolute bottom-0 inset-x-0 rounded-t bg-neutral-600/45"
                        style={{ height: `${baseHeightPct}%` }}
                      />
                    )}
                    {/* Active Solution Bar */}
                    <div
                      className="relative z-10 w-full rounded-t transition-all duration-200"
                      style={{
                        height: `${Math.max(activeVal > 0 ? 4 : 1, activeHeightPct)}%`,
                        backgroundColor: barColor,
                      }}
                    />
                  </div>
                );
              })}
            </div>

            <div className="mt-1 flex justify-between font-mono text-[9.5px] text-neutral-400">
              <span>00:00</span>
              <span>06:00</span>
              <span className="text-amber-300">12:00 (L2 400 MW)</span>
              <span className="text-red-300">19:00 (Peak)</span>
              <span>23:00</span>
            </div>
          </div>
        </div>
      </GlassContainer>
    </div>
  );
};
