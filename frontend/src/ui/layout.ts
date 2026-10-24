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
const hubAt = (i: number) => uv(-350 + i * 175, -70 + i * 48);
export const ZONES: Record<string, { hub: k.Point3; label: string; short: string }> = {
  n_norte_grande: { hub: hubAt(0), label: 'Norte Grande', short: 'NG' },
  n_norte_chico: { hub: hubAt(1), label: 'Norte Chico', short: 'NC' },
  n_centro: { hub: hubAt(2), label: 'Centro', short: 'C' },
  n_centro_sur: { hub: hubAt(3), label: 'Centro-Sur', short: 'CS' },
  n_sur: { hub: hubAt(4), label: 'Sur', short: 'S' },
};

// Where each modelled asset sits relative to its zone hub, as (u, v). Unknown ids get a free slot.
const SLOTS: Record<string, [number, number]> = {
  solar_ng: [-52, -122],
  gas_ng: [36, -140],
  b_reserve_ng: [70, 22],
  solar_nc: [-48, -124],
  wind_nc: [44, -142],
  gas_centro: [-62, -130],
  diesel_centro: [22, -152],
  b_centro: [80, -104],
  b_reserve_centro: [84, 24],
  coal_cs: [-12, -140],
  hydro_sur: [-46, -134],
  wind_sur: [48, -148],
};
const FREE: [number, number][] = [[70, -70], [-80, -30], [80, 10]];

export function slotOf(id: string, nodeId: string, used: Set<string>): k.Point3 {
  const hub = ZONES[nodeId]?.hub ?? [0, 0, 0];
  let off = SLOTS[id];
  if (!off) {
    off = FREE.find((f) => !used.has(`${nodeId}:${f}`)) ?? [0, -130];
    used.add(`${nodeId}:${off}`);
  }
  return uv(off[0], off[1], [hub[0], hub[1]]);
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
  anchors.push(uv(-85, -185, b), uv(90, -185, b), uv(-60, 105, b), uv(90, 95, b));
}
anchors.push([GEMINI[0], GEMINI[1], GEMINI[2] + 40]);

export const P = k.fitProjection(anchors, W, H, { pad: 40, azimuth: 54, elevation: 30 });

export const screen = (p: k.Point3): [number, number] => k.iso(p, P);
export const pct = (p: k.Point3) => {
  const [x, y] = screen(p);
  return { left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` };
};
