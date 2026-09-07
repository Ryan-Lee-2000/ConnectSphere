import { useEffect, useState } from 'react';

export function App() {
  const [status, setStatus] = useState('Checking API and database...');
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/health', { signal: controller.signal })
      .then(async response => {
        if (!response.ok || (await response.json()).status !== 'ok') throw new Error('unavailable');
        setStatus('API and database connected.');
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('Connection unavailable. Check that local services are running.');
      });
    return () => controller.abort();
  }, []);
  return <main>
    <h1>ConnectSphere</h1>
    <p>Sprint 0 project foundation</p>
    <p role="status">{status}</p>
    <p>Product features will be delivered through team-approved stories.</p>
  </main>;
}
