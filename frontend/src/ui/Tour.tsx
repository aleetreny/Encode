import React, { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AndesMark } from './brand';
import './tour.css';

/**
 * Guided tour of the main screen: a spotlight on one part of the real UI and a caption that explains it.
 * It only explains; it never changes the session. → / Space / Enter next · ← back · Esc exit.
 * The app stays usable underneath (the overlay lets clicks through), so the presenter can act mid-tour.
 */
type Tag = 'SIMULATED' | 'SOLVER' | 'VALIDATED' | 'MODEL' | 'HUMAN';
interface Step {
  id: string;
  title: string;
  spot?: string;               // CSS selector to spotlight; missing or not on screen → plain dim
  kicker?: string;
  head: string;
  body: ReactNode;
  tags?: Tag[];
  slide?: boolean;             // full-screen card instead of a spotlight
}

const STEPS: Step[] = [
  {
    id: 'intro', title: 'Andes', slide: true,
    head: 'Andes',
    body: <>An AI copilot for Chile’s power grid. Gemini investigates and explains, deterministic code optimises and validates, and a human approves the plan, in simulation only.</>,
  },
  {
    id: 'twin', title: 'Digital twin', spot: '.gp-scene',
    kicker: 'The grid', head: 'Chile’s grid as a model you can read at a glance',
    body: <>Five zones from north to south, with their plants, batteries and trunk lines. Lit windows are homes with power, and dark ones are homes without it. Every flow on screen comes from the solver, hour by hour.</>,
    tags: ['SIMULATED', 'SOLVER'],
  },
  {
    id: 'legend', title: 'Legend', spot: '.gp-legend',
    kicker: 'How to read it', head: 'Colour is technology, line colour is stress',
    body: <>Each colour is a type of generation. Lines turn amber at 95 % of their capacity and red when they are cut. One house stands for 200,000 homes.</>,
  },
  {
    id: 'clock', title: 'Clock and state', spot: '.gp-clock',
    kicker: 'Simulated day', head: 'One day, in Chile time',
    body: <>The simulated clock runs through a full day, shown in Chile local time. The badge next to it is the grid state: Normal, Alert, Emergency or Recovery.</>,
    tags: ['SIMULATED'],
  },
  {
    id: 'kpis', title: 'Key numbers', spot: '.gp-kpis',
    kicker: 'Numbers from code', head: 'Homes, shortfall, demand, cost and CO₂',
    body: <>The HiGHS solver computes every figure here. Cost is an assumed-cost proxy, not a market price. Gemini never invents or calculates a number.</>,
    tags: ['SOLVER'],
  },
  {
    id: 'brain', title: 'Gemini', spot: '.gp-brain',
    kicker: 'The copilot', head: 'Gemini tells you one thing at a time',
    body: <>When the grid is calm, Gemini writes a short reading every simulated hour. When something breaks, it looks for a fix and the solver tests each idea on the grid. Then two plans appear here for you to choose from. The panel always says which model answered, or whether the text was written without one.</>,
    tags: ['MODEL'],
  },
  {
    id: 'break', title: 'Break something', spot: '.gp-scene',
    kicker: 'Try it', head: 'Tap a plant or a line to knock it out',
    body: <>Tap any plant, battery or trunk line to see its output and trigger a sudden four-hour outage. The jury can do the same from their phones.</>,
    tags: ['SIMULATED'],
  },
  {
    id: 'incident', title: 'Recovery', spot: '.gp-incident',
    kicker: 'When something fails', head: 'Six steps from the outage to recovery',
    body: <>A banner shows who caused the outage and how many homes lost power. Gemini proposes two plans in its panel. HiGHS solves each one and an independent validator checks it. Hover a plan to preview it on the map, then apply the one you prefer.</>,
    tags: ['SOLVER', 'VALIDATED', 'HUMAN'],
  },
  {
    id: 'controls', title: 'Controls', spot: '.gp-controls',
    kicker: 'You are in charge', head: 'Pause, autonomous mode and the jury',
    body: <>Pause or resume the clock. In autonomous mode Gemini applies its pick after a 5-second countdown, and you can still veto it. “Invite the jury” shows a QR code so anyone can attack the grid from their phone.</>,
    tags: ['HUMAN'],
  },
  {
    id: 'conn', title: 'Live or recorded', spot: '.gp-conn',
    kicker: 'Honest about the source', head: 'Live backend or recorded session',
    body: <>“Live” means the backend is running Gemini and the solver right now. “Recorded session” replays a real run of the same solver, so the demo still works offline. Approving or rejecting a plan only ever changes the simulation.</>,
  },
  {
    id: 'end', title: 'Your turn', slide: true,
    head: 'Your turn',
    body: <>Tap a plant, cut a line or invite the jury, and watch Gemini and the solver bring the grid back. You can reopen this tour from the “Tour” button.</>,
  },
];

const TAG_LABEL: Record<Tag, string> = {
  SIMULATED: 'Simulated', SOLVER: 'Computed by solver', VALIDATED: 'Independently validated', MODEL: 'Gemini', HUMAN: 'Human decides',
};

const PAD = 8;
const GAP = 18;
const MARGIN = 16;

// Put the caption beside the spotlight where it fits (right, left, below, above), else bottom centre.
function placeCard(r: DOMRect | null, cw: number, ch: number, barH: number) {
  const W = window.innerWidth, H = window.innerHeight - barH;
  const center = { left: (W - cw) / 2, top: Math.max(MARGIN, H - ch - MARGIN) };
  if (!r) return center;
  const clampY = (y: number) => Math.min(Math.max(MARGIN, y), H - ch - MARGIN);
  const clampX = (x: number) => Math.min(Math.max(MARGIN, x), W - cw - MARGIN);
  const tries = [
    { ok: r.right + PAD + GAP + cw <= W - MARGIN, left: r.right + PAD + GAP, top: clampY(r.top) },
    { ok: r.left - PAD - GAP - cw >= MARGIN, left: r.left - PAD - GAP - cw, top: clampY(r.top) },
    { ok: r.bottom + PAD + GAP + ch <= H - MARGIN, left: clampX(r.left), top: r.bottom + PAD + GAP },
    { ok: r.top - PAD - GAP - ch >= MARGIN, left: clampX(r.left), top: r.top - PAD - GAP - ch },
  ];
  // A spotlight that fills most of the screen (the scene): sit the caption inside, bottom-left.
  if (r.width * r.height > W * H * 0.45) return { left: Math.max(MARGIN, r.left + 24), top: clampY(r.bottom - ch - 24) };
  return tries.find((t) => t.ok) ?? center;
}

const visible = (el: Element | null): el is HTMLElement => {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
};

export function Tour({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const step = STEPS[i];
  const last = i === STEPS.length - 1;

  const go = useCallback((n: number) => setI(Math.max(0, Math.min(STEPS.length - 1, n))), []);
  const next = useCallback(() => (last ? onClose() : go(i + 1)), [last, i, go, onClose]);

  // On a phone the screen scrolls, so bring the target into view first.
  useEffect(() => {
    const el = step.spot ? document.querySelector(step.spot) : null;
    if (visible(el) && window.innerWidth <= 900) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [step.spot]);

  // Follow the target: panels resize and move while the session keeps running.
  useEffect(() => {
    const upd = () => {
      const el = step.spot ? document.querySelector(step.spot) : null;
      setRect(!step.slide && visible(el) ? el.getBoundingClientRect() : null);
    };
    upd();
    const t = window.setInterval(upd, 250);
    window.addEventListener('resize', upd);
    window.addEventListener('scroll', upd, true);
    return () => { window.clearInterval(t); window.removeEventListener('resize', upd); window.removeEventListener('scroll', upd, true); };
  }, [step.spot, step.slide]);

  useLayoutEffect(() => {
    const c = card.current;
    if (!c || step.slide) return;
    if (window.innerWidth <= 900) { setPos(null); return; }   // phone: docked above the bar by CSS
    setPos(placeCard(rect, c.offsetWidth, c.offsetHeight, (bar.current?.offsetHeight ?? 0) + 30));
  }, [rect, i, step.slide]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if ((tag === 'INPUT' || tag === 'TEXTAREA') && e.key !== 'Escape') return;
      const map: Record<string, () => void> = {
        ArrowRight: next, ' ': next, Enter: next, PageDown: next,
        ArrowLeft: () => go(i - 1), PageUp: () => go(i - 1), Escape: onClose,
      };
      if (map[e.key]) { e.preventDefault(); e.stopPropagation(); map[e.key](); }
    };
    window.addEventListener('keydown', k, true);
    return () => window.removeEventListener('keydown', k, true);
  }, [i, next, go, onClose]);

  return createPortal(
    <div className="at" data-step={step.id} role="dialog" aria-modal="false" aria-label="Guided tour">
      {step.slide ? (
        <div className="at-slide" key={step.id}>
          <div className="at-slide-in">
            <AndesMark size={64} />
            <h1>{step.head}</h1>
            <p>{step.body}</p>
            {i === 0 && <small>→ or Space next · ← back · Esc exit</small>}
          </div>
        </div>
      ) : (
        <>
          {rect
            ? <div className="at-spot" style={{ left: rect.left - PAD, top: rect.top - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }} />
            : <div className="at-dim" />}
          <div className="at-card" key={step.id} ref={card} style={pos ?? undefined} aria-live="polite">
            <div className="at-kicker"><span>{i}</span>{step.kicker}</div>
            <h2>{step.head}</h2>
            <p>{step.body}</p>
            {step.id === 'incident' && !rect && <p className="at-note">No outage right now. The banner appears at the top as soon as something fails.</p>}
            {step.tags && <div className="at-tags">{step.tags.map((t) => <span key={t} className={`at-tag is-${t.toLowerCase()}`}>{TAG_LABEL[t]}</span>)}</div>}
          </div>
        </>
      )}
      <div className="at-bar" ref={bar}>
        <button onClick={() => go(i - 1)} disabled={i === 0} title="Previous (←)" aria-label="Previous">‹</button>
        <button className="at-next" onClick={next} title={last ? 'Finish' : 'Next (→ / Space)'}>{last ? 'Start' : i === 0 ? 'Take the tour' : 'Next'} ›</button>
        <div className="at-meta">
          <div className="at-name"><span>{i + 1} / {STEPS.length}</span>{step.title}</div>
          <div className="at-dots">
            {STEPS.map((s, k) => <i key={s.id} className={k < i ? 'is-done' : k === i ? 'is-now' : ''} onClick={() => go(k)} title={s.title} />)}
          </div>
        </div>
        <button onClick={onClose} title="Exit (Esc)" aria-label="Exit tour">✕</button>
      </div>
    </div>,
    document.body,
  );
}
