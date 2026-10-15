import React, { useState, useEffect, useRef, useId } from 'react';
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';
import { dateLabel, today } from './api';

const MONTH_NAMES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'
];

const WEEKDAYS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
const WEEKDAY_FULL_NAMES = [
  'Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira',
  'Quinta-feira', 'Sexta-feira', 'Sábado'
];

export function parseISODate(str) {
  if (!str || typeof str !== 'string') return null;
  const parts = str.split('-').map(Number);
  if (parts.length !== 3 || parts.some(isNaN)) return null;
  return { year: parts[0], month: parts[1] - 1, day: parts[2] };
}

export function formatISODate(year, month, day) {
  const y = String(year).padStart(4, '0');
  const m = String(month + 1).padStart(2, '0');
  const d = String(day).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function getDaysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

export function getFirstDayOfWeek(year, month) {
  return new Date(year, month, 1).getDay();
}

export function DatePicker({
  id: explicitId,
  name,
  label,
  value,
  onChange,
  min,
  max,
  required = false,
  disabled = false,
  optional = false,
  hint,
  autoFocus = false,
  className = ''
}) {
  const generatedId = useId();
  const id = explicitId || name || generatedId;

  const [isOpen, setIsOpen] = useState(false);
  const [tempDate, setTempDate] = useState('');
  const [viewYear, setViewYear] = useState(() => new Date().getFullYear());
  const [viewMonth, setViewMonth] = useState(() => new Date().getMonth());
  const [focusedDay, setFocusedDay] = useState(1);

  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const popupRef = useRef(null);
  const dayRefs = useRef({});

  // Abre e inicializa o calendário
  const openPicker = () => {
    if (disabled) return;
    const parsed = parseISODate(value);
    if (parsed) {
      setTempDate(value);
      setViewYear(parsed.year);
      setViewMonth(parsed.month);
      setFocusedDay(parsed.day);
    } else {
      setTempDate('');
      const todayParsed = parseISODate(today()) || { year: new Date().getFullYear(), month: new Date().getMonth(), day: new Date().getDate() };
      setViewYear(todayParsed.year);
      setViewMonth(todayParsed.month);
      setFocusedDay(todayParsed.day);
    }
    setIsOpen(true);
    setTimeout(() => {
      if (typeof popupRef.current?.scrollIntoView === 'function') {
        popupRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }, 50);
  };

  const handleCancel = () => {
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  const handleConfirm = () => {
    if (!tempDate) return;
    if (min && tempDate < min) return;
    if (max && tempDate > max) return;
    onChange?.(tempDate);
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  // Atalho Hoje: apenas seleciona a data de hoje na prévia
  const handleSelectToday = () => {
    const t = today();
    if ((min && t < min) || (max && t > max)) return;
    const parsed = parseISODate(t);
    if (parsed) {
      setViewYear(parsed.year);
      setViewMonth(parsed.month);
      setFocusedDay(parsed.day);
      setTempDate(t);
    }
  };

  const handlePrevMonth = () => {
    if (viewMonth === 0) {
      setViewMonth(11);
      setViewYear(y => y - 1);
    } else {
      setViewMonth(m => m - 1);
    }
  };

  const handleNextMonth = () => {
    if (viewMonth === 11) {
      setViewMonth(0);
      setViewYear(y => y + 1);
    } else {
      setViewMonth(m => m + 1);
    }
  };

  // Ajusta o foco quando o painel abrir ou a visualização de mês/ano mudar
  useEffect(() => {
    if (isOpen) {
      const el = dayRefs.current[focusedDay];
      if (el) {
        el.focus();
      }
    }
  }, [isOpen, viewYear, viewMonth]);

  // Tecla Escape: cancela apenas o calendário e previne fechar o diálogo pai
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        handleCancel();
      }
    };
    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [isOpen]);

  // Clique fora do painel do calendário e fora do acionador: fecha somente o calendário
  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (e) => {
      const isInsideTrigger = containerRef.current && containerRef.current.contains(e.target);
      const isInsidePanel = popupRef.current && popupRef.current.contains(e.target);

      if (!isInsideTrigger && !isInsidePanel) {
        // Se o clique atingiu o botão de Salvar ou botão de fechar do formulário pai,
        // intercepta para que o primeiro clique apenas feche o calendário sem submeter ou fechar a janela
        if (e.target.closest('button[type="submit"]') || e.target.closest('.dialog-heading button')) {
          e.preventDefault();
          e.stopPropagation();
        }
        handleCancel();
      }
    };

    document.addEventListener('pointerdown', handlePointerDown, true);
    return () => document.removeEventListener('pointerdown', handlePointerDown, true);
  }, [isOpen]);

  // Navegação por teclado na grade
  const handleGridKeyDown = (e, currentDay) => {
    const daysInCurrentMonth = getDaysInMonth(viewYear, viewMonth);
    let nextDay = null;

    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      if (currentDay > 1) {
        nextDay = currentDay - 1;
      } else {
        handlePrevMonth();
        const prevMonthIndex = viewMonth === 0 ? 11 : viewMonth - 1;
        const prevYearValue = viewMonth === 0 ? viewYear - 1 : viewYear;
        const daysInPrev = getDaysInMonth(prevYearValue, prevMonthIndex);
        setFocusedDay(daysInPrev);
        return;
      }
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      if (currentDay < daysInCurrentMonth) {
        nextDay = currentDay + 1;
      } else {
        handleNextMonth();
        setFocusedDay(1);
        return;
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (currentDay - 7 >= 1) {
        nextDay = currentDay - 7;
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (currentDay + 7 <= daysInCurrentMonth) {
        nextDay = currentDay + 7;
      }
    } else if (e.key === 'Home') {
      e.preventDefault();
      const firstDayCol = (getFirstDayOfWeek(viewYear, viewMonth) + currentDay - 1) % 7;
      nextDay = Math.max(1, currentDay - firstDayCol);
    } else if (e.key === 'End') {
      e.preventDefault();
      const firstDayCol = (getFirstDayOfWeek(viewYear, viewMonth) + currentDay - 1) % 7;
      nextDay = Math.min(daysInCurrentMonth, currentDay + (6 - firstDayCol));
    } else if (e.key === 'PageUp') {
      e.preventDefault();
      handlePrevMonth();
      return;
    } else if (e.key === 'PageDown') {
      e.preventDefault();
      handleNextMonth();
      return;
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      const iso = formatISODate(viewYear, viewMonth, currentDay);
      const isDayDisabled = (min && iso < min) || (max && iso > max);
      if (!isDayDisabled) {
        setTempDate(iso);
        setFocusedDay(currentDay);
      }
      return;
    }

    if (nextDay != null) {
      setFocusedDay(nextDay);
      dayRefs.current[nextDay]?.focus();
    }
  };

  // Opções de ano
  const currentY = new Date().getFullYear();
  const startY = Math.min(1950, min ? Number(min.slice(0, 4)) : currentY - 20);
  const endY = Math.max(2050, max ? Number(max.slice(0, 4)) : currentY + 20);
  const years = [];
  for (let y = startY; y <= endY; y++) {
    years.push(y);
  }

  // Montagem da grade
  const daysInMonth = getDaysInMonth(viewYear, viewMonth);
  const firstDayOfWeek = getFirstDayOfWeek(viewYear, viewMonth);
  const weeks = [];
  let currentWeek = [];

  for (let i = 0; i < firstDayOfWeek; i++) {
    currentWeek.push(null);
  }

  for (let d = 1; d <= daysInMonth; d++) {
    currentWeek.push(d);
    if (currentWeek.length === 7) {
      weeks.push(currentWeek);
      currentWeek = [];
    }
  }

  if (currentWeek.length > 0) {
    while (currentWeek.length < 7) {
      currentWeek.push(null);
    }
    weeks.push(currentWeek);
  }

  const isTodayDisabled = Boolean((min && today() < min) || (max && today() > max));
  const isTempDateValid = Boolean(tempDate && (!min || tempDate >= min) && (!max || tempDate <= max));

  const displayFormatted = value ? dateLabel(value) : '';

  return (
    <>
      <div ref={containerRef} className={`form-field datepicker-field ${className}`}>
        {label && (
          <label htmlFor={id} className="datepicker-label">
            {label}
            {optional && <small> · opcional</small>}
          </label>
        )}

        <button
          id={id}
          ref={triggerRef}
          type="button"
          className="datepicker-trigger"
          aria-haspopup="true"
          aria-expanded={isOpen}
          aria-controls={isOpen ? `${id}-calendar-panel` : undefined}
          aria-label={label ? `${label}: ${displayFormatted || 'nenhuma data selecionada'}` : undefined}
          disabled={disabled}
          autoFocus={autoFocus}
          onClick={() => {
            if (!disabled) {
              if (!isOpen) openPicker();
              else handleCancel();
            }
          }}
        >
          <span className={displayFormatted ? 'datepicker-value' : 'datepicker-placeholder'}>
            {displayFormatted || 'DD/MM/AAAA'}
          </span>
          <Calendar size={16} className="datepicker-icon" />
        </button>

        {/* Input oculto para validação HTML5 do formulário */}
        <input
          tabIndex={-1}
          aria-hidden="true"
          required={required && !disabled}
          disabled={disabled}
          value={value || ''}
          onChange={() => {}}
          style={{
            position: 'absolute',
            opacity: 0,
            width: 0,
            height: 0,
            pointerEvents: 'none'
          }}
        />

        {hint && <small className="hint">{hint}</small>}
      </div>

      {isOpen && (
        <div
          id={`${id}-calendar-panel`}
          ref={popupRef}
          className="datepicker-panel-container wide"
          role="region"
          aria-label={`Calendário: ${label || 'Selecionar data'}`}
        >
          <div className="datepicker-panel">
            <div className="datepicker-header">
              <div className="datepicker-nav">
                <button
                  type="button"
                  className="icon-button"
                  onClick={handlePrevMonth}
                  aria-label="Mês anterior"
                >
                  <ChevronLeft size={18} />
                </button>
                <div className="datepicker-title" aria-live="polite">
                  <strong>{MONTH_NAMES[viewMonth]} de {viewYear}</strong>
                </div>
                <button
                  type="button"
                  className="icon-button"
                  onClick={handleNextMonth}
                  aria-label="Próximo mês"
                >
                  <ChevronRight size={18} />
                </button>
              </div>

              <div className="datepicker-selectors">
                <select
                  aria-label="Selecionar mês"
                  value={viewMonth}
                  onChange={e => setViewMonth(Number(e.target.value))}
                >
                  {MONTH_NAMES.map((name, idx) => (
                    <option key={idx} value={idx}>{name}</option>
                  ))}
                </select>
                <select
                  aria-label="Selecionar ano"
                  value={viewYear}
                  onChange={e => setViewYear(Number(e.target.value))}
                >
                  {years.map(y => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="datepicker-weekdays" role="row">
              {WEEKDAYS.map((day, idx) => (
                <span key={day} role="columnheader" aria-label={WEEKDAY_FULL_NAMES[idx]}>
                  {day}
                </span>
              ))}
            </div>

            <div
              className="datepicker-grid"
              role="grid"
              aria-label={`Dias de ${MONTH_NAMES[viewMonth]} de ${viewYear}`}
            >
              {weeks.map((week, wIdx) => (
                <div key={wIdx} className="datepicker-row" role="row">
                  {week.map((d, dIdx) => {
                    if (d == null) {
                      return <span key={`empty-${dIdx}`} className="datepicker-empty-cell" role="gridcell" />;
                    }
                    const iso = formatISODate(viewYear, viewMonth, d);
                    const isSelected = tempDate === iso;
                    const isCurrentToday = iso === today();
                    const isDayDisabled = Boolean((min && iso < min) || (max && iso > max));
                    const isFocused = focusedDay === d;

                    return (
                      <button
                        key={iso}
                        ref={el => {
                          if (el) dayRefs.current[d] = el;
                        }}
                        type="button"
                        role="gridcell"
                        tabIndex={isFocused ? 0 : -1}
                        aria-selected={isSelected}
                        aria-disabled={isDayDisabled || undefined}
                        disabled={isDayDisabled}
                        aria-label={`${d} de ${MONTH_NAMES[viewMonth].toLowerCase()} de ${viewYear}${isCurrentToday ? ' (hoje)' : ''}${isSelected ? ' (selecionado)' : ''}`}
                        className={`datepicker-day ${isSelected ? 'selected' : ''} ${isCurrentToday ? 'is-today' : ''} ${isDayDisabled ? 'disabled' : ''}`}
                        onClick={() => {
                          if (!isDayDisabled) {
                            setTempDate(iso);
                            setFocusedDay(d);
                          }
                        }}
                        onKeyDown={e => handleGridKeyDown(e, d)}
                      >
                        {d}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>

            <div className="datepicker-summary">
              Data selecionada: <strong>{tempDate ? dateLabel(tempDate) : 'nenhuma'}</strong>
            </div>

            <div className="datepicker-footer">
              <button
                type="button"
                className="button secondary small datepicker-today-btn"
                disabled={isTodayDisabled}
                onClick={handleSelectToday}
              >
                Hoje
              </button>
              <div className="datepicker-footer-actions">
                <button
                  type="button"
                  className="button secondary small"
                  onClick={handleCancel}
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  className="button primary small"
                  disabled={!isTempDateValid}
                  onClick={handleConfirm}
                >
                  Confirmar data
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default DatePicker;
