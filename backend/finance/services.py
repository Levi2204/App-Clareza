"""Financial rules. All monetary computations use Decimal, returned as strings by DRF."""
import calendar
from datetime import date
from decimal import Decimal, ROUND_UP
from django.db import transaction as atomic_db
from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Account, Balance, Card, Invoice, Transaction, Subscription, Bill, Goal, GoalState, Contribution
from .projections import projected_subscriptions, monthly_items
from .subscription_calendar import occurrence_date

ZERO = Decimal('0.00')

def month_start(value):
    return value.replace(day=1)

def month_end(value):
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])

def next_month(value):
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)

def due(month, day):
    return month.replace(day=min(day, calendar.monthrange(month.year, month.month)[1]))

def parse_month(params):
    today = timezone.localdate()
    try:
        return date(int(params.get('year', today.year)), int(params.get('month', today.month)), 1)
    except (ValueError, TypeError):
        raise ValidationError({'month': 'Informe ano e mês válidos.'})

def total(qs, field='amount'):
    return qs.aggregate(value=Sum(field))['value'] or ZERO

def invoice_total(invoice):
    return invoice.manual_amount if invoice.manual_amount is not None else sum((row.amount for row in invoice.transactions.all()), ZERO)

def ensure_invoice(user, card, month):
    return Invoice.objects.get_or_create(user=user, card=card, month=month, defaults={'due_date': due(month, card.due_day)})[0]

@atomic_db.atomic
def materialize(user, until=None):
    # No speculative future writes. Unique(subscription, month) makes retries safe.
    until = min(until or month_end(timezone.localdate()), month_end(timezone.localdate()))
    for sub in Subscription.objects.select_for_update(of=('self',)).filter(user=user).select_related('card'):
        if not sub.is_active and not sub.end_date:
            continue
        stop = min(until, sub.end_date) if sub.end_date else until
        current = month_start(sub.first_charge_date or sub.start_date)
        while current <= month_start(stop):
            charge_date = occurrence_date(sub, current)
            if charge_date and charge_date <= stop:
                if not Transaction.objects.filter(subscription=sub, month=current).exists():
                    invoice = ensure_invoice(user, sub.card, current) if sub.card else None
                    if invoice and invoice.paid_on:
                        raise ValidationError({'invoice': f'A fatura de {invoice.card.name} em {current:%m/%Y} está paga. Reabra-a antes de registrar a cobrança de {sub.name}.'})
                    if invoice and invoice.manual_amount is not None and total(invoice.transactions.all()) + sub.amount > invoice.manual_amount:
                        raise ValidationError({'manual_amount': f'A cobrança de {sub.name} excede o total manual da fatura. Atualize a fatura primeiro.'})
                    Transaction.objects.get_or_create(subscription=sub, month=current, defaults={'user': user, 'description': sub.name, 'amount': sub.amount, 'date': charge_date, 'category': sub.category, 'account': sub.account, 'card': sub.card, 'invoice': invoice})
            current = next_month(current)


def goal_state(goal, effective=None):
    effective = month_start(effective or timezone.localdate())
    GoalState.objects.update_or_create(goal=goal, month=effective, defaults={key: getattr(goal, key) for key in ['name', 'target_amount', 'target_date', 'is_active']})


def goal_summary(user, month):
    end = month_end(month)
    result = []
    for goal in Goal.objects.filter(user=user, start_date__lte=end).prefetch_related('states', 'contributions'):
        states = [s for s in goal.states.all() if s.month <= month]
        if not states:
            continue
        state = max(states, key=lambda s: s.month)
        accumulated = sum((c.amount for c in goal.contributions.all() if c.date <= end), ZERO)
        remaining = max(ZERO, state.target_amount - accumulated)
        months = max(1, (state.target_date.year - month.year) * 12 + state.target_date.month - month.month + 1)
        monthly = (remaining / months).quantize(Decimal('.01'), rounding=ROUND_UP) if state.is_active else ZERO
        result.append({'id': goal.id, 'name': state.name, 'target_amount': state.target_amount, 'accumulated': accumulated, 'remaining': remaining, 'monthly_required': monthly, 'progress': min(Decimal(100), accumulated / state.target_amount * 100).quantize(Decimal('.1')), 'target_date': state.target_date, 'overdue': state.target_date < min(end, timezone.localdate()) and remaining > 0, 'is_active': state.is_active, 'term_type': goal.term_type})
    return result


def filtered(qs, params, card_field='card'):
    if params.get('account_id'):
        if card_field:
            qs = qs.filter(Q(account_id=params['account_id']) | Q(**{f'{card_field}__account_id': params['account_id']}))
        else:
            qs = qs.filter(account_id=params['account_id'])
    if params.get('card_id') and card_field:
        qs = qs.filter(**{f'{card_field}_id': params['card_id']})
    if params.get('category_id'):
        qs = qs.filter(category_id=params['category_id'])
    return qs


def _invoice_queryset(user, params, **filters):
    rows = Invoice.objects.filter(user=user, **filters).select_related('card', 'card__account').prefetch_related('transactions')
    if params.get('account_id'):
        rows = rows.filter(card__account_id=params['account_id'])
    if params.get('card_id'):
        rows = rows.filter(card_id=params['card_id'])
    return rows


def monthly_invoices(user, month, params=None):
    """One consolidated invoice representation per card and competence."""
    params = params or {}
    origin_params = {key: params[key] for key in ['account_id', 'card_id'] if params.get(key)}
    invoices = {row.card_id: row for row in _invoice_queryset(user, params, month=month)}
    projected_all = projected_subscriptions(user, month, origin_params)
    projected = [row for row in projected_all if not params.get('category_id') or str(row['category']) == str(params['category_id'])]
    projected_by_card = {}
    selected_projected_by_card = {}
    for row in projected_all:
        if row['card']:
            projected_by_card[row['card']] = projected_by_card.get(row['card'], ZERO) + row['amount']
    for row in projected:
        if row['card']:
            selected_projected_by_card[row['card']] = selected_projected_by_card.get(row['card'], ZERO) + row['amount']
    card_ids = set(invoices) | set(projected_by_card)
    cards = {row.id: row for row in Card.objects.filter(user=user, id__in=card_ids).select_related('account')}
    cutoff = min(month_end(month), timezone.localdate())
    current_month = month_start(timezone.localdate())
    result = []
    for card_id in sorted(card_ids):
        invoice = invoices.get(card_id)
        card = cards[card_id]
        details = list(invoice.transactions.all()) if invoice else []
        all_detail = sum((row.amount for row in details), ZERO)
        selected_detail = sum((row.amount for row in details if not params.get('category_id') or str(row.category_id) == str(params['category_id'])), ZERO)
        all_projection = projected_by_card.get(card_id, ZERO)
        selected_projection = selected_projected_by_card.get(card_id, ZERO)
        if params.get('category_id'):
            registered = selected_detail
            amount = selected_detail + selected_projection
        else:
            registered = invoice.manual_amount if invoice and invoice.manual_amount is not None else all_detail
            amount = max(registered, all_detail + all_projection)
        if amount <= ZERO:
            continue
        paid = bool(invoice and invoice.paid_on and invoice.paid_on <= cutoff)
        forecast = month > current_month or invoice is None or bool(all_projection)
        due_date = invoice.due_date if invoice else due(month, card.due_day)
        status_name = 'forecast' if forecast else ('paid' if paid else ('overdue' if due_date < cutoff else 'pending'))
        warning = None
        if not params.get('category_id') and invoice and invoice.manual_amount is not None and all_detail + all_projection > invoice.manual_amount and all_projection:
            warning = {'kind': 'manual_invoice_conflict', 'card_id': card_id, 'month': month, 'manual_amount': invoice.manual_amount, 'known_amount': all_detail + all_projection, 'message': f'O total informado da fatura de {card.name} precisa ser revisto para comportar as cobranças previstas.'}
        result.append({
            'key': f'invoice-{card_id}-{month:%Y-%m}', 'id': invoice.id if invoice else None,
            'invoice_id': invoice.id if invoice else None, 'kind': 'invoice', 'month': month,
            'card_id': card_id, 'account_id': card.account_id, 'card_name': card.name,
            'description': f'Fatura {card.name}', 'origin': f'Cartão · {card.name}',
            'due_date': due_date, 'paid_on': invoice.paid_on if invoice else None,
            'registered_amount': registered, 'registered_total': registered,
            'projected_increment': amount - registered, 'projected_total': selected_projection,
            'amount': amount, 'forecast_total': amount, 'known_amount': all_detail + all_projection,
            'manual_amount': invoice.manual_amount if invoice else None,
            'status': status_name, 'is_forecast': forecast, 'can_pay': bool(invoice and month <= current_month and not paid and not all_projection),
            'days_until': (due_date - cutoff).days, 'warning': warning,
        })
    return result


def payments(user, month, params=None):
    """Agenda strictly scoped to the selected competence."""
    params = params or {}
    cutoff = min(month_end(month), timezone.localdate())
    current_month = month_start(timezone.localdate())
    result = list(monthly_invoices(user, month, params))
    bills = filtered(Bill.objects.filter(user=user, month=month).select_related('account', 'category'), params, card_field=None)
    if params.get('card_id'):
        bills = bills.none()
    for item in bills:
        paid = bool(item.paid_on and item.paid_on <= cutoff)
        forecast = item.month > current_month
        result.append({
            'key': f'bill-{item.id}-{item.month:%Y-%m}', 'id': item.id, 'kind': 'bill',
            'month': item.month, 'card_id': None, 'account_id': item.account_id,
            'description': item.description, 'origin': f'Conta · {item.account.name}',
            'registered_amount': item.amount, 'projected_increment': ZERO, 'amount': item.amount,
            'due_date': item.due_date, 'paid_on': item.paid_on, 'days_until': (item.due_date - cutoff).days,
            'is_forecast': forecast, 'status': 'forecast' if forecast else ('paid' if paid else ('overdue' if item.due_date < cutoff else 'pending')),
            'can_pay': bool(not forecast and not paid),
        })
    direct_charges = Transaction.objects.filter(user=user, month=month, subscription__isnull=False, card__isnull=True).select_related('account', 'category')
    direct_charges = filtered(direct_charges, params)
    if params.get('card_id'):
        direct_charges = direct_charges.none()
    for item in direct_charges:
        result.append({
            'key': f'subscription-charge-{item.subscription_id}-{month:%Y-%m}', 'id': None,
            'kind': 'subscription', 'month': month, 'card_id': None, 'account_id': item.account_id,
            'description': item.description, 'origin': f'Conta · {item.account.name}',
            'registered_amount': item.amount, 'projected_increment': ZERO, 'amount': item.amount,
            'due_date': item.date, 'paid_on': None, 'days_until': (item.date - cutoff).days,
            'is_forecast': False, 'status': 'registered', 'can_pay': False,
        })
    for row in projected_subscriptions(user, month, params):
        if row['card'] is None:
            result.append({
                'key': f"payment-{row['key']}", 'id': None, 'kind': 'subscription_forecast',
                'month': month, 'card_id': None, 'account_id': row['account'],
                'description': row['description'], 'origin': f"Conta · {row['origin']}",
                'registered_amount': ZERO, 'projected_increment': row['amount'], 'amount': row['amount'],
                'due_date': row['date'], 'paid_on': None, 'days_until': (row['date'] - cutoff).days,
                'is_forecast': True, 'status': 'forecast', 'can_pay': False,
            })
    return sorted(result, key=lambda item: (item['due_date'], item['key']))


def pending_payments(user, month, params=None):
    """Persisted obligations from earlier competences still open at the selected cutoff."""
    params = params or {}
    cutoff = min(month_end(month), timezone.localdate())
    observed_month = min(month, month_start(timezone.localdate()))
    invoices = _invoice_queryset(user, params, month__lt=month, month__lte=observed_month).filter(Q(paid_on__isnull=True) | Q(paid_on__gt=cutoff))
    bills = Bill.objects.filter(user=user, month__lt=month, month__lte=observed_month).select_related('account', 'category').filter(Q(paid_on__isnull=True) | Q(paid_on__gt=cutoff))
    bills = filtered(bills, params, card_field=None)
    if params.get('card_id'):
        bills = bills.none()
    result = []
    for item in invoices:
        details = list(item.transactions.all())
        amount = sum((row.amount for row in details if str(row.category_id) == str(params['category_id'])), ZERO) if params.get('category_id') else invoice_total(item)
        if amount <= ZERO:
            continue
        result.append({'key': f'pending-invoice-{item.card_id}-{item.month:%Y-%m}', 'id': item.id, 'kind': 'invoice', 'month': item.month, 'card_id': item.card_id, 'account_id': item.card.account_id, 'description': f'Fatura {item.card.name}', 'origin': f'Cartão · {item.card.name}', 'registered_amount': amount, 'projected_increment': ZERO, 'amount': amount, 'due_date': item.due_date, 'paid_on': item.paid_on, 'days_until': (item.due_date - cutoff).days, 'is_forecast': False, 'status': 'overdue' if item.due_date < cutoff else 'pending', 'can_pay': item.paid_on is None})
    for item in bills:
        if item.amount <= ZERO:
            continue
        result.append({'key': f'pending-bill-{item.id}-{item.month:%Y-%m}', 'id': item.id, 'kind': 'bill', 'month': item.month, 'card_id': None, 'account_id': item.account_id, 'description': item.description, 'origin': f'Conta · {item.account.name}', 'registered_amount': item.amount, 'projected_increment': ZERO, 'amount': item.amount, 'due_date': item.due_date, 'paid_on': item.paid_on, 'days_until': (item.due_date - cutoff).days, 'is_forecast': False, 'status': 'overdue' if item.due_date < cutoff else 'pending', 'can_pay': item.paid_on is None})
    return sorted(result, key=lambda item: (item['due_date'], item['key']))


def observed_liabilities(user, month, params=None):
    """Persisted open obligations at the historical/current observation cutoff."""
    params = params or {}
    cutoff = min(month_end(month), timezone.localdate())
    observed_month = min(month, month_start(timezone.localdate()))
    invoices = _invoice_queryset(user, params, month__lte=observed_month).filter(Q(paid_on__isnull=True) | Q(paid_on__gt=cutoff))
    bills = Bill.objects.filter(user=user, month__lte=observed_month).select_related('account', 'category').filter(Q(paid_on__isnull=True) | Q(paid_on__gt=cutoff))
    bills = filtered(bills, params, card_field=None)
    if params.get('card_id'):
        bills = bills.none()
    invoice_amount = ZERO
    for item in invoices:
        if params.get('category_id'):
            invoice_amount += sum((row.amount for row in item.transactions.all() if str(row.category_id) == str(params['category_id'])), ZERO)
        else:
            invoice_amount += invoice_total(item)
    return invoice_amount + total(bills)


def summary(user, month, params=None):
    params = params or {}
    origin_params = {key: params[key] for key in ['account_id', 'card_id'] if params.get(key)}
    tx_all = filtered(Transaction.objects.filter(user=user, month=month).select_related('category', 'account', 'card'), origin_params)
    tx = filtered(tx_all, {'category_id': params.get('category_id')} if params.get('category_id') else {})
    bills_all = Bill.objects.filter(user=user, month=month).select_related('category')
    if params.get('account_id'):
        bills_all = bills_all.filter(account_id=params['account_id'])
    if params.get('card_id'):
        bills_all = bills_all.none()
    bills = bills_all.filter(category_id=params['category_id']) if params.get('category_id') else bills_all
    projected_all = projected_subscriptions(user, month, origin_params)
    projected = [row for row in projected_all if not params.get('category_id') or str(row['category']) == str(params['category_id'])]
    income = total(tx.filter(kind='income'))
    categories = {}
    for row in tx.filter(kind='expense'):
        categories[row.category.name] = categories.get(row.category.name, ZERO) + row.amount
    for bill in bills:
        categories[bill.category.name] = categories.get(bill.category.name, ZERO) + bill.amount
    for row in projected:
        categories[row['category_name']] = categories.get(row['category_name'], ZERO) + row['amount']

    direct_registered = total(tx.filter(kind='expense', card__isnull=True)) + total(bills)
    direct_projected = sum((row['amount'] for row in projected if row['card'] is None), ZERO)
    invoice_forecasts = monthly_invoices(user, month, params)
    card_registered = sum((row['registered_amount'] for row in invoice_forecasts), ZERO)
    card_forecast = sum((row['amount'] for row in invoice_forecasts), ZERO)
    warnings = [row['warning'] for row in invoice_forecasts if row['warning']]
    if not params.get('category_id'):
        for row in invoice_forecasts:
            synthetic = max(ZERO, row['amount'] - row['known_amount'])
            if synthetic:
                categories['Faturas sem detalhamento'] = categories.get('Faturas sem detalhamento', ZERO) + synthetic
    expenses_registered = direct_registered + card_registered
    expenses = direct_registered + direct_projected + card_forecast
    forecast_increment = expenses - expenses_registered
    assets = ZERO
    account_rows = []
    accounts = Account.objects.filter(user=user).prefetch_related('balances')
    if params.get('account_id'):
        accounts = accounts.filter(pk=params['account_id'])
    if params.get('card_id'):
        accounts = accounts.filter(cards__id=params['card_id'])
    for acc in accounts:
        balances = [b for b in acc.balances.all() if b.month <= month]
        balance = max(balances, key=lambda b: b.month).amount if balances else ZERO
        assets += balance
        account_rows.append({'id': acc.id, 'name': acc.name, 'institution': acc.institution, 'account_type': acc.account_type, 'balance': balance, 'is_active': acc.is_active, 'balance_month': max(balances, key=lambda b: b.month).month if balances else None})
    payment_rows = payments(user, month, params)
    liabilities = observed_liabilities(user, month, params)
    goals = goal_summary(user, month)
    required = sum((g['monthly_required'] for g in goals), ZERO)
    free = income - expenses - required
    contributions = total(Contribution.objects.filter(user=user, date__gte=month, date__lte=month_end(month)))
    subscription_registered = total(tx.filter(subscription__isnull=False))
    subscription_projected = sum((row['amount'] for row in projected), ZERO)
    installment_total = total(tx.filter(installment_purchase__isnull=False))
    current_month = timezone.localdate().replace(day=1)
    return {'month': month, 'assets': assets, 'liabilities': liabilities, 'net_worth': assets + free, 'income': income, 'expenses': expenses, 'expenses_registered': expenses_registered, 'expenses_forecast_increment': forecast_increment, 'goal_required': required, 'free': free, 'deficit': max(ZERO, -free), 'feasible': free >= 0 and not any(g['overdue'] and g['is_active'] for g in goals), 'contributions': contributions, 'categories': [{'name': k, 'amount': v} for k, v in sorted(categories.items(), key=lambda p: p[1], reverse=True)], 'accounts': account_rows, 'goals': goals, 'payments': payment_rows, 'subscription_total': subscription_registered + subscription_projected, 'subscription_registered_total': subscription_registered, 'subscription_projected_total': subscription_projected, 'installment_total': installment_total, 'invoice_total': card_forecast, 'invoice_forecasts': invoice_forecasts, 'is_forecast': month > current_month or bool(projected) or tx.filter(kind='expense', date__gt=timezone.localdate()).exists(), 'has_income': income > 0, 'items': monthly_items(user, month, params), 'warnings': warnings}
