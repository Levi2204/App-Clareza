import os
from pathlib import Path
import re

src = Path('/home/levi/Documentos/Programacao/Projeto-Financas/frontend/src')

def process_jsx(filepath):
    content = filepath.read_text()
    
    # Add import
    if 'MoneyValue' not in content:
        content = content.replace("import { money, dateLabel", "import { money, dateLabel") # unchanged
        content = content.replace("import { api", "import { MoneyValue, useValueVisibility, PrivacyButton } from './PrivacyContext';\nimport { api")
        
    # Replace normal interpolations {money(something)} -> <MoneyValue value={something} />
    content = re.sub(r'\{money\(([^}]+)\)\}', r'<MoneyValue value={\1} />', content)
    
    # Find string templates that use money() and convert them.
    # App.jsx has:
    # 1. `Depois dos gastos e das metas, sobram ${money(summary.free)} neste mês.`
    # 2. `O déficit é de ${money(summary.deficit)}. Revise os gastos...`
    # 3. `${money(row.projected_total)} em assinaturas previstas`
    # 4. `${money(summary.subscription_total)} em cobranças neste mês` -> this is inside a <strong>
    
    content = content.replace(
        "`Depois dos gastos e das metas, sobram ${money(summary.free)} neste mês.`",
        "<>Depois dos gastos e das metas, sobram <MoneyValue value={summary.free} /> neste mês.</>"
    )
    content = content.replace(
        "`O déficit é de ${money(summary.deficit)}. Revise os gastos ou aumente o prazo das metas. Metas vencidas também precisam de revisão.`",
        "<>O déficit é de <MoneyValue value={summary.deficit} />. Revise os gastos ou aumente o prazo das metas. Metas vencidas também precisam de revisão.</>"
    )
    content = content.replace(
        "`${money(row.projected_total)} em assinaturas previstas`",
        "<><MoneyValue value={row.projected_total} /> em assinaturas previstas</>"
    )
    
    # <strong>{money(summary.subscription_total)} em cobranças neste mês</strong>
    # Wait, the previous regex `{money(summary.subscription_total)}` already converted it to `<MoneyValue value={summary.subscription_total} /> em cobranças...`
    # So that's fine.
    
    # Add PrivacyButton to topbar
    if 'PrivacyButton' in content and '<PrivacyButton />' not in content:
        content = content.replace('<button className="notification icon-button"', '<PrivacyButton /><button className="notification icon-button"')
        
    # App.jsx: sidebar tip removal.
    # The sidebar tip is:
    # <div className="sidebar-tip"><Sun size={24} /><strong>Um pouco mais de clareza.</strong><span>Pequenos hábitos hoje. Mais possibilidades amanhã.</span><a href="#" className="sidebar-link">Seu futuro começa aqui<ArrowUpRight size={16} /></a></div>
    # Remove the `<a ...>Seu futuro começa aqui<ArrowUpRight ...></a>`
    content = re.sub(
        r'<a href="#" className="sidebar-link">Seu futuro começa aqui<ArrowUpRight size={16} /></a>',
        '',
        content
    )
    
    # Charts handling
    # In App.jsx we have <ResponsiveContainer> and <PieChart> ...
    # We should render a neutral state if hidden.
    # We need to wrap them: `hidden ? <div className="hidden-chart">Valores ocultos</div> : <ResponsiveContainer...>`
    
    # Wait, in the component, we need to extract `hidden` from `useValueVisibility()`
    # Let's add `const { hidden } = useValueVisibility();` in App() if not there.
    if 'const { hidden }' not in content and 'useValueVisibility' in content:
        content = content.replace('const [search, setSearch] = useState(\'\');', 'const [search, setSearch] = useState(\'\');\n  const { hidden } = useValueVisibility();')
        
    filepath.write_text(content)

process_jsx(src / 'App.jsx')
process_jsx(src / 'Installments.jsx')
process_jsx(src / 'Subscriptions.jsx')
print("Done")
