import React, { useEffect, useState } from 'react';
import type { useLiveSession } from '../live/store';
import type { Option } from '../live/types';

// Gemini's side panel tells one thing at a time, in plain words: how the grid is, what Gemini is
// doing, which plan to pick, or what the applied plan is restoring. Every number comes from the solver.

type LiveState = ReturnType<typeof useLiveSession>['state'];

const TAG_LABEL: Record<string, string> = {
  max_hogares: 'Most homes', min_costo: 'Lowest cost', min_co2: 'Lowest CO₂', min_riesgo_red: 'Lowest grid risk',
};
// What each lever does, in words anyone in the room understands.
const LEVER_PLAIN: Record<string, string> = {
  emergency_rating: 'Line capacity',
  demand_response: 'Flexible demand',
  activate_reserve_bess: 'Battery reserves',
  hydro_reserve_release: 'Hydro reserves',
  start_peaker: 'Backup diesel',
  add_battery: 'New battery',
  uprate_line: 'Line upgrade',
};

const fmt = (n: number) => Math.round(n).toLocaleString('en-GB');
const recipe = (o: Option) => [...new Set(o.levers.map((l) => LEVER_PLAIN[l.type] ?? l.type))].join(' + ');
const planName = (o: Option) => TAG_LABEL[o.tradeoff_tag] ?? o.title_es;

interface Props {
  state: LiveState;
  deciding: boolean;
  applied: Option | null;
  planBy: string | null;
  homesOff: number;
  onHover: (o: Option | null) => void;
  onDecide: (o: Option, decision: 'apply' | 'veto') => void;
}

export function GeminiPanel({ state, deciding, applied, planBy, homesOff, onHover, onDecide }: Props) {
  const phase = state.agent_status.phase;
  const status = deciding ? 'Two plans ready' : phase === 'analyzing' ? 'Looking for a fix' : phase === 'executing' || phase === 'resolved' ? 'Running the plan' : 'Watching the grid';

  let body: React.ReactNode;
  if (deciding && state.options) body = <Choose state={state} onHover={onHover} onDecide={onDecide} />;
  else if (phase === 'analyzing') body = <Thinking state={state} />;
  else if ((phase === 'executing' || phase === 'resolved') && state.active_incidents.length > 0) body = <Applied plan={applied} planBy={planBy} homesOff={homesOff} />;
  else body = <Calm state={state} homesOff={homesOff} />;

  return (
    <aside className={`gp-brain is-${deciding ? 'deciding' : phase}`}>
      <header className="gp-pnl-head">
        <span className={`gp-brain-dot is-${phase}`} />
        <b>Gemini</b>
        <span>{status}</span>
      </header>
      <div key={deciding ? 'choose' : phase} className="gp-pnl-body">{body}</div>
    </aside>
  );
}

function Choose({ state, onHover, onDecide }: { state: LiveState; onHover: Props['onHover']; onDecide: Props['onDecide'] }) {
  const { options, countdown, model_execution } = state;
  if (!options) return null;
  const pick = countdown?.candidate_id;
  return (
    <>
      <h2 className="gp-pnl-title">Choose a recovery plan</h2>
      <p className="gp-pnl-lead">
        {countdown?.active
          ? `Gemini applies its pick in ${countdown.seconds_left} s unless you veto it.`
          : <><span className="gp-only-pointer">Hover a plan to preview it on the map.</span><span className="gp-only-touch">Compare the two plans, then apply one.</span></>}
      </p>
      <div className="gp-plans">
        {options.map((o, n) => {
          const rec = pick === o.option_id;
          const m = o.metrics;
          return (
            <article
              key={o.option_id}
              className={`gp-plan${rec ? ' is-pick' : ''}`}
              onMouseEnter={() => onHover(o)}
              onMouseLeave={() => onHover(null)}
            >
              <small className="gp-plan-eyebrow">{rec ? 'Gemini’s pick' : pick ? 'Alternative' : `Plan ${n === 0 ? 'A' : 'B'}`}</small>
              <h3>{planName(o)}</h3>
              <p className="gp-plan-recipe">{recipe(o)}</p>
              {m.households_newly_off > 0 && <p className="gp-plan-warn">But {fmt(m.households_newly_off)} other homes lose power</p>}
              {!o.validation.passed && <p className="gp-plan-warn">✗ Failed the independent safety check</p>}
              <div className="gp-plan-foot">
                <p className="gp-plan-gain">Restore <b>{fmt(m.households_reconnected)}</b> homes</p>
                {rec && countdown?.active ? (
                  <div className="gp-plan-auto">
                    <div className="gp-count" style={{ ['--p' as string]: `${(countdown.seconds_left / 5) * 100}%` }}><span>{countdown.seconds_left}</span></div>
                    <button className="gp-btn is-ghost" onClick={() => onDecide(o, 'veto')}>Veto</button>
                  </div>
                ) : (
                  <button className="gp-btn gp-plan-apply" onClick={() => onDecide(o, 'apply')}>Apply plan →</button>
                )}
              </div>
            </article>
          );
        })}
      </div>
      <p className="gp-pnl-note">
        {model_execution && <><Who m={model_execution} /> · </>}
        Numbers computed by the solver and checked by an independent validator.
      </p>
    </>
  );
}

function Thinking({ state }: { state: LiveState }) {
  const incident = state.last_incident?.incident_id;
  const calls = state.tool_calls.filter((c) => !incident || c.incident_id === incident);
  const done = calls.filter((c) => c.status !== 'running');
  const passed = done.filter((c) => c.status === 'pass').length;
  const thought = state.thoughts[state.thoughts.length - 1];
  return (
    <>
      <h2 className="gp-pnl-title">Finding the best fix</h2>
      <p className="gp-pnl-lead">Gemini proposes recovery plans and the solver tests each one on the grid.</p>
      <div className="gp-tests">
        <div className="gp-tests-dots">
          {calls.slice(-8).map((c, i) => <i key={`${c.call_id}-${i}`} className={`is-${c.status}`} />)}
          {calls.length === 0 && <i className="is-running" />}
        </div>
        <span>{done.length === 0 ? 'Testing the first plan…' : `${done.length} ${done.length === 1 ? 'plan' : 'plans'} tested · ${passed} passed`}</span>
      </div>
      {thought && <Typed key={`${thought.ts_utc}`} className="gp-pnl-quote" text={thought.text_es} />}
    </>
  );
}

function Applied({ plan, planBy, homesOff }: { plan: Option | null; planBy: string | null; homesOff: number }) {
  return (
    <div className="gp-pnl-card is-good">
      <small className="gp-plan-eyebrow">Plan applied</small>
      <h3>{plan ? planName(plan) : 'Recovery plan running'}</h3>
      {plan && <p className="gp-plan-recipe">{recipe(plan)}</p>}
      {plan && <p className="gp-plan-gain">Restoring <b>{fmt(plan.metrics.households_reconnected)}</b> homes</p>}
      <p className="gp-pnl-note">
        {planBy ? `${planBy}. ` : ''}
        {homesOff > 1 ? `${fmt(homesOff)} homes still without power until the outage ends.` : 'Every home has power.'}
      </p>
    </div>
  );
}

const SEVERITY_LABEL = { info: 'Normal', watch: 'Watch', alert: 'Alert' } as const;

function Calm({ state, homesOff }: { state: LiveState; homesOff: number }) {
  const note = state.notes[state.notes.length - 1];
  const sev = note?.severity ?? 'info';
  const dark = homesOff > 1;
  return (
    <>
      <div className={`gp-pnl-status${dark ? ' is-bad' : ''}`}>
        <i>{dark ? '!' : '✓'}</i>
        <div>
          <h2>{dark ? `${fmt(homesOff)} homes without power` : 'All homes have power'}</h2>
          <p>{dark ? 'Gemini is getting ready to help.' : 'The grid is stable right now.'}</p>
        </div>
      </div>
      {note && (
        <div className="gp-pnl-reading">
          <small>
            Gemini’s reading
            {sev !== 'info' && <span className={`gp-sev is-${sev}`}>{SEVERITY_LABEL[sev]}</span>}
          </small>
          <p>{note.text_es}</p>
          <NoteSource m={note.model_execution} />
        </div>
      )}
    </>
  );
}

// Who actually answered. A deterministic fallback or a cached answer must never pass for a live call.
function Who({ m }: { m: NonNullable<LiveState['model_execution']> }) {
  const deterministic = (m.response_id ?? '').startsWith('det-');
  const label = m.status === 'timeout' ? `${m.model} did not answer in time · solver ranking`
    : m.status === 'error' ? `${m.model} error · solver ranking`
    : deterministic ? 'Deterministic planner · no Gemini call'
    : `Proposed by ${m.model} in ${(m.latency_ms / 1000).toLocaleString('en-GB', { maximumFractionDigits: 1 })} s${m.cached ? ' · cached answer' : ''}`;
  return <em className={deterministic || m.status !== 'ok' ? 'is-warn' : ''}>{label}</em>;
}

// The monitor's wording is deterministic unless the model really answered.
function NoteSource({ m }: { m?: LiveState['notes'][number]['model_execution'] }) {
  if (!m) return null;
  const deterministic = m.model === 'deterministic-monitor' || (m.response_id ?? '').startsWith('det-');
  const status = m.status as string;
  const label = deterministic ? 'Written without a model'
    : status === 'timeout' ? `${m.model} did not answer in time`
    : status === 'error' ? `${m.model} error`
    : status === 'no_key' ? 'No model · no key'
    : `${m.model}${m.cached ? ' · cached answer' : ''}`;
  return <em className={`gp-pnl-src${deterministic || status !== 'ok' ? ' is-warn' : ''}`}>{label}</em>;
}

// Text that types itself in, like the model is writing it right now.
function Typed({ text, className }: { text: string; className: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    const id = window.setInterval(() => setN((v) => (v >= text.length ? (window.clearInterval(id), v) : v + 2)), 18);
    return () => window.clearInterval(id);
  }, [text]);
  return (
    <p className={className}>
      {text.slice(0, n)}
      {n < text.length && <i className="gp-caret" />}
    </p>
  );
}
