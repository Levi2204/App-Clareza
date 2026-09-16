from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers
from . import models as m, services as s
from .installments import MAX_INSTALLMENTS
from .subscription_calendar import choose_first_charge


class OwnedSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        instance = self.instance
        def value(key, default=None):
            return attrs.get(key, getattr(instance, key, default))
        user = self.context['request'].user
        for key in ['account', 'card', 'category', 'goal']:
            related = attrs.get(key)
            if related and related.user_id != user.id:
                raise serializers.ValidationError({key: 'Este registro não pertence ao usuário.'})
            if related and hasattr(related, 'is_active') and not related.is_active:
                raise serializers.ValidationError({key: 'Selecione um cadastro ativo.'})
        for key in ['month']:
            if key in attrs:
                attrs[key] = s.month_start(attrs[key])
        if isinstance(instance, m.Transaction) and instance.subscription_id:
            raise serializers.ValidationError('Cobranças recorrentes devem ser alteradas pela assinatura.')
        if isinstance(instance, m.Transaction) and instance.installment_purchase_id:
            raise serializers.ValidationError('Parcelas devem ser alteradas pela compra parcelada.')
        if self.Meta.model in [m.Transaction, m.Subscription]:
            if bool(value('account')) == bool(value('card')):
                raise serializers.ValidationError({'account': 'Selecione exatamente uma conta ou um cartão.'})
            if value('kind') == 'income' and value('card'):
                raise serializers.ValidationError({'card': 'Receitas devem ser vinculadas a uma conta.'})
        if self.Meta.model == m.Goal:
            if instance and 'start_date' in attrs and attrs['start_date'] != instance.start_date:
                raise serializers.ValidationError({'start_date': 'A data inicial não pode mudar após o cadastro, para preservar o histórico.'})
            if value('target_date') < value('start_date'):
                raise serializers.ValidationError({'target_date': 'O prazo deve ser igual ou posterior à data inicial.'})
        if self.Meta.model == m.Subscription:
            if value('start_date') < timezone.localdate().replace(year=max(1, timezone.localdate().year - 10)):
                raise serializers.ValidationError({'start_date': 'O início deve estar nos últimos 10 anos.'})
            if value('end_date') and value('end_date') < value('start_date'):
                raise serializers.ValidationError({'end_date': 'O encerramento deve ser posterior ao início.'})
            if instance and ('start_date' in attrs or 'end_date' in attrs or 'is_active' in attrs):
                raise serializers.ValidationError('Use a ação de cancelamento; o período original é preservado.')
        if self.Meta.model == m.Contribution:
            if value('date') < value('goal').start_date or value('date') > timezone.localdate():
                raise serializers.ValidationError({'date': 'O aporte deve estar entre o início da meta e hoje.'})
        if self.Meta.model in [m.Invoice, m.Bill] and value('paid_on') and value('paid_on') > timezone.localdate():
            raise serializers.ValidationError({'paid_on': 'A data de pagamento não pode estar no futuro.'})
        if self.Meta.model == m.Invoice and value('manual_amount') is not None:
            if instance and value('manual_amount') < s.total(instance.transactions.all()):
                raise serializers.ValidationError({'manual_amount': 'O total não pode ser menor que os gastos detalhados.'})
        if self.Meta.model == m.Invoice and instance and instance.transactions.exists() and ('card' in attrs or 'month' in attrs):
            if value('card') != instance.card or value('month') != instance.month:
                raise serializers.ValidationError('Uma fatura com gastos não pode mudar de cartão ou competência.')
        return attrs


class AccountSerializer(OwnedSerializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, write_only=True, required=False)
    balance_month = serializers.DateField(write_only=True, required=False)
    class Meta:
        model = m.Account
        fields = ['id', 'name', 'institution', 'account_type', 'is_active', 'balance', 'balance_month']
    def create(self, validated_data):
        amount = validated_data.pop('balance', 0)
        month = s.month_start(validated_data.pop('balance_month', timezone.localdate()))
        account = super().create(validated_data)
        m.Balance.objects.create(account=account, month=month, amount=amount)
        return account
    def update(self, instance, validated_data):
        amount = validated_data.pop('balance', None)
        month = s.month_start(validated_data.pop('balance_month', timezone.localdate()))
        instance = super().update(instance, validated_data)
        if amount is not None:
            m.Balance.objects.update_or_create(account=instance, month=month, defaults={'amount': amount})
        return instance


def serializer_for(model):
    class Serializer(OwnedSerializer):
        class Meta:
            fields = '__all__'
            read_only_fields = ['user', 'created_at']
        Meta.model = model
    return Serializer

CardSerializer = serializer_for(m.Card)
CategorySerializer = serializer_for(m.Category)
GoalSerializer = serializer_for(m.Goal)
ContributionSerializer = serializer_for(m.Contribution)
BillSerializer = serializer_for(m.Bill)


class SubscriptionSerializer(OwnedSerializer):
    include_start_month = serializers.BooleanField(write_only=True, required=False, default=True)

    class Meta:
        model = m.Subscription
        fields = ['id', 'name', 'amount', 'category', 'account', 'card', 'billing_day',
                  'start_date', 'first_charge_date', 'end_date', 'is_active', 'created_at',
                  'include_start_month']
        read_only_fields = ['first_charge_date', 'end_date', 'is_active', 'created_at']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        include = attrs.get('include_start_month', True)
        if self.instance is None:
            attrs['first_charge_date'] = choose_first_charge(
                attrs['start_date'], attrs['billing_day'], include
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('include_start_month', None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('include_start_month', None)
        return super().update(instance, validated_data)

class TransactionSerializer(OwnedSerializer):
    origin = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    def get_origin(self, obj):
        return obj.card.name if obj.card else obj.account.name
    class Meta:
        model = m.Transaction
        fields = '__all__'
        read_only_fields = ['user', 'created_at', 'invoice', 'subscription', 'installment_purchase', 'installment_number']

class InvoiceSerializer(OwnedSerializer):
    total = serializers.SerializerMethodField()
    card_name = serializers.CharField(source='card.name', read_only=True)
    def get_total(self, obj):
        return str(s.invoice_total(obj))
    class Meta:
        model = m.Invoice
        fields = '__all__'
        read_only_fields = ['user', 'created_at']


class InstallmentPurchaseInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['expense', 'income'], required=False, default='expense', write_only=True)
    description = serializers.CharField(max_length=150)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    installment_count = serializers.IntegerField(min_value=2, max_value=MAX_INSTALLMENTS)
    purchase_date = serializers.DateField()
    first_month = serializers.DateField()
    category = serializers.PrimaryKeyRelatedField(queryset=m.Category.objects.all())
    account = serializers.PrimaryKeyRelatedField(queryset=m.Account.objects.all(), required=False, allow_null=True)
    card = serializers.PrimaryKeyRelatedField(queryset=m.Card.objects.all(), required=False, allow_null=True)
    request_id = serializers.CharField(max_length=64, required=False)

    def validate(self, attrs):
        user = self.context['request'].user
        if attrs.pop('kind') != 'expense':
            raise serializers.ValidationError({'kind': 'Somente despesas podem ser parceladas.'})
        account, card = attrs.get('account'), attrs.get('card')
        if bool(account) == bool(card):
            raise serializers.ValidationError({'account': 'Selecione exatamente uma conta ou um cartão.'})
        for field in ['category', 'account', 'card']:
            obj = attrs.get(field)
            if obj and obj.user_id != user.id:
                raise serializers.ValidationError({field: 'Este registro não pertence ao usuário.'})
            if obj and not obj.is_active:
                raise serializers.ValidationError({field: 'Selecione um cadastro ativo.'})
        attrs['first_month'] = attrs['first_month'].replace(day=1)
        if attrs['purchase_date'] > timezone.localdate():
            raise serializers.ValidationError({'purchase_date': 'A data da compra não pode estar no futuro.'})
        if attrs['first_month'] < attrs['purchase_date'].replace(day=1):
            raise serializers.ValidationError({'first_month': 'A primeira parcela não pode ser anterior ao mês da compra.'})
        if self.context.get('require_request_id') and not attrs.get('request_id'):
            raise serializers.ValidationError({'request_id': 'Identificador da tentativa é obrigatório.'})
        return attrs


class InstallmentPurchaseUpdateSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=150, required=False)
    notes = serializers.CharField(max_length=5000, required=False, allow_blank=True)
