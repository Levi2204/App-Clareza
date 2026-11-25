import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

const baseSummary = {
  assets: '1500.00',
  liabilities: '0.00',
  net_worth: '1500.00',
  expenses: '0.00',
  income: '0.00',
  free: '0.00',
  goal_required: '0.00',
  subscription_total: '0.00',
  contributions: '0.00',
  invoice_total: '0.00',
  invoice_forecasts: [],
  categories: [],
  history: [],
  goals: [],
  payments: [],
  accounts: [{ id: 1, name: 'Banco do Brasil', balance: '1500.00' }],
  warnings: [],
  feasible: true,
  is_forecast: false,
};

const cardsFixture = [
  { id: 7, name: 'Banco do Brasil', account: 1, closing_day: 30, due_day: 11, is_active: true },
  { id: 8, name: 'Cartão Fecha 4', account: 1, closing_day: 4, due_day: 11, is_active: true },
];

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date('2026-11-25T12:00:00-03:00'));
  history.replaceState({}, '', '/invoices');
  global.fetch = vi.fn(async (url, options = {}) => {
    if (url.includes('profile')) {
      return { ok: true, json: async () => ({ name: 'Levi', theme: 'light' }) };
    }
    if (url.includes('sync')) {
      return { ok: true, json: async () => ({ detail: 'Cobranças atualizadas.' }) };
    }
    if (url.includes('dashboard')) {
      return { ok: true, json: async () => baseSummary };
    }
    if (url.includes('/api/v1/cards/')) {
      return { ok: true, json: async () => cardsFixture };
    }
    if (url.includes('/api/v1/accounts/')) {
      return { ok: true, json: async () => [{ id: 1, name: 'Banco do Brasil', is_active: true }] };
    }
    if (url.includes('/api/v1/invoices/') && options.method === 'POST') {
      const body = JSON.parse(options.body);
      return {
        ok: true,
        status: 201,
        json: async () => ({ id: 99, ...body }),
      };
    }
    return { ok: true, json: async () => [] };
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('Vencimento da fatura no mês seguinte (due_day <= closing_day)', () => {
  it('preenche automaticamente o vencimento para 11/12/2026 ao adicionar fatura manual de cartão com due_day <= closing_day e envia payload correto', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await screen.findByText('Faturas por cartão');
    await user.click((await screen.findAllByRole('button', { name: 'Adicionar fatura' }))[0]);

    const cardSelect = screen.getByLabelText('Cartão');
    await user.selectOptions(cardSelect, '7');

    expect(screen.getByLabelText('Competência')).toHaveValue('2026-11');

    const dueDateTrigger = screen.getByRole('button', { name: /Vencimento:/ });
    await waitFor(() => {
      expect(dueDateTrigger).toHaveTextContent('11/12/2026');
    });

    await user.type(screen.getByLabelText('Total manual (R$)'), '500');
    await user.click(screen.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      const postCall = fetch.mock.calls.find(
        ([url, opt]) => url === '/api/v1/invoices/' && opt?.method === 'POST'
      );
      expect(postCall).toBeTruthy();
      expect(JSON.parse(postCall[1].body)).toMatchObject({
        card: '7',
        month: '2026-11-01',
        due_date: '2026-12-11',
        manual_amount: '500',
      });
    });
  });

  it('mantém o vencimento no próprio mês da competência (11/11/2026) quando due_day > closing_day', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await screen.findByText('Faturas por cartão');
    await user.click((await screen.findAllByRole('button', { name: 'Adicionar fatura' }))[0]);

    await user.selectOptions(screen.getByLabelText('Cartão'), '8');

    expect(screen.getByLabelText('Competência')).toHaveValue('2026-11');
    const dueDateTrigger = screen.getByRole('button', { name: /Vencimento:/ });
    await waitFor(() => {
      expect(dueDateTrigger).toHaveTextContent('11/11/2026');
    });
  });
});
