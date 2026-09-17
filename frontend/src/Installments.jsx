import React, { useEffect, useRef, useState } from 'react';
import { Check, LoaderCircle, Receipt, X } from 'lucide-react';
import { MoneyValue, useValueVisibility, PrivacyButton } from './PrivacyContext';
import { api, dateLabel, money, today } from './api';
import { confirmAction } from './confirm';

const requestId = () => globalThis.crypto?.randomUUID?.() || `purchase-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function originOptions(data) {
  return [
    ...data.accounts.filter(row => row.is_active).map(row => [`account:${row.id}`, `Conta · ${row.name}`]),
    ...data.cards.filter(row => row.is_active).map(row => [`card:${row.id}`, `Cartão · ${row.name}`]),
  ];
}

export function InstallmentDialog({ data, month, close, saved }) {
  const dialog = useRef(null);
  const previewKey = useRef('');
  const [values, setValues] = useState({
    description: '', total_amount: '', installment_count: 2, purchase_date: today(),
    first_month: `${month}-01`, category: '', origin: '', notes: '', request_id: requestId(),
  });
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { dialog.current.showModal(); }, []);
  const change = (name, value) => { setValues(current => ({ ...current, [name]: value })); setPreview(null); setPreviewBusy(false); previewKey.current = ''; };
  const payload = () => {
    const [kind, id] = values.origin.split(':');
    return {
      ...values,
      installment_count: Number(values.installment_count),
      first_month: `${values.first_month.slice(0, 7)}-01`,
      category: Number(values.category),
      account: kind === 'account' ? Number(id) : null,
      card: kind === 'card' ? Number(id) : null,
    };
  };
  async function showPreview() {
    setPreviewBusy(true); setError('');
    const current = payload();
    const key = JSON.stringify(current);
    previewKey.current = key;
    try {
      const result = await api('installment-purchases/preview/', { method: 'POST', body: JSON.stringify(current) });
      if (previewKey.current === key) setPreview(result);
    } catch (e) { if (previewKey.current === key) setError(e.message); }
    finally { if (previewKey.current === key) setPreviewBusy(false); }
  }
  async function submit(e) {
    e.preventDefault();
    const current = payload();
    if (!preview || previewKey.current !== JSON.stringify(current) || !preview.can_create) {
      setError('Revise uma prévia atualizada antes de salvar.'); return;
    }
    setBusy(true); setError('');
    try {
      const result = await api('installment-purchases/', { method: 'POST', body: JSON.stringify(current) });
      saved(`Compra registrada em ${result.installment_count} parcelas.`);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="dialog installment-dialog" onCancel={close} onClick={e => { if (e.target === dialog.current) close(); }}>
    <form onSubmit={submit}>
      <div className="dialog-heading"><div><span className="eyebrow">COMPROMISSOS MENSAIS</span><h2>Registrar compra parcelada</h2></div><button type="button" className="icon-button" onClick={close} aria-label="Fechar"><X size={20}/></button></div>
      <p className="form-note">Informe o valor total. O Clareza distribuirá os centavos e mostrará cada competência antes de salvar.</p>
      <div className="form-grid">
        <label>Descrição<input autoFocus required value={values.description} onChange={e => change('description', e.target.value)}/></label>
        <label>Valor total (R$)<input required type="number" min=".02" step=".01" value={values.total_amount} onChange={e => change('total_amount', e.target.value)}/></label>
        <label>Quantidade de parcelas<input required type="number" min="2" max="120" value={values.installment_count} onChange={e => change('installment_count', e.target.value)}/></label>
        <label>Data da compra<input required type="date" max={today()} value={values.purchase_date} onChange={e => change('purchase_date', e.target.value)}/></label>
        <label>Primeira competência<input required type="month" value={values.first_month.slice(0, 7)} onChange={e => change('first_month', e.target.value)}/></label>
        <label>Categoria<select required value={values.category} onChange={e => change('category', e.target.value)}><option value="">Selecione</option>{data.categories.filter(row => row.is_active).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label className="wide">Conta ou cartão<select required value={values.origin} onChange={e => change('origin', e.target.value)}><option value="">Selecione</option>{originOptions(data).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label className="wide">Observação <small>· opcional</small><textarea value={values.notes} onChange={e => change('notes', e.target.value)}/></label>
      </div>
      {error && <div role="alert" className="alert error">{hidden ? 'Existe um conflito financeiro. Mostre os valores para consultar os detalhes.' : error}</div>}
      <div className="preview-actions"><button type="button" className="button secondary" disabled={previewBusy || busy} onClick={showPreview}>{previewBusy ? <><LoaderCircle className="spin" size={16}/>Calculando…</> : 'Calcular prévia'}</button>{preview && <strong>Soma: <MoneyValue value={preview.sum} /></strong>}</div>
      {preview && <div className="installment-preview" aria-label="Prévia das parcelas">{preview.schedule.map(row => <div key={row.number}><span><strong>{row.number}/{preview.installment_count}</strong>{dateLabel(row.month)}</span><strong><MoneyValue value={row.amount} /></strong></div>)}{preview.conflicts.map((row, index) => <p className="negative" key={index}>{row.message}</p>)}</div>}
      <div className="dialog-footer"><button type="button" className="button secondary" onClick={close}>Cancelar</button><button className="button primary" disabled={busy || !preview?.can_create}>{busy ? 'Salvando…' : 'Confirmar parcelamento'}<Check size={16}/></button></div>
    </form>
  </dialog>;
}

export function InstallmentDetailsDialog({ purchaseId, close, saved }) {
  const dialog = useRef(null);
  const [purchase, setPurchase] = useState(null);
  const [error, setError] = useState('');
  const next = new Date(`${today()}T12:00:00`); next.setMonth(next.getMonth() + 1);
  const [fromMonth, setFromMonth] = useState(next.toLocaleDateString('sv-SE').slice(0, 7));
  const [busy, setBusy] = useState(false);
  useEffect(() => { dialog.current.showModal(); api(`installment-purchases/${purchaseId}/`).then(setPurchase).catch(e => setError(e.message)); }, [purchaseId]);
  async function cancelRemaining() {
    if (!await confirmAction(`Cancelar as parcelas a partir de ${fromMonth.split('-').reverse().join('/')}? Isso não executa estorno financeiro.`)) return;
    setBusy(true); setError('');
    try {
      await api(`installment-purchases/${purchaseId}/cancel-remaining/`, { method: 'POST', body: JSON.stringify({ from_month: `${fromMonth}-01`, confirmation: 'CANCELAR' }) });
      saved('Parcelas restantes canceladas. O histórico anterior foi preservado.');
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="dialog installment-dialog" onCancel={close}>
    <div className="dialog-heading"><div><span className="eyebrow">CRONOGRAMA DA COMPRA</span><h2>{purchase?.description || 'Carregando parcelamento…'}</h2></div><button type="button" className="icon-button" onClick={close} aria-label="Fechar"><X size={20}/></button></div>
    {error && <div role="alert" className="alert error">{hidden ? 'Existe um conflito financeiro. Mostre os valores para consultar os detalhes.' : error}</div>}
    {!purchase ? <div className="loading"><LoaderCircle className="spin" size={20}/>Carregando…</div> : <>
      <div className="purchase-summary"><span><Receipt size={18}/>Total original <strong><MoneyValue value={purchase.total_amount} /></strong></span><span>Compra em {dateLabel(purchase.purchase_date)} · {purchase.origin}</span></div>
      <div className="installment-preview">{purchase.schedule.map(row => { const affected = !row.cancelled && row.month.slice(0, 7) >= fromMonth; return <div className={row.cancelled ? 'cancelled' : affected ? 'affected' : ''} key={row.number}><span><strong>{row.number}/{purchase.installment_count}</strong>{dateLabel(row.month)}{row.cancelled && <small>Cancelada</small>}{affected && <small>Será cancelada</small>}</span><strong><MoneyValue value={row.amount} /></strong></div>; })}</div>
      <div className="cancel-installments"><label>Cancelar restantes a partir de<input type="month" min={today().slice(0, 7)} value={fromMonth} onChange={e => setFromMonth(e.target.value)}/></label><button type="button" className="button danger" disabled={busy || !fromMonth} onClick={cancelRemaining}>{busy ? 'Cancelando…' : 'Cancelar restantes'}</button></div>
    </>}
  </dialog>;
}
