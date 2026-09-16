"""Exercise packaged service in an empty, isolated user directory and across restarts."""
from pathlib import Path
import argparse
import calendar
from datetime import date, timedelta
import json
import os
import selectors
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--service', type=Path)
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='clareza-portable-') as temp:
    directory = Path(temp)
    if args.service:
        # Relocation proves that the frozen service does not depend on its build path.
        relocated = directory / 'relocated'
        shutil.copytree(args.service.resolve().parent, relocated)
        command = [str(relocated / args.service.name)]
    else:
        command = [str(root / '.venv/bin/python'), '-u', str(root / 'backend/desktop_runtime.py')]
    env = {**os.environ, 'CLAREZA_DATA_DIR': str(directory / 'user-data'),
           'PATH': '/nonexistent', 'PYTHONPATH': '', 'PYTHONHOME': ''}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    today = date.today()
    first_month = today.replace(day=1)
    next_month = first_month.replace(
        day=calendar.monthrange(first_month.year, first_month.month)[1]
    ) + timedelta(days=1)
    for launch in range(2):
        with tempfile.TemporaryFile() as log:
            child = subprocess.Popen(command, cwd=directory, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    if not selector.select(120):
                        raise RuntimeError('O serviço não ficou pronto em 120 segundos.')
                raw = child.stdout.readline()
                if not raw:
                    log.seek(0)
                    raise RuntimeError(log.read().decode())
                connection = json.loads(raw)
                origin = f"http://127.0.0.1:{connection['port']}/api/v1/"
                def request(path, method='GET', data=None, authenticated=True):
                    headers = {'Content-Type': 'application/json'}
                    if authenticated:
                        headers['X-Clareza-Token'] = connection['token']
                    req = urllib.request.Request(origin + path,
                        data=json.dumps(data).encode() if data is not None else None,
                        headers=headers, method=method)
                    with opener.open(req, timeout=30) as response:
                        return json.load(response) if response.status != 204 else None
                try:
                    request('dashboard/', authenticated=False)
                    raise AssertionError('O acesso sem segredo foi aceito.')
                except urllib.error.HTTPError as error:
                    assert error.code == 403
                assert 'assets' in request('dashboard/')
                if launch == 0:
                    request('profile/', 'PATCH', {'display_name': 'Portable test', 'theme': 'dark'})
                    account = request('accounts/', 'POST', {
                        'name': 'Conta portátil', 'account_type': 'checking',
                        'balance': '0.00', 'balance_month': first_month.isoformat(),
                    })
                    category = request('categories/', 'POST', {'name': 'Teste parcelado'})
                    purchase = request('installment-purchases/', 'POST', {
                        'description': 'Compra portátil', 'total_amount': '100.00',
                        'installment_count': 3, 'purchase_date': today.isoformat(),
                        'first_month': first_month.isoformat(), 'category': category['id'],
                        'account': account['id'], 'card': None, 'notes': '',
                        'request_id': 'portable-installment-test',
                    })
                    assert [row['amount'] for row in purchase['schedule']] == ['33.34', '33.33', '33.33']
                    subscription = request('subscriptions/', 'POST', {
                        'name': 'Assinatura portátil', 'amount': '20.00',
                        'category': category['id'], 'account': account['id'], 'card': None,
                        'billing_day': 1, 'start_date': today.isoformat(),
                        'include_start_month': True,
                    })
                    assert subscription['first_charge_date'] == today.isoformat()
                else:
                    profile = request('profile/')
                    assert profile['display_name'] == 'Portable test' and profile['theme'] == 'dark'
                    purchases = request('installment-purchases/')
                    assert len(purchases) == 1 and purchases[0]['description'] == 'Compra portátil'
                    projected = request(f'transactions/monthly/?year={next_month.year}&month={next_month.month}')
                    assert any(row['source_type'] == 'installment' for row in projected)
                    assert any(row['source_type'] == 'subscription' and row['is_projected'] for row in projected)
                    agenda = request(f'payments/upcoming/?year={today.year}&month={today.month}')
                    assert any(row['kind'] == 'subscription' and row['status'] == 'registered' for row in agenda)
                    assert request(f'payments/pending/?year={today.year}&month={today.month}') == []
                child.stdin.close()
                assert child.wait(timeout=10) == 0
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
    assert (directory / 'user-data/clareza.sqlite3').is_file()
    assert list((directory / 'user-data/backups').glob('*.sqlite3'))
    print('OK: serviço relocável, SQLite novo, autenticação, primeira cobrança, agenda mensal, parcelamento, projeção, persistência, backup e encerramento.')
