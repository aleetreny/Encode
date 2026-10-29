import React, { useState, useEffect } from 'react';
import { ChileIsoMaquette } from './components/ChileIsoMaquette';
import { JuryPage } from './live/JuryPage';
import { DevConsole } from './live/DevConsole';
import { LiveOps } from './ui/LiveOps';
import { Jury } from './ui/Jury';
import { About } from './ui/About';
import { PORTFOLIO_MODE } from './portfolio';

export function App() {
  const [pathname, setPathname] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return window.location.pathname;
    }
    return '/';
  });

  useEffect(() => {
    const handlePopState = () => {
      setPathname(window.location.pathname);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const normalizedPath = pathname.replace(/\/+$/, '') || '/';

  if (normalizedPath === '/about' || (PORTFOLIO_MODE && normalizedPath !== '/')) return <About />;

  if (normalizedPath === '/jurado') {
    return <Jury />;
  }

  if (normalizedPath === '/jurado-dev') {
    return <JuryPage />;
  }

  if (normalizedPath === '/dev') {
    return <DevConsole />;
  }

  if (normalizedPath === '/explicar') {
    return (
      <main className="open-white-viewport">
        <ChileIsoMaquette />
      </main>
    );
  }

  return <LiveOps />;
}

export default App;
