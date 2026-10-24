import React from 'react';
import * as k from '../iso/iso-kit';
import { Dots, Line, Solid } from '../iso/react/draw';
import { P } from './layout';

export type AssetState = 'ok' | 'tripped' | 'standby' | 'boost';

interface ObjectProps {
  at: k.Point3;
  state: AssetState;
  level: number; // 0..1 of capacity in use
  lit?: boolean;
}

const tone = (s: AssetState) => (s === 'tripped' ? 'mid' : s === 'standby' ? 'lo' : 'hi');

const halo = (x: number, y: number, w: number, d: number, z = 0) => (
  <path className="iso-halo" d={k.haloOf({ x, y, w, d, r: 2 }, z - 1, 2.5, P)} />
);

// Red dashed ring on the ground plus an X above: the asset is out.
export function TripMark({ at, radius = 30, height = 34 }: { at: k.Point3; radius?: number; height?: number }) {
  const [x, y] = at;
  const c = k.iso([x, y, height], P);
  const s = 6;
  return (
    <g className="gp-trip">
      <path d={k.ring(x, y, radius, 0.5, P, 48)} className="gp-trip-ring" />
      <path d={`M${c[0] - s},${c[1] - s}L${c[0] + s},${c[1] + s}M${c[0] + s},${c[1] - s}L${c[0] - s},${c[1] + s}`} className="gp-trip-x" />
    </g>
  );
}

// Green expanding ring: the asset was just pushed up by a plan.
export function BoostMark({ at, radius = 30 }: { at: k.Point3; radius?: number }) {
  const [x, y] = at;
  return <path d={k.ring(x, y, radius, 0.5, P, 48)} className="gp-boost-ring gp-spread" />;
}

export function Solar({ at, state, level, lit }: ObjectProps) {
  const [cx, cy] = at;
  const panels: React.ReactNode[] = [];
  for (const dx of [-30, -16, -2]) {
    for (const dy of [-14, 4]) {
      const x = cx + dx, y = cy + dy;
      panels.push(
        <g key={`${dx}${dy}`}>
          {halo(x, y, 11, 13)}
          <Solid paths={k.cylinder(x + 5.5, y + 6.5, 1.2, -2, 2.4, P, 10)} tone="lo" crease="none" />
          <Solid
            paths={k.slabOf({ x, y, w: 11, d: 13, r: 0.8 }, 0.4, 2.2, P, 4, 0.4)}
            tone={tone(state)}
            lit={lit}
            inner={
              <Line
                d={k.topTicks(x + 2, x + 9, 2.4, 1, y + 1.4, 2.6, [10, 10], P, 'x').minor + k.topTicks(y + 2.4, y + 10.6, 2.7, 1, x + 1.4, 2.6, [8, 8], P, 'y').minor}
                tone={state === 'tripped' ? 'red' : level > 0.05 ? 'green' : 'faint'}
              />
            }
          />
        </g>,
      );
    }
  }
  return (
    <g>
      {panels}
      {halo(cx + 14, cy - 8, 10, 16)}
      <Solid paths={k.slabOf({ x: cx + 14, y: cy - 8, w: 10, d: 16, r: 1.2 }, 0, 8, P, 4, 0.5)} tone={tone(state)} lit={lit} />
    </g>
  );
}

export function Wind({ at, state, level, lit }: ObjectProps) {
  const [cx, cy] = at;
  const still = state === 'tripped' || state === 'standby' || level < 0.02;
  const period = 6 - level * 4.5; // faster with more output
  return (
    <g>
      {[[-18, 6, 34], [4, -10, 40], [22, 10, 30]].map(([dx, dy, h], i) => {
        const x = cx + dx, y = cy + dy;
        const hubZ = h + 2;
        const hub = [x + 2.4, y + 2.4, hubZ] as k.Point3;
        return (
          <g key={i}>
            {halo(x - 4, y - 4, 8, 8)}
            <Solid paths={k.cylinder(x, y, 3.4, 0, 1.6, P, 16)} tone="mid" lit={lit} />
            <Solid paths={k.cylinder(x, y, 1.3, 1.6, h, P, 14)} tone={tone(state)} lit={lit} />
            <Solid paths={k.slabOf({ x: x - 2.2, y: y - 2, w: 5.4, d: 4.4, r: 1 }, h, 3, P, 3, 0.3)} tone={tone(state)} lit={lit} />
            {(() => {
              const [hx, hy] = k.iso(hub, P);
              const blades = [0, 1, 2].map((b) => {
                const th = i * 0.7 + (b * Math.PI * 2) / 3;
                return `M${hx},${hy}L${hx + Math.cos(th) * 13},${hy + Math.sin(th) * 13}`;
              }).join('');
              return (
                <g>
                  <path d={blades} className={`iso-line gp-blade${state === 'tripped' ? ' is-red' : ''}`} data-tone="hi" />
                  {!still && <animateTransform attributeName="transform" type="rotate" from={`0 ${hx} ${hy}`} to={`360 ${hx} ${hy}`} dur={`${period + i * 0.4}s`} repeatCount="indefinite" />}
                </g>
              );
            })()}
            <Dots points={[k.iso(hub, P)]} size={1} tone="hi" />
          </g>
        );
      })}
    </g>
  );
}

function Stacks({ at, stacks, running }: { at: k.Point3; stacks: [number, number, number, number][]; running: boolean }) {
  return (
    <>
      {stacks.map(([dx, dy, r, h], i) => {
        const x = at[0] + dx, y = at[1] + dy;
        const [sx, sy] = k.iso([x, y, h + 3], P);
        return (
          <g key={i}>
            <Solid paths={k.cylinder(x, y, r, 0, h, P, 18, 0.3)} tone="hi" />
            {running && [0, 1, 2].map((j) => (
              <circle key={j} cx={sx} cy={sy} r="2" className="gp-puff">
                <animate attributeName="cy" values={`${sy};${sy - 26}`} dur="3s" begin={`${-j - i * 0.5}s`} repeatCount="indefinite" />
                <animate attributeName="cx" values={`${sx};${sx + 8}`} dur="3s" begin={`${-j - i * 0.5}s`} repeatCount="indefinite" />
                <animate attributeName="r" values="2;7" dur="3s" begin={`${-j - i * 0.5}s`} repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.6;0" dur="3s" begin={`${-j - i * 0.5}s`} repeatCount="indefinite" />
              </circle>
            ))}
          </g>
        );
      })}
    </>
  );
}

export function GasPlant({ at, state, level, lit }: ObjectProps) {
  const [cx, cy] = at;
  const running = state !== 'tripped' && state !== 'standby' && level > 0.02;
  return (
    <g>
      {halo(cx - 24, cy - 10, 40, 24)}
      <Solid paths={k.slabOf({ x: cx - 24, y: cy - 10, w: 40, d: 24, r: 2 }, 0, 14, P, 4, 0.6)} tone={tone(state)} lit={lit} />
      <Solid paths={k.slabOf({ x: cx - 18, y: cy - 6, w: 18, d: 16, r: 1.5 }, 14, 6, P, 4, 0.4)} tone={tone(state)} lit={lit} />
      <Solid paths={k.cylinder(cx - 34, cy + 4, 7, 0, 10, P, 24, 0.4)} tone={tone(state)} lit={lit} />
      <Stacks at={at} stacks={[[8, -4, 3.2, 30], [16, 2, 3.2, 30]]} running={running} />
    </g>
  );
}

export function CoalPlant({ at, state, level, lit }: ObjectProps) {
  const [cx, cy] = at;
  const running = state !== 'tripped' && state !== 'standby' && level > 0.02;
  return (
    <g>
      {halo(cx - 28, cy - 12, 46, 28)}
      <Solid paths={k.slabOf({ x: cx - 28, y: cy - 12, w: 46, d: 28, r: 2 }, 0, 18, P, 4, 0.6)} tone={tone(state)} lit={lit} />
      <Solid paths={k.slabOf({ x: cx - 42, y: cy + 4, w: 12, d: 12, r: 6 }, 0, 4, P, 10, 1.5)} tone="mid" lit={lit} />
      <Stacks at={at} stacks={[[12, -2, 4.2, 46]]} running={running} />
    </g>
  );
}

export function Hydro({ at, state, level, lit }: ObjectProps) {
  const [cx, cy] = at;
  // Reservoir behind a curved dam wall, powerhouse at its foot.
  const water = k.slabOf({ x: cx - 30, y: cy - 34, w: 52, d: 26, r: 10 }, 0, 10, P, 12, 1);
  return (
    <g>
      {halo(cx - 30, cy - 34, 52, 40)}
      <Solid paths={water} tone="lo" crease="none" inner={<path d={k.planOutline(k.insetPlan({ x: cx - 30, y: cy - 34, w: 52, d: 26, r: 10 }, 3), 10, P)} className={`gp-water${level > 0.05 && state !== 'tripped' ? ' is-flowing' : ''}`} />} />
      <Solid paths={k.slabOf({ x: cx - 32, y: cy - 9, w: 56, d: 5, r: 1.5 }, 0, 16, P, 4, 0.5)} tone={tone(state)} lit={lit} />
      <Solid paths={k.slabOf({ x: cx - 10, y: cy - 2, w: 16, d: 12, r: 1.2 }, 0, 7, P, 4, 0.4)} tone={tone(state)} lit={lit} />
    </g>
  );
}

export function Diesel({ at, state, level, lit }: ObjectProps) {
  const [cx, cy] = at;
  const running = state !== 'tripped' && state !== 'standby' && level > 0.02;
  return (
    <g>
      {[0, 1].map((i) => (
        <g key={i}>
          {halo(cx - 18 + i * 16, cy - 6, 13, 20)}
          <Solid paths={k.slabOf({ x: cx - 18 + i * 16, y: cy - 6, w: 13, d: 20, r: 1 }, 0, 9, P, 4, 0.4)} tone={tone(state)} lit={lit} />
        </g>
      ))}
      <Stacks at={at} stacks={[[-11, -9, 1.8, 18], [5, -9, 1.8, 18]]} running={running} />
    </g>
  );
}

export function Battery({ at, state, level, lit, soc = 0.5, charging = false }: ObjectProps & { soc?: number; charging?: boolean }) {
  const [cx, cy] = at;
  const active = state !== 'tripped' && state !== 'standby' && level > 0.02;
  return (
    <g>
      {active && <path d={k.ring(cx, cy, 24, 0.5, P, 40)} className={`gp-bess-ring gp-spread${charging ? ' is-charging' : ''}`} />}
      {[-14, -2, 10].map((dx, i) => (
        <g key={i}>
          {halo(cx + dx, cy - 12, 10, 11)}
          <Solid paths={k.slabOf({ x: cx + dx, y: cy - 12, w: 10, d: 11, r: 1 }, 0, 9, P, 4, 0.4)} tone={tone(state)} lit={lit} />
        </g>
      ))}
      {[-10, 0, 10].map((dx, i) => (
        <g key={`c${i}`}>
          <Solid paths={k.cylinder(cx + dx, cy + 7, 3.4, 0, 4 + soc * 12, P, 18, 0.3)} tone={tone(state)} lit={active || lit} />
        </g>
      ))}
    </g>
  );
}

export function Hub({ at, lit }: { at: k.Point3; lit?: boolean }) {
  const [cx, cy] = at;
  return (
    <g>
      {halo(cx - 18, cy - 12, 36, 24)}
      <Solid paths={k.slabOf({ x: cx - 18, y: cy - 12, w: 36, d: 24, r: 2 }, 0, 4, P, 4, 0.5)} tone="hi" lit={lit} />
      {[-10, 0, 10].map((dx) => (
        <Solid key={dx} paths={k.cylinder(cx + dx, cy - 2, 2.6, 4, 9, P, 14, 0.2)} tone="hi" lit={lit} />
      ))}
      {(() => { const c = k.coil(cx - 14, cx + 14, [cy + 6, 6], 2.2, 6, 'x', P); return <Line d={c.back + c.front} tone="mid" />; })()}
    </g>
  );
}

// A block of houses; `dark` of them have their lights out.
export function Neighbourhood({ at, count, dark, highlight }: { at: k.Point3; count: number; dark: number; highlight?: boolean }) {
  const cols = count > 8 ? 4 : 3;
  const houses: React.ReactNode[] = [];
  for (let i = 0; i < count; i++) {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = at[0] - cols * 7 + col * 15 + (row % 2) * 4;
    const y = at[1] + row * 15;
    houses.push(<House key={i} x={x} y={y} powered={i >= dark} lit={highlight} />);
  }
  const rows = Math.ceil(count / cols);
  const [cx, cy] = [at[0] + 2, at[1] + rows * 7];
  // draw back rows first; a red pulse on the ground while any house is dark
  return (
    <g>
      {dark > 0 && <path d={k.ring(cx, cy, cols * 9 + 6, 0.3, P, 48)} className="gp-dark-ring" />}
      {dark > 0 && <path d={k.ring(cx, cy, cols * 9 + 6, 0.3, P, 48)} className="gp-dark-ring gp-spread" />}
      {houses.reverse()}
    </g>
  );
}

function House({ x, y, powered, lit }: { x: number; y: number; powered: boolean; lit?: boolean }) {
  const w = 10, d = 9, wallH = 6, roofH = 4;
  const zTop = wallH, zPeak = wallH + roofH, yMid = y + d / 2;
  const r0 = k.iso([x - 0.8, yMid, zPeak], P), r1 = k.iso([x + w + 0.8, yMid, zPeak], P);
  const f0 = k.iso([x - 0.8, y + d + 0.8, zTop], P), f1 = k.iso([x + w + 0.8, y + d + 0.8, zTop], P);
  const b1 = k.iso([x + w + 0.8, y - 0.8, zTop], P);
  const win = (x0: number, x1: number) =>
    k.pathOf([k.iso([x0, y + d + 0.05, 1.8], P), k.iso([x1, y + d + 0.05, 1.8], P), k.iso([x1, y + d + 0.05, 4.4], P), k.iso([x0, y + d + 0.05, 4.4], P)], true);
  const side = k.pathOf([k.iso([x + w + 0.05, y + 2.5, 1.8], P), k.iso([x + w + 0.05, y + 6.5, 1.8], P), k.iso([x + w + 0.05, y + 6.5, 4.4], P), k.iso([x + w + 0.05, y + 2.5, 4.4], P)], true);
  return (
    <g className={powered ? 'gp-house' : 'gp-house is-dark'}>
      <path className="iso-halo" d={k.haloOf({ x, y, w, d, r: 1 }, -1, 2, P)} />
      <Solid
        paths={k.slabOf({ x, y, w, d, r: 0.6 }, 0, wallH, P, 3, 0.2)}
        tone={powered ? 'hi' : 'mid'}
        lit={lit}
        inner={<path d={win(x + 1.6, x + 4.2) + win(x + w - 4.2, x + w - 1.6) + side} className="gp-window" />}
      />
      <Solid
        paths={{
          fill: k.pathOf([f0, r0, r1, b1, f1], true),
          shades: [k.pathOf([r0, r1, f1, f0], true), '', k.pathOf([r1, b1, f1], true), ''],
          top: k.pathOf([r0, r1, f1, f0], true),
          crease: k.pathOf([r1, f1]),
          bevel: '',
          outline: k.pathOf([f0, r0, r1, b1, f1, f0]) + k.pathOf([r1, f1]),
        }}
        tone={powered ? 'hi' : 'mid'}
        lit={lit}
      />
    </g>
  );
}

// Gemini 4 Argon: a faceted crystal floating over the grid, with orbit rings.
export function GeminiCore({ at, phase }: { at: k.Point3; phase: string }) {
  const [x, y, z] = at;
  const busy = phase === 'analyzing' || phase === 'executing';
  const zc = z;
  const r = 16, hgt = 22;
  const turn = 0.35;
  const eq = [0, 1, 2, 3].map((i) => {
    const a = turn + (i * Math.PI) / 2;
    return k.iso([x + Math.cos(a) * r, y + Math.sin(a) * r, zc], P);
  });
  const top = k.iso([x, y, zc + hgt], P);
  const bot = k.iso([x, y, zc - hgt], P);
  const faces: { d: string; shade: number }[] = [];
  for (let i = 0; i < 4; i++) {
    const a = eq[i], b = eq[(i + 1) % 4];
    const facing = (b[0] - a[0]) > 0; // faces toward the viewer
    faces.push({ d: k.pathOf([top, a, b], true), shade: facing ? 0 : 2 });
    faces.push({ d: k.pathOf([bot, a, b], true), shade: facing ? 1 : 3 });
  }
  const shadow = k.ring(x, y, 14, 0, P, 32);
  return (
    <g className={`gp-gemini is-${phase}`}>
      <path d={shadow} className="gp-gemini-shadow" />
      <line x1={k.iso([x, y, 0], P)[0]} y1={k.iso([x, y, 0], P)[1]} x2={bot[0]} y2={bot[1]} className="gp-gemini-tether" />
      <g className="gp-gemini-body">
      {[1, 1.55].map((m, i) => (
        <path key={i} d={k.ring(x, y, r * m + 6, zc - 2 + i * 4, P, 48)} className="gp-gemini-orbit" style={{ animationDuration: `${busy ? 1.4 + i : 4 + i * 2}s` }} />
      ))}
      <circle cx={(top[0] + bot[0]) / 2} cy={(top[1] + bot[1]) / 2} r={busy ? 46 : 34} className="gp-gemini-glow" />
      {faces
        .sort((p, q) => q.shade - p.shade)
        .map((f, i) => (
          <path key={i} d={f.d} className="gp-gemini-face" data-shade={f.shade} />
        ))}
      <path d={k.pathOf([top, ...eq, top])} className="gp-gemini-edge" />
      <path d={k.pathOf([bot, eq[0]]) + k.pathOf([bot, eq[1]]) + k.pathOf([bot, eq[2]]) + k.pathOf([bot, eq[3]]) + k.pathOf([...eq, eq[0]])} className="gp-gemini-edge" />
      </g>
    </g>
  );
}
