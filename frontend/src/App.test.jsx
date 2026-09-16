import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { money } from './api';
const summary = {
  assets: '1200.50',
  liabilities: '200',
  net_worth: '1000.50',
  expenses: '250',
  income: '2000',
  free: '1550',
  goal_required: '200',
  subscription_total: '0',
  contributions: '0',
  categories: [],
  history: [],
  goals: [],
  payments: [],
  accounts: [],
  feasible: true
};
beforeEach(() => {
  history.replaceState({}, '', '/');
  global.fetch = vi.fn(async url => ({
    ok: true,
    json: async () => url.includes('dashboard') ? summary : url.includes('sync') ? {} : []
  }));
});
afterEach(cleanup);
describe('Fluxos principais', () => {
  it('apresenta os cálculos retornados pela API em reais', async () => {
    render(<App />);
    expect(await screen.findByText(/R\$\s1\.000,50/)).toBeInTheDocument();
    expect(screen.getAllByText('Patrimônio líquido').length).toBeGreaterThan(0);
  });
  it('navega até contas e abre o formulário', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText(/R\$\s1\.000,50/);
    await user.click(screen.getByRole('link', {
      name: 'Minhas contas'
    }));
    await user.click((await screen.findAllByRole('button', {
      name: 'Adicionar conta'
    }))[0]);
    expect(screen.getByLabelText('Nome da conta')).toBeInTheDocument();
  });
  it('salva uma conta com saldo e mostra feedback', async () => {
    const user = userEvent.setup();
    history.replaceState({}, '', '/accounts');
    render(<App />);
    await screen.findByText(/R\$\s1\.000,50/);
    await user.click((await screen.findAllByRole('button', {
      name: 'Adicionar conta'
    }))[0]);
    await user.type(screen.getByLabelText('Nome da conta'), 'Nubank');
    await user.type(screen.getByLabelText('Saldo informado (R$)'), '1500.50');
    await user.click(screen.getByRole('button', {
      name: 'Salvar'
    }));
    await screen.findByText('Registro salvo com sucesso.');
    const call = fetch.mock.calls.find(([url, opt]) => url === '/api/v1/accounts/' && opt.method === 'POST');
    expect(JSON.parse(call[1].body)).toMatchObject({
      name: 'Nubank',
      balance: '1500.5'
    });
  });
  it('exibe erros de validação retornados pelo servidor', async () => {
    const user = userEvent.setup();
    history.replaceState({}, '', '/accounts');
    render(<App />);
    await screen.findByText(/R\$\s1\.000,50/);
    await user.click((await screen.findAllByRole('button', {
      name: 'Adicionar conta'
    }))[0]);
    await user.type(screen.getByLabelText('Nome da conta'), 'Teste');
    await user.type(screen.getByLabelText('Saldo informado (R$)'), '20');
    fetch.mockImplementationOnce(async () => ({
      ok: false,
      json: async () => ({
        balance: ['Saldo inválido.']
      })
    }));
    await user.click(screen.getByRole('button', {
      name: 'Salvar'
    }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Saldo inválido.');
    expect(screen.getByRole('button', {
      name: 'Salvar'
    })).toBeEnabled();
  });
  it('consulta o mês selecionado', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText(/R\$\s1\.000,50/);
    await user.click(screen.getByRole('button', {
      name: 'Mês anterior'
    }));
    await waitFor(() => expect(fetch.mock.calls.filter(([u]) => u.includes('dashboard')).length).toBe(2));
  });
  it('mostra falha de sincronização e não apresenta o painel como atualizado', async () => {
    fetch.mockImplementation(async url => {
      if (url.includes('profile')) return { ok: true, json: async () => ({ theme: 'light' }) };
      if (url.includes('sync')) return { ok: false, json: async () => ({ detail: 'A fatura precisa ser ajustada.' }) };
      return { ok: true, json: async () => summary };
    });
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Sincronização não concluída');
    expect(screen.queryByText(/R\$\s1\.000,50/)).not.toBeInTheDocument();
  });
  it('mantém pendências anteriores fechadas e mostra competência e ano quando solicitado', async () => {
    const user = userEvent.setup();
    history.replaceState({}, '', '/payments');
    const pending = [{ key: 'pending-invoice-1-2026-08', id: 4, kind: 'invoice', month: '2026-08-01', description: 'Fatura Cartão BB', origin: 'Cartão · Cartão BB', amount: '61.24', due_date: '2026-09-11', status: 'overdue', days_until: -5, can_pay: true }];
    fetch.mockImplementation(async url => ({ ok: true, json: async () => url.includes('dashboard') ? summary : url.includes('payments/pending') ? pending : url.includes('profile') ? { theme: 'light' } : [] }));
    render(<App />);
    await screen.findByText('Agenda de pagamentos');
    expect(screen.queryByText('Fatura Cartão BB')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Ver pendências anteriores/ }));
    expect(await screen.findByText('Fatura Cartão BB')).toBeInTheDocument();
    expect(screen.getByText(/Competência 08\/2026/)).toBeInTheDocument();
    expect(screen.getByText('2026')).toBeInTheDocument();
  });
});
