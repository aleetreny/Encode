import React, { useEffect, useMemo, useRef, useState } from 'react';
import { LiveSessionProvider, useLiveSession } from '../live/store';
import type { Disruption, Option, Solution } from '../live/types';
import { GridScene, TECH_COLOR, TECH_LABEL, assetTitle, at, buildAssets } from './GridScene';
import { ZONES } from './layout';
import { AndesMark } from './brand';
import { ZoneStatus } from './ZoneStatus';
import './ui.css';

const API_BASE = import.meta.env?.VITE_API_BASE_URL || '/api';

const STATE_LABEL: Record<string, string> = {
  normal: 'Normal', alerta: 'Alert', emergencia: 'Emergency', recuperacion: 'Recovery',
};
const TAG_LABEL: Record<string, string> = {
  max_hogares: 'Most homes', min_costo: 'Lowest cost', min_co2: 'Lowest CO₂', min_riesgo_red: 'Lowest grid risk',
};
const LEVER_LABEL: Record<string, string> = {
  emergency_rating: 'Emergency line rating',
  demand_response: 'Demand response',
  activate_reserve_bess: 'Reserve battery',
  hydro_reserve_release: 'Hydro reserve',
  start_peaker: 'Diesel start-up',
  add_battery: 'New battery (planning)',
  uprate_line: 'Line upgrade (planning)',
};

const fmt = (n: number, d = 0) => n.toLocaleString('en-GB', { maximumFractionDigits: d, minimumFractionDigits: d });
const clock = (h: number) => {
  const hh = Math.floor(h) % 24;
  const mm = Math.floor((h - Math.floor(h)) * 60);
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
};
const sum = (rec: Record<string, number[]>, h: number) => Object.values(rec).reduce((s, v) => s + at(v, h), 0);

type Attack = { who: string; target: string; headline: string; jury: boolean; at: number; homes: number; mw: number; key: string };
type Catalog = NonNullable<ReturnType<typeof useLiveSession>['state']['catalog']>;

// "Juror Ana knocked out Gas · Centro": who did it and what fell, from the disruption itself.
function describeFault(d: Disruption, catalog: Catalog) {
  const a = buildAssets(catalog).find((x) => x.id === d.asset_id);
  const line = catalog.lines.find((l) => l.id === d.asset_id);
  const target = line ? `line ${line.id} (${ZONES[line.from]?.label} → ${ZONES[line.to]?.label})` : a ? assetTitle(a) : d.asset_id;
  const jury = d.source === 'jury';
  const who = jury ? (d.jury_name ? `Juror ${d.jury_name}` : 'A juror') : d.source === 'operator' ? 'The operator' : '';
  return { who, target, jury, headline: who ? `${who} knocked out ${target}` : `Sudden outage: ${target}` };
}

const STEPS = ['Attack', 'Impact', 'Gemini analysing', 'Two options', 'Plan applied', 'Recovering'] as const;

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

  // The latest fault, worded once: who did it, what fell, and the damage the engine computed.
  const [attacks, setAttacks] = useState<Attack[]>([]);
  useEffect(() => {
    const ev = state.last_incident;
    if (!catalog || !ev || seenIncidents.current.has(ev.incident_id)) return;
    seenIncidents.current.add(ev.incident_id);
    const d = ev.disruption;
    const w = describeFault(d, catalog);
    setAttacks((list) => [{ ...w, at: d.from_hour, homes: ev.impact.households_off_peak, mw: ev.impact.unserved_mw_peak, key: ev.incident_id }, ...list].slice(0, 4));
  }, [state.last_incident, catalog]);
  useEffect(() => {
    if (countdown?.active) wasCountingDown.current = true;
  }, [countdown?.active]);
  useEffect(() => {
    if (phase !== 'executing') return;
    const byGemini = state.applied_by ? state.applied_by === 'gemini_autonomous' : wasCountingDown.current;
    wasCountingDown.current = false;
    setPlanBy(byGemini ? 'Gemini applied the plan on its own' : 'Plan applied by the operator');
  }, [phase]);

  // A preview must not outlive the options it belongs to (the panel unmounts without a mouseleave).
  useEffect(() => {
    if (phase !== 'awaiting_operator' && !countdown?.active) setHovered(null);
  }, [phase, countdown?.active]);

  // Once every outage has ended, confirm the recovery for a few seconds, then go back to calm.
  const [planBy, setPlanBy] = useState<string | null>(null);
  const [restored, setRestored] = useState<{ homes: number | null; key: number } | null>(null);
  const appliedHomes = useRef(new Map<string, number>());
  const prevActive = useRef(0);
  useEffect(() => {
    if (applied) appliedHomes.current.set(applied.option_id, applied.metrics.households_reconnected);
  }, [applied]);
  useEffect(() => {
    const n = state.active_incidents.length;
    if (n > 0 && prevActive.current === 0) { appliedHomes.current.clear(); setPlanBy(null); }
    if (n > 0) setRestored(null);
    if (n === 0 && prevActive.current > 0) setRestored({ homes: appliedHomes.current.size ? [...appliedHomes.current.values()].reduce((a, b) => a + b, 0) : null, key: Date.now() });
    prevActive.current = n;
  }, [state.active_incidents.length]);
  useEffect(() => {
    if (!restored) return;
    const id = window.setTimeout(() => setRestored(null), 9000);
    return () => window.clearTimeout(id);
  }, [restored]);

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
        <p>Connecting to the grid…</p>
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

  // Incident lifecycle, read straight from the store: grid state, agent phase, options, countdown.
  const incidentOn = state.active_incidents.length > 0;
  const showBanner = incidentOn || !!restored;
  const incidentId = state.last_incident?.incident_id;
  let stepIdx = 0;
  if (restored) stepIdx = STEPS.length;
  else if (phase === 'executing' || phase === 'resolved') stepIdx = phase === 'executing' ? 4 : 5;
  else if (phase === 'awaiting_operator' || countdown?.active) stepIdx = 3;
  else if (phase === 'analyzing') stepIdx = state.tool_calls.some((c) => c.incident_id === incidentId) ? 2 : 1;
  else if (state.grid_state === 'recuperacion') stepIdx = 5;
  const attack: Attack | undefined = attacks[0] ?? (incidentOn ? (() => {
    const d = state.active_incidents[state.active_incidents.length - 1];
    return { ...describeFault(d, catalog), at: d.from_hour, homes: off, mw: deficit, key: d.event_id };
  })() : undefined);
  const planned = stepIdx >= 4 && !restored;
  const bannerHomes = planned ? off : attack?.homes ?? off;
  const bannerMw = planned ? deficit : attack?.mw ?? deficit;

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
    <div className={`gp iso is-${state.grid_state}${deciding ? ' has-options' : ''}${showBanner ? ' has-incident' : ''}`} data-theme="light">
      <header className="gp-top">
        <div className="gp-brand">
          <AndesMark size={26} />
          <span className="gp-logo">Andes</span>
          <span className="gp-sub">Coordinator · Chile SEN · digital twin</span>
        </div>
        <div className={`gp-state is-${state.grid_state}`}>{STATE_LABEL[state.grid_state] ?? state.grid_state}</div>
        <div className="gp-clock">
          <b>{clock(hour)}<small className="gp-tz">Chile time</small></b>
          {catalog.day_profile?.label_es && <span className="gp-dayprofile">{catalog.day_profile.label_es}</span>}
          <div className="gp-day"><i style={{ width: `${(hour / 24) * 100}%` }} /></div>
        </div>
        <div className="gp-kpis">
          <Kpi label="Homes without power" value={fmt(off)} hot={off > 1} dup />
          <Kpi label="Shortfall" value={`${fmt(deficit)} MW`} hot={deficit > 1} dup />
          <Kpi label="Demand" value={`${fmt(demand)} MW`} />
          <Kpi label="Cost" value={`US$ ${fmt(cost / 1000, 1)}k/h`} />
          <Kpi label="CO₂" value={`${fmt(co2)} t/h`} />
        </div>
        <div className={`gp-conn is-${connectionMode}`} title={connectionMode === 'offline' ? 'No backend: replaying a recorded session from the real solver' : ''}>
          {connectionMode === 'live' ? '● Live' : connectionMode === 'offline' ? '● Recorded session' : '○ Connecting'}
        </div>
      </header>

      {showBanner && attack && (
        <section key={restored ? `r-${restored.key}` : attack.key} className={`gp-incident ${restored ? 'is-restored' : bannerHomes > 0 || bannerMw > 0 ? (planned ? 'is-recovering' : 'is-attack') : 'is-absorbed'}`} aria-live="polite">
          <div className="gp-inc-main">
            <span className="gp-inc-badge">{restored ? 'Restored' : planned ? 'Recovering' : attack.jury ? 'Jury attack' : 'Outage'}</span>
            <div className="gp-inc-text">
              <h2>{restored ? (restored.homes != null ? `Restored: ${fmt(restored.homes)} homes reconnected` : 'Restored: the grid is back to normal') : attack.headline}</h2>
              <p>
                {restored ? `${attack.headline} · cleared` : `${clock(attack.at)} Chile time`}
                {!restored && planBy && planned && ` · ${planBy}`}
                {!restored && state.active_incidents.length > 1 && ` · ${state.active_incidents.length} outages active`}
              </p>
            </div>
          </div>
          {!restored && (
            <div className="gp-inc-nums">
              {bannerHomes > 0 || bannerMw > 0 ? (
                <>
                  <div><b>{fmt(bannerHomes)}</b><span>homes without power · {planned ? 'now' : 'at worst'}</span></div>
                  <div><b>{fmt(bannerMw)} MW</b><span>shortfall · {planned ? 'now' : 'at worst'}</span></div>
                </>
              ) : (
                <div className="is-ok"><b>Absorbed</b><span>nobody lost power</span></div>
              )}
            </div>
          )}
          <ol className="gp-steps">
            {STEPS.map((label, i) => (
              <li key={label} className={i < stepIdx ? 'is-done' : i === stepIdx ? 'is-now' : ''}>
                <i>{i < stepIdx ? '✓' : i + 1}</i>{i === STEPS.length - 1 && stepIdx >= STEPS.length ? 'Restored' : label}
              </li>
            ))}
          </ol>
        </section>
      )}

      <GridScene
        catalog={catalog}
        solution={shown}
        hour={hour}
        incidents={state.active_incidents}
        boosted={boosted}
        phase={phase}
        focus={focus}
        selected={selected}
        onSelect={setSelected}
      />

      <div className="gp-legend">
        <b>Generation</b>
        {['solar', 'wind', 'hydro', 'gas', 'coal', 'diesel', 'battery'].map((t) => (
          <div key={t}><i className="sw" style={{ background: TECH_COLOR[t] }} />{TECH_LABEL[t]}</div>
        ))}
        <b>Transmission</b>
        <div><i className="ln" style={{ borderColor: 'var(--blue)' }} />Normal</div>
        <div><i className="ln" style={{ borderColor: 'var(--amber)' }} />Saturated ≥95 %</div>
        <div><i className="ln is-cut" style={{ borderColor: 'var(--red)' }} />Cut</div>
        <b>Homes</b>
        <div><i className="win" />Powered</div>
        <div><i className="win is-dark" />Without power</div>
        <small className="gp-legend-note">1 house = 200,000 homes</small>
      </div>

      {hovered && <div className="gp-preview-banner">Preview · how the grid would look with “{hovered.title_es}”</div>}

      <aside className="gp-brain">
        <div className="gp-brain-head">
          <span className={`gp-brain-dot is-${phase}`} />
          <div>
            <b>Gemini</b>
            <span>{phase === 'analyzing' ? 'Analysing the outage' : phase === 'awaiting_operator' ? 'Proposing two options' : phase === 'executing' ? 'Running the plan' : phase === 'resolved' ? 'Plan applied' : 'Watching the grid'}</span>
          </div>
        </div>
        <ZoneStatus catalog={catalog} solution={shown} hour={step} incidents={state.active_incidents} />
        {options && (phase === 'awaiting_operator' || countdown?.active) && (
          <section className="gp-options gp-options-panel">
            <div className="gp-options-head">
              <b>Choose a recovery plan</b>
              <span>{countdown?.active ? `Autonomous mode: Gemini applies its pick in ${countdown.seconds_left} s` : <><span className="gp-only-pointer">Hover a plan to preview the grid, then apply it.</span><span className="gp-only-touch">Pick a plan and tap “Apply”.</span></>}</span>
              {state.model_execution && <ModelBadge m={state.model_execution} />}
            </div>
            <div className="gp-options-row">
              {options.map((o, n) => {
                const rec = countdown?.candidate_id === o.option_id;
                const cd = o.metrics.cost_delta_usd;
                return (
                  <article
                    key={o.option_id}
                    className={`gp-option${rec ? ' is-rec' : ''}`}
                    onMouseEnter={() => setHovered(o)}
                    onMouseLeave={() => setHovered(null)}
                  >
                    <div className="gp-option-tags">
                      <span className="gp-tag is-trade">{n === 0 ? 'A' : 'B'} · {TAG_LABEL[o.tradeoff_tag] ?? o.tradeoff_tag}</span>
                      {rec && <span className="gp-tag is-rec">Recommended by Gemini</span>}
                    </div>
                    <h3>{o.title_es}</h3>
                    <p title={o.rationale_es}>{o.rationale_es}</p>
                    <ul className="gp-levers">
                      {o.levers.map((l, i) => (
                        <li key={i}>{LEVER_LABEL[l.type] ?? l.type} · <span>{leverTarget(l.target_id, assets, catalog.lines)}</span></li>
                      ))}
                    </ul>
                    <div className="gp-option-key">
                      <div className="is-good"><b>+{fmt(o.metrics.households_reconnected)}</b><span>homes reconnected</span></div>
                      <div><b>{cd >= 0 ? '+' : '−'}US$ {fmt(Math.abs(cd) / 1000)}k</b><span>cost (assumed)</span></div>
                      <div className={o.validation.passed ? 'is-good' : 'is-bad'}><b>{o.validation.passed ? '✓' : '✗'}</b><span>{o.validation.passed ? 'validated' : 'failed validation'}</span></div>
                    </div>
                    <small className="gp-option-more">
                      {o.metrics.households_newly_off > 0 ? <em className="is-bad">−{fmt(o.metrics.households_newly_off)} homes lose power</em> : 'No new homes lose power'}
                      {' · '}CO₂ {o.metrics.co2_delta_t >= 0 ? '+' : '−'}{fmt(Math.abs(o.metrics.co2_delta_t))} t
                      {' · '}<span className={o.metrics.max_line_loading_pct >= 98 ? 'is-warn' : ''}>line load {fmt(o.metrics.max_line_loading_pct)} %</span>
                    </small>
                    <div className="gp-option-actions">
                      {rec && countdown?.active ? (
                        <>
                          <div className="gp-count" style={{ ['--p' as string]: `${(countdown.seconds_left / 5) * 100}%` }}><span>{countdown.seconds_left}</span></div>
                          <button className="gp-btn is-ghost" onClick={() => decide(o, 'veto')}>Veto</button>
                        </>
                      ) : (
                        <button className="gp-btn" onClick={() => decide(o, 'apply')}>Apply</button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        )}
        <div className={`gp-brain-feed${deciding ? ' is-compact' : ''}`}>
          {state.thoughts.length === 0 && state.notes.length === 0 && (
            <p className="gp-idle">All quiet. Watching {catalog.generators.length} plants, {catalog.batteries.length} batteries, {catalog.lines.length} trunk lines and {catalog.nodes.length} zones, hour by hour.</p>
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
                  <b>{c.status === 'pass' ? 'PASS' : c.status === 'fail' ? 'FAIL' : c.status === 'infeasible' ? 'INFEASIBLE' : '…'}</b>
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className="gp-brain-foot">Gemini reasons and proposes. Every number is computed by the HiGHS solver and checked by an independent validator.</p>
      </aside>



      {(sel || selLine) && (
        <div className="gp-sheet" onClick={(e) => e.stopPropagation()}>
          <button className="gp-sheet-x" onClick={() => setSelected(null)} aria-label="Close">×</button>
          {sel && (
            <>
              <small>{sel.kind === 'battery' ? 'Battery' : 'Plant'} in the model · {ZONES[sel.nodeId]?.label}</small>
              <h3>{assetTitle(sel)}</h3>
              <Spark series={sel.kind === 'battery' ? shown.battery_flow_mw[sel.id] : shown.generation_mw[sel.id]} cap={sel.capacity} hour={hour} />
              <dl>
                <div><dt>Now</dt><dd>{fmt(Math.abs(sel.kind === 'battery' ? at(shown.battery_flow_mw[sel.id], hour) : at(shown.generation_mw[sel.id], hour)))} MW</dd></div>
                <div><dt>Capacity</dt><dd>{fmt(sel.capacity)} MW</dd></div>
              </dl>
              <p className="gp-prov">Aggregate asset of the 5-zone scenario (synthetic, Chile-shaped). Stands for the real plants of this technology in the zone.</p>
              <button className="gp-btn is-danger" onClick={() => { actions.injectEvent({ asset_id: sel.id, duration_h: 4, source: 'operator' }); setSelected(null); }}>Trigger a sudden outage (4 h)</button>
            </>
          )}
          {selLine && (
            <>
              <small>Trunk line · {ZONES[selLine.from]?.label} → {ZONES[selLine.to]?.label}</small>
              <h3>Line {selLine.id}</h3>
              <Spark series={shown.line_flow_mw[selLine.id]} cap={selLine.capacity_mw} hour={hour} />
              <dl>
                <div><dt>Flow now</dt><dd>{fmt(Math.abs(at(shown.line_flow_mw[selLine.id], hour)))} MW</dd></div>
                <div><dt>Capacity</dt><dd>{fmt(at(shown.line_capacity_mw[selLine.id], hour) || selLine.capacity_mw)} MW</dd></div>
              </dl>
              <button className="gp-btn is-danger" onClick={() => { actions.injectEvent({ asset_id: selLine.id, duration_h: 4, source: 'operator' }); setSelected(null); }}>Cut line (4 h)</button>
            </>
          )}
        </div>
      )}

      {invite && (
        <div className="gp-invite" onClick={() => setInvite(false)}>
          <div className="gp-invite-card" onClick={(e) => e.stopPropagation()}>
            <small>Jury · scan with your phone</small>
            <h2>Try to knock out the grid</h2>
            {connectionMode === 'live' && state.sessionId ? (
              <>
                <img src={`${API_BASE}/live/sessions/${encodeURIComponent(state.sessionId)}/qr.svg`} alt="QR code for the jury page" />
                <code>{`${window.location.origin}/jurado?s=${state.sessionId}`}</code>
              </>
            ) : (
              <p>The jury needs the live backend. A recorded session is playing right now.</p>
            )}
            <button className="gp-btn" onClick={() => setInvite(false)}>Done</button>
          </div>
        </div>
      )}

      <footer className="gp-controls">
        <button className="gp-btn is-ghost" onClick={() => actions.setClock({ action: state.clock.running ? 'pause' : 'play' })}>{state.clock.running ? 'Pause' : 'Resume'}</button>
        <label className={`gp-switch${state.clock.autonomy_mode ? ' is-on' : ''}${connectionMode !== 'live' ? ' is-disabled' : ''}`}>
          <input type="checkbox" checked={state.clock.autonomy_mode} disabled={connectionMode !== 'live'} onChange={(e) => setAutonomy(e.target.checked)} />
          <span /> Autonomous mode
        </label>
        {connectionMode === 'offline' && <button className="gp-btn is-ghost" onClick={() => actions.replayOfflineDemo()}>Replay session</button>}
        <button className="gp-btn is-ghost" onClick={() => setInvite(true)}>Invite the jury</button>
        <span className="gp-hint">Tap a plant or a line for details or to trigger an outage.</span>
      </footer>
    </div>
  );
}

function leverTarget(id: string, assets: ReturnType<typeof buildAssets>, lines: { id: string }[]) {
  const a = assets.find((x) => x.id === id);
  if (a) return assetTitle(a);
  if (ZONES[id]) return ZONES[id].label;
  if (lines.find((l) => l.id === id)) return `Line ${id}`;
  return id;
}

// `dup` KPIs repeat the incident banner's numbers, so they hide while the banner is up.
function Kpi({ label, value, hot, dup }: { label: string; value: string; hot?: boolean; dup?: boolean }) {
  return (
    <div className={`gp-kpi${hot ? ' is-hot' : ''}${dup ? ' is-dup' : ''}`}>
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
const SEVERITY_LABEL = { info: 'Normal', watch: 'Watch', alert: 'Alert' } as const;

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
  if (m.reserve_margin_pct != null) stats.push({ k: 'Reserve', v: `${fmt(m.reserve_margin_pct, 1)} %`, hot: m.reserve_margin_pct < 10 });
  if (m.max_line_loading_pct != null) stats.push({ k: lineName ? `Line ${lineName}` : 'Busiest line', v: `${fmt(m.max_line_loading_pct, 0)} %`, hot: m.max_line_loading_pct >= 90 });
  if ((m.unserved_mw ?? 0) > 0) stats.push({ k: 'Unserved', v: `${fmt(m.unserved_mw!, 0)} MW`, hot: true });
  else if (m.curtailment_mw != null) stats.push({ k: 'Curtailment', v: `${fmt(m.curtailment_mw, 0)} MW` });
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
  const label = deterministic ? 'No model · deterministic text'
    : status === 'timeout' ? `${m.model} did not answer in time`
    : status === 'error' ? `${m.model} error`
    : status === 'no_key' ? 'No model · no key'
    : `${m.model} · ${(m.latency_ms / 1000).toLocaleString('en-GB', { maximumFractionDigits: 1 })} s${m.cached ? ' · cached answer' : ''}`;
  return <em className={`gp-model gp-jimmy-model${deterministic || status !== 'ok' ? ' is-warn' : ''}`}>{label}</em>;
}

// Who actually answered. A deterministic fallback or a cached answer must never pass for a live call.
function ModelBadge({ m }: { m: NonNullable<ReturnType<typeof useLiveSession>['state']['model_execution']> }) {
  const deterministic = (m.response_id ?? '').startsWith('det-');
  const label = m.status === 'timeout' ? `${m.model} did not answer in time · solver ranking`
    : m.status === 'error' ? `${m.model} error · solver ranking`
    : deterministic ? 'Deterministic planner · no Gemini call'
    : `${m.model} · ${(m.latency_ms / 1000).toLocaleString('en-GB', { maximumFractionDigits: 1 })} s${m.cached ? ' · cached answer' : ''}`;
  return <em className={`gp-model${deterministic || m.status !== 'ok' ? ' is-warn' : ''}`}>{label}</em>;
}
