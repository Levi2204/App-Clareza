import React, { useRef, useState } from 'react';
import { Camera, Check, Moon, Sun, Trash2, UserRound, AlertTriangle } from 'lucide-react';
import { api, dateLabel } from './api';

export function Avatar({ profile, className = '' }) {
  const initials = (profile?.display_name || 'Meu espaço').split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
  return <span className={`user-avatar ${className}`}>{profile?.photo ? <img src={profile.photo} alt="" /> : initials}</span>;
}

async function preparePhoto(file) {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('Escolha uma foto PNG, JPEG ou WebP.');
  if (file.size > 5 * 1024 * 1024) throw new Error('A foto deve ter no máximo 5 MB.');
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d');
    const size = Math.min(image.width, image.height);
    context.drawImage(image, (image.width-size)/2, (image.height-size)/2, size, size, 0, 0, 256, 256);
    return canvas.toDataURL('image/png');
  } catch {
    throw new Error('Não foi possível abrir a foto. Escolha outra imagem.');
  } finally { URL.revokeObjectURL(url); }
}

export default function ProfilePage({ profile, onSaved, theme, onTheme, themeBusy, onDeleted }) {
  const [draft, setDraft] = useState({ display_name: profile.display_name || '', email: profile.email || '', phone: profile.phone || '', bio: profile.bio || '', photo: profile.photo || '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [deleting, setDeleting] = useState(false);
  const fileRef = useRef(null);
  const deletionRef = useRef(null);
  const update = e => setDraft({ ...draft, [e.target.name]: e.target.value });
  async function choosePhoto(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setPhotoBusy(true); setError('');
    try { const photo = await preparePhoto(file); setDraft(current => ({ ...current, photo })); }
    catch (e) { setError(e.message); }
    finally { setPhotoBusy(false); e.target.value = ''; }
  }
  async function save(e) {
    e.preventDefault(); setError(''); setBusy(true);
    try { onSaved(await api('profile/', { method: 'PATCH', body: JSON.stringify(draft) })); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function removeAccount(e) {
    e.preventDefault(); setDeleting(true); setError('');
    try { await api('profile/', { method: 'DELETE', body: JSON.stringify({ confirmation }) }); onDeleted(); }
    catch (e) { setError(e.message); deletionRef.current.close(); }
    finally { setDeleting(false); }
  }
  return <div className="profile-layout">
    <section className="panel profile-details"><div className="panel-head"><div><h2>Seu perfil</h2><p>Deixe seu espaço com a sua cara.</p></div><UserRound size={21}/></div>
      <form onSubmit={save}>
        <div className="photo-editor"><Avatar profile={draft} className="large"/><div><strong>Foto de perfil</strong><p>PNG, JPEG ou WebP, até 5 MB.</p><div className="photo-actions"><button type="button" className="button secondary small" disabled={photoBusy || busy} onClick={() => fileRef.current.click()}><Camera size={15}/>{photoBusy ? 'Preparando…' : 'Escolher foto'}</button>{draft.photo && <button type="button" className="text-button" disabled={busy || photoBusy} onClick={() => setDraft({ ...draft, photo: '' })}>Remover foto</button>}</div><input ref={fileRef} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Foto de perfil" onChange={choosePhoto}/></div></div>
        <div className="form-grid"><label>Nome de exibição<input name="display_name" value={draft.display_name} onChange={update} maxLength={100} required autoComplete="name"/></label><label>E-mail<input name="email" type="email" value={draft.email} onChange={update} maxLength={254} autoComplete="email"/></label><label>Telefone <small>· opcional</small><input name="phone" type="tel" value={draft.phone} onChange={update} maxLength={30} autoComplete="tel"/></label><div className="profile-created"><span>Conta criada em</span><strong>{dateLabel(profile.joined_at?.slice(0, 10))}</strong></div><label className="wide">Sobre mim <small>· opcional</small><textarea name="bio" value={draft.bio} onChange={update} maxLength={300}/><small>{draft.bio.length}/300 caracteres</small></label></div>
        {error && <div className="alert error profile-error" role="alert">{error}</div>}
        <div className="dialog-footer"><button className="button primary" disabled={busy || photoBusy}>{busy ? 'Salvando…' : 'Salvar alterações'}<Check size={16}/></button></div>
      </form>
    </section>
    <div><section className="panel"><div className="panel-head"><div><h2>Aparência</h2><p>Escolha o tema mais confortável para você.</p></div></div><div className="theme-options" role="group" aria-label="Tema da aplicação">{[['light', 'Modo claro', Sun], ['dark', 'Modo escuro', Moon]].map(([value, label, Icon]) => <button key={value} type="button" className={`theme-option ${theme === value ? 'selected' : ''}`} aria-pressed={theme === value} disabled={themeBusy} onClick={() => onTheme(value)}><div className={`theme-preview ${value}`}><span/><div><i/><i/><i/></div></div><span><Icon size={17}/>{label}{theme === value && <Check size={16}/>}</span></button>)}</div><p className="footnote">A preferência fica salva no seu perfil.</p></section>
    <section className="panel danger-zone"><div className="panel-head"><div><h2>Excluir conta</h2><p>Esta ação é permanente.</p></div><Trash2 size={19}/></div><p>Apaga seu perfil, foto, contas financeiras, movimentações, faturas, assinaturas, metas e todo o histórico deste espaço.</p><button className="button danger" onClick={() => { setConfirmation(''); deletionRef.current.showModal(); }}>Excluir minha conta</button></section></div>
    <dialog ref={deletionRef} className="dialog deletion-dialog" aria-labelledby="delete-title" onCancel={e => { if (deleting) e.preventDefault(); }}><form onSubmit={removeAccount}><div className="dialog-heading"><div><AlertTriangle size={27}/><h2 id="delete-title">Excluir sua conta?</h2></div></div><p>Todos os seus dados financeiros e seu perfil serão apagados definitivamente. Não será possível recuperá-los.</p><label>Digite EXCLUIR para confirmar<input autoComplete="off" value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={deleting}/></label><div className="dialog-footer"><button type="button" className="button secondary" disabled={deleting} onClick={() => deletionRef.current.close()}>Manter minha conta</button><button className="button danger" disabled={confirmation !== 'EXCLUIR' || deleting}>{deleting ? 'Excluindo…' : 'Excluir definitivamente'}</button></div></form></dialog>
  </div>;
}
