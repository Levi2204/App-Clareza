import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DatePicker, getDaysInMonth } from './DatePicker';

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(cleanup);

describe('DatePicker', () => {
  it('renderiza o campo fechado exibindo a data formatada em pt-BR', () => {
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: /Data:/ });
    expect(trigger).toHaveTextContent('15/10/2026');
    expect(screen.queryByRole('region', { name: /Calendário:/ })).not.toBeInTheDocument();
  });

  it('abre o calendário ao clicar no trigger e exibe os botões de ação', async () => {
    const user = userEvent.setup();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    expect(screen.getByRole('region', { name: /Calendário: Data/ })).toBeInTheDocument();
    expect(screen.getByText(/Outubro de 2026/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirmar data' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hoje' })).toBeInTheDocument();
  });

  it('ao clicar em um dia, apenas atualiza a seleção temporária e o resumo sem fechar ou chamar onChange', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    const day20 = screen.getByRole('gridcell', { name: /^20 de outubro de 2026/ });
    await user.click(day20);

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('region', { name: /Calendário:/ })).toBeInTheDocument();
    expect(screen.getByText(/Data selecionada:/)).toHaveTextContent('20/10/2026');
    expect(day20).toHaveClass('selected');
  });

  it('ao clicar em Confirmar data, chama onChange com formato ISO e fecha o calendário', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    const day25 = screen.getByRole('gridcell', { name: /^25 de outubro de 2026/ });
    await user.click(day25);

    await user.click(screen.getByRole('button', { name: 'Confirmar data' }));

    expect(onChange).toHaveBeenCalledWith('2026-10-25');
    expect(screen.queryByRole('region', { name: /Calendário:/ })).not.toBeInTheDocument();
  });

  it('ao clicar em Cancelar, descarta a seleção temporária e fecha o calendário sem chamar onChange', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    const day20 = screen.getByRole('gridcell', { name: /^20 de outubro de 2026/ });
    await user.click(day20);

    await user.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: /Calendário:/ })).not.toBeInTheDocument();

    // Reabrir deve mostrar a data confirmada original (15/10/2026)
    await user.click(screen.getByRole('button', { name: /Data:/ }));
    expect(screen.getByText(/Data selecionada:/)).toHaveTextContent('15/10/2026');
  });

  it('tecla Escape cancela e fecha apenas o calendário', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    const day10 = screen.getByRole('gridcell', { name: /^10 de outubro de 2026/ });
    await user.click(day10);

    await user.keyboard('{Escape}');

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: /Calendário:/ })).not.toBeInTheDocument();
  });

  it('atalho Hoje seleciona a data de hoje na prévia temporária sem fechar ou confirmar', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker id="test-date" label="Data" value="2026-05-10" onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    await user.click(screen.getByRole('button', { name: 'Hoje' }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('region', { name: /Calendário:/ })).toBeInTheDocument();
    // O resumo da data selecionada deve estar atualizado
    expect(screen.getByText(/Data selecionada:/)).not.toHaveTextContent('10/05/2026');
  });

  it('desabilita datas fora dos limites min e max e desabilita Confirmar data se inválido', async () => {
    const user = userEvent.setup();
    render(
      <DatePicker
        id="test-date"
        label="Data"
        value="2026-10-15"
        min="2026-10-10"
        max="2026-10-20"
        onChange={vi.fn()}
      />
    );
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    const day5 = screen.getByRole('gridcell', { name: /^5 de outubro de 2026/ });
    expect(day5).toBeDisabled();

    const day15 = screen.getByRole('gridcell', { name: /^15 de outubro de 2026/ });
    expect(day15).not.toBeDisabled();

    const day25 = screen.getByRole('gridcell', { name: /^25 de outubro de 2026/ });
    expect(day25).toBeDisabled();
  });

  it('respeita anos bissextos em fevereiro (2028 permite 29, 2027 permite 28)', () => {
    expect(getDaysInMonth(2028, 1)).toBe(29);
    expect(getDaysInMonth(2027, 1)).toBe(28);
    expect(getDaysInMonth(2024, 1)).toBe(29);
    expect(getDaysInMonth(2025, 1)).toBe(28);
  });

  it('permite navegar entre meses anterior e próximo incluindo virada de ano', async () => {
    const user = userEvent.setup();
    render(<DatePicker id="test-date" label="Data" value="2026-12-15" onChange={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    expect(screen.getByText(/Dezembro de 2026/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Próximo mês' }));
    expect(screen.getByText(/Janeiro de 2027/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Mês anterior' }));
    expect(screen.getByText(/Dezembro de 2026/)).toBeInTheDocument();
  });

  it('permite mudar mês e ano diretamente através dos seletores', async () => {
    const user = userEvent.setup();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    await user.selectOptions(screen.getByLabelText('Selecionar mês'), '3'); // Abril
    await user.selectOptions(screen.getByLabelText('Selecionar ano'), '2025');

    expect(screen.getByText(/Abril de 2025/)).toBeInTheDocument();
  });

  it('campo desabilitado não abre o calendário', async () => {
    const user = userEvent.setup();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" disabled onChange={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: /Data:/ });
    expect(trigger).toBeDisabled();
    await user.click(trigger);
    expect(screen.queryByRole('region', { name: /Calendário:/ })).not.toBeInTheDocument();
  });

  it('navega por setas do teclado na grade e seleciona com Enter sem confirmar nem fechar', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    const day15 = screen.getByRole('gridcell', { name: /^15 de outubro de 2026/ });
    day15.focus();

    await user.keyboard('{ArrowRight}');
    const day16 = screen.getByRole('gridcell', { name: /^16 de outubro de 2026/ });
    expect(day16).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    const day23 = screen.getByRole('gridcell', { name: /^23 de outubro de 2026/ });
    expect(day23).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('region', { name: /Calendário:/ })).toBeInTheDocument();
    expect(screen.getByText(/Data selecionada:/)).toHaveTextContent('23/10/2026');
  });

  it('navegação para mês de seis semanas (agosto de 2026) mantém todas as semanas e botões disponíveis', async () => {
    const user = userEvent.setup();
    render(<DatePicker id="test-date" label="Data" value="2026-08-15" onChange={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    expect(screen.getByText(/Agosto de 2026/)).toBeInTheDocument();
    // 1º de agosto de 2026 é sábado, 31 é segunda-feira => 6 semanas
    const day1 = screen.getByRole('gridcell', { name: /^1 de agosto de 2026/ });
    const day31 = screen.getByRole('gridcell', { name: /^31 de agosto de 2026/ });
    expect(day1).toBeInTheDocument();
    expect(day31).toBeInTheDocument();

    // Rodapé continua completamente presente
    expect(screen.getByRole('button', { name: 'Hoje' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirmar data' })).toBeInTheDocument();
  });

  it('todos os botões internos do calendário possuem type="button" para não submeter formulários', async () => {
    const user = userEvent.setup();
    render(<DatePicker id="test-date" label="Data" value="2026-10-15" onChange={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    const buttons = screen.getAllByRole('button');
    for (const btn of buttons) {
      expect(btn).toHaveAttribute('type', 'button');
    }
  });

  it('datas desabilitadas não podem ser selecionadas nem confirmadas', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <DatePicker
        id="test-date"
        label="Data"
        value=""
        min="2026-10-10"
        max="2026-10-20"
        onChange={onChange}
      />
    );
    await user.click(screen.getByRole('button', { name: /Data:/ }));

    // Tentativa de clicar em dia desabilitado
    const day5 = screen.getByRole('gridcell', { name: /^5 de outubro de 2026/ });
    await user.click(day5);

    expect(screen.getByRole('button', { name: 'Confirmar data' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Confirmar data' }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
