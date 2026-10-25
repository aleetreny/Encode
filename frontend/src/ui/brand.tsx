import React from 'react';

// Andes: the ridge drawn as one continuous stroke, like a grid signal. The highest peak
// (Aconcagua) is a node in Gemini's gradient; the line below is the trunk that crosses Chile.
export function AndesMark({ size = 30, ink = '#18181b' }: { size?: number; ink?: string }) {
  const id = React.useId();
  return (
    <svg width={size * 1.36} height={size} viewBox="0 0 120 88" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" x2="1">
          <stop offset="0" stopColor="#4f8bff" />
          <stop offset=".55" stopColor="#9b72ff" />
          <stop offset="1" stopColor="#ff7ab6" />
        </linearGradient>
      </defs>
      <path d="M6 70 L30 40 L42 54 L64 16 L80 44 L90 34 L114 70" fill="none" stroke={ink} strokeWidth="9" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M6 84 L114 84" stroke={`url(#${id})`} strokeWidth="7" strokeLinecap="round" />
      <circle cx="64" cy="16" r="8" fill="#fff" stroke={`url(#${id})`} strokeWidth="6" />
    </svg>
  );
}
