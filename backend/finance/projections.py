"""Read-only monthly projections. Future subscription occurrences are never persisted here."""
import calendar
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from . import models as m
from .subscription_calendar import occurrence_date

ZERO = Decimal('0.00')


def month_end(month):
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def projected_subscriptions(user, month, params=None):
    params = params or {}
    today = timezone.localdate()
    current_month = today.replace(day=1)
    if month < current_month:
        return []
    subscriptions = m.Subscription.objects.filter(user=user, start_date__lte=month_end(month)).select_related('account', 'card__account', 'category')
    if params.get('account_id'):
        subscriptions = subscriptions.filter(Q(account_id=params['account_id']) | Q(card__account_id=params['account_id']))
    if params.get('card_id'):
        subscriptions = subscriptions.filter(card_id=params['card_id'])
    if params.get('category_id'):
        subscriptions = subscriptions.filter(category_id=params['category_id'])
    existing = set(m.Transaction.objects.filter(user=user, subscription__in=subscriptions, month=month).values_list('subscription_id', flat=True))
    rows = []
    for subscription in subscriptions:
        charged_on = occurrence_date(subscription, month)
        if subscription.id in existing or charged_on is None:
            continue
        if month == current_month and charged_on < today:
            continue
        rows.append({
            'key': f'subscription-{subscription.id}-{month:%Y-%m}',
            'id': None,
            'description': subscription.name,
            'amount': subscription.amount,
            'kind': 'expense',
            'date': charged_on,
            'month': month,
            'category': subscription.category_id,
            'category_name': subscription.category.name,
            'account': subscription.account_id,
            'card': subscription.card_id,
            'origin': subscription.card.name if subscription.card else subscription.account.name,
            'subscription': subscription.id,
            'installment_purchase': None,
            'installment_number': None,
            'installment_count': None,
            'source_type': 'subscription',
            'is_projected': True,
            'is_programmed': False,
        })
    return rows


def persisted_transaction_items(user, month, params=None):
    params = params or {}
    rows = m.Transaction.objects.filter(user=user, month=month).select_related(
        'category', 'account', 'card', 'card__account', 'installment_purchase'
    )
    if params.get('account_id'):
        rows = rows.filter(Q(account_id=params['account_id']) | Q(card__account_id=params['account_id']))
    if params.get('card_id'):
        rows = rows.filter(card_id=params['card_id'])
    if params.get('category_id'):
        rows = rows.filter(category_id=params['category_id'])
    today = timezone.localdate()
    result = []
    for row in rows:
        result.append({
            'key': f'transaction-{row.id}',
            'id': row.id,
            'description': row.description,
            'amount': row.amount,
            'kind': row.kind,
            'date': row.date,
            'month': row.month,
            'category': row.category_id,
            'category_name': row.category.name,
            'account': row.account_id,
            'card': row.card_id,
            'origin': row.card.name if row.card else row.account.name,
            'subscription': row.subscription_id,
            'installment_purchase': row.installment_purchase_id,
            'installment_number': row.installment_number,
            'installment_count': row.installment_purchase.installment_count if row.installment_purchase_id else None,
            'source_type': 'installment' if row.installment_purchase_id else ('subscription' if row.subscription_id else 'transaction'),
            'is_projected': False,
            'is_programmed': row.kind == 'expense' and row.date > today,
            'notes': row.notes,
        })
    return result


def monthly_items(user, month, params=None):
    return persisted_transaction_items(user, month, params) + projected_subscriptions(user, month, params)
