import React, { memo, useMemo } from 'react';
import * as k from '../iso/iso-kit';
import type { Catalog, Disruption, Solution } from '../live/types';
import { GEMINI, H, P, W, ZONES, housesOf, pct, screen, slotOf, uv } from './layout';

const uvAt = (hub: k.Point3, u: number, v: number) => uv(u, v, [hub[0], hub[1]]);
import { AssetState, Battery, BoostMark, CoalPlant, Diesel, GasPlant, GeminiCore, Hub, Hydro, Neighbourhood, Solar, TripMark, Wind } from './objects';

export interface Asset {
  id: string;
  kind: 'generator' | 'battery' | 'line';
  name: string;
  nodeId: string;
  technology: string;
  capacity: number;
  at: k.Point3;
}

const TECH_LABEL: Record<string, string> = {
  solar: 'Solar', wind: 'Eólica', hydro: 'Hidro', gas: 'Gas', coal: 'Carbón', diesel: 'Diésel', battery: 'Batería',
};
export const assetTitle = (a: Asset) =>
  a.kind === 'line' ? `Línea ${a.id}` : `${TECH_LABEL[a.technology] ?? a.technology} · ${ZONES[a.nodeId]?.label ?? a.nodeId}`;

export function buildAssets(catalog: Catalog): Asset[] {
  const used = new Set<string>();
  const gens: Asset[] = catalog.generators.map((g) => ({
    id: g.id, kind: 'generator', name: g.name, nodeId: g.node_id, technology: g.technology, capacity: g.capacity_mw, at: slotOf(g.id, g.node_id, used),
  }));
  const bats: Asset[] = catalog.batteries.map((b) => ({
    id: b.id, kind: 'battery', name: b.name, nodeId: b.node_id, technology: 'battery', capacity: b.power_mw, at: slotOf(b.id, b.node_id, used),
  }));
  return [...gens, ...bats];
}

// Value of a 24-step series at a fractional hour, interpolated between steps.
export const at = (series: number[] | undefined, hour: number) => {
  if (!series || series.length === 0) return 0;
  const h0 = Math.floor(hour) % series.length;
  const h1 = (h0 + 1) % series.length;
  const f = hour - Math.floor(hour);
  return series[h0] * (1 - f) + series[h1] * f;
};

const active = (d: Disruption, hour: number) => hour >= d.from_hour && hour < d.to_hour;

interface Props {
  catalog: Catalog;
  solution: Solution;
  hour: number;
  incidents: Disruption[];
  boosted: Set<string>;
  phase: string;
  focus: string[]; // asset ids Gemini is looking at
  selected: string | null;
  onSelect: (id: string | null) => void;
}

// Point along a polyline of screen points, t in [0,1).
function along(pts: [number, number][], t: number): [number, number] {
  const seg: number[] = [];
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    const l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    seg.push(l);
    total += l;
  }
  let d = (((t % 1) + 1) % 1) * total;
  for (let i = 0; i < seg.length; i++) {
    if (d <= seg[i]) {
      const f = seg[i] ? d / seg[i] : 0;
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f];
    }
    d -= seg[i];
  }
  return pts[pts.length - 1];
}

// A sagging wire between two ground points with packets moving in the flow direction.
function PowerWire({ from, to, mw, cap, state, lift = 14, label }: {
  from: k.Point3; to: k.Point3; mw: number; cap: number; state: 'ok' | 'hot' | 'tripped' | 'feeder'; lift?: number; label?: string;
}) {
  const mid: k.Point3 = [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2, lift * 0.75];
  const pts = [k.iso([from[0], from[1], lift], P), k.iso(mid, P), k.iso([to[0], to[1], lift], P)];
  const d = k.pathOf(pts);
  const abs = Math.abs(mw);
  const load = cap > 0 ? Math.min(1, abs / cap) : 0;
  const n = state === 'tripped' || abs < 3 ? 0 : Math.max(2, Math.round(2 + load * 3));
  const dur = 5 - load * 3.2;
  const reverse = mw < 0;
  return (
    <g className={`gp-wire is-${state}`}>
      <path d={k.pathOf([k.iso([from[0], from[1], 0], P), pts[0]])} className="gp-pole" />
      <path d={k.pathOf([k.iso([to[0], to[1], 0], P), pts[2]])} className="gp-pole" />
      {state === 'hot' && <path d={d} className="gp-wire-aura" />}
      <path d={d} className="gp-wire-line" />
      {Array.from({ length: n }).map((_, i) => (
        <circle key={`${i}-${n}-${reverse}`} r={state === 'feeder' ? 1.6 : 2.4} className="gp-packet">
          <animateMotion dur={`${dur}s`} begin={`${(-i * dur) / n}s`} repeatCount="indefinite" path={d} keyPoints={reverse ? '1;0' : '0;1'} keyTimes="0;1" calcMode="linear" />
        </circle>
      ))}
      {label && (() => {
        const [x, y] = along(pts, 0.5);
        return (
          <text x={x} y={y - 9} className="gp-wire-label" textAnchor="middle">{label}</text>
        );
      })()}
    </g>
  );
}

export const GridScene = memo(function GridScene({ catalog, solution, hour, incidents, boosted, phase, focus, selected, onSelect }: Props) {
  const assets = useMemo(() => buildAssets(catalog), [catalog]);
  const tripped = useMemo(() => new Set(incidents.filter((d) => active(d, hour)).map((d) => d.asset_id)), [incidents, hour]);

  const stateOf = (a: Asset): AssetState => {
    if (tripped.has(a.id)) return 'tripped';
    if (boosted.has(a.id)) return 'boost';
    if (a.kind === 'battery') {
      const b = catalog.batteries.find((x) => x.id === a.id);
      const flow = Math.abs(at(solution.battery_flow_mw[a.id], hour));
      if (b?.standby && flow < 0.5) return 'standby';
    }
    return 'ok';
  };
  const output = (a: Asset) => (a.kind === 'battery' ? at(solution.battery_flow_mw[a.id], hour) : at(solution.generation_mw[a.id], hour));

  // Draw back-to-front: larger screen y last.
  const drawables: { y: number; node: React.ReactNode }[] = [];
  for (const a of assets) {
    const s = stateOf(a);
    const out = output(a);
    const level = a.capacity ? Math.min(1, Math.abs(out) / a.capacity) : 0;
    const lit = selected === a.id || focus.includes(a.id);
    const common = { at: a.at, state: s, level, lit };
    const body =
      a.kind === 'battery' ? (
        <Battery {...common} soc={Math.min(1, at(solution.battery_soc_mwh[a.id], hour) / Math.max(1, (catalog.batteries.find((b) => b.id === a.id)?.energy_mwh ?? 1)))} charging={out < 0} />
      ) : a.technology === 'solar' ? <Solar {...common} />
      : a.technology === 'wind' ? <Wind {...common} />
      : a.technology === 'gas' ? <GasPlant {...common} />
      : a.technology === 'coal' ? <CoalPlant {...common} />
      : a.technology === 'hydro' ? <Hydro {...common} />
      : <Diesel {...common} />;
    drawables.push({
      y: screen(a.at)[1],
      node: (
        <g key={a.id} className={`gp-asset${selected === a.id ? ' is-selected' : ''}${s === 'standby' ? ' is-standby' : ''}`} onClick={(e) => { e.stopPropagation(); onSelect(selected === a.id ? null : a.id); }}>
          {body}
          {s === 'tripped' && <TripMark at={a.at} />}
          {s === 'boost' && <BoostMark at={a.at} />}
        </g>
      ),
    });
  }
  for (const n of catalog.nodes) {
    const z = ZONES[n.id];
    if (!z) continue;
    const off = at(solution.households_off[n.id], hour);
    const count = n.households_total > 2_000_000 ? 12 : n.households_total > 900_000 ? 9 : 6;
    const dark = off > 1 ? Math.max(1, Math.round((off / n.households_total) * count)) : 0;
    drawables.push({ y: screen(z.hub)[1], node: <g key={`hub-${n.id}`}><Hub at={z.hub} lit={focus.includes(n.id)} /></g> });
    drawables.push({ y: screen(housesOf(n.id))[1], node: <g key={`hh-${n.id}`}><Neighbourhood at={housesOf(n.id)} count={count} dark={dark} highlight={focus.includes(n.id)} /></g> });
  }
  drawables.sort((p, q) => p.y - q.y);

  // Trunk lines between hubs.
  const wires = catalog.lines.map((l) => {
    const from = ZONES[l.from]?.hub, to = ZONES[l.to]?.hub;
    if (!from || !to) return null;
    const mw = at(solution.line_flow_mw[l.id], hour);
    const cap = at(solution.line_capacity_mw[l.id], hour) || l.capacity_mw;
    const isTripped = tripped.has(l.id);
    const hot = !isTripped && Math.abs(mw) >= cap * 0.97;
    return (
      <g key={l.id} className="gp-asset" onClick={(e) => { e.stopPropagation(); onSelect(selected === l.id ? null : l.id); }}>
        <PowerWire from={from} to={to} mw={mw} cap={cap} state={isTripped ? 'tripped' : hot ? 'hot' : 'ok'} lift={22} label={`${l.id} · ${isTripped ? 'CORTADA' : `${Math.round(Math.abs(mw))}/${Math.round(cap)} MW`}`} />
        {isTripped && <TripMark at={[(from[0] + to[0]) / 2, (from[1] + to[1]) / 2, 0]} radius={14} height={30} />}
      </g>
    );
  });
  // Feeders: plant → hub and hub → neighbourhood.
  const feeders = [
    ...assets.map((a) => {
      const hub = ZONES[a.nodeId]?.hub;
      if (!hub) return null;
      const out = output(a);
      return <PowerWire key={`f-${a.id}`} from={a.at} to={hub} mw={out} cap={a.capacity} state={tripped.has(a.id) ? 'tripped' : 'feeder'} lift={9} />;
    }),
    ...catalog.nodes.map((n) => {
      const hub = ZONES[n.id]?.hub;
      if (!hub) return null;
      const served = at(solution.demand_mw[n.id], hour) - at(solution.unserved_mw[n.id], hour);
      return <PowerWire key={`d-${n.id}`} from={hub} to={housesOf(n.id)} mw={served} cap={Math.max(1, at(solution.demand_mw[n.id], hour))} state="feeder" lift={9} />;
    }),
  ];

  // Gemini's gaze: beams to whatever it is analysing or acting on.
  const core = screen([GEMINI[0], GEMINI[1], GEMINI[2] - 22]);
  const targets = focus
    .map((id) => assets.find((a) => a.id === id)?.at ?? (ZONES[id] ? housesOf(id) : catalog.lines.find((l) => l.id === id) ? (() => {
      const l = catalog.lines.find((x) => x.id === id)!;
      const a = ZONES[l.from].hub, b = ZONES[l.to].hub;
      return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 18] as k.Point3;
    })() : null))
    .filter(Boolean) as k.Point3[];

  return (
    <div className="gp-scene" onClick={() => onSelect(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="gp-svg" aria-label="Maqueta isométrica de la red eléctrica de Chile">
        <defs>
          <linearGradient id="gp-gem" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4f8bff" />
            <stop offset="0.55" stopColor="#9b72ff" />
            <stop offset="1" stopColor="#ff7ab6" />
          </linearGradient>
          <radialGradient id="gp-gem-glow">
            <stop offset="0" stopColor="#8b7bff" stopOpacity="0.35" />
            <stop offset="1" stopColor="#8b7bff" stopOpacity="0" />
          </radialGradient>
        </defs>
        <g className="gp-feeders">{feeders}</g>
        <g className="gp-trunk">{wires}</g>
        <g>{drawables.map((d) => d.node)}</g>
        <g className="gp-beams">
          {targets.map((p, i) => {
            const [x, y] = screen([p[0], p[1], 10]);
            return <path key={i} d={`M${core[0]},${core[1]} Q${(core[0] + x) / 2},${Math.min(core[1], y) - 40} ${x},${y}`} className={`gp-beam is-${phase}`} />;
          })}
        </g>
        <GeminiCore at={GEMINI} phase={phase} />
      </svg>
      <div className="gp-labels">
        {Object.entries(ZONES).map(([id, z]) => {
          const n = catalog.nodes.find((x) => x.id === id);
          const off = at(solution.households_off[id], hour);
          return (
            <div key={id} className={`gp-zone-label${off > 1 ? ' is-dark' : ''}`} style={pct(uvAt(z.hub, -8, 128))}>
              <b>{z.label}</b>
              <span>{off > 1 ? `${Math.round(off).toLocaleString('es-CL')} hogares sin luz` : n ? `${(n.households_total / 1e6).toLocaleString('es-CL', { maximumFractionDigits: 2 })} M hogares · con luz` : ''}</span>
            </div>
          );
        })}
        {assets.map((a) => {
          const s = stateOf(a);
          const out = output(a);
          if (s === 'standby' && selected !== a.id) return null; // reserve units stay quiet until used
          return (
            <div key={a.id} className={`gp-asset-label is-${s}${selected === a.id ? ' is-selected' : ''}`} style={pct([a.at[0], a.at[1], a.technology === 'wind' ? 62 : a.technology === 'coal' ? 64 : a.technology === 'gas' || a.technology === 'diesel' ? 46 : 30])}>
              <span className="gp-asset-name">{TECH_LABEL[a.technology] ?? a.technology}</span>
              <span className="gp-asset-mw">
                {s === 'tripped' ? 'FUERA' : s === 'standby' ? 'reserva' : `${Math.round(Math.abs(out))} MW${a.kind === 'battery' ? (out < -0.5 ? ' ↓' : out > 0.5 ? ' ↑' : '') : ''}`}
              </span>
            </div>
          );
        })}
        <div className={`gp-gemini-label is-${phase}`} style={pct([GEMINI[0], GEMINI[1], GEMINI[2] + 44])}>
          <b>Gemini 4 Argon</b>
          <span>{phase === 'analyzing' ? 'analizando la red…' : phase === 'awaiting_operator' ? 'esperando tu decisión' : phase === 'executing' ? 'ejecutando el plan' : phase === 'resolved' ? 'plan aplicado · vigilando' : 'vigilando la red'}</span>
        </div>
      </div>
    </div>
  );
});
