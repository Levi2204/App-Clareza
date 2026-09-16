import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { isTauri, invoke } from '@tauri-apps/api/core';
import Desktop from './Desktop';
import { api } from './api';
import { confirmAction } from './confirm';

vi.mock('@tauri-apps/api/core', () => ({ isTauri: vi.fn(), invoke: vi.fn() }));
beforeEach(() => { vi.resetAllMocks(); isTauri.mockReturnValue(true); });
afterEach(cleanup);

describe('Desktop', () => {
  it('aguarda o serviço antes de abrir as finanças', async () => {
    invoke.mockResolvedValue({ state: 'ready', message: 'Pronto' });
    render(<Desktop><h1>Minhas finanças</h1></Desktop>);
    expect(await screen.findByText('Minhas finanças')).toBeInTheDocument();
  });
  it('explica uma falha de inicialização', async () => {
    invoke.mockResolvedValue({ state: 'error', message: 'Banco local indisponível.' });
    render(<Desktop><h1>Minhas finanças</h1></Desktop>);
    expect(await screen.findByText('Banco local indisponível.')).toBeInTheDocument();
    expect(screen.queryByText('Minhas finanças')).not.toBeInTheDocument();
  });
  it('usa IPC com o mesmo contrato de dados e erros da API', async () => {
    invoke.mockResolvedValueOnce({ status: 200, body: { assets: '350.00' } });
    expect(await api('dashboard/')).toEqual({ assets: '350.00' });
    expect(invoke).toHaveBeenCalledWith('api_request', { path: 'dashboard/', method: 'GET', body: null });
    invoke.mockResolvedValueOnce({ status: 400, body: { amount: ['Valor inválido.'] } });
    await expect(api('transactions/', { method: 'POST', body: '{}' })).rejects.toThrow('Valor inválido.');
    invoke.mockResolvedValueOnce({ status: 204, body: null });
    expect(await api('profile/', { method: 'DELETE', body: '{}' })).toBeNull();
  });
  it('mantém o cliente web funcionando', async () => {
    isTauri.mockReturnValue(false);
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    expect(await api('accounts/')).toEqual([]);
    expect(invoke).not.toHaveBeenCalled();
    fetch.mockRestore();
  });
  it('confirma e cancela usando diálogo compatível com WebKit', async () => {
    const user = userEvent.setup();
    HTMLDialogElement.prototype.close = function () { this.open = false; };
    const cancel = confirmAction('Cancelar assinatura?');
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(await cancel).toBe(false);
    const accept = confirmAction('Excluir movimentação?');
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    expect(await accept).toBe(true);
  });
});
