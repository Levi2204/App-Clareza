/** HTML dialogs work consistently in the browser and the native WebKit window. */
export function confirmAction(message) {
  return new Promise(resolve => {
    const dialog = document.createElement('dialog');
    dialog.className = 'dialog confirmation-dialog';
    dialog.setAttribute('aria-label', 'Confirmar ação');
    const heading = document.createElement('h2');
    heading.textContent = 'Confirmar ação';
    const text = document.createElement('p');
    text.textContent = message;
    const footer = document.createElement('div');
    footer.className = 'dialog-footer';
    const cancel = document.createElement('button');
    cancel.className = 'button secondary';
    cancel.textContent = 'Cancelar';
    const accept = document.createElement('button');
    accept.className = 'button primary';
    accept.textContent = 'Confirmar';
    function finish(value) { dialog.close(); dialog.remove(); resolve(value); }
    cancel.onclick = () => finish(false);
    accept.onclick = () => finish(true);
    dialog.oncancel = event => { event.preventDefault(); finish(false); };
    footer.append(cancel, accept);
    dialog.append(heading, text, footer);
    document.body.append(dialog);
    dialog.showModal();
    cancel.focus();
  });
}
