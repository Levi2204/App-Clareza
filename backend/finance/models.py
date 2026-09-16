from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q


def money(default=0, positive=False):
    return models.DecimalField(max_digits=14, decimal_places=2, default=default, validators=[MinValueValidator(Decimal('0.01') if positive else Decimal('0'))])


class Owned(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        abstract = True
        ordering = ['-id']


class Account(Owned):
    name = models.CharField(max_length=100)
    institution = models.CharField(max_length=100, blank=True)
    account_type = models.CharField(max_length=20, choices=[('checking', 'Conta corrente'), ('savings', 'Poupança'), ('investment', 'Investimento'), ('cash', 'Dinheiro')], default='checking')
    is_active = models.BooleanField(default=True)


class Balance(models.Model):
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='balances')
    month = models.DateField()
    amount = money()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['account', 'month'], name='unique_balance_month'), models.CheckConstraint(condition=Q(amount__gte=0), name='balance_nonnegative')]


class Card(Owned):
    name = models.CharField(max_length=100)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='cards')
    closing_day = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(31)])
    due_day = models.PositiveSmallIntegerField(default=12, validators=[MinValueValidator(1), MaxValueValidator(31)])
    is_active = models.BooleanField(default=True)


class Category(Owned):
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='unique_user_category')]


class Invoice(Owned):
    card = models.ForeignKey(Card, on_delete=models.PROTECT, related_name='invoices')
    month = models.DateField()
    due_date = models.DateField()
    manual_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    paid_on = models.DateField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['card', 'month'], name='unique_card_invoice'), models.CheckConstraint(condition=Q(manual_amount__gte=0) | Q(manual_amount__isnull=True), name='invoice_nonnegative')]


class Subscription(Owned):
    name = models.CharField(max_length=100)
    amount = money(positive=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True)
    card = models.ForeignKey(Card, on_delete=models.PROTECT, null=True, blank=True)
    billing_day = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(31)])
    start_date = models.DateField()
    first_charge_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(account__isnull=False, card__isnull=True) | Q(account__isnull=True, card__isnull=False)), name='subscription_one_origin'), models.CheckConstraint(condition=Q(amount__gt=0), name='subscription_positive')]


class InstallmentPurchase(Owned):
    description = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    total_amount = money(positive=True)
    installment_count = models.PositiveSmallIntegerField(validators=[MinValueValidator(2), MaxValueValidator(120)])
    purchase_date = models.DateField()
    first_month = models.DateField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True)
    card = models.ForeignKey(Card, on_delete=models.PROTECT, null=True, blank=True)
    request_id = models.CharField(max_length=64)
    cancelled_from_month = models.DateField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-id']
        constraints = [
            models.CheckConstraint(condition=Q(total_amount__gt=0), name='installment_purchase_positive'),
            models.CheckConstraint(condition=Q(installment_count__gte=2, installment_count__lte=120), name='installment_count_range'),
            models.CheckConstraint(condition=(Q(account__isnull=False, card__isnull=True) | Q(account__isnull=True, card__isnull=False)), name='installment_purchase_one_origin'),
            models.UniqueConstraint(fields=['user', 'request_id'], name='unique_installment_request'),
        ]


class Transaction(Owned):
    description = models.CharField(max_length=150)
    amount = money(positive=True)
    kind = models.CharField(max_length=10, choices=[('expense', 'Despesa'), ('income', 'Receita')], default='expense')
    date = models.DateField()
    month = models.DateField(db_index=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True)
    card = models.ForeignKey(Card, on_delete=models.PROTECT, null=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name='transactions')
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, null=True, blank=True)
    installment_purchase = models.ForeignKey(InstallmentPurchase, on_delete=models.PROTECT, null=True, blank=True, related_name='installments')
    installment_number = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='transaction_positive'),
            models.CheckConstraint(condition=(Q(account__isnull=False, card__isnull=True, invoice__isnull=True) | Q(account__isnull=True, card__isnull=False, invoice__isnull=False, kind='expense')), name='transaction_valid_origin'),
            models.CheckConstraint(condition=(Q(installment_number__isnull=True, installment_purchase__isnull=True) | Q(installment_number__isnull=False, installment_purchase__isnull=False, kind='expense', subscription__isnull=True)), name='transaction_installment_fields'),
            models.UniqueConstraint(fields=['subscription', 'month'], name='unique_subscription_charge'),
            models.UniqueConstraint(fields=['installment_purchase', 'installment_number'], name='unique_purchase_installment_number'),
            models.UniqueConstraint(fields=['installment_purchase', 'month'], name='unique_purchase_installment_month'),
        ]


class Bill(Owned):
    description = models.CharField(max_length=150)
    amount = money(positive=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    month = models.DateField(db_index=True)
    due_date = models.DateField()
    paid_on = models.DateField(null=True, blank=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='bill_positive')]


class Goal(Owned):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    target_amount = money(positive=True)
    start_date = models.DateField()
    target_date = models.DateField()
    term_type = models.CharField(max_length=10, choices=[('short', 'Curto prazo'), ('medium', 'Médio prazo'), ('long', 'Longo prazo')], default='short')
    priority = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(5)])
    is_active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(target_amount__gt=0), name='goal_positive'), models.CheckConstraint(condition=Q(target_date__gte=models.F('start_date')), name='goal_valid_dates')]


class GoalState(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.PROTECT, related_name='states')
    month = models.DateField()
    name = models.CharField(max_length=120)
    target_amount = money(positive=True)
    target_date = models.DateField()
    is_active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['goal', 'month'], name='unique_goal_state')]


class Contribution(Owned):
    goal = models.ForeignKey(Goal, on_delete=models.PROTECT, related_name='contributions')
    amount = money(positive=True)
    date = models.DateField()
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='contribution_positive')]


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=100, default='Meu espaço')
    phone = models.CharField(max_length=30, blank=True)
    bio = models.CharField(max_length=300, blank=True)
    photo = models.TextField(blank=True)
    theme = models.CharField(max_length=5, choices=[('light', 'Claro'), ('dark', 'Escuro')], default='light')


class LocalAccountState(models.Model):
    """Preserves the explicit deletion of the single local workspace across reloads."""
    deleted = models.BooleanField(default=False)
