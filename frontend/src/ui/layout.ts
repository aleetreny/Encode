import * as k from '../iso/iso-kit';

// Stage size in SVG units; the scene scales to the viewport.
export const W = 1440;
export const H = 860;

// Offsets are written in screen-aligned units: u runs to the right of the stage, v runs toward
// the viewer (negative = behind). With the camera at azimuth 54° these map to world axes:
const A = (54 * Math.PI) / 180;
const RIGHT: [number, number] = [Math.sin(A), -Math.cos(A)];
const FRONT: [number, number] = [Math.cos(A), Math.sin(A)];
export const uv = (u: number, v: number, base: [number, number] = [0, 0]): k.Point3 => [
  base[0] + u * RIGHT[0] + v * FRONT[0],
  base[1] + u * RIGHT[1] + v * FRONT[1],
  0,
];

// North → south runs left to right with a gentle slope, like a maquette of Chile lying on a
// table. Each zone has a hub (substation) with its plants behind it and its neighbourhood in front.
const hubAt = (i: number) => uv(-400 + i * 200, -110 + i * 66);
export const ZONES: Record<string, { hub: k.Point3; label: string; short: string }> = {
  n_norte_grande: { hub: hubAt(0), label: 'Norte Grande', short: 'NG' },
  n_norte_chico: { hub: hubAt(1), label: 'Norte Chico', short: 'NC' },
  n_centro: { hub: hubAt(2), label: 'Centro', short: 'C' },
  n_centro_sur: { hub: hubAt(3), label: 'Centro-Sur', short: 'CS' },
  n_sur: { hub: hubAt(4), label: 'Sur', short: 'S' },
};

// Everything that produces or stores sits behind its zone hub, in one tidy row: largest
// generators first, then batteries (operating before reserve), evenly spaced and staggered in
// depth so neither the objects nor their labels overlap. Only the houses go in front, which keeps
// the trunk line between hubs clear.
const SPACING = 72;
const DEPTH: [number, number] = [-112, -150];

export interface Placeable { id: string; nodeId: string; kind: 'generator' | 'battery'; capacity: number; standby?: boolean }

export function placeAssets(items: Placeable[]): Record<string, k.Point3> {
  const out: Record<string, k.Point3> = {};
  const byZone = new Map<string, Placeable[]>();
  for (const it of items) byZone.set(it.nodeId, [...(byZone.get(it.nodeId) ?? []), it]);
  for (const [nodeId, list] of byZone) {
    const hub = ZONES[nodeId]?.hub ?? [0, 0, 0];
    const rank = (p: Placeable) => (p.kind === 'generator' ? 0 : p.standby ? 2 : 1);
    const row = [...list].sort((a, b) => rank(a) - rank(b) || b.capacity - a.capacity);
    row.forEach((p, i) => {
      const u = (i - (row.length - 1) / 2) * SPACING;
      const v = row.length === 1 ? -126 : DEPTH[i % 2];
      out[p.id] = uv(u, v, [hub[0], hub[1]]);
    });
  }
  return out;
}

// Neighbourhood sits in front of the hub.
export const housesOf = (nodeId: string): k.Point3 => {
  const hub = ZONES[nodeId]?.hub ?? [0, 0, 0];
  return uv(-8, 58, [hub[0], hub[1]]);
};

// Gemini floats above the middle of the country.
const g = uv(-90, -230);
export const GEMINI: k.Point3 = [g[0], g[1], 70];

const anchors: k.Point3[] = [];
for (const z of Object.values(ZONES)) {
  const b: [number, number] = [z.hub[0], z.hub[1]];
  anchors.push(uv(-112, -178, b), uv(112, -178, b), uv(-50, 96, b), uv(70, 90, b));
}
anchors.push([GEMINI[0], GEMINI[1], GEMINI[2] + 40]);

export const P = k.fitProjection(anchors, W, H, { pad: 14, azimuth: 54, elevation: 30 });

export const screen = (p: k.Point3): [number, number] => k.iso(p, P);
export const pct = (p: k.Point3) => {
  const [x, y] = screen(p);
  return { left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` };
};
