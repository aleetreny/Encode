import React, { useEffect, useMemo, useRef, useState } from 'react';
import { LiveSessionProvider, useLiveSession } from '../live/store';
import type { Disruption, Option, Solution } from '../live/types';
import { GridScene, TECH_COLOR, TECH_LABEL, assetTitle, at, buildAssets } from './GridScene';
import { ZONES } from './layout';
import { AndesMark } from './brand';
import { GeminiPanel } from './GeminiPanel';
import { planName, recipe } from './plain';
import './ui.css';

const API_BASE = import.meta.env?.VITE_API_BASE_URL || '/api';

const STATE_LABEL: Record<string, string> = {
  normal: 'Normal', alerta: 'Alert', emergencia: 'Emergency', recuperacion: 'Recovery',
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

const STEPS = ['Outage', 'Gemini checks', 'Choose a plan', 'See the result'] as const;

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
  // The recorded session holds the clock at the decision, so Resume would do nothing there.
  const holding = deciding && !state.clock.running && connectionMode === 'offline';
  const assets = useMemo(() => (catalog ? buildAssets(catalog) : []), [catalog]);

  const boosted = useMemo(() => new Map((applied?.levers ?? []).map((l) => [l.target_id, l.type] as const)), [applied]);
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
  let stepIdx = 0;
  if (restored) stepIdx = STEPS.length;
  else if (phase === 'executing' || phase === 'resolved' || state.grid_state === 'recuperacion') stepIdx = 3;
  else if (phase === 'awaiting_operator' || countdown?.active) stepIdx = 2;
  else if (phase === 'analyzing') stepIdx = 1;
  const attack: Attack | undefined = attacks[0] ?? (incidentOn ? (() => {
    const d = state.active_incidents[state.active_incidents.length - 1];
    return { ...describeFault(d, catalog), at: d.from_hour, homes: off, mw: deficit, key: d.event_id };
  })() : undefined);
  const planned = stepIdx >= 3 && !restored;
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
      method: 'POST', headers: { 'Content-Type': 'application/json', ...NGROK_HEADERS }, body: JSON.stringify({ enabled }),
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

      {showBanner && attack && (() => {
        // One sentence for what is happening right now, coloured by stage.
        const hit = bannerHomes > 0 || bannerMw > 0;
        const tested = state.tool_calls.filter((c) => c.incident_id === state.last_incident?.incident_id && c.status !== 'running').length;
        const more = state.active_incidents.length > 1 ? ` · ${state.active_incidents.length} outages active` : '';
        let stage: string, chip: string, title: string, sub: string;
        if (restored) {
          stage = 'restored'; chip = '✓ Restored';
          title = 'Power restored';
          sub = `${restored.homes != null ? `${fmt(restored.homes)} homes reconnected · ` : ''}${attack.headline} · cleared`;
        } else if (planned) {
          stage = 'result'; chip = '⚡ Plan running';
          title = applied ? `Plan applied: ${planName(applied)}` : 'Recovery plan running';
          sub = [planBy, applied && recipe(applied), hit ? 'homes are coming back' : 'every home has power'].filter(Boolean).join(' · ') + more;
        } else if (stepIdx === 2) {
          stage = 'choose'; chip = '◆ Your decision';
          title = countdown?.active ? `Gemini applies its pick in ${countdown.seconds_left} s` : 'Choose how to restore power';
          sub = countdown?.active ? 'Veto it on the right if you disagree.' : 'Compare the two plans on the right, then apply one.';
        } else if (stepIdx === 1) {
          stage = 'checks'; chip = '◌ Gemini';
          title = 'Gemini is finding a fix';
          sub = `Testing recovery plans with the solver${tested ? ` · ${tested} tested so far` : '…'}${more}`;
        } else if (!hit) {
          stage = 'absorbed'; chip = '✓ Absorbed';
          title = attack.headline;
          sub = 'The grid absorbed it: nobody lost power.';
        } else {
          stage = 'outage'; chip = attack.jury ? '✕ Jury attack' : '✕ Outage';
          title = attack.headline;
          sub = `${fmt(attack.homes)} homes lost power at ${clock(attack.at)} Chile time${more}`;
        }
        return (
          <section key={restored ? `r-${restored.key}` : attack.key} className={`gp-incident is-${stage}`} aria-live="polite">
            <ol className="gp-steps">
              {STEPS.map((label, i) => (
                <li key={label} className={i < stepIdx ? 'is-done' : i === stepIdx ? 'is-now' : ''}>
                  <i>{i < stepIdx ? '✓' : i + 1}</i>{i === STEPS.length - 1 && stepIdx >= STEPS.length ? 'Restored' : label}
                </li>
              ))}
            </ol>
            <div key={stage + title} className="gp-inc-main">
              <span className="gp-inc-badge">{chip}</span>
              <div className="gp-inc-text">
                <h2>{title}</h2>
                <p>{sub}</p>
              </div>
            </div>
            {!restored && hit && (
              <div className="gp-inc-nums">
                <b>{fmt(bannerHomes)}</b>
                <span>homes without power · {planned ? 'now' : 'at worst'}</span>
                <small>{fmt(bannerMw)} MW short</small>
              </div>
            )}
          </section>
        );
      })()}

      <GridScene
        catalog={catalog}
        solution={shown}
        hour={hour}
        incidents={state.active_incidents}
        boosted={boosted}
        preview={!!hovered}
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

      <GeminiPanel
        state={state}
        deciding={deciding}
        applied={applied}
        planBy={planBy}
        homesOff={off}
        onHover={setHovered}
        onDecide={decide}
      />



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
                <JuryQr sessionId={state.sessionId} />
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
        <button
          className="gp-btn is-ghost gp-btn-clock"
          disabled={holding}
          title={holding ? 'The clock waits until you pick a plan' : undefined}
          onClick={() => actions.setClock({ action: state.clock.running ? 'pause' : 'play' })}
        >{holding ? 'Waiting for you' : state.clock.running ? 'Pause' : 'Resume'}</button>
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

// `dup` KPIs repeat the incident banner's numbers, so they hide while the banner is up.
function Kpi({ label, value, hot, dup }: { label: string; value: string; hot?: boolean; dup?: boolean }) {
  return (
    <div className={`gp-kpi${hot ? ' is-hot' : ''}${dup ? ' is-dup' : ''}`}>
      <span>{label}</span>
      <b key={value} className="gp-kpi-v">{value}</b>
    </div>
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

// ngrok's free tier answers a browser request without this header with an HTML warning page,
// so API calls made outside client.ts must send it too.
const NGROK_HEADERS: Record<string, string> = API_BASE.includes('ngrok') ? { 'ngrok-skip-browser-warning': '1' } : {};

// An <img> cannot send that header, so the QR is fetched and shown from memory.
function JuryQr({ sessionId }: { sessionId: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let alive = true;
    fetch(`${API_BASE}/live/sessions/${encodeURIComponent(sessionId)}/qr.svg`, { headers: NGROK_HEADERS })
      .then((r) => (r.ok ? r.blob() : Promise.reject(r.status)))
      .then((b) => { if (!alive) return; url = URL.createObjectURL(b); setSrc(url); })
      .catch(() => alive && setSrc(null));
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [sessionId]);
  return src ? <img src={src} alt="QR code for the jury page" /> : <div className="gp-qr-loading">Loading QR…</div>;
}
