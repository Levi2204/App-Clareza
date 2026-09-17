import os
from pathlib import Path
import re

src = Path('/home/levi/Documentos/Programacao/Projeto-Financas/frontend/src')

# Fix App.jsx Components
app_content = (src / 'App.jsx').read_text()

# 1. Add `const { hidden, setHidden } = useValueVisibility();` to Editor
app_content = re.sub(
    r'function Editor\(\{([^}]+)\}\) \{',
    r'function Editor({\1}) {\n  const { hidden, setHidden } = useValueVisibility();',
    app_content
)

# 1b. Replace number inputs in Editor with hidden toggle
app_content = re.sub(
    r'<input autoFocus=\{f === fields\[0\]\}(.*?)type=\{f.type\}(.*?) />',
    r'{f.type === \'number\' && hidden ? <button type="button" className="button secondary hidden-input" onClick={() => setHidden(false)}>Mostrar valores para editar</button> : <input autoFocus={f === fields[0]}\1type={f.type}\2 />}',
    app_content
)

# 2. Add hidden to GoalCard
app_content = re.sub(
    r'function GoalCard\(\{([^}]+)\}\) \{',
    r'function GoalCard({\1}) {\n  const { hidden } = useValueVisibility();',
    app_content
)

# 2b. Hide GoalCard progress
app_content = app_content.replace(
    '<span style={{\n        width: `${goal.progress}%`\n      }} />',
    '<span style={{ width: hidden ? "0%" : `${goal.progress}%` }} className={hidden ? "hidden-progress" : ""} />'
)
app_content = app_content.replace(
    '<span>{Number(goal.progress)}% concluído</span>',
    '<span>{hidden ? "Valor oculto" : `${Number(goal.progress)}% concluído`}</span>'
)

# 3. Add hidden to Categories
app_content = re.sub(
    r'function Categories\(\{([^}]+)\}\) \{',
    r'function Categories({\1}) {\n  const { hidden } = useValueVisibility();',
    app_content
)

# 3b. Hide Categories chart
app_content = app_content.replace(
    '<ResponsiveContainer width="100%" height={185}>',
    '{hidden ? <div className="hidden-chart" style={{height: 185, display: "flex", alignItems: "center", justifyContent: "center", color: "#83877c"}}>Valores ocultos</div> : <ResponsiveContainer width="100%" height={185}>'
)
app_content = app_content.replace(
    '</PieChart></ResponsiveContainer>',
    '</PieChart></ResponsiveContainer>}'
)

# 4. Add hidden to Evolution
app_content = re.sub(
    r'function Evolution\(\{([^}]+)\}\) \{',
    r'function Evolution({\1}) {\n  const { hidden } = useValueVisibility();',
    app_content
)

# 4b. Hide Evolution chart
app_content = app_content.replace(
    '<ResponsiveContainer width="100%" height={230}>',
    '{hidden ? <div className="hidden-chart" style={{height: 230, display: "flex", alignItems: "center", justifyContent: "center", color: "#83877c"}}>Valores ocultos</div> : <ResponsiveContainer width="100%" height={230}>'
)
app_content = app_content.replace(
    '</AreaChart></ResponsiveContainer>',
    '</AreaChart></ResponsiveContainer>}'
)

(src / 'App.jsx').write_text(app_content)

# Fix Installments.jsx Components
inst_content = (src / 'Installments.jsx').read_text()
inst_content = re.sub(
    r'export default function InstallmentDialog\(\{([^}]+)\}\) \{',
    r'export default function InstallmentDialog({\1}) {\n  const { hidden, setHidden } = useValueVisibility();',
    inst_content
)
inst_content = re.sub(
    r'<input required disabled=\{busy\}(.*?)type="number"(.*?) />',
    r'{hidden ? <button type="button" className="button secondary hidden-input" onClick={() => setHidden(false)}>Mostrar valores para editar</button> : <input required disabled={busy}\1type="number"\2 />}',
    inst_content
)
(src / 'Installments.jsx').write_text(inst_content)

# Fix Subscriptions.jsx Components
sub_content = (src / 'Subscriptions.jsx').read_text()
sub_content = re.sub(
    r'export default function SubscriptionReviewDialog\(\{([^}]+)\}\) \{',
    r'export default function SubscriptionReviewDialog({\1}) {\n  const { hidden, setHidden } = useValueVisibility();',
    sub_content
)
(src / 'Subscriptions.jsx').write_text(sub_content)

print("Refactored components")
