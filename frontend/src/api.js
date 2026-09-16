import { isTauri, invoke } from '@tauri-apps/api/core';

export async function api(path, options = {}) {
  const response = isTauri() ? await desktopRequest(path, options) : await fetch(`/api/v1/${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({
    detail: 'Não foi possível interpretar a resposta do servidor.'
  }));
  if (!response.ok) throw new Error(Object.entries(data).map(([key, value]) => `${key === 'detail' || key === 'non_field_errors' ? '' : `${labels[key] || key}: `}${Array.isArray(value) ? value.join(' ') : value}`).join('\n'));
  return data;
}

async function desktopRequest(path, options) {
  try {
    const result = await invoke('api_request', {
      path, method: options.method || 'GET', body: options.body || null,
    });
    return { status: result.status, ok: result.status >= 200 && result.status < 300, json: async () => result.body };
  } catch (message) {
    throw new Error(String(message));
  }
}
const labels = {
  amount: 'Valor',
  account: 'Conta',
  card: 'Cartão',
  month: 'Competência',
  target_date: 'Prazo',
  date: 'Data',
  manual_amount: 'Total da fatura',
  name: 'Nome'
};
export const money = value => Number(value || 0).toLocaleString('pt-BR', {
  style: 'currency',
  currency: 'BRL'
});
export const dateLabel = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR') : '—';
export const today = () => new Date().toLocaleDateString('sv-SE');
