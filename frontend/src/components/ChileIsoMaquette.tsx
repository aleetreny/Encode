import React, { useState } from 'react';
import * as k from '../iso/iso-kit';
import {
  Dots,
  Line,
  Solid,
  Wire,
} from '../iso/react/draw';
import { Stage, useEased, useLoop } from '../iso/react/live';

export type NodeId =
  | 'solar'
  | 'wind'
  | 'thermal'
  | 'battery'
  | 'substation'
  | 'houses';

const W = 1440;
const H = 860;

// True isometric projection calibrated so our 6 free-floating 3D nodes
// span the entire full-screen white canvas from Left -> Center -> Right.
const ALL_ANCHORS: k.Point3[] = [
  [-245, -45, -10],
  [-160, 35, 32],
  [-175, 75, -10],
  [-95, 155, 38],
  [-75, 160, -10],
  [10, 245, 36],
  [-95, -105, -10],
  [-10, -25, 34],
  [10, 25, -10],
  [95, 105, 32],
  [90, -135, -10],
  [195, -35, 32],
];

const P = k.fitProjection(ALL_ANCHORS, W, H, {
  pad: 130,
  azimuth: 54,
  elevation: 30,
});

// Exact 3D world centers derived from screen (u, v) inverse mapping:
// Left column (Generation):
const SOLAR_C: k.Point3 = [-202, -6, 0];      // Top-Left on screen
const WIND_C: k.Point3 = [-135, 113, 0];      // Middle-Left on screen
const THERMAL_C: k.Point3 = [-33, 202, 0];    // Bottom-Left on screen

// Center column (AI Battery & 500 kV Substation):
const BATTERY_C: k.Point3 = [-53, -65, 0];    // Upper-Center on screen
const SUBSTATION_C: k.Point3 = [53, 65, 0];   // Lower-Center on screen

// Right column (Residential Neighborhood of Houses):
const HOUSES_C: k.Point3 = [134, -88, 0];     // Center-Right on screen

function toPct(world: k.Point3): { left: string; top: string } {
  const [sx, sy] = k.iso(world, P);
  return {
    left: `${((sx / W) * 100).toFixed(2)}%`,
    top: `${((sy / H) * 100).toFixed(2)}%`,
  };
}

// Free-floating 3D isometric pitched-roof house (no ground plate)
function FloatingHouse({
  x,
  y,
  w,
  d,
  z,
  wallH,
  roofH,
  highlighted,
}: {
  x: number;
  y: number;
  w: number;
  d: number;
  z: number;
  wallH: number;
  roofH: number;
  highlighted: boolean;
}) {
  const zTop = z + wallH;
  const zPeak = zTop + roofH;
  const yMid = y + d / 2;

  const x0 = x - 0.9;
  const x1 = x + w + 0.9;
  const yFront = y + d + 0.9;
  const yBack = y - 0.9;

  const r0 = k.iso([x0, yMid, zPeak], P);
  const r1 = k.iso([x1, yMid, zPeak], P);
  const f0 = k.iso([x0, yFront, zTop], P);
  const f1 = k.iso([x1, yFront, zTop], P);
  const b1 = k.iso([x1, yBack, zTop], P);

  const frontSlopePath = k.pathOf([r0, r1, f1, f0], true);
  const rightGablePath = k.pathOf([r1, b1, f1], true);
  const roofOutlinePath =
    k.pathOf([f0, r0, r1, b1, f1, f0], false) + k.pathOf([r1, f1], false);
  const roofSilhouette = k.pathOf([f0, r0, r1, b1, f1], true);

  // Illuminated windows on front & side walls
  const winZ0 = z + 2.0;
  const winZ1 = z + wallH - 1.5;
  const win1Path = k.pathOf(
    [
      k.iso([x + 2.2, y + d + 0.06, winZ0], P),
      k.iso([x + 5.4, y + d + 0.06, winZ0], P),
      k.iso([x + 5.4, y + d + 0.06, winZ1], P),
      k.iso([x + 2.2, y + d + 0.06, winZ1], P),
    ],
    true
  );
  const win2Path = k.pathOf(
    [
      k.iso([x + w - 5.4, y + d + 0.06, winZ0], P),
      k.iso([x + w - 2.2, y + d + 0.06, winZ0], P),
      k.iso([x + w - 2.2, y + d + 0.06, winZ1], P),
      k.iso([x + w - 5.4, y + d + 0.06, winZ1], P),
    ],
    true
  );
  const sideWinPath = k.pathOf(
    [
      k.iso([x + w + 0.06, y + d * 0.3, winZ0], P),
      k.iso([x + w + 0.06, y + d * 0.7, winZ0], P),
      k.iso([x + w + 0.06, y + d * 0.7, winZ1], P),
      k.iso([x + w + 0.06, y + d * 0.3, winZ1], P),
    ],
    true
  );

  return (
    <g>
      {/* Subtle floating shadow halo beneath each house */}
      <path
        className="iso-halo"
        d={k.haloOf({ x, y, w, d, r: 1 }, z - 1.5, 2.5, P)}
      />
      {/* House Walls */}
      <Solid
        paths={k.slabOf({ x, y, w, d, r: 0.7 }, z, wallH, P, 3, 0.25)}
        tone="hi"
        lit={highlighted}
        inner={
          <path
            d={win1Path + win2Path + sideWinPath}
            fill="#fde047"
            fillOpacity={0.88}
            stroke="#d97706"
            strokeWidth={0.38}
            strokeLinejoin="round"
          />
        }
      />
      {/* Pitched Gabled Roof */}
      <Solid
        paths={{
          fill: roofSilhouette,
          shades: [frontSlopePath, '', rightGablePath, ''],
          top: frontSlopePath,
          crease: k.pathOf([r1, f1], false),
          bevel: '',
          outline: roofOutlinePath,
        }}
        tone="hi"
        lit={highlighted}
      />
    </g>
  );
}

// Free-floating 3D Wind Turbine
function FloatingWindTurbine({
  tx,
  ty,
  tz,
  towerH,
  bladeR,
  angleRad,
  highlighted,
}: {
  tx: number;
  ty: number;
  tz: number;
  towerH: number;
  bladeR: number;
  angleRad: number;
  highlighted: boolean;
}) {
  const hubZ = tz + towerH + 1.8;
  const hubX = tx + 2.8;
  const hubY = ty + 2.8;

  return (
    <g>
      <path
        className="iso-halo"
        d={k.haloOf({ x: tx - 4, y: ty - 4, w: 8, d: 8, r: 4 }, tz - 1, 2.5, P)}
      />
      {/* Foundation Collar */}
      <Solid
        paths={k.cylinder(tx, ty, 3.6, tz, 1.8, P, 18)}
        tone="mid"
        lit={highlighted}
      />
      {/* Tapered Tower */}
      <Solid
        paths={k.cylinder(tx, ty, 1.45, tz + 1.8, towerH, P, 16)}
        tone="hi"
        lit={highlighted}
      />
      {/* Nacelle Housing */}
      <Solid
        paths={k.slabOf(
          { x: tx - 2.4, y: ty - 2.2, w: 5.8, d: 4.8, r: 1.0 },
          tz + towerH,
          3.4,
          P,
          3,
          0.3
        )}
        tone="hi"
        lit={highlighted}
      />
      {/* 3 Rotating Blades */}
      {[0, 1, 2].map((bIdx) => {
        const theta = angleRad + (bIdx * Math.PI * 2) / 3;
        const tipX = hubX + Math.cos(theta) * bladeR * 0.72;
        const tipY = hubY - Math.cos(theta) * bladeR * 0.42;
        const tipZ = hubZ + Math.sin(theta) * bladeR;
        return (
          <Line
            key={bIdx}
            d={k.pathOf([k.iso([hubX, hubY, hubZ], P), k.iso([tipX, tipY, tipZ], P)])}
            tone="hi"
          />
        );
      })}
      <Dots points={[k.iso([hubX, hubY, hubZ], P)]} size={1.1} tone="hi" />
    </g>
  );
}

// 3D Mid-Air Transmission Pylon / Insulator Post along the wires
function MidAirPylon({ x, y, z }: { x: number; y: number; z: number }) {
  return (
    <g>
      <Solid
        paths={k.cylinder(x, y, 1.5, z - 2, 5.5, P, 12)}
        tone="mid"
        crease="none"
      />
      <Dots points={[k.iso([x, y, z + 3.8], P)]} size={0.95} tone="hi" pulse />
    </g>
  );
}

export const ChileIsoMaquette: React.FC = () => {
  const [activeNode, setActiveNode] = useState<NodeId | null>(null);
  const [rotorPhase, setRotorPhase] = useState<number>(0);

  // Calm continuous rotation for the wind turbines
  useLoop((dt, calm) => {
    if (calm) return false;
    setRotorPhase((p) => (p + dt * 1.65) % (Math.PI * 2));
    return true;
  }, true);

  // Smooth vertical lift when hovering or clicking any free-floating 3D node
  const solarLift = useEased(activeNode === 'solar' ? 4.5 : 0, 0.22);
  const windLift = useEased(activeNode === 'wind' ? 4.5 : 0, 0.22);
  const thermalLift = useEased(activeNode === 'thermal' ? 4.5 : 0, 0.22);
  const batteryLift = useEased(activeNode === 'battery' ? 4.5 : 0, 0.22);
  const subLift = useEased(activeNode === 'substation' ? 4.5 : 0, 0.22);
  const housesLift = useEased(activeNode === 'houses' ? 4.5 : 0, 0.22);

  // Dial ticks for the 500 kV Substation frequency/load gauge
  const dialX = SUBSTATION_C[0] - 12;
  const dialY = SUBSTATION_C[1] + 16;
  const dialR = 13.5;
  const dialZ = SUBSTATION_C[2] + 3.2 + subLift;

  const dialTicks = k.radialTicks(
    dialX,
    dialY,
    dialR - 2.2,
    24,
    4,
    dialZ,
    [1.3, 2.6],
    P,
    -Math.PI * 0.75,
    Math.PI * 1.5
  );

  const needleAngle = -Math.PI * 0.75 + 0.78 * Math.PI * 1.5;
  const needleTip: k.Point3 = [
    dialX + Math.cos(needleAngle) * (dialR - 3.6),
    dialY + Math.sin(needleAngle) * (dialR - 3.6),
    dialZ + 0.4,
  ];

  // 4-datum minimalist borderless specifications for each node
  const nodeSpecs: Array<{
    id: NodeId;
    pos: { left: string; top: string };
    align: 'left' | 'right' | 'center';
    dotColor: string;
    name: string;
    d1: string;
    d2: string;
    d3: string;
  }> = [
    {
      id: 'solar',
      pos: toPct([SOLAR_C[0] - 4, SOLAR_C[1] - 28, 16]),
      align: 'center',
      dotColor: '#16a34a',
      name: '01 · PLANTA SOLAR ATACAMA',
      d1: '665 MW · FV',
      d2: '220 kV DC/AC',
      d3: '95% IRRADIANCIA',
    },
    {
      id: 'wind',
      pos: toPct([WIND_C[0] + 6, WIND_C[1] + 22, -20]),
      align: 'center',
      dotColor: '#16a34a',
      name: '02 · PARQUE EÓLICO NORTE',
      d1: '240 MW · EÓLICA',
      d2: '220 kV AC',
      d3: '14.2 RPM · 3 TURBINAS',
    },
    {
      id: 'thermal',
      pos: toPct([THERMAL_C[0] - 4, THERMAL_C[1] + 34, -14]),
      align: 'center',
      dotColor: '#2563eb',
      name: '03 · CENTRAL TÉRMICA GAS',
      d1: '320 MW · COMBINADO',
      d2: '500 kV AC',
      d3: 'RESERVA SINCRÓNICA',
    },
    {
      id: 'battery',
      pos: toPct([BATTERY_C[0] - 2, BATTERY_C[1] - 32, 18]),
      align: 'center',
      dotColor: '#16a34a',
      name: '04 · BATERÍA AGENTE IA (BESS)',
      d1: '+385 MW · CARGANDO',
      d2: '1.2 GWh · 500 kV',
      d3: '78% SoC · IA ACTIVA',
    },
    {
      id: 'substation',
      pos: toPct([SUBSTATION_C[0] - 2, SUBSTATION_C[1] + 36, -12]),
      align: 'center',
      dotColor: '#2563eb',
      name: '05 · SUBESTACIÓN TRONCAL',
      d1: '840 / 900 MVA',
      d2: '500 kV / 220 kV',
      d3: '50.00 Hz NOMINAL',
    },
    {
      id: 'houses',
      pos: toPct([HOUSES_C[0] - 12, HOUSES_C[1] - 24, 28]),
      align: 'center',
      dotColor: '#16a34a',
      name: '06 · BARRIO RESIDENCIAL',
      d1: '540 MW · DEMANDA',
      d2: '23 kV / 220 V AC',
      d3: '100% SUMINISTRO',
    },
  ];

  return (
    <Stage className="iso iso-fullspace">
      <div className="fullspace-stage">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="fullspace-svg"
          aria-label="Esquema 3D de la red eléctrica"
        >
          {/* =========================================================
              SUSPENDED MID-AIR NETWORK WIRES (No ground plates!)
             ========================================================= */}
          <g className="network-wires">
            {/* 1. Solar Plant -> AI Battery (Direct DC/AC solar storage link) */}
            <Wire
              from={k.iso([SOLAR_C[0] + 24, SOLAR_C[1] - 4, 2 + solarLift], P)}
              via={[
                k.iso([-132, -38, 2], P),
                k.iso([-95, -52, 2], P),
              ]}
              to={k.iso([BATTERY_C[0] - 24, BATTERY_C[1] + 2, 2 + batteryLift], P)}
              tone="green"
              flow
              size={1.6}
            />

            {/* 2. Solar Plant -> 500 kV Substation */}
            <Wire
              from={k.iso([SOLAR_C[0] + 22, SOLAR_C[1] + 12, 2 + solarLift], P)}
              via={[
                k.iso([-115, 22, 1], P),
                k.iso([-42, 48, 1], P),
              ]}
              to={k.iso([SUBSTATION_C[0] - 26, SUBSTATION_C[1] - 6, 2 + subLift], P)}
              tone="green"
              flow
              size={1.6}
            />

            {/* 3. Wind Farm -> 500 kV Substation */}
            <Wire
              from={k.iso([WIND_C[0] + 24, WIND_C[1] - 4, 2 + windLift], P)}
              via={[
                k.iso([-68, 92, 1], P),
                k.iso([-12, 78, 1], P),
              ]}
              to={k.iso([SUBSTATION_C[0] - 24, SUBSTATION_C[1] + 8, 2 + subLift], P)}
              tone="green"
              flow
              size={1.5}
            />

            {/* 4. Thermal Gas Plant -> 500 kV Substation */}
            <Wire
              from={k.iso([THERMAL_C[0] + 24, THERMAL_C[1] - 12, 2 + thermalLift], P)}
              via={[
                k.iso([8, 152, 1], P),
                k.iso([35, 112, 1], P),
              ]}
              to={k.iso([SUBSTATION_C[0] - 6, SUBSTATION_C[1] + 22, 2 + subLift], P)}
              tone="blue"
              flow
              size={1.5}
            />

            {/* 5. Bidirectional AI Battery <-> 500 kV Substation Link */}
            <Wire
              from={k.iso([BATTERY_C[0] + 4, BATTERY_C[1] + 20, 2 + batteryLift], P)}
              via={[k.iso([0, 0, 2], P)]}
              to={k.iso([SUBSTATION_C[0] - 4, SUBSTATION_C[1] - 20, 2 + subLift], P)}
              tone="green"
              flow
              size={1.5}
            />

            {/* 6. AI Battery -> Residential Neighborhood (Smart AI Dispatch Line) */}
            <Wire
              from={k.iso([BATTERY_C[0] + 26, BATTERY_C[1] - 4, 2 + batteryLift], P)}
              via={[
                k.iso([28, -76, 2], P),
                k.iso([78, -82, 2], P),
              ]}
              to={k.iso([HOUSES_C[0] - 32, HOUSES_C[1] - 8, 2 + housesLift], P)}
              tone="green"
              flow
              size={1.6}
            />

            {/* 7. 500 kV Substation -> Residential Neighborhood (Main Trunk Feeder) */}
            <Wire
              from={k.iso([SUBSTATION_C[0] + 26, SUBSTATION_C[1] - 6, 2 + subLift], P)}
              via={[
                k.iso([96, 12, 2], P),
                k.iso([118, -32, 2], P),
              ]}
              to={k.iso([HOUSES_C[0] - 18, HOUSES_C[1] + 26, 2 + housesLift], P)}
              tone="blue"
              flow
              size={1.7}
            />

            {/* Mid-Air Junction Pylons along the network */}
            <MidAirPylon x={-132} y={-38} z={2} />
            <MidAirPylon x={-68} y={92} z={1} />
            <MidAirPylon x={0} y={0} z={2} />
            <MidAirPylon x={28} y={-76} z={2} />
            <MidAirPylon x={96} y={12} z={2} />
          </g>

          {/* =========================================================
              NODE 01: PLANTA SOLAR ATACAMA (Free-floating 3D arrays)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('solar')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'solar' ? null : 'solar'))}
          >
            {/* 8 Tilted Solar PV Collector Arrays in 2 rows (back to front) */}
            {[-18, -5, 8, 21].map((dx) =>
              [-14, 4].map((dy) => {
                const px = SOLAR_C[0] + dx - 10;
                const py = SOLAR_C[1] + dy;
                const pz = SOLAR_C[2] + solarLift;
                return (
                  <g key={`pv-${dx}-${dy}`}>
                    <path
                      className="iso-halo"
                      d={k.haloOf({ x: px, y: py, w: 10.5, d: 12.5, r: 1 }, pz - 1, 2, P)}
                    />
                    {/* Support Pedestal */}
                    <Solid
                      paths={k.cylinder(px + 5.2, py + 6.2, 1.3, pz - 2, 2.2, P, 12)}
                      tone="lo"
                      crease="none"
                    />
                    {/* Machined Solar Panel Array */}
                    <Solid
                      paths={k.slabOf(
                        { x: px, y: py, w: 10.5, d: 12.5, r: 0.9 },
                        pz,
                        2.4,
                        P,
                        4,
                        0.4
                      )}
                      tone="hi"
                      lit={activeNode === 'solar'}
                      inner={
                        <Line
                          d={
                            k.topTicks(
                              px + 1.8,
                              px + 8.8,
                              2.4,
                              1,
                              py + 1.4,
                              pz + 2.4,
                              [9.6, 9.6],
                              P,
                              'x'
                            ).minor +
                            k.topTicks(
                              py + 2.2,
                              py + 10.4,
                              2.8,
                              1,
                              px + 1.4,
                              pz + 2.4,
                              [7.8, 7.8],
                              P,
                              'y'
                            ).minor
                          }
                          tone="green"
                        />
                      }
                    />
                  </g>
                );
              })
            )}

            {/* Solar Field Inverter & Step-Up Transformer */}
            <Solid
              paths={k.slabOf(
                { x: SOLAR_C[0] + 15, y: SOLAR_C[1] - 10, w: 10, d: 18, r: 1.2 },
                SOLAR_C[2] + solarLift,
                7.5,
                P,
                4,
                0.5
              )}
              tone="hi"
              lit={activeNode === 'solar'}
            />
            <Solid
              paths={k.cylinder(
                SOLAR_C[0] + 20,
                SOLAR_C[1] - 1,
                2.0,
                SOLAR_C[2] + 7.5 + solarLift,
                4.2,
                P,
                14
              )}
              tone="mid"
            />
          </g>

          {/* =========================================================
              NODE 04: BATERÍA AGENTE IA (BESS) (Upper-Center in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('battery')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'battery' ? null : 'battery'))}
          >
            {/* 4 Modular BESS Rack Enclosures (back row) */}
            {[-20, -8, 4, 16].map((dx, i) => {
              const bx = BATTERY_C[0] + dx;
              const by = BATTERY_C[1] - 14;
              const bz = BATTERY_C[2] + batteryLift;
              return (
                <g key={`bess-rack-${i}`}>
                  <path
                    className="iso-halo"
                    d={k.haloOf({ x: bx, y: by, w: 9.5, d: 11, r: 1.2 }, bz - 1, 2.2, P)}
                  />
                  <Solid
                    paths={k.slabOf(
                      { x: bx, y: by, w: 9.5, d: 11, r: 1.1 },
                      bz,
                      9.5,
                      P,
                      4,
                      0.5
                    )}
                    tone="hi"
                    lit
                    inner={
                      <Line
                        d={
                          k.sideTicks(
                            bx + 1.8,
                            bx + 7.7,
                            2.0,
                            1,
                            by + 11,
                            bz + 7.5,
                            [5.2, 5.2],
                            P,
                            'x'
                          ).minor
                        }
                        tone="green"
                      />
                    }
                  />
                </g>
              );
            })}

            {/* 4 Cylindrical Energy Cores (front row) */}
            {[-15, -5, 5, 15].map((dx, idx) => {
              const cx = BATTERY_C[0] + dx;
              const cy = BATTERY_C[1] + 6;
              const cz = BATTERY_C[2] + batteryLift;
              return (
                <g key={`cell-${idx}`}>
                  <path
                    className="iso-halo"
                    d={k.haloOf({ x: cx - 4, y: cy - 4, w: 8, d: 8, r: 4 }, cz - 1, 2, P)}
                  />
                  <Solid
                    paths={k.cylinder(cx, cy, 4.0, cz, 2.0, P, 20)}
                    tone="lo"
                  />
                  <Solid
                    paths={k.cylinder(cx, cy, 3.4, cz + 2.0, 9.2, P, 20)}
                    tone="hi"
                    lit
                    inner={
                      <Line
                        d={k.ring(cx, cy, 2.2, cz + 11.2, P, 18)}
                        tone="green"
                      />
                    }
                  />
                </g>
              );
            })}

            {/* AI Dispatch Core Module */}
            <Solid
              paths={k.slabOf(
                { x: BATTERY_C[0] - 8, y: BATTERY_C[1] + 15, w: 16, d: 9, r: 1.4 },
                BATTERY_C[2] + batteryLift,
                5.5,
                P,
                4,
                0.5
              )}
              tone="hi"
              lit
            />
            <Dots
              points={[
                k.iso([BATTERY_C[0] - 3, BATTERY_C[1] + 19.5, BATTERY_C[2] + 5.8 + batteryLift], P),
                k.iso([BATTERY_C[0], BATTERY_C[1] + 19.5, BATTERY_C[2] + 5.8 + batteryLift], P),
                k.iso([BATTERY_C[0] + 3, BATTERY_C[1] + 19.5, BATTERY_C[2] + 5.8 + batteryLift], P),
              ]}
              size={1.05}
              tone="hi"
              pulse
            />
          </g>

          {/* =========================================================
              NODE 02: PARQUE EÓLICO NORTE (Middle-Left in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('wind')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'wind' ? null : 'wind'))}
          >
            <FloatingWindTurbine
              tx={WIND_C[0] - 14}
              ty={WIND_C[1] - 10}
              tz={WIND_C[2] + windLift}
              towerH={24}
              bladeR={12.5}
              angleRad={rotorPhase}
              highlighted={activeNode === 'wind'}
            />
            <FloatingWindTurbine
              tx={WIND_C[0] + 4}
              ty={WIND_C[1] - 2}
              tz={WIND_C[2] + windLift}
              towerH={26}
              bladeR={13.5}
              angleRad={rotorPhase + 1.1}
              highlighted={activeNode === 'wind'}
            />
            <FloatingWindTurbine
              tx={WIND_C[0] - 6}
              ty={WIND_C[1] + 14}
              tz={WIND_C[2] + windLift}
              towerH={22}
              bladeR={11.5}
              angleRad={rotorPhase + 2.3}
              highlighted={activeNode === 'wind'}
            />
            {/* Wind Collector Transformer */}
            <Solid
              paths={k.slabOf(
                { x: WIND_C[0] + 12, y: WIND_C[1] + 6, w: 11, d: 11, r: 1.2 },
                WIND_C[2] + windLift,
                6.5,
                P,
                4,
                0.5
              )}
              tone="hi"
              lit={activeNode === 'wind'}
            />
          </g>

          {/* =========================================================
              NODE 05: SUBESTACIÓN TRONCAL 500 kV (Lower-Center in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('substation')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'substation' ? null : 'substation'))}
          >
            {/* High-Voltage Transformer Bank + Copper Coils */}
            <path
              className="iso-halo"
              d={k.haloOf(
                { x: SUBSTATION_C[0] - 22, y: SUBSTATION_C[1] - 18, w: 44, d: 20, r: 2 },
                SUBSTATION_C[2] - 1 + subLift,
                3,
                P
              )}
            />
            <Solid
              paths={k.slabOf(
                { x: SUBSTATION_C[0] - 22, y: SUBSTATION_C[1] - 18, w: 44, d: 20, r: 1.8 },
                SUBSTATION_C[2] + subLift,
                7.2,
                P,
                5,
                0.7
              )}
              tone="hi"
              lit={activeNode === 'substation'}
              inner={
                <Line
                  d={
                    k.coil(
                      SUBSTATION_C[0] - 14,
                      SUBSTATION_C[0] + 14,
                      [SUBSTATION_C[1] + 2, SUBSTATION_C[2] + 3.6 + subLift],
                      3.2,
                      9,
                      'x',
                      P
                    ).front
                  }
                  tone="blue"
                />
              }
            />
            {/* 4 High-Voltage Ceramic Insulator Bushings */}
            {[-15, -5, 5, 15].map((dx, idx) => (
              <Solid
                key={`bushing-${idx}`}
                paths={k.cylinder(
                  SUBSTATION_C[0] + dx,
                  SUBSTATION_C[1] - 13,
                  1.5,
                  SUBSTATION_C[2] + 7.2 + subLift,
                  6.2,
                  P,
                  14
                )}
                tone="mid"
              />
            ))}

            {/* Precision 50.00 Hz / MVA Dial Gauge floating in front of the transformer */}
            <path
              className="iso-halo"
              d={k.haloOf(
                { x: dialX - dialR, y: dialY - dialR, w: dialR * 2, d: dialR * 2, r: dialR },
                SUBSTATION_C[2] - 1 + subLift,
                2.5,
                P
              )}
            />
            <Solid
              paths={k.cylinder(
                dialX,
                dialY,
                dialR,
                SUBSTATION_C[2] + subLift,
                3.2,
                P,
                36
              )}
              tone="hi"
              lit={activeNode === 'substation'}
              inner={
                <g>
                  <Line
                    d={k.knurl(
                      dialX,
                      dialY,
                      dialR,
                      SUBSTATION_C[2] + 0.4 + subLift,
                      SUBSTATION_C[2] + 2.8 + subLift,
                      28,
                      P
                    )}
                    tone="faint"
                  />
                  <Line d={dialTicks.minor} tone="lo" />
                  <Line d={dialTicks.major} tone="hi" />
                  <Line
                    d={k.ring(dialX, dialY, dialR - 1.5, dialZ, P, 32)}
                    tone="blue"
                  />
                  <Line
                    d={k.pathOf([
                      k.iso([dialX, dialY, dialZ + 0.4], P),
                      k.iso(needleTip, P),
                    ])}
                    tone="blue"
                  />
                </g>
              }
            />
            <Solid
              paths={k.cylinder(dialX, dialY, 2.0, dialZ, 1.3, P, 16)}
              tone="mid"
            />
          </g>

          {/* =========================================================
              NODE 03: CENTRAL TÉRMICA GAS (Bottom-Left in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('thermal')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'thermal' ? null : 'thermal'))}
          >
            <path
              className="iso-halo"
              d={k.haloOf(
                { x: THERMAL_C[0] - 24, y: THERMAL_C[1] - 16, w: 38, d: 28, r: 2 },
                THERMAL_C[2] - 1 + thermalLift,
                3.5,
                P
              )}
            />
            {/* Main Combined-Cycle Turbine Hall */}
            <Solid
              paths={k.slabOf(
                { x: THERMAL_C[0] - 24, y: THERMAL_C[1] - 16, w: 34, d: 24, r: 1.8 },
                THERMAL_C[2] + thermalLift,
                11.5,
                P,
                5,
                0.8
              )}
              tone="hi"
              lit={activeNode === 'thermal'}
              inner={
                <Line
                  d={
                    k.sideTicks(
                      THERMAL_C[0] - 20,
                      THERMAL_C[0] + 6,
                      3.2,
                      2,
                      THERMAL_C[1] + 8,
                      THERMAL_C[2] + 9.0 + thermalLift,
                      [6.5, 6.5],
                      P,
                      'x'
                    ).minor
                  }
                  tone="lo"
                />
              }
            />
            {/* Secondary Heat Recovery Boiler */}
            <Solid
              paths={k.slabOf(
                { x: THERMAL_C[0] + 10, y: THERMAL_C[1] - 12, w: 14, d: 18, r: 1.4 },
                THERMAL_C[2] + thermalLift,
                8.5,
                P,
                4,
                0.6
              )}
              tone="mid"
              lit={activeNode === 'thermal'}
            />
            {/* Twin Flue Stacks */}
            <Solid
              paths={k.cylinder(
                THERMAL_C[0] - 14,
                THERMAL_C[1] - 4,
                3.2,
                THERMAL_C[2] + 11.5 + thermalLift,
                13.5,
                P,
                20
              )}
              tone="mid"
            />
            <Solid
              paths={k.cylinder(
                THERMAL_C[0] - 2,
                THERMAL_C[1] - 4,
                3.2,
                THERMAL_C[2] + 11.5 + thermalLift,
                11.0,
                P,
                20
              )}
              tone="mid"
            />
            {/* Cylindrical Gas Storage Tank */}
            <Solid
              paths={k.cylinder(
                THERMAL_C[0] - 14,
                THERMAL_C[1] + 18,
                6.2,
                THERMAL_C[2] + thermalLift,
                7.2,
                P,
                24
              )}
              tone="hi"
              lit={activeNode === 'thermal'}
            />
          </g>

          {/* =========================================================
              NODE 06: BARRIO RESIDENCIAL · CASAS (Right in space)
             ========================================================= */}
          <g
            className="maquette-station-group"
            onMouseEnter={() => setActiveNode('houses')}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === 'houses' ? null : 'houses'))}
          >
            {/* Aerial neighborhood distribution lines linking the floating houses */}
            <Line
              d={k.pathOf([
                k.iso([HOUSES_C[0] - 24, HOUSES_C[1] - 8, 5 + housesLift], P),
                k.iso([HOUSES_C[0] + 24, HOUSES_C[1] - 8, 5 + housesLift], P),
              ])}
              tone="faint"
              dashed
            />
            <Line
              d={k.pathOf([
                k.iso([HOUSES_C[0] - 24, HOUSES_C[1] + 16, 5 + housesLift], P),
                k.iso([HOUSES_C[0] + 24, HOUSES_C[1] + 16, 5 + housesLift], P),
              ])}
              tone="faint"
              dashed
            />

            {/* 6 Free-Floating 3D Houses with Pitched Roofs & Warm Lit Windows */}
            {[
              { hx: HOUSES_C[0] - 28, hy: HOUSES_C[1] - 28, hw: 15, hd: 16, wallH: 6.8, roofH: 4.8 },
              { hx: HOUSES_C[0] - 6,  hy: HOUSES_C[1] - 28, hw: 15, hd: 16, wallH: 7.5, roofH: 5.2 },
              { hx: HOUSES_C[0] + 16, hy: HOUSES_C[1] - 28, hw: 15, hd: 16, wallH: 6.4, roofH: 4.5 },
              { hx: HOUSES_C[0] - 28, hy: HOUSES_C[1] - 2,  hw: 15, hd: 16, wallH: 7.2, roofH: 5.0 },
              { hx: HOUSES_C[0] - 6,  hy: HOUSES_C[1] - 2,  hw: 15, hd: 16, wallH: 8.0, roofH: 5.4 },
              { hx: HOUSES_C[0] + 16, hy: HOUSES_C[1] - 2,  hw: 15, hd: 16, wallH: 6.8, roofH: 4.8 },
            ].map((h, idx) => (
              <FloatingHouse
                key={`house-${idx}`}
                x={h.hx}
                y={h.hy}
                w={h.hw}
                d={h.hd}
                z={HOUSES_C[2] + housesLift}
                wallH={h.wallH}
                roofH={h.roofH}
                highlighted={activeNode === 'houses'}
              />
            ))}

            {/* Neighborhood Pole Transformer */}
            <Solid
              paths={k.cylinder(
                HOUSES_C[0] - 32,
                HOUSES_C[1] - 8,
                1.8,
                HOUSES_C[2] + housesLift,
                8.5,
                P,
                14
              )}
              tone="mid"
            />
            <Dots
              points={[
                k.iso([HOUSES_C[0] - 32, HOUSES_C[1] - 8, HOUSES_C[2] + 8.8 + housesLift], P),
              ]}
              size={1.2}
              tone="hi"
              pulse
            />
          </g>
        </svg>

        {/* =========================================================
            BORDERLESS 4-DATUM LABELS DIRECTLY ON THE WHITE CANVAS
           ========================================================= */}
        {nodeSpecs.map((spec) => (
          <div
            key={spec.id}
            className={`bare-node-label align-${spec.align} ${
              activeNode === spec.id ? 'is-active' : ''
            }`}
            style={spec.pos}
            onMouseEnter={() => setActiveNode(spec.id)}
            onMouseLeave={() => setActiveNode(null)}
            onClick={() => setActiveNode((n) => (n === spec.id ? null : spec.id))}
          >
            <div className="bare-node-title">
              <span
                className="bare-node-dot"
                style={{ backgroundColor: spec.dotColor }}
              />
              {spec.name}
            </div>
            <div className="bare-node-meta">
              <span>{spec.d1}</span>
              <span>{spec.d2}</span>
              <span>{spec.d3}</span>
            </div>
          </div>
        ))}
      </div>
    </Stage>
  );
};
