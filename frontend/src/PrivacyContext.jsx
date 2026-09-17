import React, { createContext, useContext, useState } from 'react';
import { money } from './api';
import { Eye, EyeOff } from 'lucide-react';

const PrivacyContext = createContext({
  hidden: false,
  toggle: () => {},
  setHidden: () => {}
});

export function PrivacyProvider({ children }) {
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem('clareza-values-hidden') === 'true';
    } catch (e) {
      return false;
    }
  });

  const toggle = () => {
    setHidden(prev => {
      const next = !prev;
      try {
        localStorage.setItem('clareza-values-hidden', String(next));
      } catch (e) {}
      return next;
    });
  };

  return (
    <PrivacyContext.Provider value={{ hidden, toggle, setHidden }}>
      {children}
    </PrivacyContext.Provider>
  );
}

export function useValueVisibility() {
  return useContext(PrivacyContext);
}

export function MoneyValue({ value }) {
  const { hidden } = useValueVisibility();
  if (hidden) {
    return <span aria-label="Valor oculto" title="">••••</span>;
  }
  return <>{money(value)}</>;
}

export function PrivacyButton() {
  const { hidden, toggle } = useValueVisibility();
  return (
    <button className="icon-button privacy-button" aria-label={hidden ? "Mostrar valores" : "Ocultar valores"} onClick={toggle} title={hidden ? "Mostrar valores" : "Ocultar valores"}>
      {hidden ? <EyeOff size={19} /> : <Eye size={19} />}
    </button>
  );
}
