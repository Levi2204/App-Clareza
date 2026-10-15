import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InstallmentDialog } from './Installments';

const mockData = {
  accounts: [{ id: 1, name: 'Conta Principal', is_active: true }],
  cards: [{ id: 10, name: 'Cartão A', closing_day: 2, due_day: 11, is_active: true }],
  categories: [{ id: 5, name: 'Compras', is_active: true }],
};

const cardSchedulePreview = {
  installment_count: 3,
  total_amount: '300.00',
  sum: '300.00',
  can_create: true,
  conflicts: [],
  schedule: [
    { number: 1, month: '2027-01-01', date: '2027-02-01', amount: '100.00' },
    { number: 2, month: '2027-02-01', date: '2027-03-01', amount: '100.00' },
    { number: 3, month: '2027-03-01', date: '2027-04-01', amount: '100.00' },
  ],
};

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(cleanup);

describe('Competência pelo fechamento do cartão - Interface (Section 7)', () => {
  it('ao selecionar cartão e data 01/02/2027, a prévia de parcelas calcula competência inicial em janeiro', async () => {
    const user = userEvent.setup();
    const saved = vi.fn();

    fetch.mockImplementation(async (url) => {
      if (url.includes('preview')) {
        return { ok: true, status: 200, json: async () => cardSchedulePreview };
      }
      return { ok: true, status: 201, json: async () => ({ ...cardSchedulePreview, id: 99 }) };
    });

    render(<InstallmentDialog data={mockData} month="2027-02" close={vi.fn()} saved={saved} />);

    await user.type(screen.getByLabelText('Descrição'), 'Notebook');
    await user.type(screen.getByLabelText('Valor total (R$)'), '300');
    await user.clear(screen.getByLabelText('Quantidade de parcelas'));
    await user.type(screen.getByLabelText('Quantidade de parcelas'), '3');
    await user.selectOptions(screen.getByLabelText('Categoria'), '5');
    await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'card:10');

    // Ao selecionar cartão, primeira competência deve ser calculada e a prévia deve refletir o cronograma
    await user.click(screen.getByRole('button', { name: 'Calcular prévia' }));

    expect(await screen.findByText('1/3')).toBeInTheDocument();
    // A parcela 1/3 deve estar atribuída à fatura de janeiro
    expect(screen.getByText(/01\/2027/)).toBeInTheDocument();
  });

  it('alterar data ou cartão invalida a prévia anterior e resposta atrasada é descartada', async () => {
    const user = userEvent.setup();
    let delayedResolve;

    fetch.mockImplementation(
      (url) =>
        new Promise((resolve) => {
          if (url.includes('preview')) {
            delayedResolve = resolve;
          }
        })
    );

    render(<InstallmentDialog data={mockData} month="2027-02" close={vi.fn()} saved={vi.fn()} />);

    await user.type(screen.getByLabelText('Descrição'), 'Smartphone');
    await user.type(screen.getByLabelText('Valor total (R$)'), '300');
    await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'card:10');

    await user.click(screen.getByRole('button', { name: 'Calcular prévia' }));

    // Usuário altera o valor antes da resposta
    await user.type(screen.getByLabelText('Valor total (R$)'), '0');

    // Resposta antiga chega atrasada
    delayedResolve({ ok: true, status: 200, json: async () => cardSchedulePreview });

    // A prévia obsoleta não deve aparecer
    await waitFor(() => {
      expect(screen.queryByText('1/3')).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Confirmar parcelamento' })).toBeDisabled();
  });

  it('em conta a competência manual permanece selecionável', async () => {
    const user = userEvent.setup();
    render(<InstallmentDialog data={mockData} month="2027-02" close={vi.fn()} saved={vi.fn()} />);

    await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'account:1');

    // Em conta, o campo de primeira competência deve estar visível e editável
    const firstMonthInput = screen.getByLabelText('Primeira competência');
    expect(firstMonthInput).toBeInTheDocument();
    expect(firstMonthInput).not.toBeDisabled();
  });

  it('erros de fatura paga na prévia exibem alerta sem descartar os demais campos', async () => {
    const user = userEvent.setup();
    const conflictPreview = {
      installment_count: 3,
      total_amount: '300.00',
      sum: '300.00',
      can_create: false,
      conflicts: [
        {
          month: '2027-01-01',
          kind: 'paid_invoice',
          message: 'A fatura de Cartão A em 01/2027 está paga. Reabra-a antes de parcelar.',
        },
      ],
      schedule: cardSchedulePreview.schedule,
    };

    fetch.mockImplementation(async () => ({
      ok: true,
      status: 200,
      json: async () => conflictPreview,
    }));

    render(<InstallmentDialog data={mockData} month="2027-02" close={vi.fn()} saved={vi.fn()} />);

    await user.type(screen.getByLabelText('Descrição'), 'Geladeira');
    await user.type(screen.getByLabelText('Valor total (R$)'), '300');
    await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'card:10');

    await user.click(screen.getByRole('button', { name: 'Calcular prévia' }));

    expect(await screen.findByText(/A fatura de Cartão A em 01\/2027 está paga/)).toBeInTheDocument();
    // Campos preenchidos permanecem intactos
    expect(screen.getByLabelText('Descrição')).toHaveValue('Geladeira');
    expect(screen.getByLabelText('Valor total (R$)')).toHaveValue(300);
    expect(screen.getByRole('button', { name: 'Confirmar parcelamento' })).toBeDisabled();
  });
});
