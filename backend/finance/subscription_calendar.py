"""Single source of truth for subscription occurrence dates."""
import calendar
from datetime import date


def month_start(value):
    return value.replace(day=1)


def next_month(value):
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def recurring_date(month, billing_day):
    return month.replace(day=min(billing_day, calendar.monthrange(month.year, month.month)[1]))


def choose_first_charge(start_date, billing_day, include_start_month=True):
    """Resolve the explicit choice made when a new subscription is created."""
    regular = recurring_date(month_start(start_date), billing_day)
    if regular >= start_date:
        return regular
    if include_start_month:
        return start_date
    return recurring_date(next_month(month_start(start_date)), billing_day)


def occurrence_date(subscription, month):
    """Return at most one eligible charge date for a subscription/month."""
    month = month_start(month)
    if subscription.first_charge_date:
        first_month = month_start(subscription.first_charge_date)
        if month < first_month:
            return None
        charged_on = subscription.first_charge_date if month == first_month else recurring_date(month, subscription.billing_day)
    else:
        # Legacy subscriptions retain the original rule after the additive migration.
        charged_on = recurring_date(month, subscription.billing_day)
        if charged_on < subscription.start_date:
            return None
    if subscription.end_date and charged_on > subscription.end_date:
        return None
    if not subscription.is_active and not subscription.end_date:
        return None
    return charged_on
