import React, { memo } from 'react';
import type { Catalog, Disruption, Solution } from '../live/types';
import { at } from './GridScene';
import { ZONES } from './layout';

// The country north to south: homes with and without supply in each zone, and the state of the
// trunk line that joins each zone to the next. Same story as the maquette, read in one glance.
interface Props {
  catalog: Catalog;
  solution: Solution;
  hour: number;
  incidents: Disruption[];
}

const ORDER = ['n_norte_grande', 'n_norte_chico', 'n_centro', 'n_centro_sur', 'n_sur'];
const fmt = (n: number) => Math.round(n).toLocaleString('es-CL');

export const ZoneStatus = memo(function ZoneStatus({ catalog, solution, hour, incidents }: Props) {
  const cut = new Set(incidents.filter((d) => d.type === 'line_outage' && hour >= d.from_hour && hour < d.to_hour).map((d) => d.asset_id));
  const nodes = ORDER.map((id) => catalog.nodes.find((n) => n.id === id)).filter(Boolean) as Catalog['nodes'];
  const totalHomes = nodes.reduce((a, n) => a + n.households_total, 0);
  const totalOff = nodes.reduce((a, n) => a + at(solution.households_off[n.id], hour), 0);
  const lineBetween = (a: string, b: string) => catalog.lines.find((l) => (l.from === a && l.to === b) || (l.from === b && l.to === a));

  return (
    <div className="gp-zones">
      <div className="gp-zones-head">
        <b>Estado de la red · ahora</b>
        <span className={totalOff > 1 ? 'is-bad' : 'is-ok'}>
          {totalOff > 1 ? `${fmt(totalOff)} hogares sin luz (${((totalOff / totalHomes) * 100).toLocaleString('es-CL', { maximumFractionDigits: 1 })} %)` : 'Todos los hogares con luz'}
        </span>
      </div>
      {nodes.map((n, i) => {
        const off = at(solution.households_off[n.id], hour);
        const pct = Math.min(100, (off / n.households_total) * 100);
        const next = nodes[i + 1];
        const line = next ? lineBetween(n.id, next.id) : null;
        let lineState = '', lineText = '';
        if (line) {
          const flow = Math.abs(at(solution.line_flow_mw[line.id], hour));
          const cap = at(solution.line_capacity_mw[line.id], hour) || line.capacity_mw;
          const load = (flow / cap) * 100;
          lineState = cut.has(line.id) ? 'is-cut' : load >= 95 ? 'is-hot' : 'is-ok';
          lineText = cut.has(line.id) ? `${line.id} cortada` : `${line.id} · ${Math.round(load)} %${load >= 95 ? ' saturada' : ''}`;
        }
        return (
          <React.Fragment key={n.id}>
            <div className={`gp-zone${off > 1 ? ' is-dark' : ''}`}>
              <div className="gp-zone-name">{ZONES[n.id]?.label ?? n.name}</div>
              <div className="gp-zone-bar" title={`${fmt(n.households_total - off)} con luz · ${fmt(off)} sin luz`}>
                <i style={{ width: `${pct}%` }} />
              </div>
              <div className="gp-zone-n">{off > 1 ? `−${fmt(off)}` : 'ok'}</div>
            </div>
            {line && (
              <div className={`gp-zone-link ${lineState}`}>
                <span className="gp-zone-wire" />
                <span>{lineText}</span>
              </div>
            )}
          </React.Fragment>
        );
      })}
      <div className="gp-zones-key"><i className="ok" />con luz <i className="off" />sin luz · barra = hogares de la zona</div>
    </div>
  );
});
