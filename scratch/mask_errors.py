import os
from pathlib import Path
import re

src = Path('/home/levi/Documentos/Programacao/Projeto-Financas/frontend/src')

def mask_error(filepath):
    content = filepath.read_text()
    
    # 1. App.jsx global error
    content = content.replace(
        "error.includes('fetch') ? 'Não foi possível conectar ao servidor. Verifique se o Django está em execução.' : error",
        "error.includes('fetch') ? 'Não foi possível conectar ao servidor. Verifique se o Django está em execução.' : (hidden ? 'Existe um conflito financeiro. Mostre os valores para consultar os detalhes.' : error)"
    )
    
    # 2. Editor dialog error
    content = content.replace(
        "{error && <div role=\"alert\" className=\"alert error\">{error}</div>}",
        "{error && <div role=\"alert\" className=\"alert error\">{hidden ? 'Existe um conflito financeiro. Mostre os valores para consultar os detalhes.' : error}</div>}"
    )
    
    # 3. Installments.jsx and Subscriptions.jsx errors
    if 'Installments' in str(filepath) or 'Subscriptions' in str(filepath):
        # We need to make sure hidden is defined in the main component of these files if not already.
        # Actually, we added it to `InstallmentDialog` and `SubscriptionReviewDialog`.
        pass
        
    filepath.write_text(content)

mask_error(src / 'App.jsx')
mask_error(src / 'Installments.jsx')
mask_error(src / 'Subscriptions.jsx')
print("Masked errors")
