import React, { useEffect, useState } from 'react';
import { isTauri, invoke } from '@tauri-apps/api/core';
import { AlertCircle, LoaderCircle } from 'lucide-react';

export default function Desktop({ children }) {
  const [status, setStatus] = useState({ state: isTauri() ? 'starting' : 'ready', message: 'Preparando suas finanças…' });
  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    let timer;
    async function check() {
      try {
        const next = await invoke('runtime_status');
        if (cancelled) return;
        setStatus(next);
        if (next.state === 'starting') timer = setTimeout(check, 400);
      } catch {
        if (!cancelled) setStatus({ state: 'error', message: 'Não foi possível preparar o aplicativo. Feche e abra o Clareza novamente.' });
      }
    }
    check();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);
  if (status.state === 'ready') return children;
  return <div className="desktop-start" role="status">
    <img src="/clareza.svg" width="72" height="72" alt=""/>
    <h1>clareza<span>.</span></h1>
    {status.state === 'error' ? <AlertCircle size={24}/> : <LoaderCircle className="spin" size={24}/>}
    <h2>{status.state === 'error' ? 'Precisamos de um ajuste para abrir' : 'Seu espaço está quase pronto'}</h2>
    <p>{status.message}</p>
    {status.state === 'error' && <button className="button secondary" onClick={() => location.reload()}>Verificar novamente</button>}
    <small>Clareza para hoje. Tranquilidade para amanhã.</small>
  </div>;
}
