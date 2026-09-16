import ProfilePage, { Avatar } from './Profile';
import { InstallmentDialog, InstallmentDetailsDialog } from './Installments';
import { SubscriptionDialog, ReviewFirstChargeDialog } from './Subscriptions';
import { confirmAction } from './confirm';
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { LayoutDashboard, Wallet, CreditCard, ArrowLeftRight, Receipt, Repeat2, Target, ChartNoAxesCombined, CalendarClock, History, Plus, ArrowUpRight, ArrowDownRight, ArrowRight, ChevronLeft, ChevronRight, X, Check, Pencil, Trash2, Bell, Search, Menu, Landmark, CircleHelp, LoaderCircle, ChevronDown, Sun, CheckCircle2, AlertCircle, LogOut } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, PieChart, Pie, Cell } from 'recharts';
import { api, money, dateLabel, today } from './api';
const NAV = [['/', 'Visão geral', LayoutDashboard], ['/accounts', 'Minhas contas', Wallet], ['/cards', 'Cartões', CreditCard], ['/transactions', 'Movimentações', ArrowLeftRight], ['/invoices', 'Faturas', Receipt], ['/subscriptions', 'Assinaturas', Repeat2], ['/goals', 'Metas', Target], ['/planning', 'Planejamento', ChartNoAxesCombined], ['/payments', 'Vencimentos', CalendarClock], ['/history', 'Histórico', History]];
const COLORS = ['#edc348', '#929978', '#566955', '#d1d5c5', '#db995d', '#738692', '#b5a0b4'];
const MONTHS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
const ENDPOINTS = ['accounts', 'cards', 'categories', 'transactions', 'invoices', 'subscriptions', 'goals', 'bills'];
const TITLES = {
  accounts: 'conta',
  cards: 'cartão',
  transactions: 'movimentação',
  invoices: 'fatura',
  subscriptions: 'assinatura',
  goals: 'meta',
  bills: 'conta a pagar',
  contributions: 'aporte',
  categories: 'categoria'
};
const emptyData = Object.fromEntries(ENDPOINTS.map(k => [k, []]));
const field = (name, label, type = 'text', extra = {}) => ({
  name,
  label,
  type,
  ...extra
});
function FormDialog({
  modal,
  data,
  month,
  close,
  saved,
  switchToInstallments
}) {
  const {
    type,
    item = {}
  } = modal;
  const dialog = useRef(null);
  const initial = {
    date: today(),
    month: `${month}-01`,
    start_date: today(),
    due_date: `${month}-15`,
    billing_day: 10,
    due_day: 12,
    closing_day: 5,
    kind: 'expense',
    account_type: 'checking',
    term_type: 'short',
    priority: 1,
    ...item
  };
  if (item.balance != null) initial.balance = item.balance;
  initial.balance_month = `${month}-01`;
  initial.origin = item.card ? `card:${item.card}` : item.account ? `account:${item.account}` : '';
  const [values, setValues] = useState(initial);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const options = key => data[key].filter(x => x.is_active !== false || x.id === item[key === 'accounts' ? 'account' : key === 'cards' ? 'card' : 'category']).map(x => [x.id, x.name]);
  const origin = field('origin', 'Conta ou cartão', 'select', {
    options: [...options('accounts').map(([id, n]) => [`account:${id}`, `Conta · ${n}`]), ...options('cards').map(([id, n]) => [`card:${id}`, `Cartão · ${n}`])]
  });
  const category = field('category', 'Categoria', 'select', {
    options: options('categories')
  });
  const account = field('account', 'Conta', 'select', {
    options: options('accounts')
  });
  const amount = field('amount', 'Valor (R$)', 'number', {
    min: '.01',
    step: '.01'
  });
  const competency = field('month', 'Competência', 'month');
  let fields = {
    accounts: [field('name', 'Nome da conta'), field('institution', 'Instituição', 'text', {
      optional: true
    }), field('account_type', 'Tipo de conta', 'select', {
      options: [['checking', 'Conta corrente'], ['savings', 'Poupança'], ['investment', 'Investimento / reserva'], ['cash', 'Dinheiro']]
    }), field('balance', 'Saldo informado (R$)', 'number', {
      min: '0',
      step: '.01'
    }), field('balance_month', 'Mês do saldo', 'month')],
    cards: [field('name', 'Nome do cartão'), account, field('closing_day', 'Dia de fechamento', 'number', {
      min: 1,
      max: 31
    }), field('due_day', 'Dia de vencimento', 'number', {
      min: 1,
      max: 31
    })],
    transactions: [field('description', 'Descrição'), amount, field('kind', 'Tipo', 'select', {
      options: [['expense', 'Despesa'], ['income', 'Receita']]
    }), origin, category, field('date', 'Data', 'date'), competency, field('notes', 'Observação', 'textarea', {
      optional: true
    })],
    invoices: [field('card', 'Cartão', 'select', {
      options: options('cards')
    }), competency, field('due_date', 'Vencimento', 'date'), field('manual_amount', 'Total manual (R$)', 'number', {
      optional: true,
      min: 0,
      step: '.01',
      hint: 'Deixe vazio para somar os gastos do cartão. O total manual já inclui os gastos detalhados.'
    })],
    subscriptions: [field('name', 'Nome do serviço'), amount, origin, category, field('billing_day', 'Dia da cobrança', 'number', {
      min: 1,
      max: 31
    }), ...(!item.id ? [field('start_date', 'Início da assinatura', 'date')] : [])],
    goals: [field('name', 'Nome da meta'), field('target_amount', 'Valor alvo (R$)', 'number', {
      min: '.01',
      step: '.01'
    }), field('start_date', 'Data inicial', 'date', {
      disabled: !!item.id
    }), field('target_date', 'Quero realizar até', 'date'), field('term_type', 'Horizonte', 'select', {
      options: [['short', 'Curto prazo'], ['medium', 'Médio prazo'], ['long', 'Longo prazo']]
    }), field('priority', 'Prioridade (1 = maior)', 'number', {
      min: 1,
      max: 5
    }), field('description', 'Descrição', 'textarea', {
      optional: true
    })],
    bills: [field('description', 'Descrição'), amount, account, category, competency, field('due_date', 'Vencimento', 'date')],
    contributions: [amount, field('date', 'Data do aporte', 'date')],
    categories: [field('name', 'Nome da categoria')]
  }[type];
  useEffect(() => {
    dialog.current.showModal();
  }, []);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const payload = {};
    for (const f of fields) {
      let v = values[f.name];
      if (f.type === 'month' && v) v = `${v.slice(0, 7)}-01`;
      if (f.name === 'origin') {
        const [kind, id] = (v || '').split(':');
        payload.account = kind === 'account' ? Number(id) : null;
        payload.card = kind === 'card' ? Number(id) : null;
      } else payload[f.name] = v === '' || v == null ? f.name === 'manual_amount' ? null : '' : v;
    }
    try {
      const url = type === 'contributions' ? `goals/${modal.goalId}/contributions/` : `${type}/${item.id ? `${item.id}/` : ''}`;
      await api(url, {
        method: item.id && type !== 'contributions' ? 'PATCH' : 'POST',
        body: JSON.stringify(payload)
      });
      saved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return <dialog ref={dialog} className="dialog" onCancel={close} onClick={e => {
    if (e.target === dialog.current) close();
  }}><form onSubmit={submit}>
    <div className="dialog-heading"><div><span className="eyebrow">SUAS FINANÇAS, EM DIA</span><h2>{type === 'contributions' ? 'Registrar aporte' : `${item.id ? 'Editar' : 'Adicionar'} ${TITLES[type]}`}</h2></div><button type="button" className="icon-button" onClick={close} aria-label="Fechar"><X size={20} /></button></div>
    {type === 'accounts' && <p className="form-note">O saldo é uma posição informada manualmente. Movimentações e pagamentos não alteram esse valor automaticamente.</p>}
    {type === 'contributions' && <p className="form-note">Aportes registram o progresso da meta. Se o dinheiro já está em uma conta ou reserva, ele já faz parte dos seus ativos.</p>}
    {type === 'transactions' && !item.id && values.kind === 'expense' && <div className="payment-mode" role="group" aria-label="Forma de pagamento"><button type="button" className="selected">À vista</button><button type="button" onClick={switchToInstallments}>Parcelada</button></div>}
    <div className="form-grid">{fields.map(f => <label className={f.type === 'textarea' || f.hint ? 'wide' : ''} key={f.name}>{f.label}{f.optional && <small> · opcional</small>}{f.type === 'select' ? <select required={!f.optional} value={values[f.name] ?? ''} onChange={e => setValues({
            ...values,
            [f.name]: e.target.value
          })}><option value="">Selecione</option>{f.options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select> : f.type === 'textarea' ? <textarea value={values[f.name] || ''} onChange={e => setValues({
            ...values,
            [f.name]: e.target.value
          })} /> : <input autoFocus={f === fields[0]} required={!f.optional} disabled={f.disabled} type={f.type} min={f.min} max={f.max} step={f.step} value={f.type === 'month' ? (values[f.name] || '').slice(0, 7) : values[f.name] ?? ''} onChange={e => setValues({
            ...values,
            [f.name]: e.target.value
          })} />}{f.hint && <small className="hint">{f.hint}</small>}</label>)}</div>
    {error && <div role="alert" className="alert error">{error}</div>}<div className="dialog-footer"><button type="button" className="button secondary" onClick={close}>Cancelar</button><button className="button primary" disabled={busy}>{busy ? 'Salvando…' : 'Salvar'}<Check size={16} /></button></div>
  </form></dialog>;
}
function Empty({
  icon: Icon = Wallet,
  title = 'Tudo começa com um registro',
  text = 'Adicione seus dados para acompanhar suas finanças por aqui.',
  action,
  button = 'Adicionar registro'
}) {
  return <div className="empty"><span className="empty-icon"><Icon size={27} /></span><h3>{title}</h3><p>{text}</p>{action && <button className="button secondary" onClick={action}><Plus size={16} />{button}</button>}</div>;
}
function Panel({
  title,
  sub,
  action,
  children,
  className = ''
}) {
  return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{sub && <p>{sub}</p>}</div>{action}</div>{children}</section>;
}
function Stat({
  label,
  value,
  icon: Icon,
  note,
  highlight,
  negative
}) {
  return <div className={`stat ${highlight ? 'highlight' : ''}`}><div className="stat-top"><span>{label}</span><Icon size={19} /></div><strong className={negative ? 'negative' : ''}>{money(value)}</strong><span className="stat-note">{note}</span></div>;
}
function GoalCard({
  goal,
  add,
  edit
}) {
  return <div className="goal-card"><div className="goal-head"><span className="goal-symbol"><Target size={19} /></span><span className="tag">{{
          short: 'Curto prazo',
          medium: 'Médio prazo',
          long: 'Longo prazo'
        }[goal.term_type]}</span>{edit && <button className="icon-button" aria-label={`Editar ${goal.name}`} onClick={edit}><Pencil size={15} /></button>}</div><h3>{goal.name}</h3><div className="goal-amount"><strong>{money(goal.accumulated)}</strong><span>de {money(goal.target_amount)}</span></div><div className="progress"><span style={{
        width: `${goal.progress}%`
      }} /></div><div className="goal-footer"><span>{Number(goal.progress)}% concluído</span><span>{dateLabel(goal.target_date)}</span></div><div className="goal-monthly"><span>{goal.overdue ? 'Prazo encerrado' : 'Aporte necessário'}</span><strong>{money(goal.monthly_required)}<small>/mês</small></strong></div>{add && <button className="button secondary full" onClick={add}><Plus size={15} />Registrar aporte</button>}</div>;
}
function PaymentList({
  rows,
  pay,
  all = false
}) {
  const visible = all ? rows : rows.filter(p => p.status !== 'paid').slice(0, 4);
  return visible.length ? <div className="payment-list">{visible.map(p => <div className="payment-row" key={p.key}><div className={`date-box ${p.status === 'overdue' ? 'late' : p.days_until <= 7 && !['paid', 'forecast', 'registered'].includes(p.status) ? 'soon' : ''}`}><strong>{p.due_date.slice(8)}</strong><span>{MONTHS[Number(p.due_date.slice(5, 7)) - 1]}</span><small>{p.due_date.slice(0, 4)}</small></div><div className="payment-info"><strong>{p.description}</strong><span className={p.status === 'overdue' ? 'negative' : ''}>{p.status === 'paid' ? 'Pago' : p.status === 'registered' ? 'Cobrança registrada' : p.status === 'forecast' ? 'Compromisso previsto' : p.status === 'overdue' ? 'Vencido · pendente' : p.days_until === 0 ? 'Vence hoje' : p.days_until <= 7 ? `Vence em ${p.days_until} dia(s)` : 'A vencer'} · {p.origin}</span><small>Competência {p.month.slice(5, 7)}/{p.month.slice(0, 4)} · vencimento {dateLabel(p.due_date)}</small></div><strong>{money(p.amount)}</strong>{pay && p.can_pay && <button className="icon-button pay" title="Registrar pagamento" aria-label={`Marcar ${p.description} como pago`} onClick={() => pay(p)}><Check size={18} /></button>}</div>)}</div> : <Empty icon={CheckCircle2} title="Nenhum pagamento nesta competência" text="Não há obrigações para o mês selecionado." />;
}
function Categories({
  rows
}) {
  return rows.length ? <div className="category-content"><div className="donut"><ResponsiveContainer width="100%" height={185}><PieChart><Pie data={rows.map(r => ({
            ...r,
            amount: Number(r.amount)
          }))} dataKey="amount" innerRadius={58} outerRadius={79} paddingAngle={3} stroke="none">{rows.map((r, i) => <Cell key={r.name} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip formatter={v => money(v)} /></PieChart></ResponsiveContainer><div className="donut-center"><small>Categorias</small><strong>{rows.length}</strong></div></div><div className="category-legend">{rows.map((r, i) => <div key={r.name}><span className="dot" style={{
          background: COLORS[i % COLORS.length]
        }} /><span>{r.name}</span><strong>{money(r.amount)}</strong></div>)}</div></div> : <Empty icon={ChartNoAxesCombined} title="Seus gastos, bem explicados" text="Registre despesas para ver a distribuição por categoria." />;
}
function Evolution({
  rows
}) {
  return <div className="evolution"><ResponsiveContainer width="100%" height={230}><AreaChart data={rows.map(r => ({
        ...r,
        net_worth: Number(r.net_worth),
        label: MONTHS[Number(r.month.slice(5, 7)) - 1]
      }))} margin={{
        left: 8,
        right: 12,
        top: 15,
        bottom: 0
      }}><defs><linearGradient id="gold" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#e7be43" stopOpacity={.24} /><stop offset="95%" stopColor="#e7be43" stopOpacity={0} /></linearGradient></defs><CartesianGrid vertical={false} stroke="#eceee7" strokeDasharray="4 4" /><XAxis dataKey="label" axisLine={false} tickLine={false} tick={{
          fill: '#83877c',
          fontSize: 11
        }} dy={8} /><YAxis axisLine={false} tickLine={false} tick={{
          fill: '#83877c',
          fontSize: 11
        }} tickFormatter={v => Math.abs(v) >= 1000 ? `${v / 1000} mil` : v} /><Tooltip formatter={v => [money(v), 'Patrimônio líquido']} contentStyle={{
          borderRadius: 12,
          border: '1px solid #e5e7df'
        }} /><Area type="monotone" dataKey="net_worth" stroke="#cba52d" strokeWidth={2.5} fill="url(#gold)" /></AreaChart></ResponsiveContainer></div>;
}
export default function App() {
  const [profile, setProfile] = useState(null);
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem('clareza-theme') === 'dark' ? 'dark' : 'light'; } catch { return 'light'; } });
  const [themeBusy, setThemeBusy] = useState(false);
  const [path, setPath] = useState(location.pathname);
  const [month, setMonth] = useState(today().slice(0, 7));
  const [data, setData] = useState(emptyData);
  const [summary, setSummary] = useState(null);
  const [modal, setModal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [mobile, setMobile] = useState(false);
  const [origin, setOrigin] = useState('');
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [contributions, setContributions] = useState([]);
  const [previousPending, setPreviousPending] = useState(null);
  const [pendingBusy, setPendingBusy] = useState(false);
  const generation = useRef(0);
  const [route, detailId] = path.slice(1).split('/');
  const section = route || 'dashboard';
  const title = section === 'profile' ? 'Meu perfil' : NAV.find(([p]) => p === `/${route || ''}`)?.[1] || 'Visão geral';
  const query = `year=${month.slice(0, 4)}&month=${Number(month.slice(5))}`;
  const load = useCallback(async () => {
    const ticket = ++generation.current;
    setLoading(true);
    setError('');
    setSummary(null);
    setData(emptyData);
    setPreviousPending(null);
    try {
      const userProfile = await api('profile/');
      if (ticket !== generation.current) return;
      setProfile(userProfile);
      if (userProfile.deleted) { setSummary(null); setData(emptyData); return; }
      if (['light', 'dark'].includes(userProfile.theme)) setTheme(userProfile.theme);
      try { await api('sync/', { method: 'POST', body: '{}' }); }
      catch (syncError) { throw new Error(`Sincronização não concluída. Os dados desta competência não foram atualizados.\n${syncError.message}`); }
      let filter = origin ? `&account_id=${origin}` : '';
      if (route === 'accounts' && detailId) filter = `&account_id=${detailId}`;
      if (route === 'cards' && detailId) filter = `&card_id=${detailId}`;
      const summaryUrl = route === 'planning' ? `planning/${month.slice(0, 4)}/${Number(month.slice(5))}/?${filter.slice(1)}` : route === 'history' ? `history/${month.slice(0, 4)}/${Number(month.slice(5))}/?${filter.slice(1)}` : `dashboard/?${query}${filter}`;
      const results = await Promise.all([api(summaryUrl), ...ENDPOINTS.map(key => api(key === 'transactions' ? `transactions/monthly/?${query}${filter}` : `${key}/?${['invoices', 'bills'].includes(key) ? query : ''}`))]);
      if (ticket !== generation.current) return;
      setSummary(results[0]);
      setData(Object.fromEntries(ENDPOINTS.map((key, i) => [key, results[i + 1]])));
      if (route === 'goals' && detailId) setContributions(await api(`goals/${detailId}/contributions/`));
    } catch (e) {
      if (ticket === generation.current) setError(e.message);
    } finally {
      if (ticket === generation.current) setLoading(false);
    }
  }, [query, origin, route, detailId]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    const handler = () => setPath(location.pathname);
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, []);
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(''), 4500);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('clareza-theme', theme); } catch { /* Theme still works without local storage. */ }
  }, [theme]);
  async function changeTheme(value) {
    if (themeBusy || value === theme) return;
    const previous = theme;
    setTheme(value); setThemeBusy(true);
    try { await api('profile/', { method: 'PATCH', body: JSON.stringify({ theme: value }) }); }
    catch (e) { setTheme(previous); setError(e.message); }
    finally { setThemeBusy(false); }
  }
  function accountDeleted() {
    generation.current += 1;
    setProfile({ deleted: true }); setData(emptyData); setSummary(null); setModal(null);
    setTheme('light'); setLoading(false); setError(''); setToast('');
  }
  async function createWorkspace() {
    setLoading(true); setError('');
    try { await api('profile/', { method: 'POST', body: JSON.stringify({ confirmation: 'CRIAR' }) }); navigate('/'); await load(); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }
  function navigate(p) {
    history.pushState({}, '', p);
    setPath(p);
    setMobile(false);
    setSearch('');
    setCategoryFilter('');
    setOrigin('');
  }
  function add(type, item) {
    if (type === 'subscriptions' && !item) { setModal({ type: 'subscription-create' }); return; }
    setModal({
      type,
      item
    });
  }
  async function togglePreviousPending() {
    if (previousPending !== null) { setPreviousPending(null); return; }
    setPendingBusy(true); setError('');
    try { setPreviousPending(await api(`payments/pending/?${query}`)); }
    catch (e) { setError(e.message); }
    finally { setPendingBusy(false); }
  }
  async function mutate(url, body, message, method = 'POST') {
    try {
      await api(url, {
        method,
        body: body ? JSON.stringify(body) : undefined
      });
      setToast(message);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }
  const pay = p => mutate(`${p.kind === 'invoice' ? 'invoices' : 'bills'}/${p.id}/pay/`, {}, 'Pagamento registrado. Atualize o saldo da conta se necessário.');
  const editButton = (type, item) => <button className="icon-button" aria-label={`Editar ${item.name || item.description || 'fatura'}`} onClick={() => add(type, item)}><Pencil size={15} /></button>;
  const archive = (type, item) => mutate(`${type}/${item.id}/`, {
    is_active: !item.is_active
  }, item.is_active ? 'Cadastro arquivado. Histórico preservado.' : 'Cadastro reativado.', 'PATCH');
  const link = (label, p) => <button className="text-button" onClick={() => navigate(p)}>{label}<ArrowRight size={14} /></button>;
  const activeGoals = summary?.goals.filter(g => g.is_active) || [];
  const currentAccount = detailId && data.accounts.find(a => String(a.id) === detailId);
  const currentCard = detailId && data.cards.find(a => String(a.id) === detailId);
  const txRows = data.transactions.filter(t => {
    const accountId = route === 'accounts' && detailId ? detailId : origin;
    const card = data.cards.find(c => c.id === t.card);
    return (!accountId || String(t.account || card?.account) === String(accountId)) && (!(route === 'cards' && detailId) || String(t.card) === detailId) && (!categoryFilter || String(t.category) === categoryFilter) && t.description.toLowerCase().includes(search.toLowerCase());
  });
  function transactionsPanel() {
    return <Panel title="Movimentações do mês" sub={summary.is_forecast ? 'Valores registrados e previsões para esta competência' : 'Despesas e receitas de todas as suas origens'} action={<button className="button secondary small" onClick={() => add('categories')}><Plus size={14} />Categoria</button>}><div className="table-filters"><div className="search-input"><Search size={16} /><input aria-label="Buscar movimentação" placeholder="Buscar movimentação…" value={search} onChange={e => setSearch(e.target.value)} /></div><select aria-label="Filtrar por categoria" value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)}><option value="">Todas as categorias</option>{data.categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>{txRows.length ? <div className="table-scroll"><table><thead><tr><th>Descrição</th><th>Categoria</th><th>Origem</th><th>Data</th><th className="right">Valor</th><th><span className="sr-only">Ações</span></th></tr></thead><tbody>{txRows.map(t => <tr key={t.key || t.id}><td><span className={`transaction-icon ${t.kind === 'income' ? 'income' : ''}`}>{t.kind === 'income' ? <ArrowDownRight size={16} /> : <ArrowUpRight size={16} />}</span><strong>{t.description}{t.installment_purchase ? ` — parcela ${t.installment_number}/${t.installment_count}` : ''}</strong>{t.is_projected && <span className="tiny forecast">Previsto</span>}{t.is_programmed && <span className="tiny">Programado</span>}{t.subscription && !t.is_projected && <span className="tiny">Recorrente</span>}</td><td><span className="tag">{t.category_name}</span></td><td>{t.origin}</td><td>{dateLabel(t.date)}</td><td className={`right amount ${t.kind === 'income' ? 'positive' : ''}`}>{t.kind === 'income' ? '+' : '−'} {money(t.amount)}</td><td><div className="row-actions">{t.installment_purchase ? <button className="text-button" onClick={() => setModal({ type: 'installment-details', purchaseId: t.installment_purchase })}>Ver parcelas</button> : t.is_projected ? <button className="text-button" onClick={() => navigate('/subscriptions')}>Ver assinatura</button> : !t.subscription && <>{editButton('transactions', t)}<button className="icon-button" aria-label={`Excluir ${t.description}`} onClick={() => {
                      confirmAction(`Excluir “${t.description}”? Isso corrige também os totais históricos desse mês.`).then(confirmed => {
                        if (confirmed) mutate(`transactions/${t.id}/`, null, 'Movimentação excluída.', 'DELETE');
                      });
                    }}><Trash2 size={15} /></button></>}</div></td></tr>)}</tbody></table></div> : <Empty icon={ArrowLeftRight} title={search || categoryFilter ? 'Nenhum resultado encontrado' : 'Seu mês ainda está em branco'} text="Registre suas receitas e despesas para começar a acompanhar." action={() => add('transactions')} />}</Panel>;
  }
  function planning() {
    return <><div className="planning-layout"><Panel title="Um plano para o seu mês" sub="Entenda para onde vai cada real"><div className="planning-row"><span><span className="plan-icon green"><ArrowDownRight size={18} /></span>Renda do mês</span><strong>{money(summary.income)}</strong></div><div className="planning-row"><span><span className="plan-icon"><ArrowUpRight size={18} /></span>{summary.is_forecast ? 'Gastos previstos' : 'Gastos do mês'}</span><strong>− {money(summary.expenses)}</strong></div><div className="planning-row"><span><span className="plan-icon yellow"><Target size={18} /></span>Aportes necessários para metas</span><strong>− {money(summary.goal_required)}</strong></div><div className="planning-total"><span>Dinheiro livre<strong className={Number(summary.free) < 0 ? 'negative' : ''}>{money(summary.free)}</strong></span><span className="plan-icon"><Wallet size={25} /></span></div><p className="footnote">Os gastos incluem despesas, parcelas, contas a pagar, faturas e assinaturas previstas uma única vez. Aportes já feitos não são descontados novamente.</p>{summary.is_forecast && !summary.has_income && <p className="forecast-note">Nenhuma receita foi cadastrada para esta competência. O saldo projetado não é uma certeza de déficit.</p>}</Panel><Panel title={summary.feasible ? 'Seu planejamento está equilibrado' : 'Seu plano precisa de atenção'} sub="Renda, gastos e metas na mesma conta"><div className={`planning-status ${summary.feasible ? '' : 'warning'}`}>{summary.feasible ? <CheckCircle2 size={32} /> : <AlertCircle size={32} />}<h3>{summary.feasible ? 'Cabe no seu mês' : 'Vamos ajustar o plano?'}</h3><p>{summary.feasible ? `Depois dos gastos e das metas, sobram ${money(summary.free)} neste mês.` : `O déficit é de ${money(summary.deficit)}. Revise os gastos ou aumente o prazo das metas. Metas vencidas também precisam de revisão.`}</p></div><div className="planning-mini"><span>Parcelas nesta competência</span><strong>{money(summary.installment_total)}</strong></div><div className="planning-mini"><span>Assinaturas previstas</span><strong>{money(summary.subscription_projected_total)}</strong></div><button className="button secondary full" onClick={() => add('transactions', {
          kind: 'income'
        })}><Plus size={16} />Registrar receita</button></Panel></div>{summary.forecast && <Panel title="Próximos 12 meses" sub="Parcelas e assinaturas ativas entram na estimativa"><div className="table-scroll"><table><thead><tr><th>Competência</th><th>Parcelas</th><th>Assinaturas previstas</th><th>Gastos previstos</th><th>Receita cadastrada</th></tr></thead><tbody>{summary.forecast.map(row => <tr key={row.month}><td>{MONTHS[Number(row.month.slice(5, 7)) - 1]} / {row.month.slice(0, 4)}</td><td>{money(row.installment_total)}</td><td>{money(row.subscription_projected_total)}</td><td className="amount">{money(row.expenses)}</td><td className={row.has_income ? 'positive' : 'muted'}>{row.has_income ? money(row.income) : 'Não informada'}</td></tr>)}</tbody></table></div></Panel>}</>;
  }
  const subtitles = {
    profile: 'Seus dados e preferências, do seu jeito.',
    dashboard: 'Um olhar para o seu dinheiro. Mais espaço para seus planos.',
    accounts: 'Cada conta no seu lugar. Seu dinheiro em uma só visão.',
    cards: 'Acompanhe seus cartões e mantenha as faturas sob controle.',
    transactions: 'Os pequenos registros que tornam tudo mais claro.',
    invoices: 'Todas as suas faturas, sem perder nenhum detalhe.',
    subscriptions: 'Saiba quanto seus serviços recorrentes custam por mês.',
    goals: 'Transforme os seus próximos planos em conquistas.',
    planning: 'Dê um destino ao seu dinheiro antes que o mês acabe.',
    payments: 'As próximas datas importantes para o seu bolso.',
    history: 'Olhe para trás e veja o caminho que você está construindo.'
  };
  const createType = {
    accounts: 'accounts',
    cards: 'cards',
    transactions: 'transactions',
    invoices: 'invoices',
    subscriptions: 'subscriptions',
    goals: 'goals',
    payments: 'bills',
    planning: 'transactions',
    history: 'transactions',
    dashboard: 'transactions'
  }[section] || 'transactions';
  if (profile?.deleted) return <div className="deleted-account"><div className="panel"><span className="goal-symbol"><CheckCircle2 size={28}/></span><h1>Conta excluída</h1><p>Seu perfil e seus dados financeiros foram apagados. Você pode começar novamente com um espaço vazio.</p>{error && <div className="alert error" role="alert">{error}</div>}<button className="button primary" disabled={loading} onClick={createWorkspace}>{loading ? 'Criando…' : 'Criar novo espaço'}</button></div></div>;
  return <div className="app"><aside className={`sidebar ${mobile ? 'open' : ''}`}><a className="brand" href="/" onClick={e => {
        e.preventDefault();
        navigate('/');
      }}><span className="brand-mark"><ChartNoAxesCombined size={23} /></span>clareza<span className="brand-dot">.</span></a><div className="workspace"><span className="workspace-icon"><Wallet size={18} /></span><div><strong>Minhas finanças</strong><small>Espaço pessoal</small></div><ChevronDown size={15} /></div><span className="nav-label">ACOMPANHAR</span><nav>{NAV.map(([p, label, Icon], i) => <React.Fragment key={p}>{i === 6 && <span className="nav-label second">PLANEJAR & CUIDAR</span>}<a href={p} className={(p === '/' ? path === '/' : path.startsWith(p)) ? 'active' : ''} onClick={e => {
            e.preventDefault();
            navigate(p);
          }}><Icon size={19} />{label}{p === '/payments' && summary?.payments.some(p => p.status === 'overdue') && <span className="nav-dot" />}</a></React.Fragment>)}</nav><div className="sidebar-tip"><Sun size={22} /><strong>Um pouco mais de clareza.</strong><p>Pequenos hábitos hoje.<br />Mais possibilidades amanhã.</p><span>Seu futuro começa aqui <ArrowUpRight size={14} /></span></div><button className="profile" aria-label="Abrir meu perfil" onClick={() => navigate('/profile')}><Avatar profile={profile}/><span className="profile-name"><strong>{profile?.display_name || 'Meu espaço'}</strong><small>Ver meu perfil</small></span><span className="online-dot" /></button></aside>
    {mobile && <button className="overlay" aria-label="Fechar menu" onClick={() => setMobile(false)} />}
    <div className="main-shell"><header className="topbar"><div><button className="icon-button mobile-menu" aria-label="Abrir menu" onClick={() => setMobile(true)}><Menu size={21} /></button><button className="header-profile-name" onClick={() => navigate('/profile')}>{profile?.display_name || 'Meu espaço'}</button><span className="breadcrumb">/</span><strong>{title}</strong></div><div><span className="local-badge"><span />Dados salvos localmente</span><button className="notification icon-button" aria-label="Ver vencimentos" onClick={() => navigate('/payments')}><Bell size={19} />{summary?.payments.some(p => p.status === 'overdue') && <i />}</button><button className="avatar-button" aria-label="Abrir perfil pelo avatar" onClick={() => navigate('/profile')}><Avatar profile={profile}/></button></div></header>
    <main><div className="page-heading"><div><span className="eyebrow">{section === 'dashboard' ? 'CUIDAR DO DINHEIRO É CUIDAR DE VOCÊ' : 'MINHAS FINANÇAS'}</span><h1>{detailId && section === 'accounts' ? currentAccount?.name || 'Conta' : detailId && section === 'cards' ? currentCard?.name || 'Cartão' : title}{section === 'dashboard' && <span className="heading-sun">✳</span>}</h1><p>{subtitles[section]}</p></div>{section !== 'profile' && <button className="button primary" onClick={() => add(createType)}><Plus size={18} />{section === 'dashboard' || section === 'transactions' ? 'Nova movimentação' : `Adicionar ${TITLES[createType]}`}</button>}</div>
    {section !== 'profile' && <div className="period-bar"><div className="period-control"><button className="icon-button" aria-label="Mês anterior" onClick={() => {
              const d = new Date(`${month}-15T12:00:00`);
              d.setMonth(d.getMonth() - 1);
              setMonth(d.toLocaleDateString('sv-SE').slice(0, 7));
            }}><ChevronLeft size={17} /></button><input aria-label="Mês de referência" type="month" value={month} onChange={e => {
              if (e.target.value) setMonth(e.target.value);
            }} /><button className="icon-button" aria-label="Próximo mês" onClick={() => {
              const d = new Date(`${month}-15T12:00:00`);
              d.setMonth(d.getMonth() + 1);
              setMonth(d.toLocaleDateString('sv-SE').slice(0, 7));
            }}><ChevronRight size={17} /></button>{month === today().slice(0, 7) && <span className="tag current-month">Mês atual</span>}</div>{!detailId && <select aria-label="Filtrar por conta" value={origin} onChange={e => setOrigin(e.target.value)}><option value="">Todas as contas</option>{data.accounts.map(a => <option key={a.id} value={a.id}>{a.name}{!a.is_active ? ' (arquivada)' : ''}</option>)}</select>}</div>}
    {error && <div className="alert error" role="alert"><AlertCircle size={18} /><div>{error.includes('fetch') ? 'Não foi possível conectar ao servidor. Verifique se o Django está em execução.' : error}</div><button className="text-button" onClick={load}>Tentar novamente</button></div>}
    {section === 'profile' && profile && !loading && <ProfilePage profile={profile} theme={theme} themeBusy={themeBusy} onTheme={changeTheme} onDeleted={accountDeleted} onSaved={value => { setProfile(value); setToast('Perfil atualizado com sucesso.'); }}/>}
    {loading ? <div className="loading" role="status"><LoaderCircle size={26} className="spin" />Organizando suas finanças…</div> : summary && <>
      {['dashboard', 'history', 'accounts', 'cards'].includes(section) && <div className="stats"><Stat label="Patrimônio líquido" value={summary.net_worth} icon={Wallet} highlight note="Seus ativos mais o dinheiro livre do mês" /><Stat label="Total em ativos" value={summary.assets} icon={ArrowDownRight} note="Saldos em contas e reservas" /><Stat label="Passivos em aberto" value={summary.liabilities} icon={ArrowUpRight} note="Não inclui compromissos de competências futuras" /><Stat label={summary.is_forecast ? 'Gastos previstos' : 'Gastos do mês'} value={summary.expenses} icon={Receipt} note={summary.is_forecast ? 'Inclui parcelas e assinaturas previstas' : 'Todas as despesas da competência'} /></div>}
      {section === 'dashboard' && <><div className="dashboard-grid"><Panel title="Evolução do patrimônio" sub="Uma visão dos últimos seis meses" action={<span className="chart-key"><span className="dot" />Patrimônio líquido</span>}><Evolution rows={summary.history} /></Panel><Panel title="Gastos por categoria" sub="Para onde seu dinheiro está indo" action={link('Ver gastos', '/transactions')}><Categories rows={summary.categories} /></Panel></div><div className="dashboard-grid bottom-grid"><Panel title="Pagamentos da competência" sub="Somente as obrigações do mês selecionado" action={link('Ver todos', '/payments')}><PaymentList rows={summary.payments} pay={pay} /></Panel><Panel title="Seu mês, planejado" sub="Mais intenção em cada escolha" action={link('Detalhes', '/planning')}><div className="mini-plan"><div><span>Renda do mês</span><strong className="positive">{money(summary.income)}</strong></div><div><span>Gastos do mês</span><strong>− {money(summary.expenses)}</strong></div><div><span>Reservado para metas</span><strong>− {money(summary.goal_required)}</strong></div><div className="mini-plan-total"><span>Dinheiro livre<small>Depois dos gastos e das metas</small></span><strong className={Number(summary.free) < 0 ? 'negative' : ''}>{money(summary.free)}</strong></div></div></Panel></div><Panel title="Um passo mais perto das suas metas" sub="Seus planos merecem sair do papel" action={link('Ver metas', '/goals')}>{activeGoals.length ? <div className="goal-grid">{activeGoals.slice(0, 3).map(g => <GoalCard key={g.id} goal={g} />)}</div> : <div className="goal-empty-inline"><span className="goal-symbol"><Target size={23} /></span><div><h3>Qual é a sua próxima conquista?</h3><p>Crie uma meta e descubra quanto guardar por mês.</p></div><button className="button secondary" onClick={() => add('goals')}><Plus size={16} />Criar minha primeira meta</button></div>}</Panel></>}
      {section === 'accounts' && !detailId && <div className="account-grid">{summary.accounts.map((a, i) => <section className={`account-card ${!a.is_active ? 'archived' : ''}`} key={a.id}><div className="account-top"><span className="bank-icon" style={{
                  background: COLORS[i % COLORS.length]
                }}>{a.name.slice(0, 2).toUpperCase()}</span><span className="tag">{a.is_active ? 'Ativa' : 'Arquivada'}</span>{editButton('accounts', a)}</div><h2>{a.name}</h2><p>{a.institution || 'Conta pessoal'}</p><span className="eyebrow">SALDO INFORMADO</span><strong className="account-balance">{money(a.balance)}</strong><small>Posição: {a.balance_month ? dateLabel(a.balance_month).slice(3) : 'sem registro'}</small><div className="account-bottom">{link('Ver detalhes', `/accounts/${a.id}`)}<button className="text-button muted" onClick={() => archive('accounts', a)}>{a.is_active ? 'Arquivar' : 'Reativar'}</button></div></section>)}<button className="add-card" onClick={() => add('accounts')}><Plus size={26} /><strong>Adicionar conta</strong><span>Conecte seus números, manualmente.</span></button></div>}
      {section === 'cards' && !detailId && <div className="account-grid">{data.cards.filter(c => !origin || String(c.account) === origin).map((c, i) => <section className="card-wrapper" key={c.id}><div className={`credit-card color-${i % 3}`}><div><Landmark size={25} /><span>{c.is_active ? 'CRÉDITO' : 'ARQUIVADO'}</span></div><span className="chip">▥</span><h2>{c.name}</h2><div><span>{data.accounts.find(a => a.id === c.account)?.name}</span><CreditCard size={24} /></div></div><div className="card-details"><span>Fecha dia <strong>{c.closing_day}</strong></span><span>Vence dia <strong>{c.due_day}</strong></span></div><div className="account-bottom">{link('Ver cartão', `/cards/${c.id}`)}{editButton('cards', c)}<button className="text-button muted" onClick={() => archive('cards', c)}>{c.is_active ? 'Arquivar' : 'Reativar'}</button></div></section>)}<button className="add-card" onClick={() => add('cards')}><Plus size={26} /><strong>Adicionar cartão</strong><span>Suas faturas, lado a lado.</span></button></div>}
      {['accounts', 'cards'].includes(section) && detailId && <><div className="dashboard-grid"><Panel title="Gastos por categoria"><Categories rows={summary.categories} /></Panel><Panel title="Vencimentos desta origem"><PaymentList rows={summary.payments} pay={pay} all /></Panel></div>{transactionsPanel()}<Panel title="Assinaturas vinculadas"><div className="simple-list">{data.subscriptions.filter(s => section === 'cards' ? String(s.card) === detailId : String(s.account || data.cards.find(c => c.id === s.card)?.account) === detailId).map(s => <div key={s.id}><strong>{s.name}</strong><span>{s.is_active ? 'Ativa' : 'Cancelada'}</span><strong>{money(s.amount)}</strong></div>)}</div></Panel></>}
      {section === 'transactions' && transactionsPanel()}
      {section === 'invoices' && <><div className="stats three"><Stat label={summary.is_forecast ? 'Faturas previstas' : 'Faturas no mês'} value={summary.invoice_total} icon={Receipt} highlight note="Total manual ou detalhamento conhecido, sem duplicação" /><Stat label="Gastos consolidados" value={summary.expenses} icon={ArrowUpRight} note="Faturas + despesas fora dos cartões" /><Stat label="Obrigações observadas" value={summary.liabilities} icon={CalendarClock} note="Não inclui competências futuras" /></div>{summary.warnings.map((warning, index) => <div className="alert error" key={index}><AlertCircle size={18}/><div>{warning.message}</div></div>)}<Panel title="Faturas por cartão" sub="A previsão combina parcelas, assinaturas e o total informado sem somá-los duas vezes">{summary.invoice_forecasts.length ? <div className="table-scroll"><table><thead><tr><th>Cartão</th><th>Vencimento</th><th>Composição</th><th>Situação</th><th className="right">Total previsto</th><th>Ações</th></tr></thead><tbody>{summary.invoice_forecasts.map(row => { const invoice = data.invoices.find(item => item.id === row.invoice_id); return <tr key={row.card_id}><td><button className="text-button" onClick={() => navigate(`/cards/${row.card_id}`)}>{row.card_name}<ArrowUpRight size={14}/></button></td><td>{dateLabel(row.due_date)}</td><td>{Number(row.projected_total) ? `${money(row.projected_total)} em assinaturas previstas` : row.manual_amount == null ? 'Gastos detalhados' : 'Total informado'}</td><td><span className={`tag ${row.paid_on ? 'green' : ''}`}>{row.paid_on ? 'Paga' : row.is_forecast ? 'Prevista' : 'Em aberto'}</span></td><td className="right amount">{money(row.forecast_total)}</td><td>{invoice && <div className="row-actions">{editButton('invoices', invoice)}{!row.is_forecast && <button className="text-button" onClick={() => invoice.paid_on ? mutate(`invoices/${invoice.id}/`, { paid_on: null }, 'Fatura reaberta.', 'PATCH') : pay({ ...invoice, kind: 'invoice' })}>{invoice.paid_on ? 'Reabrir' : 'Marcar paga'}</button>}</div>}</td></tr>; })}</tbody></table></div> : <Empty icon={Receipt} title="Nenhuma fatura neste mês" text="Cadastre uma fatura, parcela ou assinatura no cartão." action={() => add('invoices')} />}</Panel></>}
      {section === 'subscriptions' && <><div className="notice"><Repeat2 size={22} /><div><strong>{money(summary.subscription_total)} em cobranças neste mês</strong><p>As cobranças são registradas nas movimentações automaticamente. Cancele para interromper os próximos lançamentos.</p></div></div>{data.subscriptions.length ? <div className="account-grid">{data.subscriptions.filter(s => !origin || String(s.account || data.cards.find(c => c.id === s.card)?.account) === origin).map(s => <section className="subscription-card" key={s.id}><div className="account-top"><span className="service-icon">{s.name.slice(0, 1).toUpperCase()}</span><span className={`tag ${s.is_active ? 'green' : ''}`}>{s.is_active ? 'Ativa' : 'Cancelada'}</span>{s.is_active && editButton('subscriptions', s)}</div><h2>{s.name}</h2><strong className="subscription-price">{money(s.amount)}<small>/mês</small></strong><p>Cobrança recorrente dia {s.billing_day} · {s.card ? `Cartão · ${data.cards.find(c => c.id === s.card)?.name}` : `Conta · ${data.accounts.find(a => a.id === s.account)?.name}`}</p><p>{s.first_charge_date ? `Primeira cobrança: ${dateLabel(s.first_charge_date)}` : 'Cadastro antigo: primeira cobrança segue a regra original'}</p><div className="account-bottom"><span className="muted">Desde {dateLabel(s.start_date)}</span><div className="row-actions">{s.is_active && !s.first_charge_date && <button className="text-button" onClick={() => setModal({ type: 'subscription-review', subscription: s })}>Revisar primeira cobrança</button>}{s.is_active && <button className="text-button negative" onClick={() => {
                    confirmAction(`Cancelar ${s.name}? As cobranças anteriores serão mantidas.`).then(confirmed => {
                      if (confirmed) mutate(`subscriptions/${s.id}/cancel/`, {}, 'Assinatura cancelada. Histórico preservado.');
                    });
                  }}>Cancelar serviço</button>}</div></div></section>)}</div> : <Panel title="Seus serviços recorrentes"><Empty icon={Repeat2} title="Sem assinaturas cadastradas" action={() => add('subscriptions')} /></Panel>}</>}
      {section === 'goals' && <><div className="notice"><Target size={23} /><div><strong>{money(summary.goal_required)} por mês para os seus planos</strong><p>O valor considera todas as metas ativas, o que já foi guardado e os meses restantes, incluindo o mês selecionado.</p></div>{link('Ver planejamento', '/planning')}</div>{summary.goals.length ? <div className="goal-grid standalone">{summary.goals.filter(g => !detailId || String(g.id) === detailId).map(g => <div key={g.id}><GoalCard goal={g} add={g.is_active ? () => setModal({
                  type: 'contributions',
                  goalId: g.id
                }) : null} edit={() => add('goals', data.goals.find(x => x.id === g.id))} /><div className="account-bottom">{link('Histórico de aportes', `/goals/${g.id}`)}<button className="text-button muted" onClick={() => archive('goals', data.goals.find(x => x.id === g.id))}>{g.is_active ? 'Arquivar' : 'Reativar'}</button></div></div>)}</div> : <Panel title="Seus próximos planos"><Empty icon={Target} title="Toda conquista começa com uma meta" text="Uma viagem, uma reserva ou um novo começo. O que vem a seguir?" action={() => add('goals')} button="Criar meta" /></Panel>}{detailId && <Panel title="Histórico de aportes"><div className="simple-list">{contributions.filter(c => c.date.slice(0, 7) <= month).map(c => <div key={c.id}><span>{dateLabel(c.date)}</span><strong>{money(c.amount)}</strong></div>)}</div>{!contributions.length && <Empty icon={Target} title="Nenhum aporte registrado" text="Cada aporte ficará registrado aqui." />}</Panel>}</>}
      {section === 'planning' && planning()}
      {section === 'payments' && <><Panel title="Agenda de pagamentos" sub="Pagamentos da competência selecionada" action={<button className="text-button" disabled={pendingBusy} onClick={togglePreviousPending}>{previousPending === null ? 'Ver pendências anteriores' : 'Ocultar pendências anteriores'}<ChevronDown size={14}/></button>}><PaymentList rows={summary.payments} pay={pay} all />{data.bills.length > 0 && <div className="bills-edit"><h3>Gerenciar contas a pagar deste mês</h3>{data.bills.map(b => <div key={b.id}><span>{b.description}</span>{editButton('bills', b)}{b.paid_on && <button className="text-button" onClick={() => mutate(`bills/${b.id}/`, {
                  paid_on: null
                }, 'Conta reaberta.', 'PATCH')}>Reabrir</button>}</div>)}</div>}</Panel>{previousPending !== null && <Panel title="Pendências anteriores" sub="Obrigações persistidas de competências anteriores; não entram novamente nos gastos deste mês"><PaymentList rows={previousPending} pay={pay} all /></Panel>}</>}
      {section === 'history' && <><div className="dashboard-grid"><Panel title="Evolução patrimonial" sub="Saldos históricos e dinheiro livre do mês"><Evolution rows={summary.history} /></Panel><Panel title="Categorias no período"><Categories rows={summary.categories} /></Panel></div><Panel title="Comparação entre meses"><div className="table-scroll"><table><thead><tr><th>Mês</th><th>Receitas</th><th>Gastos</th><th>Patrimônio líquido</th></tr></thead><tbody>{summary.history.map(r => <tr key={r.month}><td>{MONTHS[Number(r.month.slice(5, 7)) - 1]} / {r.month.slice(0, 4)}</td><td className="positive amount">{money(r.income)}</td><td className="amount">{money(r.expenses)}</td><td className="amount">{money(r.net_worth)}</td></tr>)}</tbody></table></div></Panel>{planning()}</>}
    </>}
    <footer className="page-footer"><span><span className="mini-brand">✳</span> Clareza para hoje. Tranquilidade para amanhã.</span><span>Feito para o seu ritmo.</span></footer></main></div>
    {modal?.type === 'installment-purchases' && <InstallmentDialog data={data} month={month} close={() => setModal(null)} saved={message => { setModal(null); setToast(message); load(); }}/>}
    {modal?.type === 'installment-details' && <InstallmentDetailsDialog purchaseId={modal.purchaseId} close={() => setModal(null)} saved={message => { setModal(null); setToast(message); load(); }}/>}
    {modal?.type === 'subscription-create' && <SubscriptionDialog data={data} close={() => setModal(null)} saved={message => { setModal(null); setToast(message); load(); }}/>}
    {modal?.type === 'subscription-review' && <ReviewFirstChargeDialog subscription={modal.subscription} close={() => setModal(null)} saved={message => { setModal(null); setToast(message); load(); }}/>}
    {modal && !['installment-purchases', 'installment-details', 'subscription-create', 'subscription-review'].includes(modal.type) && <FormDialog key={`${modal.type}-${modal.item?.id || 'new'}`} modal={modal} data={data} month={month} close={() => setModal(null)} switchToInstallments={() => setModal({ type: 'installment-purchases' })} saved={() => {
      setModal(null);
      setToast('Registro salvo com sucesso.');
      load();
    }} />} {toast && <div className="toast" role="status"><CheckCircle2 size={19} />{toast}<button className="icon-button" aria-label="Fechar mensagem" onClick={() => setToast('')}><X size={15} /></button></div>}
  </div>;
}
