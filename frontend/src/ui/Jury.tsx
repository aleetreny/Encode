import React, { useEffect, useMemo, useReducer, useState } from 'react';
import * as client from '../live/client';
import { createInitialLiveState, liveReducer } from '../live/store';
import { Asset, assetTitle, at, buildAssets } from './GridScene';
import { P, ZONES, screen } from './layout';
import { Battery, CoalPlant, Diesel, GasPlant, Hydro, Solar, Wind } from './objects';
import * as k from '../iso/iso-kit';
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
  const cooldown = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));
  const full = state.active_incidents.length >= 2;

  const trip = async (assetId: string) => {
    if (cooldown > 0 || busy) return;
    setBusy(assetId);
    setMessage(null);
    try {
      const res = await client.postJuryCommand(sessionId, { asset_id: assetId, jury_name: name.trim() || undefined, device_id: deviceId() });
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
        <div>
          <b>GridPilot</b>
          <span>Sala en vivo · jurado</span>
        </div>
        <span className={`jr-state is-${state.grid_state}`}>{link === 'live' ? state.grid_state : link === 'down' ? 'sin conexión' : 'conectando'}</span>
      </header>

      <section className="jr-hero">
        <p>Intenta botar la red eléctrica de Chile. <b>Gemini 4 Argon</b> la está vigilando y tiene que proponer cómo recuperarla, en vivo, frente a todos.</p>
        <div className={`jr-counter${off > 1 ? ' is-hot' : ''}`}>
          <b>{Math.round(off).toLocaleString('es-CL')}</b>
          <span>hogares sin luz ahora</span>
        </div>
        <div className="jr-phase"><i className={`is-${state.agent_status.phase}`} />{PHASE[state.agent_status.phase] ?? ''}</div>
      </section>

      <label className="jr-name">
        <span>Tu nombre aparece en la pantalla grande</span>
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
          <Card key={a.id} title={assetTitle(a)} sub={`${Math.round(a.capacity)} MW · ${solution ? Math.round(at(solution.generation_mw[a.id], hour)) : 0} MW ahora`} down={out.has(a.id)} disabled={cooldown > 0 || full || link !== 'live' || out.has(a.id)} busy={busy === a.id} onTrip={() => trip(a.id)} action="Botar central">
            <Mini asset={a} down={out.has(a.id)} />
          </Card>
        ))}
      </div>
      <h2 className="jr-h">Líneas troncales</h2>
      <div className="jr-grid">
        {(catalog?.lines ?? []).filter((l) => l.disruptable).map((l) => (
          <Card key={l.id} title={`Línea ${l.id}`} sub={`${ZONES[l.from]?.label} → ${ZONES[l.to]?.label} · ${Math.round(l.capacity_mw)} MW`} down={out.has(l.id)} disabled={cooldown > 0 || full || link !== 'live' || out.has(l.id)} busy={busy === l.id} onTrip={() => trip(l.id)} action="Cortar línea">
            <svg viewBox="0 0 120 70" className="jr-mini"><path d="M8 52 Q60 30 112 18" className={out.has(l.id) ? 'jr-line is-down' : 'jr-line'} /><circle cx="8" cy="52" r="4" /><circle cx="112" cy="18" r="4" /></svg>
          </Card>
        ))}
      </div>
      <footer className="jr-foot">
        Sesión {sessionId} · Simulación con física real (solver HiGHS) sobre una red de Chile simplificada. Nada de esto afecta la red real.
      </footer>
    </div>
  );
}

function Card({ title, sub, down, disabled, busy, onTrip, action, children }: {
  title: string; sub: string; down: boolean; disabled: boolean; busy: boolean; onTrip: () => void; action: string; children: React.ReactNode;
}) {
  return (
    <article className={`jr-card${down ? ' is-down' : ''}`}>
      {children}
      <h3>{title}</h3>
      <p>{down ? 'Fuera de servicio' : sub}</p>
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
