import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SubscriptionDialog } from './Subscriptions';

const data = {
  accounts: [{ id: 1, name: 'BB', is_active: true }],
  cards: [{ id: 2, name: 'Cartão BB', is_active: true }],
  categories: [{ id: 3, name: 'Serviços', is_active: true }],
};

beforeEach(() => { global.fetch = vi.fn(); });
afterEach(cleanup);

describe('Primeira cobrança da assinatura', () => {
  it('exige a prévia, mostra o destino exato e salva a escolha revisada', async () => {
    const user = userEvent.setup(); const saved = vi.fn();
    fetch.mockImplementation(async url => ({ ok: true, status: url.includes('preview') ? 200 : 201, json: async () => url.includes('preview') ? {
      first_charge_date: '2026-09-16', month: '2026-09-01', amount: '20.00',
      destination: 'Fatura do Cartão · Cartão BB de 09/2026', conflicts: [], can_create: true,
    } : { id: 8, first_charge_date: '2026-09-16' } }));
    render(<SubscriptionDialog data={data} close={vi.fn()} saved={saved}/>);
    expect(screen.getByRole('button', { name: 'Confirmar assinatura' })).toBeDisabled();
    await user.type(screen.getByLabelText('Nome do serviço'), 'Google One');
    await user.type(screen.getByLabelText('Valor (R$)'), '20');
    await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'card:2');
    await user.selectOptions(screen.getByLabelText('Categoria'), '3');
    await user.click(screen.getByRole('button', { name: 'Revisar primeira cobrança' }));
    expect(await screen.findByText(/Fatura do Cartão · Cartão BB/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirmar assinatura' }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    const payloads = fetch.mock.calls.map(([, options]) => JSON.parse(options.body));
    expect(payloads[0]).toMatchObject({ account: null, card: 2, include_start_month: true });
    expect(payloads[1]).toEqual(payloads[0]);
  });

  it('invalida a prévia ao trocar para a próxima cobrança regular', async () => {
    const user = userEvent.setup();
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ first_charge_date: '2026-09-16', amount: '20.00', destination: 'Conta · BB', conflicts: [], can_create: true }) });
    render(<SubscriptionDialog data={data} close={vi.fn()} saved={vi.fn()}/>);
    await user.type(screen.getByLabelText('Nome do serviço'), 'Serviço');
    await user.type(screen.getByLabelText('Valor (R$)'), '20');
    await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'account:1');
    await user.selectOptions(screen.getByLabelText('Categoria'), '3');
    await user.click(screen.getByRole('button', { name: 'Revisar primeira cobrança' }));
    await screen.findByText(/Primeira cobrança:/);
    await user.click(screen.getByRole('button', { name: 'Próxima cobrança regular' }));
    expect(screen.getByRole('button', { name: 'Confirmar assinatura' })).toBeDisabled();
  });
});
