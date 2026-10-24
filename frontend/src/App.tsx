import React, { useState, useEffect } from 'react';
import { ChileIsoMaquette } from './components/ChileIsoMaquette';
import { JuryPage } from './live/JuryPage';
import { DevConsole } from './live/DevConsole';

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

  if (normalizedPath === '/jurado') {
    return <JuryPage />;
  }

  if (normalizedPath === '/dev') {
    return <DevConsole />;
  }

  // Routes '/' and '/explicar' render the isometric maquette
  return (
    <main className="open-white-viewport">
      <ChileIsoMaquette />
    </main>
  );
}

export default App;
