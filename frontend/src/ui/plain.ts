import type { Option } from '../live/types';

// Plain words for the room: what a plan is called and what it does.
export const TAG_LABEL: Record<string, string> = {
  max_hogares: 'Most homes', min_costo: 'Lowest cost', min_co2: 'Lowest CO₂', min_riesgo_red: 'Lowest grid risk',
};
export const LEVER_PLAIN: Record<string, string> = {
  emergency_rating: 'Line capacity',
  demand_response: 'Flexible demand',
  activate_reserve_bess: 'Battery reserves',
  hydro_reserve_release: 'Hydro reserves',
  start_peaker: 'Backup diesel',
  add_battery: 'New battery',
  uprate_line: 'Line upgrade',
};

export const fmtInt = (n: number) => Math.round(n).toLocaleString('en-GB');
export const recipe = (o: Option) => [...new Set(o.levers.map((l) => LEVER_PLAIN[l.type] ?? l.type))].join(' + ');
export const planName = (o: Option) => TAG_LABEL[o.tradeoff_tag] ?? o.title_es;
