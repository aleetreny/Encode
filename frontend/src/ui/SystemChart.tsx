import React, { memo, useMemo } from 'react';
import type { Catalog, Disruption, Solution } from '../live/types';
import { TECH_COLOR } from './GridScene';

// The whole day at a glance: what each technology produces (stacked), what the country asks for
// (black line) and the homes left without supply (red gap). The solution covers all 24 hours,
// so a fault shows up as a dip over its window and a plan as the gap closing again.
const ORDER = ['coal', 'gas', 'hydro', 'wind', 'solar', 'diesel', 'battery'];

interface Props {
  catalog: Catalog;
  solution: Solution;
  hour: number;
  incidents: Disruption[];
  planFrom: number | null;
}

export const SystemChart = memo(function SystemChart({ catalog, solution, hour, incidents, planFrom }: Props) {
  const W = 280, H = 168, PAD = { l: 30, r: 6, t: 8, b: 18 };
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;

  const series = useMemo(() => {
    const byTech: Record<string, number[]> = {};
    for (const g of catalog.generators) {
      const s = solution.generation_mw[g.id] ?? [];
      byTech[g.technology] = (byTech[g.technology] ?? Array(24).fill(0)).map((v, i) => v + (s[i] ?? 0));
    }
    byTech.battery = Array(24).fill(0).map((_, i) => catalog.batteries.reduce((a, b) => a + Math.max(0, solution.battery_flow_mw[b.id]?.[i] ?? 0), 0));
    const demand = Array(24).fill(0).map((_, i) => Object.values(solution.demand_mw).reduce((a, v) => a + (v[i] ?? 0), 0));
    const unserved = Array(24).fill(0).map((_, i) => Object.values(solution.unserved_mw).reduce((a, v) => a + (v[i] ?? 0), 0));
    return { byTech, demand, unserved };
  }, [catalog, solution]);

  const total = series.demand.map((_, i) => ORDER.reduce((a, t) => a + (series.byTech[t]?.[i] ?? 0), 0));
  const max = Math.max(...total, ...series.demand, 1) * 1.08;
  const x = (i: number) => PAD.l + (i / 23) * iw;
  const y = (v: number) => PAD.t + ih - (v / max) * ih;

  // stacked areas, step-free (each hour is a point)
  let base = Array(24).fill(0);
  const areas = ORDER.filter((t) => series.byTech[t]?.some((v) => v > 0.5)).map((t) => {
    const top = base.map((b, i) => b + (series.byTech[t]?.[i] ?? 0));
    const d = `M${top.map((v, i) => `${x(i)},${y(v)}`).join('L')}L${base.map((v, i) => `${x(23 - i)},${y(base[23 - i])}`).join('L')}Z`;
    base = top;
    return { t, d };
  });
  const demandLine = `M${series.demand.map((v, i) => `${x(i)},${y(v)}`).join('L')}`;
  const served = series.demand.map((v, i) => v - series.unserved[i]);
  const gap = series.unserved.some((u) => u > 0.5)
    ? `M${series.demand.map((v, i) => `${x(i)},${y(v)}`).join('L')}L${served.map((_, i) => `${x(23 - i)},${y(served[23 - i])}`).join('L')}Z`
    : '';
  const now = Math.min(23, Math.max(0, hour));
  const peakOff = Math.max(...Object.values(solution.households_off).reduce((acc, v) => acc.map((a, i) => a + (v[i] ?? 0)), Array(24).fill(0)));
  const ticks = [0, 6, 12, 18, 23];
  const yTicks = [0, Math.round(max / 2 / 100) * 100, Math.round((max * 0.92) / 100) * 100];

  return (
    <div className="gp-chart">
      <div className="gp-chart-head">
        <b>Sistema · hoy</b>
        <span>{peakOff > 1 ? `peor hora: ${Math.round(peakOff).toLocaleString('es-CL')} hogares sin luz` : 'toda la demanda cubierta'}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="gp-chart-svg" role="img" aria-label="Generación por tecnología y demanda del día">
        {/* the future is still a forecast */}
        <rect x={x(now)} y={PAD.t} width={Math.max(0, PAD.l + iw - x(now))} height={ih} className="gp-chart-future" />
        {incidents.map((d) => (
          <g key={d.event_id}>
            <rect x={x(Math.max(0, d.from_hour))} y={PAD.t} width={Math.max(2, x(Math.min(23, d.to_hour)) - x(Math.max(0, d.from_hour)))} height={ih} className="gp-chart-fault" />
            <text x={x(Math.max(0, d.from_hour)) + 2} y={PAD.t + 9} className="gp-chart-fault-label">{d.jury_name || d.asset_id}</text>
          </g>
        ))}
        {areas.map((a) => (
          <path key={a.t} d={a.d} style={{ fill: TECH_COLOR[a.t] }} className="gp-chart-area" />
        ))}
        {gap && <path d={gap} className="gp-chart-gap" />}
        <path d={demandLine} className="gp-chart-demand" />
        {planFrom !== null && <line x1={x(planFrom)} x2={x(planFrom)} y1={PAD.t} y2={PAD.t + ih} className="gp-chart-plan" />}
        <line x1={x(now)} x2={x(now)} y1={PAD.t - 2} y2={PAD.t + ih} className="gp-chart-now" />
        <circle cx={x(now)} cy={y(series.demand[Math.floor(now)] ?? 0)} r="3" className="gp-chart-dot" />
        {ticks.map((t) => (
          <text key={t} x={x(t)} y={H - 4} textAnchor="middle" className="gp-chart-axis">{String(t).padStart(2, '0')}h</text>
        ))}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={PAD.l + iw} y1={y(v)} y2={y(v)} className="gp-chart-grid" />
            <text x={PAD.l - 4} y={y(v) + 3} textAnchor="end" className="gp-chart-axis">{v >= 1000 ? `${(v / 1000).toLocaleString('es-CL', { maximumFractionDigits: 1 })}k` : v}</text>
          </g>
        ))}
      </svg>
      <div className="gp-chart-key">
        <span><i className="ln" />Demanda</span>
        <span><i className="gap" />Sin suministro</span>
        <span><i className="fault" />Falla</span>
        <span className="gp-chart-unit">MW · colores por tecnología</span>
      </div>
    </div>
  );
});
