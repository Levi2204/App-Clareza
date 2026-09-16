import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InstallmentDialog } from './Installments';

const data = {
  accounts: [{ id: 1, name: 'Conta', is_active: true }],
  cards: [{ id: 2, name: 'Cartão', is_active: true }],
  categories: [{ id: 3, name: 'Compras', is_active: true }],
};
const preview = {
  installment_count: 3, total_amount: '100.00', sum: '100.00', can_create: true, conflicts: [],
  schedule: [
    { number: 1, month: '2026-09-01', amount: '33.34' },
    { number: 2, month: '2026-10-01', amount: '33.33' },
    { number: 3, month: '2026-11-01', amount: '33.33' },
  ],
};

async function fill(user) {
  await user.type(screen.getByLabelText('Descrição'), 'Notebook');
  await user.type(screen.getByLabelText('Valor total (R$)'), '100');
  await user.clear(screen.getByLabelText('Quantidade de parcelas'));
  await user.type(screen.getByLabelText('Quantidade de parcelas'), '3');
  await user.selectOptions(screen.getByLabelText('Categoria'), '3');
  await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'account:1');
}

beforeEach(() => { global.fetch = vi.fn(); });
afterEach(cleanup);

describe('Compras parceladas', () => {
  it('consulta a prévia do servidor e salva exatamente o cronograma revisado', async () => {
    const user = userEvent.setup();
    const saved = vi.fn();
    fetch.mockImplementation(async url => ({ ok: true, status: url.includes('preview') ? 200 : 201, json: async () => url.includes('preview') ? preview : { ...preview, id: 8 } }));
    render(<InstallmentDialog data={data} month="2026-09" close={vi.fn()} saved={saved}/>);
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Calcular prévia' }));
    expect(await screen.findByText('1/3')).toBeInTheDocument();
    expect(screen.getByText(/R\$\s33,34/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirmar parcelamento' }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith('Compra registrada em 3 parcelas.'));
    const calls = fetch.mock.calls.map(([, options]) => JSON.parse(options.body));
    expect(calls[0]).toMatchObject({ total_amount: '100', installment_count: 3, account: 1, card: null, first_month: '2026-09-01' });
    expect(calls[1].request_id).toBe(calls[0].request_id);
  });

  it('descarta uma resposta antiga quando os valores mudam', async () => {
    const user = userEvent.setup();
    let resolve;
    fetch.mockImplementation(() => new Promise(done => { resolve = done; }));
    render(<InstallmentDialog data={data} month="2026-09" close={vi.fn()} saved={vi.fn()}/>);
    await fill(user);
    await user.click(screen.getByRole('button', { name: 'Calcular prévia' }));
    await user.type(screen.getByLabelText('Valor total (R$)'), '0');
    resolve({ ok: true, status: 200, json: async () => preview });
    await waitFor(() => expect(screen.queryByText('1/3')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Confirmar parcelamento' })).toBeDisabled();
  });
});
