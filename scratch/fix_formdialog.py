import os
from pathlib import Path
import re

src = Path('/home/levi/Documentos/Programacao/Projeto-Financas/frontend/src')

app_content = (src / 'App.jsx').read_text()

# Add `const { hidden, setHidden } = useValueVisibility();` to FormDialog
app_content = re.sub(
    r'function FormDialog\(\{([^}]+)\}\) \{',
    r'function FormDialog({\1}) {\n  const { hidden, setHidden } = useValueVisibility();',
    app_content
)

# 1b. Replace number inputs in FormDialog with hidden toggle
app_content = re.sub(
    r'<input autoFocus=\{f === fields\[0\]\}(.*?)type=\{f.type\}(.*?) />',
    r'{f.type === \'number\' && hidden ? <button type="button" className="button secondary hidden-input" onClick={() => setHidden(false)}>Mostrar valores para editar</button> : <input autoFocus={f === fields[0]}\1type={f.type}\2 />}',
    app_content
)

(src / 'App.jsx').write_text(app_content)
print("Fixed FormDialog")
