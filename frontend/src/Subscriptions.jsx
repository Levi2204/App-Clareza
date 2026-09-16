import React, { useEffect, useRef, useState } from 'react';
import { Check, LoaderCircle, X } from 'lucide-react';
import { api, dateLabel, money, today } from './api';
import { confirmAction } from './confirm';

const origins = data => [
  ...data.accounts.filter(row => row.is_active).map(row => [`account:${row.id}`, `Conta · ${row.name}`]),
  ...data.cards.filter(row => row.is_active).map(row => [`card:${row.id}`, `Cartão · ${row.name}`]),
];

export function SubscriptionDialog({ data, close, saved }) {
  const dialog = useRef(null);
  const previewKey = useRef('');
  const [values, setValues] = useState({ name: '', amount: '', category: '', origin: '', billing_day: 10, start_date: today(), include_start_month: true });
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { dialog.current.showModal(); }, []);
  const change = (name, value) => { setValues(current => ({ ...current, [name]: value })); setPreview(null); previewKey.current = ''; };
  const payload = () => {
    const [kind, id] = values.origin.split(':');
    return { ...values, category: Number(values.category), billing_day: Number(values.billing_day), account: kind === 'account' ? Number(id) : null, card: kind === 'card' ? Number(id) : null };
  };
  async function showPreview() {
    const current = payload(); const key = JSON.stringify(current);
    previewKey.current = key; setPreviewBusy(true); setError('');
    try {
      const result = await api('subscriptions/preview/', { method: 'POST', body: JSON.stringify(current) });
      if (previewKey.current === key) setPreview(result);
    } catch (e) { if (previewKey.current === key) setError(e.message); }
    finally { if (previewKey.current === key) setPreviewBusy(false); }
  }
  async function submit(e) {
    e.preventDefault(); const current = payload();
    if (!preview || previewKey.current !== JSON.stringify(current) || !preview.can_create) { setError('Revise uma prévia atualizada antes de salvar.'); return; }
    setBusy(true); setError('');
    try { await api('subscriptions/', { method: 'POST', body: JSON.stringify(current) }); saved('Assinatura cadastrada e primeira cobrança confirmada.'); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="dialog" onCancel={close}><form onSubmit={submit}>
    <div className="dialog-heading"><div><span className="eyebrow">COBRANÇAS RECORRENTES</span><h2>Adicionar assinatura</h2></div><button type="button" className="icon-button" onClick={close} aria-label="Fechar"><X size={20}/></button></div>
    <p className="form-note">Confirme quando será a primeira cobrança e se ela irá diretamente para uma conta ou para a fatura de um cartão.</p>
    <div className="form-grid">
      <label>Nome do serviço<input autoFocus required value={values.name} onChange={e => change('name', e.target.value)}/></label>
      <label>Valor (R$)<input required type="number" min=".01" step=".01" value={values.amount} onChange={e => change('amount', e.target.value)}/></label>
      <label>Conta ou cartão<select required value={values.origin} onChange={e => change('origin', e.target.value)}><option value="">Selecione</option>{origins(data).map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select></label>
      <label>Categoria<select required value={values.category} onChange={e => change('category', e.target.value)}><option value="">Selecione</option>{data.categories.filter(row => row.is_active).map(row => <option value={row.id} key={row.id}>{row.name}</option>)}</select></label>
      <label>Dia mensal recorrente<input required type="number" min="1" max="31" value={values.billing_day} onChange={e => change('billing_day', e.target.value)}/></label>
      <label>Início da assinatura<input required type="date" value={values.start_date} onChange={e => change('start_date', e.target.value)}/></label>
    </div>
    <div className="payment-mode" role="group" aria-label="Escolha da primeira cobrança"><button type="button" className={values.include_start_month ? 'selected' : ''} onClick={() => change('include_start_month', true)}>Incluir no mês inicial</button><button type="button" className={!values.include_start_month ? 'selected' : ''} onClick={() => change('include_start_month', false)}>Próxima cobrança regular</button></div>
    {error && <div role="alert" className="alert error">{error}</div>}
    <div className="preview-actions"><button type="button" className="button secondary" disabled={busy || previewBusy} onClick={showPreview}>{previewBusy ? <><LoaderCircle className="spin" size={16}/>Calculando…</> : 'Revisar primeira cobrança'}</button></div>
    {preview && <div className="subscription-preview"><strong>Primeira cobrança: {dateLabel(preview.first_charge_date)}</strong><span>{money(preview.amount)} · {preview.destination}</span>{preview.conflicts.map((message, index) => <small className="negative" key={index}>{message}</small>)}</div>}
    <div className="dialog-footer"><button type="button" className="button secondary" onClick={close}>Cancelar</button><button className="button primary" disabled={busy || !preview?.can_create}>{busy ? 'Salvando…' : 'Confirmar assinatura'}<Check size={16}/></button></div>
  </form></dialog>;
}

export function ReviewFirstChargeDialog({ subscription, close, saved }) {
  const dialog = useRef(null);
  const [include, setInclude] = useState(true);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { dialog.current.showModal(); }, []);
  async function review() {
    setBusy(true); setError('');
    try { setPreview(await api(`subscriptions/${subscription.id}/review-first-charge/`, { method: 'POST', body: JSON.stringify({ include_start_month: include }) })); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function apply() {
    if (!await confirmAction(`Definir a primeira cobrança de ${subscription.name} em ${dateLabel(preview.first_charge_date)}?`)) return;
    setBusy(true); setError('');
    try { await api(`subscriptions/${subscription.id}/review-first-charge/`, { method: 'POST', body: JSON.stringify({ include_start_month: include, apply: true, confirmation: 'REVISAR' }) }); saved('Primeira cobrança revisada com segurança.'); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="dialog" onCancel={close}>
    <div className="dialog-heading"><div><span className="eyebrow">REVISÃO INDIVIDUAL</span><h2>Primeira cobrança de {subscription.name}</h2></div><button type="button" className="icon-button" onClick={close} aria-label="Fechar"><X size={20}/></button></div>
    <p className="form-note">Esta ação só é permitida quando ainda não existe histórico da assinatura.</p>
    <div className="payment-mode"><button type="button" className={include ? 'selected' : ''} onClick={() => { setInclude(true); setPreview(null); }}>Incluir mês inicial</button><button type="button" className={!include ? 'selected' : ''} onClick={() => { setInclude(false); setPreview(null); }}>Próxima regular</button></div>
    {error && <div role="alert" className="alert error">{error}</div>}
    {preview && <div className="subscription-preview"><strong>Primeira cobrança: {dateLabel(preview.first_charge_date)}</strong>{!preview.can_apply && <small className="negative">{preview.reason}</small>}</div>}
    <div className="dialog-footer"><button type="button" className="button secondary" onClick={close}>Cancelar</button><button type="button" className="button secondary" disabled={busy} onClick={review}>{busy ? 'Verificando…' : 'Calcular'}</button><button type="button" className="button primary" disabled={busy || !preview?.can_apply} onClick={apply}>Aplicar revisão</button></div>
  </dialog>;
}
