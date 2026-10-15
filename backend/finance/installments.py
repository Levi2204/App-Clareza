"""Creation and lifecycle rules for monthly installment purchases."""
import calendar
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from . import models as m
from .card_cycle import calculate_due_date, cycle_closing_date

MAX_INSTALLMENTS = 120


class IdempotencyConflict(APIException):
    status_code = 409
    default_detail = 'Este identificador de envio já foi usado com dados diferentes.'


def add_months(month, offset):
    index = month.year * 12 + month.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def installment_date(purchase_date, month):
    return month.replace(day=min(purchase_date.day, calendar.monthrange(month.year, month.month)[1]))


def scheduled_card_date(purchase_date, offset):
    index = purchase_date.year * 12 + purchase_date.month - 1 + offset
    year, month_index = divmod(index, 12)
    month = month_index + 1
    return date(year, month, min(purchase_date.day, calendar.monthrange(year, month)[1]))


def split_amount(total_amount, count):
    cents = int(total_amount * 100)
    if count < 2 or count > MAX_INSTALLMENTS:
        raise ValidationError({'installment_count': f'Informe entre 2 e {MAX_INSTALLMENTS} parcelas.'})
    if cents < count:
        raise ValidationError({'total_amount': 'O valor precisa permitir pelo menos R$ 0,01 por parcela.'})
    base, remainder = divmod(cents, count)
    return [Decimal(base + (1 if number < remainder else 0)) / 100 for number in range(count)]


def schedule_for(values):
    amounts = split_amount(values['total_amount'], values['installment_count'])
    first = values['first_month'].replace(day=1)
    card = values.get('card')
    schedule = []
    for index, amount in enumerate(amounts):
        month = add_months(first, index)
        row = {
            'number': index + 1,
            'month': month,
            'date': scheduled_card_date(values['purchase_date'], index) if card else installment_date(values['purchase_date'], month),
            'amount': amount,
        }
        if card:
            row.update({
                'closing_date': cycle_closing_date(month, card.closing_day),
                'due_date': calculate_due_date(month, card.closing_day, card.due_day),
            })
        schedule.append(row)
    return schedule


def _invoice_conflicts(user, card, schedule, lock=False):
    if not card:
        return []
    query = m.Invoice.objects.filter(user=user, card=card, month__in=[row['month'] for row in schedule]).prefetch_related('transactions')
    if lock:
        query = query.select_for_update()
    invoices = {invoice.month: invoice for invoice in query}
    conflicts = []
    for row in schedule:
        invoice = invoices.get(row['month'])
        if not invoice:
            continue
        label = row['month'].strftime('%m/%Y')
        from .services import invoice_cycle_conflict
        cycle_conflict = invoice_cycle_conflict(invoice, card, row['month'])
        if cycle_conflict:
            conflicts.append({'month': row['month'], 'kind': 'cycle', 'message': cycle_conflict})
        if invoice.paid_on:
            conflicts.append({'month': row['month'], 'kind': 'paid_invoice', 'message': f'A fatura de {card.name} em {label} está paga. Reabra-a antes de parcelar.'})
        detailed = sum((item.amount for item in invoice.transactions.all()), Decimal('0.00'))
        if invoice.manual_amount is not None and detailed + row['amount'] > invoice.manual_amount:
            conflicts.append({'month': row['month'], 'kind': 'manual_amount', 'message': f'O total manual da fatura de {card.name} em {label} não comporta a parcela.'})
    return conflicts


def preview(user, values):
    schedule = schedule_for(values)
    conflicts = _invoice_conflicts(user, values.get('card'), schedule)
    public_schedule = [{**row, 'cancelled': False} for row in schedule]
    if values.get('card'):
        public_schedule = [_serialize_card_schedule_row(row) for row in public_schedule]
    return {
        'schedule': public_schedule,
        'total_amount': values['total_amount'],
        'installment_count': values['installment_count'],
        'sum': sum((row['amount'] for row in schedule), Decimal('0.00')),
        'conflicts': conflicts,
        'can_create': not conflicts,
    }


def _same_payload(purchase, values):
    comparable = ['description', 'notes', 'total_amount', 'installment_count', 'purchase_date']
    if not purchase.card_id:
        comparable.append('first_month')
    return all(getattr(purchase, key) == values.get(key, '' if key == 'notes' else None) for key in comparable) and purchase.category_id == values['category'].id and purchase.account_id == getattr(values.get('account'), 'id', None) and purchase.card_id == getattr(values.get('card'), 'id', None)


@transaction.atomic
def create_purchase(user, values):
    existing = m.InstallmentPurchase.objects.filter(user=user, request_id=values['request_id']).first()
    if existing:
        if not _same_payload(existing, values):
            raise IdempotencyConflict()
        return existing, False

    schedule = schedule_for(values)
    conflicts = _invoice_conflicts(user, values.get('card'), schedule, lock=True)
    if conflicts:
        raise ValidationError({'conflicts': [row['message'] for row in conflicts]})
    try:
        with transaction.atomic():
            purchase = m.InstallmentPurchase.objects.create(user=user, **values)
    except IntegrityError:
        existing = m.InstallmentPurchase.objects.get(user=user, request_id=values['request_id'])
        if not _same_payload(existing, values):
            raise IdempotencyConflict()
        return existing, False

    for row in schedule:
        invoice = None
        if purchase.card:
            from .services import ensure_invoice
            invoice = ensure_invoice(user, purchase.card, row['month'])
        m.Transaction.objects.create(
            user=user,
            description=purchase.description,
            notes=purchase.notes,
            amount=row['amount'],
            kind='expense',
            date=row['date'],
            month=row['month'],
            category=purchase.category,
            account=purchase.account,
            card=purchase.card,
            invoice=invoice,
            installment_purchase=purchase,
            installment_number=row['number'],
        )
    return purchase, True


def purchase_data(purchase):
    original = schedule_for({
        'total_amount': purchase.total_amount,
        'installment_count': purchase.installment_count,
        'purchase_date': purchase.purchase_date,
        'first_month': purchase.first_month,
        'card': purchase.card,
    })
    transactions = {row.installment_number: row for row in purchase.installments.all()}
    invoices = {
        invoice.month: invoice
        for invoice in m.Invoice.objects.filter(
            user=purchase.user,
            card=purchase.card,
            month__in=[row['month'] for row in original],
        )
    } if purchase.card else {}
    schedule = []
    maintained = Decimal('0.00')
    cancelled = Decimal('0.00')
    for row in original:
        item = transactions.get(row['number'])
        invoice = invoices.get(row['month'])
        if invoice:
            row['closing_date'] = invoice.cycle_closing_date or row.get('closing_date')
            row['due_date'] = invoice.due_date
        is_cancelled = item is None and purchase.cancelled_from_month is not None and row['month'] >= purchase.cancelled_from_month
        if is_cancelled:
            cancelled += row['amount']
        else:
            maintained += row['amount']
        public_row = {**row, 'cancelled': is_cancelled}
        schedule.append(_serialize_card_schedule_row(public_row) if purchase.card else public_row)
    return {
        'id': purchase.id,
        'description': purchase.description,
        'notes': purchase.notes,
        'total_amount': purchase.total_amount,
        'installment_count': purchase.installment_count,
        'purchase_date': purchase.purchase_date,
        'first_month': purchase.first_month,
        'category': purchase.category_id,
        'category_name': purchase.category.name,
        'account': purchase.account_id,
        'card': purchase.card_id,
        'origin': purchase.card.name if purchase.card else purchase.account.name,
        'request_id': purchase.request_id,
        'cancelled_from_month': purchase.cancelled_from_month,
        'cancelled_at': purchase.cancelled_at,
        'maintained_total': maintained,
        'cancelled_total': cancelled,
        'schedule': schedule,
    }


def _serialize_card_schedule_row(row):
    return {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in row.items()
    }


@transaction.atomic
def update_purchase(purchase, values):
    changed = []
    for field in ['description', 'notes']:
        if field in values and getattr(purchase, field) != values[field]:
            setattr(purchase, field, values[field])
            changed.append(field)
    if changed:
        purchase.save(update_fields=changed)
        updates = {}
        if 'description' in changed:
            updates['description'] = purchase.description
        if 'notes' in changed:
            updates['notes'] = purchase.notes
        purchase.installments.update(**updates)
    return purchase


@transaction.atomic
def cancel_remaining(purchase, from_month):
    from_month = from_month.replace(day=1)
    current = timezone.localdate().replace(day=1)
    if from_month < current:
        raise ValidationError({'from_month': 'Não é possível cancelar parcelas de competências passadas.'})
    if purchase.cancelled_from_month and from_month >= purchase.cancelled_from_month:
        return purchase
    affected = purchase.installments.filter(month__gte=from_month).select_related('invoice')
    paid = affected.filter(invoice__paid_on__isnull=False).first()
    if paid:
        raise ValidationError({'from_month': f'A fatura de {paid.month:%m/%Y} está paga. Reabra-a antes de cancelar as parcelas.'})
    affected.delete()
    purchase.cancelled_from_month = from_month
    purchase.cancelled_at = timezone.now()
    purchase.save(update_fields=['cancelled_from_month', 'cancelled_at'])
    purchase._prefetched_objects_cache = {}
    return purchase
