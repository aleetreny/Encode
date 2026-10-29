// Public builds are self-contained; opt in explicitly to the original backend.
export const PORTFOLIO_MODE = import.meta.env.VITE_PORTFOLIO_MODE !== 'false';
