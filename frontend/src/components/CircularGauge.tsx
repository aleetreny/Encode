import React from 'react';

interface CircularGaugeProps {
  percentage: number;
  label: string;
  sublabel?: string;
  color?: string;
  size?: number;
  strokeWidth?: number;
}

/**
 * Exact replica of Electricity Maps' CircularGauge.tsx
 * SVG circular progress ring with tabular-nums percentage inside
 */
export const CircularGauge: React.FC<CircularGaugeProps> = ({
  percentage,
  label,
  sublabel,
  color = '#2AA364',
  size = 56,
  strokeWidth = 5.5,
}) => {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(percentage) ? percentage : 0));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (clamped / 100) * circumference;

  return (
    <div className="flex items-center gap-2.5">
      <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90 transform">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="transparent"
            stroke="#383838"
            strokeWidth={strokeWidth}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="transparent"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            className="transition-all duration-300 ease-out"
          />
        </svg>
        <span className="absolute font-poppins text-xs font-semibold tabular-nums text-neutral-100">
          {Math.round(clamped)}%
        </span>
      </div>
      <div className="flex flex-col leading-tight">
        <span className="text-xs font-medium text-neutral-200">{label}</span>
        {sublabel && <span className="text-[11px] text-neutral-400">{sublabel}</span>}
      </div>
    </div>
  );
};

interface IntensitySquareProps {
  score: number;
  unit: string;
  label: string;
  bgColor: string;
}

/**
 * Exact replica of Electricity Maps' CO2Square / IntensitySquare
 */
export const IntensitySquare: React.FC<IntensitySquareProps> = ({
  score,
  unit,
  label,
  bgColor,
}) => {
  const isLightBg = bgColor === '#F5EB4D' || bgColor === '#87B953';
  const textColor = isLightBg ? 'text-neutral-950' : 'text-white';

  return (
    <div className="flex items-center gap-2.5">
      <div
        className={`flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-xl shadow-inner transition-colors duration-300 ${textColor}`}
        style={{ backgroundColor: bgColor }}
      >
        <span className="font-poppins text-base font-bold leading-none tabular-nums">
          {Math.round(score)}
        </span>
        <span className="mt-0.5 text-[9px] font-semibold opacity-90">{unit}</span>
      </div>
      <div className="flex flex-col leading-tight">
        <span className="text-xs font-medium text-neutral-200">{label}</span>
        <span className="text-[11px] text-neutral-400">Grid stress index</span>
      </div>
    </div>
  );
};
