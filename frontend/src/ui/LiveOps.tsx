import React, { useEffect, useMemo, useRef, useState } from 'react';
import { LiveSessionProvider, useLiveSession } from '../live/store';
import type { Option, Solution } from '../live/types';
import { GridScene, TECH_COLOR, TECH_LABEL, assetTitle, at, buildAssets } from './GridScene';
import { ZONES } from './layout';
import { AndesMark } from './brand';
import { ZoneStatus } from './ZoneStatus';
import './ui.css';

const API_BASE = import.meta.env?.VITE_API_BASE_URL || '/api';

const STATE_LABEL: Record<string, string> = {
  normal: 'Normal', alerta: 'Alerta', emergencia: 'Emergencia', recuperacion: 'Recuperación',
};
const TAG_LABEL: Record<string, string> = {
  max_hogares: 'Más hogares', min_costo: 'Menor costo', min_co2: 'Menos CO₂', min_riesgo_red: 'Menor riesgo de red',
};
const LEVER_LABEL: Record<string, string> = {
  emergency_rating: 'Límite de emergencia en línea',
  demand_response: 'Respuesta de la demanda',
  activate_reserve_bess: 'Batería de reserva',
  hydro_reserve_release: 'Reserva hidro',
  start_peaker: 'Arranque de diésel',
  add_battery: 'Batería nueva (planificación)',
  uprate_line: 'Ampliación de línea (planificación)',
};

const fmt = (n: number, d = 0) => n.toLocaleString('es-CL', { maximumFractionDigits: d, minimumFractionDigits: d });
const clock = (h: number) => {
  const hh = Math.floor(h) % 24;
  const mm = Math.floor((h - Math.floor(h)) * 60);
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
};
const sum = (rec: Record<string, number[]>, h: number) => Object.values(rec).reduce((s, v) => s + at(v, h), 0);

export function LiveOps() {
  return (
    <LiveSessionProvider>
      <Screen />
    </LiveSessionProvider>
  );
}

function Screen() {
  const { state, connectionMode, actions, interpolatedSimHour } = useLiveSession();
  // The provider ticks every frame; the scene only needs a new picture every couple of sim-minutes.
  const hour = Math.round(interpolatedSimHour * 30) / 30;
  const { catalog, solution, options, countdown } = state;
  const phase = state.agent_status.phase;
  const [selected, setSelected] = useState<string | null>(null);
  const [invite, setInvite] = useState(false);
  const [hovered, setHovered] = useState<Option | null>(null);
  const [applied, setApplied] = useState<Option | null>(null);
  const lastCandidate = useRef<string | null>(null);
  const [toast, setToast] = useState<{ kind: 'fault' | 'plan'; title: string; sub: string; key: number } | null>(null);
  const seenIncidents = useRef(new Set<string>());
  const wasCountingDown = useRef(false);

  // Remember which option is in play so the scene can light up its levers once applied,
  // including when Gemini applies it on its own after the countdown.
  useEffect(() => {
    if (countdown?.candidate_id) lastCandidate.current = countdown.candidate_id;
  }, [countdown?.candidate_id]);
  useEffect(() => {
    if (phase === 'executing' && options) {
      setApplied((prev) => prev ?? options.find((o) => o.option_id === lastCandidate.current) ?? null);
    }
    if (phase === 'analyzing') setApplied(null);
  }, [phase, options]);
  useEffect(() => {
    if (state.active_incidents.length === 0) setApplied(null);
  }, [state.active_incidents.length]);

  // Which zones each fault left in the dark, as the engine computed it, so the map can aim the
  // optimisation at them even after the plan brings the lights back.
  const [hitZones, setHitZones] = useState<Record<string, string[]>>({});
  useEffect(() => {
    const ev = state.last_incident;
    if (!ev || seenIncidents.current.has(ev.incident_id)) return;
    seenIncidents.current.add(ev.incident_id);
    setHitZones((m) => ({ ...m, [ev.disruption.event_id]: ev.impact.nodes_affected }));
  }, [state.last_incident]);
  useEffect(() => {
    if (countdown?.active) wasCountingDown.current = true;
  }, [countdown?.active]);
  useEffect(() => {
    if (phase !== 'executing') return;
    const byGemini = state.applied_by ? state.applied_by === 'gemini_autonomous' : wasCountingDown.current;
    wasCountingDown.current = false;
    setToast({ kind: 'plan', title: byGemini ? 'Gemini aplicó el plan por su cuenta' : 'Plan aplicado por el operador', sub: byGemini ? 'Modo autónomo · validado por el solver antes de ejecutarse' : 'Validado por el solver antes de ejecutarse', key: Date.now() });
  }, [phase]);
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(id);
  }, [toast]);

  // `?hora=18.3` jumps the session to that hour on load (handy to rehearse a moment of the demo).
  const jumped = useRef(false);
  useEffect(() => {
    const h = Number(new URLSearchParams(window.location.search).get('hora'));
    if (jumped.current || !catalog || connectionMode === 'connecting' || !Number.isFinite(h) || h <= 0) return;
    // The provider restarts the offline player once while it settles; seek after that.
    const id = window.setTimeout(() => {
      jumped.current = true;
      actions.setClock({ action: 'seek', hour: h });
    }, 700);
    return () => window.clearTimeout(id);
  }, [catalog, connectionMode]);

  const shown: Solution | null = hovered?.solution ?? solution;
  const deciding = !!options && (phase === 'awaiting_operator' || !!countdown?.active);
  const assets = useMemo(() => (catalog ? buildAssets(catalog) : []), [catalog]);

  const affected = useMemo(() => {
    const ids = new Set<string>();
    state.active_incidents.forEach((d) => {
      (hitZones[d.event_id] ?? []).forEach((n) => ids.add(n));
      const a = assets.find((x) => x.id === d.asset_id);
      if (a && !hitZones[d.event_id]?.length) ids.add(a.nodeId);
    });
    return [...ids];
  }, [state.active_incidents, hitZones, assets]);
  const proposed = useMemo(() => {
    const o = hovered ?? options?.find((x) => x.option_id === countdown?.candidate_id) ?? null;
    return new Set((o?.levers ?? []).map((l) => l.target_id));
  }, [hovered, options, countdown?.candidate_id]);
  const boosted = useMemo(() => new Set((applied?.levers ?? []).map((l) => l.target_id)), [applied]);
  const focus = useMemo(() => {
    if (!shown) return [] as string[];
    const ids = new Set<string>();
    if (phase === 'analyzing' || phase === 'awaiting_operator') {
      state.active_incidents.forEach((d) => ids.add(d.asset_id));
      Object.keys(shown.unserved_mw).forEach((n) => at(shown.unserved_mw[n], hour) > 1 && ids.add(n));
    }
    const lit = hovered ?? (phase === 'awaiting_operator' ? options?.find((o) => o.option_id === countdown?.candidate_id) : null) ?? (phase === 'executing' ? applied : null);
    lit?.levers.forEach((l) => ids.add(l.target_id));
    return [...ids];
  }, [shown, phase, state.active_incidents, hour, hovered, options, countdown, applied]);

  if (!catalog || !shown) {
    return (
      <div className="gp gp-loading iso" data-theme="light">
        <div className="gp-spinner" />
        <p>Conectando con la red…</p>
      </div>
    );
  }

  // KPIs move once per simulated hour (and glide), so they stay readable while the clock runs fast.
  const step = Math.floor(hour);
  const off = sum(shown.households_off, step);
  const deficit = sum(shown.unserved_mw, step);
  const demand = sum(shown.demand_mw, step);
  const cost = at(shown.cost_proxy_usd, step);
  const co2 = at(shown.co2_t, step);
  const sel = selected ? assets.find((a) => a.id === selected) ?? null : null;
  const selLine = selected ? catalog.lines.find((l) => l.id === selected) ?? null : null;

  const decide = (o: Option, decision: 'apply' | 'veto') => {
    const incident = state.tool_calls[state.tool_calls.length - 1]?.incident_id ?? state.active_incidents[state.active_incidents.length - 1]?.event_id ?? '';
    if (decision === 'apply') setApplied(o);
    setHovered(null);
    return actions.submitOperatorDecision({ incident_id: incident, option_id: o.option_id, decision });
  };
  const setAutonomy = async (enabled: boolean) => {
    if (connectionMode !== 'live' || !state.sessionId) return;
    await fetch(`${API_BASE}/live/sessions/${encodeURIComponent(state.sessionId)}/autonomy`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
    });
  };

  return (
    <div className={`gp iso is-${state.grid_state}${deciding ? ' has-options' : ''}`} data-theme="light">
      <header className="gp-top">
        <div className="gp-brand">
          <AndesMark size={26} />
          <span className="gp-logo">Andes</span>
          <span className="gp-sub">Coordinador · SEN Chile · gemelo digital</span>
        </div>
        <div className={`gp-state is-${state.grid_state}`}>{STATE_LABEL[state.grid_state] ?? state.grid_state}</div>
        <div className="gp-clock">
          <b>{clock(hour)}</b>
          {catalog.day_profile?.label_es && <span className="gp-dayprofile">{catalog.day_profile.label_es}</span>}
          <div className="gp-day"><i style={{ width: `${(hour / 24) * 100}%` }} /></div>
        </div>
        <div className="gp-kpis">
          <Kpi label="Hogares sin luz" value={fmt(off)} hot={off > 1} />
          <Kpi label="Déficit" value={`${fmt(deficit)} MW`} hot={deficit > 1} />
          <Kpi label="Demanda" value={`${fmt(demand)} MW`} />
          <Kpi label="Costo" value={`US$ ${fmt(cost / 1000, 1)} mil/h`} />
          <Kpi label="CO₂" value={`${fmt(co2)} t/h`} />
        </div>
        <div className={`gp-conn is-${connectionMode}`} title={connectionMode === 'offline' ? 'Sin backend: reproduce una sesión grabada con el solver real' : ''}>
          {connectionMode === 'live' ? '● En vivo' : connectionMode === 'offline' ? '● Sesión grabada' : '○ Conectando'}
        </div>
      </header>

      <GridScene
        catalog={catalog}
        solution={shown}
        hour={hour}
        incidents={state.active_incidents}
        boosted={boosted}
        phase={phase}
        focus={focus}
        affected={affected}
        proposed={proposed}
        selected={selected}
        onSelect={setSelected}
      />

      <div className="gp-legend">
        <b>Producción</b>
        {['solar', 'wind', 'hydro', 'gas', 'coal', 'diesel', 'battery'].map((t) => (
          <div key={t}><i className="sw" style={{ background: TECH_COLOR[t] }} />{TECH_LABEL[t]}</div>
        ))}
        <b>Transmisión</b>
        <div><i className="ln" style={{ borderColor: 'var(--blue)' }} />Normal</div>
        <div><i className="ln" style={{ borderColor: 'var(--amber)' }} />Saturada ≥95 %</div>
        <div><i className="ln is-cut" style={{ borderColor: 'var(--red)' }} />Cortada</div>
        <b>Hogares</b>
        <div><i className="win" />Con luz</div>
        <div><i className="win is-dark" />Sin luz</div>
        <small className="gp-legend-note">1 casa = 200.000 hogares</small>
      </div>

      {toast && (
        <div key={toast.key} className={`gp-toast is-${toast.kind}`}>
          <b>{toast.kind === 'fault' ? 'Falla' : 'Plan en marcha'}</b>
          <span>{toast.title}</span>
          <small>{toast.sub}</small>
        </div>
      )}

      {hovered && <div className="gp-preview-banner">Vista previa · así quedaría la red con «{hovered.title_es}»</div>}

      <aside className="gp-brain">
        <div className="gp-brain-head">
          <span className={`gp-brain-dot is-${phase}`} />
          <div>
            <b>Gemini</b>
            <span>{phase === 'analyzing' ? 'Analizando la falla' : phase === 'awaiting_operator' ? 'Propone dos caminos' : phase === 'executing' ? 'Ejecutando el plan' : phase === 'resolved' ? 'Plan aplicado' : 'Vigilando la red'}</span>
          </div>
        </div>
        <ZoneStatus catalog={catalog} solution={shown} hour={step} incidents={state.active_incidents} />
        {options && (phase === 'awaiting_operator' || countdown?.active) && (
          <section className="gp-options gp-options-panel">
            <div className="gp-options-head">
              <b>¿Qué hacemos?</b>
              <span>{countdown?.active ? `Modo autónomo: Gemini aplica su recomendación en ${countdown.seconds_left} s` : <><span className="gp-only-pointer">Elige un camino. Pasa el cursor para ver cómo quedaría la red.</span><span className="gp-only-touch">Elige un camino y toca «Aplicar».</span></>}</span>
              {state.model_execution && <ModelBadge m={state.model_execution} />}
            </div>
            <div className="gp-options-row">
              {options.map((o) => {
                const rec = countdown?.candidate_id === o.option_id;
                return (
                  <article
                    key={o.option_id}
                    className={`gp-option${rec ? ' is-rec' : ''}`}
                    onMouseEnter={() => setHovered(o)}
                    onMouseLeave={() => setHovered(null)}
                  >
                    <div className="gp-option-tags">
                      <span className="gp-tag">{TAG_LABEL[o.tradeoff_tag] ?? o.tradeoff_tag}</span>
                      {rec && <span className="gp-tag is-rec">Recomendada por Gemini</span>}
                      <span className={`gp-tag ${o.validation.passed ? 'is-ok' : 'is-bad'}`}>{o.validation.passed ? 'Validador ✓' : 'Validador ✗'}</span>
                    </div>
                    <h3>{o.title_es}</h3>
                    <p title={o.rationale_es}>{o.rationale_es}</p>
                    <ul className="gp-levers">
                      {o.levers.map((l, i) => (
                        <li key={i}>{LEVER_LABEL[l.type] ?? l.type} · <span>{leverTarget(l.target_id, assets, catalog.lines)}</span></li>
                      ))}
                    </ul>
                    <div className="gp-option-foot">
                    <dl>
                      <div><dt>Reconecta</dt><dd className="is-good">+{fmt(o.metrics.households_reconnected)}</dd></div>
                      <div><dt>Pierden luz</dt><dd className={o.metrics.households_newly_off > 0 ? 'is-bad' : ''}>{o.metrics.households_newly_off > 0 ? `−${fmt(o.metrics.households_newly_off)}` : '0'}</dd></div>
                      <div><dt>Costo US$</dt><dd>{o.metrics.cost_delta_usd >= 0 ? '+' : '−'}{fmt(Math.abs(o.metrics.cost_delta_usd) / 1000)} mil</dd></div>
                      <div><dt>CO₂</dt><dd>{o.metrics.co2_delta_t >= 0 ? '+' : '−'}{fmt(Math.abs(o.metrics.co2_delta_t))} t</dd></div>
                      <div><dt>Carga máx. línea</dt><dd className={o.metrics.max_line_loading_pct >= 98 ? 'is-warn' : ''}>{fmt(o.metrics.max_line_loading_pct)} %</dd></div>
                    </dl>
                    <div className="gp-option-actions">
                      {rec && countdown?.active ? (
                        <>
                          <div className="gp-count" style={{ ['--p' as string]: `${(countdown.seconds_left / 5) * 100}%` }}><span>{countdown.seconds_left}</span></div>
                          <button className="gp-btn is-ghost" onClick={() => decide(o, 'veto')}>Vetar</button>
                        </>
                      ) : (
                        <button className="gp-btn" onClick={() => decide(o, 'apply')}>Aplicar</button>
                      )}
                    </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        )}
        <div className={`gp-brain-feed${deciding ? ' is-compact' : ''}`}>
          {state.thoughts.length === 0 && state.notes.length === 0 && (
            <p className="gp-idle">Sin incidentes. Vigilo {catalog.generators.length} centrales, {catalog.batteries.length} baterías, {catalog.lines.length} líneas troncales y {catalog.nodes.length} zonas, hora a hora.</p>
          )}
          <MonitorBlock notes={state.notes} catalog={catalog} />
          {state.thoughts.slice(-3).map((th, i, arr) => (
            <Typed key={`${th.ts_utc}-${i}`} className="gp-thought" text={th.text_es} prefix={clock(th.sim_hour)} live={i === arr.length - 1} />
          ))}
          {state.tool_calls.length > 0 && (
            <ul className="gp-tools">
              {state.tool_calls.slice(-5).map((c, i) => (
                <li key={`${c.call_id}-${i}`} className={`is-${c.status}`}>
                  <code>{c.tool}</code>
                  <span>{c.args_summary_es}</span>
                  <b>{c.status === 'pass' ? 'PASS' : c.status === 'fail' ? 'FAIL' : c.status === 'infeasible' ? 'INFACTIBLE' : '…'}</b>
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className="gp-brain-foot">Gemini razona y propone. Cada número lo calcula el solver HiGHS y lo revisa un validador independiente.</p>
      </aside>



      {(sel || selLine) && (
        <div className="gp-sheet" onClick={(e) => e.stopPropagation()}>
          <button className="gp-sheet-x" onClick={() => setSelected(null)} aria-label="Cerrar">×</button>
          {sel && (
            <>
              <small>{sel.kind === 'battery' ? 'Batería' : 'Central'} del modelo · {ZONES[sel.nodeId]?.label}</small>
              <h3>{assetTitle(sel)}</h3>
              <Spark series={sel.kind === 'battery' ? shown.battery_flow_mw[sel.id] : shown.generation_mw[sel.id]} cap={sel.capacity} hour={hour} />
              <dl>
                <div><dt>Ahora</dt><dd>{fmt(Math.abs(sel.kind === 'battery' ? at(shown.battery_flow_mw[sel.id], hour) : at(shown.generation_mw[sel.id], hour)))} MW</dd></div>
                <div><dt>Capacidad</dt><dd>{fmt(sel.capacity)} MW</dd></div>
              </dl>
              <p className="gp-prov">Activo agregado del escenario de 5 zonas (sintético, con forma chilena). Representa a las centrales reales de esta tecnología en la zona.</p>
              <button className="gp-btn is-danger" onClick={() => { actions.injectEvent({ asset_id: sel.id, duration_h: 4, source: 'operator' }); setSelected(null); }}>Provocar falla repentina (4 h)</button>
            </>
          )}
          {selLine && (
            <>
              <small>Línea troncal · {ZONES[selLine.from]?.label} → {ZONES[selLine.to]?.label}</small>
              <h3>Línea {selLine.id}</h3>
              <Spark series={shown.line_flow_mw[selLine.id]} cap={selLine.capacity_mw} hour={hour} />
              <dl>
                <div><dt>Flujo ahora</dt><dd>{fmt(Math.abs(at(shown.line_flow_mw[selLine.id], hour)))} MW</dd></div>
                <div><dt>Capacidad</dt><dd>{fmt(at(shown.line_capacity_mw[selLine.id], hour) || selLine.capacity_mw)} MW</dd></div>
              </dl>
              <button className="gp-btn is-danger" onClick={() => { actions.injectEvent({ asset_id: selLine.id, duration_h: 4, source: 'operator' }); setSelected(null); }}>Cortar línea (4 h)</button>
            </>
          )}
        </div>
      )}

      {invite && (
        <div className="gp-invite" onClick={() => setInvite(false)}>
          <div className="gp-invite-card" onClick={(e) => e.stopPropagation()}>
            <small>Jurado · escanea con tu celular</small>
            <h2>Intenta botar la red</h2>
            {connectionMode === 'live' && state.sessionId ? (
              <>
                <img src={`${API_BASE}/live/sessions/${encodeURIComponent(state.sessionId)}/qr.svg`} alt="Código QR de la página del jurado" />
                <code>{`${window.location.origin}/jurado?s=${state.sessionId}`}</code>
              </>
            ) : (
              <p>El jurado necesita el backend en vivo. Ahora mismo se está reproduciendo una sesión grabada.</p>
            )}
            <button className="gp-btn" onClick={() => setInvite(false)}>Listo</button>
          </div>
        </div>
      )}

      <footer className="gp-controls">
        <button className="gp-btn is-ghost" onClick={() => actions.setClock({ action: state.clock.running ? 'pause' : 'play' })}>{state.clock.running ? 'Pausa' : 'Reanudar'}</button>
        <label className={`gp-switch${state.clock.autonomy_mode ? ' is-on' : ''}${connectionMode !== 'live' ? ' is-disabled' : ''}`}>
          <input type="checkbox" checked={state.clock.autonomy_mode} disabled={connectionMode !== 'live'} onChange={(e) => setAutonomy(e.target.checked)} />
          <span /> Modo autónomo
        </label>
        {connectionMode === 'offline' && <button className="gp-btn is-ghost" onClick={() => actions.replayOfflineDemo()}>Repetir sesión</button>}
        <button className="gp-btn is-ghost" onClick={() => setInvite(true)}>Invitar al jurado</button>
        <span className="gp-hint">Toca una central o una línea para ver su detalle o provocar una falla.</span>
      </footer>
    </div>
  );
}

function leverTarget(id: string, assets: ReturnType<typeof buildAssets>, lines: { id: string }[]) {
  const a = assets.find((x) => x.id === id);
  if (a) return assetTitle(a);
  if (ZONES[id]) return ZONES[id].label;
  if (lines.find((l) => l.id === id)) return `Línea ${id}`;
  return id;
}

function Kpi({ label, value, hot }: { label: string; value: string; hot?: boolean }) {
  return (
    <div className={`gp-kpi${hot ? ' is-hot' : ''}`}>
      <span>{label}</span>
      <b key={value} className="gp-kpi-v">{value}</b>
    </div>
  );
}

// Text that types itself in, like the model is writing it right now.
function Typed({ text, prefix, live, className }: { text: string; prefix: string; live: boolean; className: string }) {
  const [n, setN] = useState(live ? 0 : text.length);
  useEffect(() => {
    if (!live) return;
    setN(0);
    const id = window.setInterval(() => setN((v) => (v >= text.length ? (window.clearInterval(id), v) : v + 2)), 18);
    return () => window.clearInterval(id);
  }, [text, live]);
  return (
    <p className={className}>
      <em>{prefix}</em>
      {text.slice(0, n)}
      {n < text.length && <i className="gp-caret" />}
    </p>
  );
}

function Spark({ series, cap, hour }: { series?: number[]; cap: number; hour: number }) {
  if (!series) return null;
  const w = 260, h = 56;
  const max = Math.max(cap, ...series.map(Math.abs), 1);
  const pts = series.map((v, i) => `${(i / (series.length - 1)) * w},${h - (Math.abs(v) / max) * (h - 6) - 3}`).join(' ');
  return (
    <svg className="gp-spark" viewBox={`0 0 ${w} ${h}`}>
      <line x1="0" x2={w} y1={h - (cap / max) * (h - 6) - 3} y2={h - (cap / max) * (h - 6) - 3} className="gp-spark-cap" />
      <polyline points={pts} className="gp-spark-line" />
      <line x1={(hour / 24) * w} x2={(hour / 24) * w} y1="0" y2={h} className="gp-spark-now" />
    </svg>
  );
}

type Note = ReturnType<typeof useLiveSession>['state']['notes'][number];
const SEVERITY_LABEL = { info: 'Normal', watch: 'Vigilar', alert: 'Alerta' } as const;

// Jimmy: the hourly monitor. Numbers arrive from code in `metrics`; the sentence may be model-worded.
function MonitorBlock({ notes, catalog }: { notes: Note[]; catalog: NonNullable<ReturnType<typeof useLiveSession>['state']['catalog']> }) {
  if (notes.length === 0) return null;
  const last = notes[notes.length - 1];
  const earlier = notes.slice(0, -1).reverse().slice(0, 4);
  if (last.kind !== 'monitor' && !last.severity && !last.metrics) {
    return <p className="gp-note"><em>{clock(last.sim_hour)}</em>{last.text_es}</p>;
  }
  const m = last.metrics ?? {};
  const sev = last.severity ?? 'info';
  const line = m.max_line_id ? catalog.lines.find((l) => l.id === m.max_line_id) : undefined;
  const lineName = line ? `${line.id} · ${ZONES[line.from]?.label ?? line.from} → ${ZONES[line.to]?.label ?? line.to}` : m.max_line_id;
  const stats: { k: string; v: string; hot?: boolean }[] = [];
  if (m.reserve_margin_pct != null) stats.push({ k: 'Reserva', v: `${fmt(m.reserve_margin_pct, 1)} %`, hot: m.reserve_margin_pct < 10 });
  if (m.max_line_loading_pct != null) stats.push({ k: lineName ? `Línea ${lineName}` : 'Línea más cargada', v: `${fmt(m.max_line_loading_pct, 0)} %`, hot: m.max_line_loading_pct >= 90 });
  if ((m.unserved_mw ?? 0) > 0) stats.push({ k: 'Sin servir', v: `${fmt(m.unserved_mw!, 0)} MW`, hot: true });
  else if (m.curtailment_mw != null) stats.push({ k: 'Vertimiento', v: `${fmt(m.curtailment_mw, 0)} MW` });
  return (
    <section className={`gp-jimmy is-${sev}`}>
      <div className="gp-jimmy-head">
        <b>Jimmy · monitor</b>
        <span className={`gp-sev is-${sev}`}>{SEVERITY_LABEL[sev]}</span>
        <em>{clock(last.sim_hour)}</em>
      </div>
      <p>{last.text_es}</p>
      {stats.length > 0 && (
        <dl className="gp-jimmy-stats">
          {stats.slice(0, 3).map((x) => <div key={x.k} className={x.hot ? 'is-hot' : ''}><dt>{x.k}</dt><dd>{x.v}</dd></div>)}
        </dl>
      )}
      <MonitorBadge m={last.model_execution} />
      {earlier.length > 0 && (
        <ul className="gp-jimmy-hist">
          {earlier.map((n, i) => (
            <li key={i} className={`is-${n.severity ?? 'info'}`}><em>{clock(n.sim_hour)}</em>{n.text_es}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

// The monitor's wording is deterministic unless the model really answered.
function MonitorBadge({ m }: { m?: Note['model_execution'] }) {
  if (!m) return null;
  const deterministic = m.model === 'deterministic-monitor' || (m.response_id ?? '').startsWith('det-');
  const status = m.status as string;
  const label = deterministic ? 'Sin modelo · texto determinista'
    : status === 'timeout' ? `${m.model} no respondió a tiempo`
    : status === 'error' ? `${m.model} con error`
    : status === 'no_key' ? 'Sin modelo · sin clave'
    : `${m.model} · ${(m.latency_ms / 1000).toLocaleString('es-CL', { maximumFractionDigits: 1 })} s${m.cached ? ' · respuesta en caché' : ''}`;
  return <em className={`gp-model gp-jimmy-model${deterministic || status !== 'ok' ? ' is-warn' : ''}`}>{label}</em>;
}

// Who actually answered. A deterministic fallback or a cached answer must never pass for a live call.
function ModelBadge({ m }: { m: NonNullable<ReturnType<typeof useLiveSession>['state']['model_execution']> }) {
  const deterministic = (m.response_id ?? '').startsWith('det-');
  const label = m.status === 'timeout' ? `${m.model} no respondió a tiempo · ranking del solver`
    : m.status === 'error' ? `${m.model} con error · ranking del solver`
    : deterministic ? 'Planificador determinista · sin llamada a Gemini'
    : `${m.model} · ${(m.latency_ms / 1000).toLocaleString('es-CL', { maximumFractionDigits: 1 })} s${m.cached ? ' · respuesta en caché' : ''}`;
  return <em className={`gp-model${deterministic || m.status !== 'ok' ? ' is-warn' : ''}`}>{label}</em>;
}
