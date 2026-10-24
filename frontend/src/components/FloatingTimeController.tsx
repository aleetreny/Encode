import React from 'react';
import { Play, Pause, Sun, Moon, AlertTriangle } from 'lucide-react';
import { OperationMode, TimeGranularity } from '../types/grid';
import { GlassContainer } from './GlassContainer';

interface FloatingTimeControllerProps {
  step96: number; // 0..95 (96 fifteen-minute intervals in 24h)
  onChangeStep96: (step: number) => void;
  isPlaying: boolean;
  onTogglePlay: () => void;
  granularity: TimeGranularity;
  onChangeGranularity: (g: TimeGranularity) => void;
  operationMode: OperationMode;
  chileTimeLabel: string;
}

export const FloatingTimeController: React.FC<FloatingTimeControllerProps> = ({
  step96,
  onChangeStep96,
  isPlaying,
  onTogglePlay,
  granularity,
  onChangeGranularity,
  operationMode,
  chileTimeLabel,
}) => {
  const hourIndex = Math.floor(step96 / 4);
  const isMiddayCongestion = hourIndex >= 9 && hourIndex <= 16;
  const isCrisisWindow = operationMode === 'sudden_outage' && hourIndex >= 18 && hourIndex <= 21;

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = Number(e.target.value);
    if (granularity === 'hourly') {
      onChangeStep96(Math.round(raw / 4) * 4);
    } else {
      onChangeStep96(raw);
    }
  };

  return (
    <div className="fixed bottom-3 left-[75px] z-30 w-[428px]">
      <GlassContainer className="px-3.5 py-2.5">
        {/* Top Row: Play/Pause, Date/Time in America/Santiago, Status Pill, 15-min/Hourly Selector */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onTogglePlay}
              className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500 text-neutral-950 shadow hover:bg-emerald-400 transition-colors"
              title={isPlaying ? 'Pause simulation' : 'Play 24h dispatch'}
            >
              {isPlaying ? (
                <Pause className="h-3.5 w-3.5 fill-current" />
              ) : (
                <Play className="h-3.5 w-3.5 fill-current ml-0.5" />
              )}
            </button>

            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="font-poppins text-xs font-semibold text-white tabular-nums">
                  Oct 1, 2026 · {chileTimeLabel}
                </span>
                {isCrisisWindow ? (
                  <span className="inline-flex items-center gap-0.5 rounded bg-red-500/25 px-1.5 py-0.5 text-[10px] font-semibold text-red-300 ring-1 ring-red-500/50">
                    <AlertTriangle className="h-2.5 w-2.5" />
                    OUTAGE HR {hourIndex}
                  </span>
                ) : isMiddayCongestion ? (
                  <span className="inline-flex items-center gap-0.5 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-300 ring-1 ring-amber-500/40">
                    ☀ L2 Peak
                  </span>
                ) : null}
              </div>
              <span className="text-[10px] text-neutral-400">
                America/Santiago (UTC-3) · {granularity === '15min' ? '15-min intervals' : 'Hourly steps'}
              </span>
            </div>
          </div>

          {/* Electricity Maps 15-min / Hourly Pill Toggle */}
          <div className="flex items-center rounded-lg bg-neutral-950/90 p-0.5 border border-neutral-800">
            <button
              type="button"
              onClick={() => onChangeGranularity('15min')}
              className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
                granularity === '15min'
                  ? 'bg-neutral-700 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              15 min
            </button>
            <button
              type="button"
              onClick={() => onChangeGranularity('hourly')}
              className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
                granularity === 'hourly'
                  ? 'bg-neutral-700 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              Hourly
            </button>
          </div>
        </div>

        {/* Electricity Maps Day/Night TimeSlider Track */}
        <div className="mt-2.5 relative">
          {/* Day/Night Background Bar with Congestion & Crisis Window Highlights */}
          <div className="relative h-5 w-full overflow-hidden rounded-lg border border-neutral-700/70 bg-neutral-950 flex items-center">
            {/* Night 00:00 - 07:00 (29.1%) */}
            <div
              className="h-full flex items-center justify-center bg-neutral-900/90"
              style={{ width: '29.1%' }}
            >
              <Moon className="h-3 w-3 text-neutral-500" />
            </div>
            {/* Daylight 07:00 - 18:00 (45.8%) */}
            <div
              className="h-full flex items-center justify-center bg-neutral-700/55 relative"
              style={{ width: '45.8%' }}
            >
              {/* Midday L2 Congestion Highlight (09:00..16:00) */}
              <div
                className="absolute inset-y-0 bg-amber-400/20 border-x border-amber-400/40"
                style={{ left: '18%', width: '64%' }}
                title="Hours 09:00–16:00: L2 Corridor Binding (400 MW) & Solar Curtailment Window"
              />
              <Sun className="h-3.5 w-3.5 text-[#FFC700] relative z-10" />
            </div>
            {/* Night 18:00 - 24:00 (25.1%) */}
            <div
              className="h-full flex items-center justify-center bg-neutral-900/90 relative"
              style={{ width: '25.1%' }}
            >
              {/* 18:00..21:00 Sudden Outage Highlight */}
              {operationMode === 'sudden_outage' && (
                <div
                  className="absolute inset-y-0 left-0 bg-red-500/35 border-x border-red-500/70"
                  style={{ width: '66%' }}
                  title="Hours 18:00–21:00: Sudden gas_centro 600 MW Outage Window"
                />
              )}
              <Moon className="h-3 w-3 text-neutral-500 relative z-10" />
            </div>
          </div>

          {/* Native Range Input Overlaid for Smooth Dragging */}
          <input
            type="range"
            min={0}
            max={95}
            step={granularity === '15min' ? 1 : 4}
            value={step96}
            onChange={handleSliderChange}
            aria-label="Simulation time slider"
            className="absolute inset-0 h-5 w-full cursor-pointer opacity-0 z-20"
          />

          {/* Custom Playhead Thumb Indicator */}
          <div
            className="pointer-events-none absolute top-0 bottom-0 z-10 flex items-center transition-all duration-75"
            style={{ left: `calc(${(step96 / 95) * 100}% - 6px)` }}
          >
            <div className="h-6 w-3 rounded-sm border-2 border-white bg-emerald-500 shadow-lg" />
          </div>
        </div>

        {/* Hour Tick Labels + Quick Jump Buttons */}
        <div className="mt-1.5 flex items-center justify-between text-[10px] font-mono text-neutral-400">
          <button
            type="button"
            onClick={() => onChangeStep96(0)}
            className="hover:text-white transition-colors"
          >
            00:00
          </button>
          <button
            type="button"
            onClick={() => onChangeStep96(6 * 4)}
            className="hover:text-white transition-colors"
          >
            06:00
          </button>
          <button
            type="button"
            onClick={() => onChangeStep96(12 * 4)}
            className={`px-1.5 py-0.2 rounded transition-colors ${
              hourIndex >= 9 && hourIndex <= 16
                ? 'bg-amber-500/20 text-amber-300 font-semibold'
                : 'hover:text-amber-300'
            }`}
            title="Jump to 12:00 CLST Solar Peak & L2 Bottleneck"
          >
            ☀ 12:00 Peak
          </button>
          <button
            type="button"
            onClick={() => {
              onChangeStep96(19 * 4);
            }}
            className={`px-1.5 py-0.2 rounded transition-colors ${
              hourIndex >= 18 && hourIndex <= 21
                ? 'bg-red-500/25 text-red-300 font-semibold'
                : 'hover:text-red-300'
            }`}
            title="Jump to 19:00 CLST Evening Peak / Crisis Window"
          >
            ⚡ 19:00 Crisis
          </button>
          <button
            type="button"
            onClick={() => onChangeStep96(23 * 4)}
            className="hover:text-white transition-colors"
          >
            23:00
          </button>
        </div>
      </GlassContainer>
    </div>
  );
};
