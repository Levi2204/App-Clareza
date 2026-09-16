import React from 'react';
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProfilePage from './Profile';
import App from './App';
const profile = { display_name: 'Levi', email: 'levi@example.com', phone: '', bio: '', photo: '', theme: 'light', joined_at: '2026-09-15T12:00:00Z' };
const props = () => ({ profile, theme: 'light', onSaved: vi.fn(), onTheme: vi.fn(), onDeleted: vi.fn() });
beforeEach(() => { localStorage.clear(); history.replaceState({}, '', '/'); fetch = vi.fn(async () => ({ ok: true, json: async () => profile })); });
afterEach(cleanup);
describe('Perfil e aparência', () => {
  it('edita os dados e mantém o retorno do servidor', async () => {
    const user = userEvent.setup(); const p = props(); render(<ProfilePage {...p}/>);
    await user.clear(screen.getByLabelText('Nome de exibição')); await user.type(screen.getByLabelText('Nome de exibição'), 'Levi Silva');
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ display_name: 'Levi Silva', email: 'levi@example.com' });
    expect(p.onSaved).toHaveBeenCalledWith(profile);
  });
  it('permite escolher modo escuro', async () => {
    const user = userEvent.setup(); const p = props(); render(<ProfilePage {...p}/>);
    await user.click(screen.getByRole('button', { name: 'Modo escuro' })); expect(p.onTheme).toHaveBeenCalledWith('dark');
  });
  it('exige confirmação textual para excluir', async () => {
    const user = userEvent.setup(); const p = props(); render(<ProfilePage {...p}/>);
    await user.click(screen.getByRole('button', { name: 'Excluir minha conta' }));
    expect(screen.getByRole('button', { name: 'Excluir definitivamente' })).toBeDisabled();
    await user.type(screen.getByLabelText('Digite EXCLUIR para confirmar'), 'EXCLUIR');
    fetch.mockResolvedValueOnce({ status: 204, ok: true });
    await user.click(screen.getByRole('button', { name: 'Excluir definitivamente' }));
    expect(p.onDeleted).toHaveBeenCalled(); expect(fetch.mock.calls[0][1].method).toBe('DELETE');
  });
  it('permite remover a foto antes de salvar', async () => {
    const user = userEvent.setup(); render(<ProfilePage {...props()} profile={{ ...profile, photo: 'data:image/png;base64,example' }}/>);
    await user.click(screen.getByRole('button', { name: 'Remover foto' })); await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(JSON.parse(fetch.mock.calls[0][1].body).photo).toBe('');
  });
  it('mostra erro quando salvar falha', async () => {
    const user = userEvent.setup(); render(<ProfilePage {...props()}/>);
    fetch.mockResolvedValueOnce({ ok: false, json: async () => ({ email: ['E-mail inválido.'] }) });
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' })); expect(await screen.findByRole('alert')).toHaveTextContent('E-mail inválido.');
  });
  it('abre perfil pelo nome e persiste o tema na aplicação', async () => {
    const user = userEvent.setup(); const summary = { accounts: [], goals: [], payments: [], history: [], categories: [] };
    fetch.mockImplementation(async (url, options) => ({ ok: true, json: async () => url.includes('profile') ? options.method === 'PATCH' ? { ...profile, theme: 'dark' } : profile : url.includes('dashboard') ? summary : [] }));
    render(<App/>); await screen.findByRole('button', { name: 'Levi' });
    await user.click(screen.getByRole('button', { name: 'Levi' }));
    await user.click(await screen.findByRole('button', { name: 'Modo escuro' }));
    expect(document.documentElement.dataset.theme).toBe('dark'); expect(localStorage.getItem('clareza-theme')).toBe('dark');
  });
});
