import React, { useEffect, useMemo, useReducer, useState } from 'react';
import * as client from '../live/client';
import { createInitialLiveState, liveReducer } from '../live/store';
import { Asset, TECH_COLOR, assetTitle, at, buildAssets } from './GridScene';
import { P, ZONES, screen } from './layout';
import { Battery, CoalPlant, Diesel, GasPlant, Hydro, Solar, Wind } from './objects';
import * as k from '../iso/iso-kit';
import { AndesMark } from './brand';
import './ui.css';
import './jury.css';

const COOLDOWN_S = 30;
const sessionFromUrl = () => new URLSearchParams(window.location.search).get('s') || new URLSearchParams(window.location.search).get('session') || 'demo';

function deviceId() {
  let id = localStorage.getItem('gp_jury_device');
  if (!id) {
    id = Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem('gp_jury_device', id);
  }
  return id;
}

const PHASE: Record<string, string> = {
  idle: 'Gemini vigila la red',
  analyzing: 'Gemini está analizando la falla…',
  awaiting_operator: 'Gemini propuso dos caminos al operador',
  executing: 'Se está aplicando un plan',
  resolved: 'Plan aplicado. La red se está recuperando',
};

export function Jury() {
  const sessionId = useMemo(sessionFromUrl, []);
  const [state, dispatch] = useReducer(liveReducer, createInitialLiveState(sessionId));
  const [link, setLink] = useState<'connecting' | 'live' | 'down'>('connecting');
  const [name, setName] = useState(() => localStorage.getItem('gp_jury_name') ?? '');
  const [busy, setBusy] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [cooldownUntil, setCooldownUntil] = useState(() => Number(localStorage.getItem('gp_jury_cooldown') || 0));
  const [now, setNow] = useState(Date.now());
  const [confirm, setConfirm] = useState<{ id: string; title: string; risk: number; unit: string } | null>(null);
  const named = name.trim().length >= 2;

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    let stop: (() => void) | null = null;
    client
      .fetchLiveCatalog()
      .then(() => {
        stop = client.connectLiveStream(sessionId, {
          onEvent: (ev) => dispatch(ev),
          onOpen: () => setLink('live'),
          onError: () => setLink((l) => (l === 'live' ? 'live' : 'down')),
        });
      })
      .catch(() => setLink('down'));
    return () => stop?.();
  }, [sessionId]);

  const catalog = state.catalog;
  const solution = state.solution;
  const hour = state.clock.sim_hour;
  const assets = useMemo(() => (catalog ? buildAssets(catalog).filter((a) => a.kind === 'generator') : []), [catalog]);
  const out = new Set(state.active_incidents.map((d) => d.asset_id));
  const off = solution ? Object.values(solution.households_off).reduce((s, v) => s + at(v, hour), 0) : 0;
  const deficit = solution ? Object.values(solution.unserved_mw).reduce((s, v) => s + at(v, hour), 0) : 0;
  const cooldown = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));
  const full = state.active_incidents.length >= 2;

  const trip = async (assetId: string) => {
    if (cooldown > 0 || busy || !named) return;
    setConfirm(null);
    setBusy(assetId);
    setMessage(null);
    try {
      const res = await client.postJuryCommand(sessionId, { asset_id: assetId, jury_name: name.trim(), device_id: deviceId() });
      if (res.ok) {
        const until = Date.now() + COOLDOWN_S * 1000;
        localStorage.setItem('gp_jury_cooldown', String(until));
        setCooldownUntil(until);
        setSent(assetId);
      } else {
        const body = await res.json().catch(() => ({}));
        setMessage(body.message_es || body.detail || 'La sala no aceptó la falla. Intenta de nuevo en unos segundos.');
      }
    } catch {
      setMessage('Sin conexión con la sala.');
    } finally {
      setBusy(null);
    }
  };

  const label = (id: string) => {
    const a = assets.find((x) => x.id === id);
    return a ? assetTitle(a) : `Línea ${id}`;
  };

  return (
    <div className="jr">
      <header className="jr-top">
        <div className="jr-brand">
          <AndesMark size={22} />
          <div>
            <b>Andes</b>
            <span>Sala en vivo · jurado</span>
          </div>
        </div>
        <span className={`jr-state is-${state.grid_state}`}>{link === 'live' ? state.grid_state : link === 'down' ? 'sin conexión' : 'conectando'}</span>
      </header>

      <section className="jr-hero">
        <p>Intenta botar la red eléctrica de Chile. <b>Gemini 4 Argon</b> la está vigilando y tiene que proponer cómo recuperarla, en vivo, frente a todos.</p>
        <div className="jr-kpis">
          <div className={off > 1 ? 'is-hot' : ''}><span>Sin luz</span><b>{Math.round(off).toLocaleString('es-CL')}</b></div>
          <div className={deficit > 1 ? 'is-hot' : ''}><span>Déficit</span><b>{Math.round(deficit)} MW</b></div>
          <div><span>Hora</span><b>{String(Math.floor(hour)).padStart(2, '0')}:{String(Math.floor((hour % 1) * 60)).padStart(2, '0')}</b></div>
        </div>
        {state.active_incidents.length > 0 && (
          <ul className="jr-live">
            {state.active_incidents.map((d) => (
              <li key={d.event_id}><b>{d.jury_name || (d.source === 'operator' ? 'Operador' : 'Jurado')}</b> {d.type === 'line_outage' ? 'cortó' : 'botó'} {label(d.asset_id)}</li>
            ))}
          </ul>
        )}
        <div className="jr-phase"><i className={`is-${state.agent_status.phase}`} />{PHASE[state.agent_status.phase] ?? ''}</div>
      </section>

      <label className={`jr-name${named ? '' : ' is-required'}`}>
        <span>{named ? 'Tu nombre aparecerá en la pantalla grande' : 'Escribe tu nombre para poder atacar · aparecerá en la pantalla grande'}</span>
        <input value={name} maxLength={24} placeholder="Ej.: Ana, jurado" onChange={(e) => { setName(e.target.value); localStorage.setItem('gp_jury_name', e.target.value); }} />
      </label>

      {link === 'down' && <p className="jr-msg is-bad">No hay conexión con la sala. Revisa que el QR sea el de la pantalla y que haya internet.</p>}
      {message && <p className="jr-msg is-bad">{message}</p>}
      {sent && cooldown > 0 && (
        <p className="jr-msg is-ok">
          <b>¡Listo! {label(sent)} cayó.</b> Mira la pantalla grande. Puedes volver a atacar en {cooldown} s.
        </p>
      )}
      {full && <p className="jr-msg">Ya hay dos fallas en curso. Espera a que Gemini resuelva una.</p>}

      <h2 className="jr-h">Centrales</h2>
      <div className="jr-grid">
        {assets.map((a) => (
          <Card key={a.id} title={assetTitle(a)} color={TECH_COLOR[a.technology]} risk={solution ? at(solution.generation_mw[a.id], hour) : 0} unit="MW que produce ahora" down={out.has(a.id)} disabled={cooldown > 0 || full || link !== 'live' || out.has(a.id) || !named} busy={busy === a.id} onTrip={() => setConfirm({ id: a.id, title: assetTitle(a), risk: solution ? at(solution.generation_mw[a.id], hour) : 0, unit: 'MW que produce ahora' })} action="Botar central">
            <Mini asset={a} down={out.has(a.id)} />
          </Card>
        ))}
      </div>
      <h2 className="jr-h">Líneas troncales</h2>
      <div className="jr-grid">
        {(catalog?.lines ?? []).filter((l) => l.disruptable).map((l) => (
          <Card key={l.id} title={`Línea ${l.id} · ${ZONES[l.from]?.short}→${ZONES[l.to]?.short}`} color="#3e63dd" risk={solution ? Math.abs(at(solution.line_flow_mw[l.id], hour)) : 0} unit="MW que transporta ahora" down={out.has(l.id)} disabled={cooldown > 0 || full || link !== 'live' || out.has(l.id) || !named} busy={busy === l.id} onTrip={() => setConfirm({ id: l.id, title: `Línea ${l.id} (${ZONES[l.from]?.label} → ${ZONES[l.to]?.label})`, risk: solution ? Math.abs(at(solution.line_flow_mw[l.id], hour)) : 0, unit: 'MW que transporta ahora' })} action="Cortar línea">
            <svg viewBox="0 0 120 70" className="jr-mini"><path d="M8 52 Q60 30 112 18" className={out.has(l.id) ? 'jr-line is-down' : 'jr-line'} /><circle cx="8" cy="52" r="4" /><circle cx="112" cy="18" r="4" /></svg>
          </Card>
        ))}
      </div>
      {confirm && (
        <div className="jr-sheet" onClick={() => setConfirm(null)}>
          <div className="jr-sheet-card" onClick={(e) => e.stopPropagation()}>
            <small>Vas a atacar como <b>{name.trim()}</b></small>
            <h3>{confirm.title}</h3>
            <div className="jr-impact"><b>{Math.round(confirm.risk).toLocaleString('es-CL')}</b><span>{confirm.unit} quedarían en riesgo</span></div>
            <p>Cuánto daño hace depende de cómo responda la red. El número exacto de hogares sin luz aparecerá en la pantalla grande, junto a tu nombre.</p>
            <button className="jr-btn" disabled={!!busy} onClick={() => trip(confirm.id)}>{busy ? 'Enviando…' : 'Confirmar ataque'}</button>
            <button className="jr-btn is-ghost" onClick={() => setConfirm(null)}>Cancelar</button>
          </div>
        </div>
      )}

      <footer className="jr-foot">
        Sesión {sessionId} · Simulación con física real (solver HiGHS) sobre una red de Chile simplificada. Nada de esto afecta la red real.
      </footer>
    </div>
  );
}

function Card({ title, color, risk, unit, down, disabled, busy, onTrip, action, children }: {
  title: string; color: string; risk: number; unit: string; down: boolean; disabled: boolean; busy: boolean; onTrip: () => void; action: string; children: React.ReactNode;
}) {
  return (
    <article className={`jr-card${down ? ' is-down' : ''}`} style={{ ['--c' as string]: color }}>
      {children}
      <h3>{title}</h3>
      {down ? <p className="jr-out">Fuera de servicio</p> : (
        <div className="jr-risk"><b>{Math.round(risk).toLocaleString('es-CL')}</b><span>{unit}</span></div>
      )}
      <button className="jr-btn" disabled={disabled} onClick={onTrip}>{busy ? 'Enviando…' : down ? 'Ya cayó' : action}</button>
    </article>
  );
}

// The same 3D object as on the big screen, framed on its own.
function Mini({ asset, down }: { asset: Asset; down: boolean }) {
  const [x, y] = screen(asset.at);
  const props = { at: asset.at, state: down ? ('tripped' as const) : ('ok' as const), level: 0.6 };
  const body =
    asset.technology === 'solar' ? <Solar {...props} />
    : asset.technology === 'wind' ? <Wind {...props} />
    : asset.technology === 'gas' ? <GasPlant {...props} />
    : asset.technology === 'coal' ? <CoalPlant {...props} />
    : asset.technology === 'hydro' ? <Hydro {...props} />
    : asset.technology === 'battery' ? <Battery {...props} />
    : <Diesel {...props} />;
  const top = k.iso([asset.at[0], asset.at[1], 60], P)[1];
  return (
    <svg viewBox={`${x - 48} ${top - 4} 96 ${y - top + 24}`} className="jr-mini iso" data-theme="light">
      {body}
    </svg>
  );
}
