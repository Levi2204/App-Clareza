import React from 'react';
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
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
  it('rejeita arquivo com mais de 5 MB antes do envio', async () => {
    const user = userEvent.setup(); render(<ProfilePage {...props()}/>);
    const bigFile = new File(['a'.repeat(100)], 'big.png', { type: 'image/png' });
    Object.defineProperty(bigFile, 'size', { value: 6 * 1024 * 1024 });
    const input = screen.getByLabelText('Foto de perfil');
    await user.upload(input, bigFile);
    expect(await screen.findByRole('alert')).toHaveTextContent('A foto deve ter no máximo 5 MB.');
  });
  it('rejeita tipo de arquivo não suportado', async () => {
    render(<ProfilePage {...props()}/>);
    const gifFile = new File(['gif'], 'anim.gif', { type: 'image/gif' });
    const input = screen.getByLabelText('Foto de perfil');
    fireEvent.change(input, { target: { files: [gifFile] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Escolha uma foto PNG, JPEG ou WebP.');
  });
  it('preserva a prévia no formulário quando o servidor rejeita o salvamento', async () => {
    const user = userEvent.setup();
    const photoData = 'data:image/png;base64,previewdata123';
    render(<ProfilePage {...props()} profile={{ ...profile, photo: photoData }}/>);
    fetch.mockResolvedValueOnce({ ok: false, json: async () => ({ photo: ['Foto inválida.'] }) });
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Foto: Foto inválida.');
    expect(screen.getByRole('alert')).not.toHaveTextContent('photo:');
    // O botão de remover foto ainda está disponível porque a foto permanece no draft
    expect(screen.getByRole('button', { name: 'Remover foto' })).toBeInTheDocument();
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
