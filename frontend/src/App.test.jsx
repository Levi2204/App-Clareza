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
  it('seleciona e confirma data no formulário de movimentação sem salvar ou fechar o diálogo', async () => {
    const user = userEvent.setup();
    history.replaceState({}, '', '/transactions');
    render(<App />);
    await screen.findByText('Movimentações do mês');
    await user.click(screen.getByRole('button', { name: 'Nova movimentação' }));

    expect(screen.getByRole('heading', { name: 'Adicionar movimentação' })).toBeInTheDocument();

    const dateTrigger = screen.getByRole('button', { name: /Data:/ });
    await user.click(dateTrigger);

    expect(screen.getByRole('region', { name: /Calendário: Data/ })).toBeInTheDocument();

    const dayBtn = screen.getAllByRole('gridcell').find(el => el.textContent === '10');
    expect(dayBtn).toBeDefined();
    await user.click(dayBtn);

    await user.click(screen.getByRole('button', { name: 'Confirmar data' }));

    expect(screen.queryByRole('region', { name: /Calendário: Data/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Adicionar movimentação' })).toBeInTheDocument();
    expect(fetch.mock.calls.some(([url, opt]) => url.includes('transactions') && opt?.method === 'POST')).toBe(false);
    expect(dateTrigger).toHaveTextContent(/10\/\d\d\/\d\d\d\d/);
  });

  it('integração completa: preenche campos, altera data via calendário, confirma e salva sem perda de dados', async () => {
    const user = userEvent.setup();
    history.replaceState({}, '', '/transactions');
    fetch.mockImplementation(async url => ({
      ok: true,
      json: async () => {
        if (url.includes('dashboard')) return summary;
        if (url.includes('accounts')) return [{ id: 1, name: 'Conta Principal', is_active: true }];
        if (url.includes('categories')) return [{ id: 1, name: 'Alimentação', is_active: true }];
        return [];
      }
    }));
    render(<App />);
    await screen.findByText('Movimentações do mês');
    await user.click(screen.getByRole('button', { name: 'Nova movimentação' }));

    // Preenche descrição e valor
    await user.type(screen.getByLabelText('Descrição'), 'Compra de teste');
    await user.type(screen.getByLabelText('Valor (R$)'), '50');

    const dateTrigger = screen.getByRole('button', { name: /Data:/ });
    const originalDateText = dateTrigger.textContent;

    // Abre o calendário
    await user.click(dateTrigger);
    expect(screen.getByRole('region', { name: /Calendário: Data/ })).toBeInTheDocument();

    // Seleciona um dia diferente
    const dayBtn = screen.getAllByRole('gridcell').find(el => el.textContent === '15');
    await user.click(dayBtn);

    // Sem confirmar, o botão acionador ainda mantém o texto original
    expect(dateTrigger).toHaveTextContent(originalDateText);

    // Clica em Confirmar data
    await user.click(screen.getByRole('button', { name: 'Confirmar data' }));

    // Diálogo da movimentação permanece aberto com dados intactos e sem POST
    expect(screen.getByRole('heading', { name: 'Adicionar movimentação' })).toBeInTheDocument();
    expect(screen.getByLabelText('Descrição')).toHaveValue('Compra de teste');
    expect(screen.getByLabelText('Valor (R$)')).toHaveValue(50);
    expect(fetch.mock.calls.filter(([url, opt]) => url === '/api/v1/transactions/' && opt?.method === 'POST').length).toBe(0);

    // Seleciona conta e categoria para poder salvar
    await user.selectOptions(screen.getByLabelText('Conta ou cartão'), 'account:1');
    await user.selectOptions(screen.getByLabelText('Categoria'), '1');

    // Salva a movimentação
    await user.click(screen.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      const calls = fetch.mock.calls.filter(([url, opt]) => url === '/api/v1/transactions/' && opt?.method === 'POST');
      expect(calls.length).toBe(1);
      const body = JSON.parse(calls[0][1].body);
      expect(body).toMatchObject({
        description: 'Compra de teste',
        amount: '50',
        date: expect.stringMatching(/-\d{2}-15/)
      });
    });
  });

  it('clicar fora do calendário fecha apenas o calendário sem fechar a janela do formulário', async () => {
    const user = userEvent.setup();
    history.replaceState({}, '', '/transactions');
    render(<App />);
    await screen.findByText('Movimentações do mês');
    await user.click(screen.getByRole('button', { name: 'Nova movimentação' }));

    const dateTrigger = screen.getByRole('button', { name: /Data:/ });
    await user.click(dateTrigger);

    expect(screen.getByRole('region', { name: /Calendário: Data/ })).toBeInTheDocument();

    // Dispara clique fora do calendário (ex: no título do formulário)
    await user.click(screen.getByRole('heading', { name: 'Adicionar movimentação' }));

    // O painel do calendário deve fechar
    expect(screen.queryByRole('region', { name: /Calendário: Data/ })).not.toBeInTheDocument();

    // O formulário de movimentação continua aberto
    expect(screen.getByRole('heading', { name: 'Adicionar movimentação' })).toBeInTheDocument();
  });
});
