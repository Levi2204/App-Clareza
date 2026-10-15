"""Credit-card cycle calendar rules.

The invoice competence names the cycle that closes in the following month.
Purchases strictly before the effective closing date belong to the previous
competence; a purchase on the closing date starts the new competence.
"""
import calendar
from datetime import date


CARD_CYCLE_POLICY = 'closing-day-v1'


def add_months(value, offset):
    index = value.year * 12 + value.month - 1 + offset
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def effective_closing_day(year, month, closing_day):
    return min(closing_day, calendar.monthrange(year, month)[1])


def effective_closing_date(value, closing_day):
    return date(value.year, value.month, effective_closing_day(value.year, value.month, closing_day))


def card_competence(purchase_date, closing_day):
    purchase_month = purchase_date.replace(day=1)
    if purchase_date < effective_closing_date(purchase_date, closing_day):
        return add_months(purchase_month, -1)
    return purchase_month


def cycle_closing_date(competence, closing_day):
    closing_month = add_months(competence.replace(day=1), 1)
    return effective_closing_date(closing_month, closing_day)


def calculate_due_date(competence, closing_day, due_day):
    closing = cycle_closing_date(competence, closing_day)
    candidate = closing.replace(day=min(due_day, calendar.monthrange(closing.year, closing.month)[1]))
    if candidate <= closing:
        following = add_months(closing, 1)
        candidate = following.replace(day=min(due_day, calendar.monthrange(following.year, following.month)[1]))
    return candidate
