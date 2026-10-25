import { 
  Catalog, LiveEvent, ClockCommandRequest, DisruptCommandRequest, 
  JuryDisruptCommandRequest, DecideCommandRequest 
} from './types';
import demoStreamRaw from './fixtures/demo-stream.jsonl?raw';

function parseDemoStream(): LiveEvent[] {
  return demoStreamRaw
    .split('\n')
    .filter(line => line.trim().length > 0)
    .map(line => JSON.parse(line) as LiveEvent);
}

const offlineEvents = parseDemoStream();
const snapshotEvent = offlineEvents.find(e => e.type === 'session.snapshot') as Extract<LiveEvent, { type: 'session.snapshot' }>;

export const OFFLINE_CATALOG: Catalog = snapshotEvent.catalog;

export const LIBRARY_HOURS = [9, 12, 13, 18, 19, 20];

export class OfflineSessionController {
  private events: LiveEvent[] = offlineEvents;
  private onEvent: (ev: LiveEvent) => void;
  
  private clockInterval: number | null = null;
  private countdownInterval: number | null = null;
  private simHour = 12.0;
  private running = true;
  private speedSPerHour = 4.0;
  private currentSeq = 0; // sequence of events sent to the reducer (ticks included)
  private cursor = 0; // next recorded event to replay
  private holding = false; // paused at a recorded operator decision, waiting for a real click
  private skipApplied = false; // drop the recorded plan (and its solution) after a veto or a different choice
  private autonomy = false;
  private isVetoed = false;
  private lastOptions: Extract<LiveEvent, { type: 'options.ready' }> | null = null;
  private lastCountdownEmitMs = 0;

  constructor(onEvent: (ev: LiveEvent) => void) {
    this.onEvent = onEvent;
  }

  start() {
    const snapshot = this.events.find(e => e.type === 'session.snapshot') as Extract<LiveEvent, { type: 'session.snapshot' }>;
    if (snapshot) {
      this.simHour = snapshot.clock.hour;
      this.running = snapshot.clock.running;
      this.speedSPerHour = snapshot.clock.speed_s_per_hour;
      this.autonomy = snapshot.autonomy ?? false;
      this.holding = false;
      this.skipApplied = false;
      this.onEvent({ ...snapshot, catalog: OFFLINE_CATALOG });
      this.currentSeq = snapshot.seq;
      this.cursor = this.events.indexOf(snapshot) + 1;
    }
    
    this.startClock();
  }

  stop() {
    if (this.clockInterval) {
      clearInterval(this.clockInterval);
      this.clockInterval = null;
    }
    this.cancelCountdown();
  }

  getClosestLibraryHour(simHour: number): number {
    return LIBRARY_HOURS.reduce((prev, curr) =>
      Math.abs(curr - simHour) < Math.abs(prev - simHour) ? curr : prev
    );
  }

  setAutonomy(enabled: boolean) {
    this.autonomy = enabled;
    if (!enabled) {
      this.cancelCountdown();
    }
  }

  getAutonomy(): boolean {
    return this.autonomy;
  }

  private cancelCountdown() {
    if (this.countdownInterval !== null) {
      clearInterval(this.countdownInterval);
      this.countdownInterval = null;
    }
  }

  private startClock() {
    this.stop();
    const TICK_RATE_MS = 100;
    
    this.clockInterval = window.setInterval(() => {
      if (this.running) {
        const simHoursPerTick = (TICK_RATE_MS / 1000) / this.speedSPerHour;
        this.simHour = (this.simHour + simHoursPerTick) % 24;
      }
      this.emitPendingEvents();
    }, TICK_RATE_MS);
  }

  private emitPendingEvents() {
    // Replay recorded events in order once the clock reaches their hour. Each one gets a fresh
    // sequence number, so the clock ticks sent in between never make the reducer drop them.
    while (this.cursor < this.events.length && this.events[this.cursor].hour <= this.simHour) {
      const ev = this.events[this.cursor];
      if (ev.type === 'plan.applied' && ev.by === 'operator' && !this.skipApplied) {
        // The recording contains the operator's click; wait for the real one instead.
        this.holding = true;
        this.running = false;
        break;
      }
      if (ev.type === 'autonomy.countdown' && !this.skipApplied) {
        const now = Date.now();
        if (this.lastCountdownEmitMs > 0 && now - this.lastCountdownEmitMs < 950) {
          this.simHour = ev.hour;
          break;
        }
        this.lastCountdownEmitMs = ev.seconds_left === 0 ? 0 : now;
      }
      this.cursor++;
      if (ev.type === 'session.snapshot') continue;
      if (this.skipApplied && (ev.type === 'plan.applied' || ev.type === 'autonomy.countdown')) continue;
      if (this.skipApplied && ev.type === 'solution.updated' && ev.reason === 'plan_applied') {
        this.skipApplied = false;
        continue;
      }
      if (ev.type === 'options.ready') {
        this.lastOptions = ev;
        this.lastCountdownEmitMs = 0;
      }
      // A recorded answer is a replay: every model-worded event says so and never passes for a live call.
      const replayed = (ev.type === 'options.ready' || ev.type === 'agent.note') && ev.model_execution
        ? { ...ev, model_execution: { ...ev.model_execution, cached: true, cached_at_utc: ev.model_execution.cached_at_utc ?? ev.ts_utc } }
        : ev;
      this.onEvent({ ...replayed, seq: ++this.currentSeq } as LiveEvent);
    }

    // Always emit clock tick to keep UI interpolated smooth sync
    this.currentSeq++;
    this.onEvent({
      seq: this.currentSeq,
      session_id: 'offline',
      hour: this.simHour,
      ts_utc: new Date().toISOString(),
      type: 'clock.tick',
      running: this.running
    });
  }

  resetAndPlayDemo() {
    this.cancelCountdown();
    this.currentSeq = 0;
    this.cursor = 0;
    this.holding = false;
    this.skipApplied = false;
    this.lastCountdownEmitMs = 0;
    this.events = parseDemoStream();
    this.start();
  }

  async postClockCommand(sessionId: string, cmd: ClockCommandRequest): Promise<void> {
    if (cmd.action === 'play') this.running = true;
    if (cmd.action === 'pause') this.running = false;
    if (cmd.action === 'seek' && cmd.hour !== undefined) {
      this.simHour = cmd.hour;
    }
  }

  async postEventCommand(sessionId: string, cmd: DisruptCommandRequest): Promise<void> {
    await this.injectCrisis(cmd.asset_id);
  }

  async postJuryCommand(sessionId: string, cmd: JuryDisruptCommandRequest): Promise<Response> {
    await this.injectCrisis(cmd.asset_id, cmd.jury_name);
    return new Response(null, { status: 202 });
  }

  async postAutonomyCommand(sessionId: string, cmd: { autonomy: boolean }): Promise<void> {
    this.setAutonomy(cmd.autonomy);
  }

  async injectCrisis(assetId: string, juryName?: string): Promise<void> {
    const nearestHour = this.getClosestLibraryHour(this.simHour);
    try {
      const res = await fetch(`/incidents/${assetId}_${nearestHour}.jsonl`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      const lines = text.split('\n').filter(l => l.trim().length > 0);
      if (lines.length === 0) throw new Error('Empty incident library file');
      const libraryEvents = lines.map(l => JSON.parse(l) as LiveEvent);

      this.cancelCountdown();
      this.isVetoed = false;
      this.holding = false;

      // Replay incident events into onEvent up to options.ready
      for (const ev of libraryEvents) {
        if (ev.type === 'session.snapshot') continue;
        if (ev.type === 'plan.applied') continue;
        if (ev.type === 'solution.updated' && ev.reason === 'plan_applied') continue;

        this.currentSeq++;
        const stamped: LiveEvent = {
          ...ev,
          seq: this.currentSeq,
          session_id: 'offline',
          hour: this.simHour,
          ts_utc: new Date().toISOString(),
        };

        if (stamped.type === 'incident.detected' && juryName) {
          stamped.disruption = {
            ...stamped.disruption,
            source: 'jury',
            jury_name: juryName,
          };
        }

        if (stamped.type === 'options.ready') {
          stamped.model_execution = {
            ...stamped.model_execution,
            cached: true,
          };
          this.lastOptions = stamped;
        }

        this.onEvent(stamped);

        if (stamped.type === 'options.ready') {
          if (this.autonomy) {
            const recOpt = stamped.options.find(o => o.option_id === stamped.recommended_id) ?? stamped.options[0];
            if (recOpt && recOpt.metrics.households_reconnected > 0 && recOpt.metrics.unserved_mwh_avoided > 0) {
              this.startAutonomyCountdown(stamped.incident_id, stamped.recommended_id);
            } else {
              this.currentSeq++;
              this.onEvent({
                seq: this.currentSeq,
                session_id: 'offline',
                hour: this.simHour,
                ts_utc: new Date().toISOString(),
                type: 'agent.note',
                text_es: 'Modo autónomo en espera: ninguna maniobra operativa disponible reduce el déficit residencial actual, por lo que no se aplica ningún plan automáticamente.',
              });
            }
          } else {
            this.running = false;
          }
        }
      }
    } catch {
      this.cancelCountdown();
      this.currentSeq++;
      this.onEvent({
        seq: this.currentSeq,
        session_id: 'offline',
        hour: this.simHour,
        ts_utc: new Date().toISOString(),
        type: 'error',
        code: 'INCIDENT_NOT_FOUND',
        message_es: `No se encontró el archivo precalculado de contingencia para el activo ${assetId} en la biblioteca offline.`,
      });
    }
  }

  private startAutonomyCountdown(incidentId: string, optionId: string) {
    this.cancelCountdown();
    let secondsLeft = 5;

    this.countdownInterval = window.setInterval(() => {
      if (this.isVetoed || !this.autonomy) {
        this.cancelCountdown();
        return;
      }

      this.currentSeq++;
      this.onEvent({
        seq: this.currentSeq,
        session_id: 'offline',
        hour: this.simHour,
        ts_utc: new Date().toISOString(),
        type: 'autonomy.countdown',
        incident_id: incidentId,
        option_id: optionId,
        seconds_left: secondsLeft,
      });

      if (secondsLeft <= 0) {
        this.cancelCountdown();
        if (!this.isVetoed && this.autonomy) {
          this.postDecisionCommand('offline', {
            incident_id: incidentId,
            option_id: optionId,
            decision: 'apply',
          });
        }
      } else {
        secondsLeft--;
      }
    }, 1000);
  }

  async postDecisionCommand(sessionId: string, cmd: DecideCommandRequest): Promise<void> {
    this.cancelCountdown();
    const base = { session_id: 'offline', hour: this.simHour, ts_utc: new Date().toISOString() };
    const chosen =
      this.lastOptions?.options.find((o) => o.option_id === cmd.option_id) ??
      this.lastOptions?.options.find((o) => o.option_id === this.lastOptions?.recommended_id) ??
      this.lastOptions?.options[0];

    // Whatever the operator does, the recorded plan no longer applies.
    this.skipApplied = true;
    if (this.holding && this.events[this.cursor]?.type === 'plan.applied') this.cursor++;
    this.holding = false;
    this.running = true;

    if (cmd.decision === 'veto') {
      this.isVetoed = true;
      this.onEvent({ ...base, seq: ++this.currentSeq, type: 'plan.vetoed', incident_id: cmd.incident_id, option_id: cmd.option_id });
      return;
    }

    this.onEvent({
      ...base,
      seq: ++this.currentSeq,
      type: 'plan.applied',
      incident_id: cmd.incident_id,
      option_id: chosen?.option_id ?? cmd.option_id,
      by: this.autonomy ? 'gemini_autonomous' : 'operator'
    });

    if (chosen?.solution) {
      // Show the solution the solver computed for the option that was actually chosen.
      this.onEvent({
        ...base,
        seq: ++this.currentSeq,
        type: 'solution.updated',
        reason: 'plan_applied',
        solution: chosen.solution,
        grid_state: 'recuperacion',
      });
    }
  }
}
