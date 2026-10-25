import React, { memo, useMemo, useRef, useState } from 'react';
import * as k from '../iso/iso-kit';
import type { Catalog, Disruption, Solution } from '../live/types';
import { GEMINI, H, P, W, ZONES, housesOf, placeAssets, screen, uv } from './layout';

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

// One colour per technology, used as a ground pad under each plant and in the legend.
export const TECH_COLOR: Record<string, string> = {
  solar: '#f5b301', wind: '#38bdf8', hydro: '#2563eb', gas: '#f97316', coal: '#6b7280', diesel: '#be185d', battery: '#8b5cf6',
};
export const TECH_LABEL: Record<string, string> = {
  solar: 'Solar', wind: 'Eólica', hydro: 'Hidro', gas: 'Gas', coal: 'Carbón', diesel: 'Diésel', battery: 'Batería',
};
export const assetTitle = (a: Asset) =>
  a.kind === 'line' ? `Línea ${a.id}` : `${TECH_LABEL[a.technology] ?? a.technology} · ${ZONES[a.nodeId]?.label ?? a.nodeId}`;

export function buildAssets(catalog: Catalog): Asset[] {
  const spots = placeAssets([
    ...catalog.generators.map((g) => ({ id: g.id, nodeId: g.node_id, kind: 'generator' as const, capacity: g.capacity_mw })),
    ...catalog.batteries.map((b) => ({ id: b.id, nodeId: b.node_id, kind: 'battery' as const, capacity: b.power_mw, standby: b.standby })),
  ]);
  const gens: Asset[] = catalog.generators.map((g) => ({
    id: g.id, kind: 'generator', name: g.name, nodeId: g.node_id, technology: g.technology, capacity: g.capacity_mw, at: spots[g.id],
  }));
  const bats: Asset[] = catalog.batteries.map((b) => ({
    id: b.id, kind: 'battery', name: b.name, nodeId: b.node_id, technology: 'battery', capacity: b.power_mw, at: spots[b.id],
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

export const HOMES_PER_HOUSE = 200_000;

const active = (d: Disruption, hour: number) => hour >= d.from_hour && hour < d.to_hour;

interface Props {
  catalog: Catalog;
  solution: Solution;
  hour: number;
  incidents: Disruption[];
  boosted: Set<string>;
  phase: string;
  focus: string[]; // asset ids Gemini is looking at
  affected: string[]; // zones that lost supply because of the active incidents
  proposed: Set<string>; // lever targets of the plan on the table (recommended or hovered)
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

// Trunk lines ride above everything else: thick, coloured by state, with a pill label.
function TrunkLine({ from, to, mw, cap, state, label, lift = 26 }: {
  from: k.Point3; to: k.Point3; mw: number; cap: number; state: 'ok' | 'hot' | 'tripped'; label: string; lift?: number;
}) {
  const mid: k.Point3 = [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2, lift * 0.8];
  const pts = [k.iso([from[0], from[1], lift], P), k.iso(mid, P), k.iso([to[0], to[1], lift], P)];
  const d = k.pathOf(pts);
  const load = cap > 0 ? Math.min(1, Math.abs(mw) / cap) : 0;
  const width = state === 'tripped' ? 3.2 : 1.8 + load * 2.8;
  const n = state === 'tripped' || Math.abs(mw) < 3 ? 0 : 3 + Math.round(load * 4);
  const dur = 4.6 - load * 3;
  const [lx, ly] = along(pts, 0.5);
  const tw = label.length * 7.3 + 18;
  // A break in the middle of a cut line
  const [b0x, b0y] = along(pts, 0.46), [b1x, b1y] = along(pts, 0.54);
  return (
    <g className={`gp-trunk-line is-${state}`}>
      {[pts[0], pts[2]].map(([x, y], i) => (
        <g key={i}>
          <line x1={x} y1={y} x2={x} y2={k.iso([i ? to[0] : from[0], i ? to[1] : from[1], 0], P)[1]} className="gp-pylon" />
          <circle cx={x} cy={y} r="2.6" className="gp-pylon-top" />
        </g>
      ))}
      <path d={d} className="gp-trunk-glow" style={{ strokeWidth: width + 7 }} />
      {state === 'tripped' ? (
        <>
          <path d={k.pathOf([pts[0], [b0x, b0y]])} className="gp-trunk-core" style={{ strokeWidth: width }} />
          <path d={k.pathOf([[b1x, b1y], pts[2]])} className="gp-trunk-core" style={{ strokeWidth: width }} />
          <path d={`M${b0x - 4},${b0y - 7}l5,7l-5,7M${b1x + 4},${b1y - 7}l-5,7l5,7`} className="gp-trunk-break" />
        </>
      ) : (
        <path d={d} className="gp-trunk-core" style={{ strokeWidth: width }} />
      )}
      {Array.from({ length: n }).map((_, i) => (
        <circle key={`${i}-${n}-${mw < 0}`} r={2.2 + load * 1.4} className="gp-trunk-packet">
          <animateMotion dur={`${dur}s`} begin={`${(-i * dur) / n}s`} repeatCount="indefinite" path={d} keyPoints={mw < 0 ? '1;0' : '0;1'} keyTimes="0;1" calcMode="linear" />
        </circle>
      ))}
      <g transform={`translate(${lx},${ly - 16})`}>
        <rect x={-tw / 2} y={-11} width={tw} height={20} rx={10} className="gp-trunk-pill" />
        <text y={3.5} textAnchor="middle" className="gp-trunk-text">{label}</text>
      </g>
    </g>
  );
}

// An arc of power from a source to a zone in trouble. `probe` is the solver trying a path,
// `proposed` is the plan on the table, `applied` is the plan running with energy flowing in.
function RescueArc({ from, to, kind, delay = 0 }: { from: [number, number]; to: [number, number]; kind: 'probe' | 'proposed' | 'applied'; delay?: number }) {
  const lift = Math.max(50, Math.hypot(to[0] - from[0], to[1] - from[1]) * 0.35);
  const d = `M${from[0]},${from[1]} Q${(from[0] + to[0]) / 2},${Math.min(from[1], to[1]) - lift} ${to[0]},${to[1]}`;
  return (
    <g className={`gp-rescue is-${kind}`} style={{ ['--d' as string]: `${delay}s` }}>
      {kind !== 'probe' && <path d={d} className="gp-rescue-glow" />}
      <path d={d} className="gp-rescue-line" pathLength={1} />
      {kind === 'applied' && [0, 1, 2, 3].map((i) => (
        <circle key={i} r="3.2" className="gp-rescue-packet">
          <animateMotion dur="1.8s" begin={`${-i * 0.45}s`} repeatCount="indefinite" path={d} />
        </circle>
      ))}
      {kind !== 'probe' && <circle cx={to[0]} cy={to[1]} r="5" className="gp-rescue-land gp-spread" />}
    </g>
  );
}

export const GridScene = memo(function GridScene({ catalog, solution, hour, incidents, boosted, phase, focus, affected, proposed, selected, onSelect }: Props) {
  // Pan and zoom: drag to move, wheel or pinch to zoom around the pointer, double click to reset.
  const [view, setView] = useState({ x: 0, y: 0, s: 1 });
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ px: number; py: number; moved: boolean; id: number } | null>(null);
  const toSvg = (clientX: number, clientY: number) => {
    const m = svgRef.current?.getScreenCTM();
    if (!m) return { x: 0, y: 0, k: 1 };
    const p = new DOMPoint(clientX, clientY).matrixTransform(m.inverse());
    return { x: p.x, y: p.y, k: 1 / m.a };
  };
  const zoomAt = (cx: number, cy: number, factor: number) =>
    setView((v) => {
      const s2 = Math.min(4, Math.max(1, v.s * factor));
      const r = s2 / v.s;
      return clampView({ s: s2, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r });
    });
  const clampView = (v: { x: number; y: number; s: number }) => {
    // keep at least part of the maquette in view
    const minX = W - W * v.s - W * 0.2, minY = H - H * v.s - H * 0.2;
    return { s: v.s, x: Math.min(W * 0.2, Math.max(minX, v.x)), y: Math.min(H * 0.2, Math.max(minY, v.y)) };
  };
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
        <g key={a.id} className={`gp-asset is-${s}${selected === a.id ? ' is-selected' : ''}`} onClick={(e) => { e.stopPropagation(); onSelect(selected === a.id ? null : a.id); }}>
          <path d={k.ring(a.at[0], a.at[1], a.technology === 'wind' ? 24 : 27, 0.1, P, 44)} className="gp-pad" style={s === 'tripped' ? undefined : { fill: TECH_COLOR[a.technology], stroke: TECH_COLOR[a.technology] }} />
          <g className="gp-asset-body">{body}</g>
          {s === 'tripped' && (
            <>
              <path d={k.ring(a.at[0], a.at[1], 34, 0.2, P, 48)} className="gp-shock" />
              <path d={k.ring(a.at[0], a.at[1], 34, 0.2, P, 48)} className="gp-shock is-late" />
              <TripMark at={a.at} />
            </>
          )}
          {s === 'boost' && <BoostMark at={a.at} />}
        </g>
      ),
    });
  }
  const alarmHubs = new Set(catalog.lines.filter((l) => tripped.has(l.id)).flatMap((l) => [l.from, l.to]));
  for (const n of catalog.nodes) {
    const z = ZONES[n.id];
    if (!z) continue;
    const off = at(solution.households_off[n.id], Math.floor(hour));
    // Same scale everywhere so houses can be counted: one house = 200,000 homes.
    const count = Math.max(1, Math.round(n.households_total / HOMES_PER_HOUSE));
    const dark = off > 1 ? Math.min(count, Math.max(1, Math.round(off / HOMES_PER_HOUSE))) : 0;
    drawables.push({ y: screen(z.hub)[1], node: <g key={`hub-${n.id}`}>{alarmHubs.has(n.id) && <path d={k.ring(z.hub[0], z.hub[1], 26, 0.3, P, 40)} className="gp-hub-alarm" />}<Hub at={z.hub} lit={focus.includes(n.id)} /></g> });
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
    const hot = !isTripped && Math.abs(mw) >= cap * 0.95;
    const who = incidents.find((d) => d.asset_id === l.id && active(d, hour));
    const label = isTripped
      ? `${l.id} CORTADA${who?.jury_name ? ` · ${who.jury_name}` : who?.source === 'jury' ? ' · jurado' : ''}`
      : `${l.id} · ${Math.round((Math.abs(mw) / cap) * 100)} %${hot ? ' ⚠' : ''}`;
    return (
      <g key={l.id} className="gp-asset" onClick={(e) => { e.stopPropagation(); onSelect(selected === l.id ? null : l.id); }}>
        <TrunkLine from={from} to={to} mw={mw} cap={cap} state={isTripped ? 'tripped' : hot ? 'hot' : 'ok'} label={label} />
        {!isTripped && (boosted.has(l.id) || proposed.has(l.id)) && (() => {
          const lift = 26;
          const d = k.pathOf([k.iso([from[0], from[1], lift], P), k.iso([(from[0] + to[0]) / 2, (from[1] + to[1]) / 2, lift * 0.8], P), k.iso([to[0], to[1], lift], P)]);
          return <path d={d} className={`gp-trunk-rescue${boosted.has(l.id) ? ' is-applied' : ''}`} />;
        })()}
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

  // The optimisation, drawn on the map: while Gemini analyses, the solver probes every flexible
  // source towards the zones in the dark; then the plan on the table shows as dashed arcs, and
  // once applied, energy flows along them into the zone.
  const zoneTargets = affected.map((n) => (ZONES[n] ? screen([...housesOf(n).slice(0, 2), 14] as k.Point3) : null)).filter(Boolean) as [number, number][];
  const sourceOf = (id: string): [number, number] | null => {
    const a = assets.find((x) => x.id === id);
    if (a) return screen([a.at[0], a.at[1], 30]);
    return null;
  };
  const rescues: React.ReactNode[] = [];
  const nearest = (p: [number, number]) => zoneTargets.reduce((b, t) => (Math.hypot(t[0] - p[0], t[1] - p[1]) < Math.hypot(b[0] - p[0], b[1] - p[1]) ? t : b), zoneTargets[0]);
  if (zoneTargets.length) {
    if (phase === 'analyzing') {
      const flexible = assets.filter((a) => !tripped.has(a.id) && (a.kind === 'battery' || ['gas', 'hydro', 'diesel', 'coal'].includes(a.technology)));
      flexible.forEach((a, i) => {
        const from = sourceOf(a.id)!;
        rescues.push(<RescueArc key={`p-${a.id}`} from={from} to={nearest(from)} kind="probe" delay={i * 0.22} />);
      });
    }
    const drawLevers = (ids: Set<string>, kind: 'proposed' | 'applied') => ids.forEach((id) => {
      const from = sourceOf(id);
      if (from) rescues.push(<RescueArc key={`${kind}-${id}`} from={from} to={nearest(from)} kind={kind} />);
    });
    if (phase === 'awaiting_operator') drawLevers(proposed, 'proposed');
    if (phase === 'executing' || phase === 'resolved') drawLevers(boosted, 'applied');
  }
  // Demand response lands on the zone itself: its houses glow while load is being shed.
  const easedZones = new Set([...(phase === 'awaiting_operator' ? proposed : []), ...(phase === 'executing' || phase === 'resolved' ? boosted : [])].filter((id) => ZONES[id]));

  // Labels live inside the drawing (so they zoom with it) and are spread out so none overlap:
  // each one starts right above its object and climbs until it is clear, keeping a thin leader.
  type Lbl = { id: string; x: number; y: number; ax: number; ay: number; w: number; name: string; mw: string; color: string; state: string };
  const labels: Lbl[] = [];
  for (const a of assets) {
    const s = stateOf(a);
    if (s === 'standby' && selected !== a.id) continue; // reserve units stay quiet until used
    const out = output(a);
    const top = a.technology === 'wind' ? 62 : a.technology === 'coal' ? 64 : a.technology === 'gas' || a.technology === 'diesel' ? 46 : 30;
    const [ax, ay] = screen([a.at[0], a.at[1], top]);
    const name = TECH_LABEL[a.technology] ?? a.technology;
    const mw = s === 'tripped' ? '' : `${Math.round(Math.abs(out))} MW${a.kind === 'battery' ? (out < -0.5 ? ' ↓' : out > 0.5 ? ' ↑' : '') : ''}`;
    const w = (name.length + mw.length) * 7.4 + (mw ? 34 : 26);
    labels.push({ id: a.id, x: ax, y: ay - 10, ax, ay, w, name, mw, color: TECH_COLOR[a.technology], state: s });
  }
  labels.sort((p, q) => q.ay - p.ay); // lower objects first, so higher labels climb above them
  const placed: Lbl[] = [];
  const LH = 20;
  for (const l of labels) {
    for (let k2 = 0; k2 < 8; k2++) {
      const hit = placed.find((o) => Math.abs(o.x - l.x) < (o.w + l.w) / 2 + 4 && Math.abs(o.y - l.y) < LH + 2);
      if (!hit) break;
      l.y = hit.y - LH - 3;
    }
    placed.push(l);
  }

  return (
    <div className="gp-scene" onClick={() => onSelect(null)}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className={`gp-svg${view.s > 1 ? ' is-zoomed' : ''}`}
        aria-label="Maqueta isométrica de la red eléctrica de Chile"
        onWheel={(e) => {
          const p = toSvg(e.clientX, e.clientY);
          zoomAt(p.x, p.y, Math.exp(-e.deltaY * 0.0015));
        }}
        onPointerDown={(e) => {
          drag.current = { px: e.clientX, py: e.clientY, moved: false, id: e.pointerId };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d || d.id !== e.pointerId) return;
          const dx = e.clientX - d.px, dy = e.clientY - d.py;
          if (!d.moved && Math.hypot(dx, dy) < 4) return;
          if (!d.moved) (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
          d.moved = true;
          const k3 = toSvg(0, 0).k;
          d.px = e.clientX; d.py = e.clientY;
          setView((v) => clampView({ ...v, x: v.x + dx * k3, y: v.y + dy * k3 }));
        }}
        onPointerUp={(e) => {
          const d = drag.current;
          if (d?.moved) (e.currentTarget as SVGSVGElement).releasePointerCapture?.(e.pointerId);
        }}
        onClickCapture={(e) => {
          if (drag.current?.moved) e.stopPropagation(); // a drag is not a click
          drag.current = null;
        }}
        onDoubleClick={() => setView({ x: 0, y: 0, s: 1 })}
      >
        <defs>
          <linearGradient id="gp-gem" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4f8bff" />
            <stop offset="0.55" stopColor="#9b72ff" />
            <stop offset="1" stopColor="#ff7ab6" />
          </linearGradient>
          {/* Recolours a plant in shades of red while keeping its shading, for a tripped asset. */}
          <filter id="gp-redden" colorInterpolationFilters="sRGB">
            <feColorMatrix type="matrix" values="0.45 0.45 0.1 0 0.25  0.12 0.12 0.04 0 0.02  0.12 0.12 0.04 0 0.04  0 0 0 1 0" />
          </filter>
          <radialGradient id="gp-gem-glow">
            <stop offset="0" stopColor="#8b7bff" stopOpacity="0.35" />
            <stop offset="1" stopColor="#8b7bff" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect x={-W} y={-H} width={W * 3} height={H * 3} fill="transparent" />
        <g transform={`translate(${view.x} ${view.y}) scale(${view.s})`}>
          <g className="gp-feeders">{feeders}</g>
          <g>{drawables.map((d) => d.node)}</g>
          <g className="gp-trunk">{wires}</g>
          <g className="gp-rescues">
            {[...easedZones].map((id) => {
              const h = housesOf(id);
              return <path key={`dr-${id}`} d={k.ring(h[0] - 3, h[1] + 12, 48, 0.3, P, 48)} className={`gp-dr-ring${boosted.has(id) ? ' is-applied' : ''}`} />;
            })}
            {rescues}
          </g>
          <g className="gp-beams">
            {targets.map((p, i) => {
              const [x, y] = screen([p[0], p[1], 10]);
              return <path key={i} d={`M${core[0]},${core[1]} Q${(core[0] + x) / 2},${Math.min(core[1], y) - 40} ${x},${y}`} className={`gp-beam is-${phase}`} />;
            })}
          </g>
          <GeminiCore at={GEMINI} phase={phase} />
          <g className="gp-svg-labels">
            {Object.entries(ZONES).map(([id, z]) => {
              const n = catalog.nodes.find((x) => x.id === id);
              const off = at(solution.households_off[id], Math.floor(hour));
              const [x, y] = screen(uvAt(z.hub, -8, 128));
              return (
                <g key={id} className={`gp-zlabel${off > 1 ? ' is-dark' : ''}`}>
                  <text x={x} y={y} textAnchor="middle" className="gp-zlabel-name">{z.label.toUpperCase()}</text>
                  <text x={x} y={y + 17} textAnchor="middle" className="gp-zlabel-sub">
                    {off > 1 ? `${Math.round(off).toLocaleString('es-CL')} hogares sin luz` : n ? `${(n.households_total / 1e6).toLocaleString('es-CL', { maximumFractionDigits: 2 })} M hogares · con luz` : ''}
                  </text>
                </g>
              );
            })}
            {placed.map((l) => (
              <g key={l.id} className={`gp-alabel is-${l.state}${selected === l.id ? ' is-selected' : ''}`} onClick={(e) => { e.stopPropagation(); onSelect(selected === l.id ? null : l.id); }}>
                {l.ay - l.y > 16 && <line x1={l.ax} y1={l.ay} x2={l.x} y2={l.y + 8} className="gp-alabel-leader" />}
                <rect x={l.x - l.w / 2} y={l.y - 12} width={l.w} height={20} rx={5} className="gp-alabel-bg" />
                <rect x={l.x - l.w / 2 + 6} y={l.y - 6} width={9} height={9} rx={2} fill={l.color} />
                <text x={l.x - l.w / 2 + 20} y={l.y + 2.5} className="gp-alabel-name">{l.name}</text>
                <text x={l.x + l.w / 2 - 7} y={l.y + 2.5} textAnchor="end" className="gp-alabel-mw">{l.mw}</text>
              </g>
            ))}
            {(() => {
              const [x, y] = screen([GEMINI[0], GEMINI[1], GEMINI[2] + 44]);
              return (
                <g className={`gp-glabel is-${phase}`}>
                  <text x={x} y={y} textAnchor="middle" className="gp-glabel-name">Gemini</text>
                  <text x={x} y={y + 17} textAnchor="middle" className="gp-glabel-sub">{phase === 'analyzing' ? 'analizando la red…' : phase === 'awaiting_operator' ? 'esperando tu decisión' : phase === 'executing' ? 'ejecutando el plan' : phase === 'resolved' ? 'plan aplicado · vigilando' : 'vigilando la red'}</text>
                </g>
              );
            })()}
          </g>
        </g>
      </svg>
      <div className="gp-zoom" onClick={(e) => e.stopPropagation()}>
        <button onClick={() => zoomAt(W / 2, H / 2, 1.3)} aria-label="Acercar">+</button>
        <button onClick={() => zoomAt(W / 2, H / 2, 1 / 1.3)} aria-label="Alejar">−</button>
        <button onClick={() => setView({ x: 0, y: 0, s: 1 })} aria-label="Ver toda la red" disabled={view.s === 1 && view.x === 0 && view.y === 0}>⟲</button>
      </div>
    </div>
  );
});
