/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        poppins: ['Poppins', 'sans-serif'],
        inter: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      colors: {
        em: {
          ocean: '#262626',
          land: '#3A4046',
          border: '#6D6D6D',
          solar: '#FFC700',
          wind: '#69D6F8',
          hydro: '#1878EA',
          battery: '#1DA484',
          gas: '#AAA189',
          coal: '#545454',
          diesel: '#584745',
          curtailment: '#EF4444',
          unserved: '#DC2626',
          green: '#2AA364',
          yellow: '#F5EB4D',
          orange: '#9E4229',
          brown: '#381D02',
        },
      },
      keyframes: {
        flowDash: {
          '0%': { strokeDashoffset: '24' },
          '100%': { strokeDashoffset: '0' },
        },
        flowDashReverse: {
          '0%': { strokeDashoffset: '-24' },
          '100%': { strokeDashoffset: '0' },
        },
      },
      animation: {
        flow: 'flowDash 1.2s linear infinite',
        'flow-fast': 'flowDash 0.6s linear infinite',
        'flow-reverse': 'flowDashReverse 1.2s linear infinite',
      },
    },
  },
  plugins: [],
};
