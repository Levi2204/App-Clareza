from datetime import date
from decimal import Decimal
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler as drf_exception_handler
from . import models as m, serializers as ser, services as s, installments, projections
from .subscription_calendar import choose_first_charge


def exception_handler(exc, context):
    if isinstance(exc, IntegrityError):
        return Response({'detail': 'Registro duplicado ou relacionamento inválido. Verifique os dados.'}, status=400)
    return drf_exception_handler(exc, context)


def local_request_allowed(request):
    if settings.DESKTOP_TOKEN:
        import secrets
        return (settings.LOCAL_MODE
                and request.META.get('REMOTE_ADDR') == '127.0.0.1'
                and secrets.compare_digest(request.META.get('HTTP_X_CLAREZA_TOKEN', ''), settings.DESKTOP_TOKEN))
    origin = request.META.get('HTTP_ORIGIN')
    return (settings.LOCAL_MODE
            and request.META.get('REMOTE_ADDR') in ['127.0.0.1', '::1']
            and (not origin or origin in settings.CORS_ALLOWED_ORIGINS + ['http://localhost:8000', 'http://127.0.0.1:8000']))


class LocalAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if local_request_allowed(request):
            if m.LocalAccountState.objects.filter(pk=1, deleted=True).exists():
                return None
            user, _ = get_user_model().objects.get_or_create(username='local', defaults={'is_active': True})
            if user.is_active:
                return user, None
        return None

AUTH = [LocalAuthentication, SessionAuthentication]

class BaseViewSet(viewsets.ModelViewSet):
    authentication_classes = AUTH
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    def get_queryset(self):
        qs = self.queryset.filter(user=self.request.user)
        p = self.request.query_params
        for name in ['account_id', 'card_id', 'category_id']:
            if p.get(name) and not p[name].isdigit():
                raise ValidationError({name: 'Informe um identificador válido.'})
        if self.queryset.model in [m.Transaction, m.Invoice, m.Bill] and ('month' in p or 'year' in p):
            qs = qs.filter(month=s.parse_month(p))
        model = self.queryset.model
        if model in [m.Transaction, m.Subscription]:
            qs = s.filtered(qs, p)
        elif model == m.Invoice:
            if p.get('card_id'): qs = qs.filter(card_id=p['card_id'])
            if p.get('account_id'): qs = qs.filter(card__account_id=p['account_id'])
        elif model == m.Bill:
            qs = s.filtered(qs, p, card_field=None)
        return qs
    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save(user=self.request.user)
        if isinstance(obj, m.Goal): s.goal_state(obj, obj.start_date)
        if isinstance(obj, m.Subscription): s.materialize(self.request.user)
    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.instance
        if isinstance(obj, m.Subscription):
            s.materialize(self.request.user)
            m.Transaction.objects.filter(subscription=obj, date__gt=timezone.localdate()).delete()
        obj = serializer.save()
        if isinstance(obj, m.Goal): s.goal_state(obj)
        if isinstance(obj, m.Subscription): s.materialize(self.request.user)
    def perform_destroy(self, instance):
        raise ValidationError('Este cadastro possui histórico. Utilize editar para desativá-lo.')


class AccountViewSet(BaseViewSet):
    queryset = m.Account.objects.all()
    serializer_class = ser.AccountSerializer
    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        return Response(s.summary(request.user, s.parse_month(request.query_params), {'account_id': self.get_object().id}))
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        acc = self.get_object()
        qs = m.Transaction.objects.filter(user=request.user, month=s.parse_month(request.query_params)).filter(Q(account=acc) | Q(card__account=acc)).select_related('category', 'card', 'account')
        return Response(ser.TransactionSerializer(qs, many=True).data)

class CardViewSet(BaseViewSet):
    queryset = m.Card.objects.select_related('account')
    serializer_class = ser.CardSerializer

class CategoryViewSet(BaseViewSet):
    queryset = m.Category.objects.all()
    serializer_class = ser.CategorySerializer

class TransactionViewSet(BaseViewSet):
    queryset = m.Transaction.objects.select_related('category', 'card', 'account', 'invoice')
    serializer_class = ser.TransactionSerializer
    @transaction.atomic
    def save_transaction(self, serializer):
        data = serializer.validated_data
        old = serializer.instance
        card = data.get('card', old.card if old else None)
        month = data.get('month', old.month if old else None)
        invoice = s.ensure_invoice(self.request.user, card, month) if card else None
        if invoice:
            invoice = m.Invoice.objects.select_for_update().get(pk=invoice.pk)
            subtotal = s.total(invoice.transactions.exclude(pk=old.pk if old else None))
            amount = data.get('amount', old.amount if old else Decimal(0))
            if invoice.paid_on:
                raise ValidationError('Reabra a fatura antes de alterar seus gastos.')
            if invoice.manual_amount is not None and subtotal + amount > invoice.manual_amount:
                raise ValidationError({'amount': 'Os gastos ultrapassam o total manual da fatura. Atualize o total primeiro.'})
        if old and old.invoice and old.invoice.paid_on:
            raise ValidationError('Reabra a fatura antes de alterar seus gastos.')
        serializer.save(user=self.request.user, invoice=invoice)
    perform_create = save_transaction
    perform_update = save_transaction
    def perform_destroy(self, instance):
        if instance.subscription_id:
            raise ValidationError('Cancele a assinatura para interromper cobranças futuras.')
        if instance.installment_purchase_id:
            raise ValidationError('Abra a compra parcelada para cancelar parcelas restantes.')
        if instance.invoice and instance.invoice.paid_on:
            raise ValidationError('Reabra a fatura antes de excluir seus gastos.')
        instance.delete()
    @action(detail=False, methods=['get'])
    def monthly(self, request):
        return Response(projections.monthly_items(request.user, s.parse_month(request.query_params), request.query_params))

class InvoiceViewSet(BaseViewSet):
    queryset = m.Invoice.objects.select_related('card').prefetch_related('transactions')
    serializer_class = ser.InvoiceSerializer
    @action(detail=False, methods=['get'])
    def consolidated(self, request):
        return Response(s.summary(request.user, s.parse_month(request.query_params)))
    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        obj = self.get_object()
        if obj.month > timezone.localdate().replace(day=1):
            raise ValidationError('Uma fatura futura é apenas um compromisso previsto e ainda não pode ser paga.')
        if s.invoice_total(obj) <= 0:
            raise ValidationError('Uma fatura vazia não pode ser marcada como paga.')
        if projections.projected_subscriptions(request.user, obj.month, {'card_id': obj.card_id}):
            raise ValidationError('Existem cobranças previstas nesta fatura. Sincronize a competência antes de registrar o pagamento.')
        obj.paid_on = timezone.localdate(); obj.save(update_fields=['paid_on'])
        return Response(self.get_serializer(obj).data)

class BillViewSet(BaseViewSet):
    queryset = m.Bill.objects.select_related('account', 'category')
    serializer_class = ser.BillSerializer
    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        obj = self.get_object()
        if obj.month > timezone.localdate().replace(day=1):
            raise ValidationError('Uma conta futura é apenas um compromisso previsto e ainda não pode ser paga.')
        obj.paid_on = timezone.localdate(); obj.save(update_fields=['paid_on'])
        return Response(self.get_serializer(obj).data)

class SubscriptionViewSet(BaseViewSet):
    queryset = m.Subscription.objects.select_related('account', 'card', 'category')
    serializer_class = ser.SubscriptionSerializer
    @action(detail=False, methods=['post'])
    def preview(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        charged_on = values['first_charge_date']
        card = values.get('card')
        conflicts = []
        if card:
            invoice = m.Invoice.objects.filter(user=request.user, card=card, month=charged_on.replace(day=1)).prefetch_related('transactions').first()
            if invoice and invoice.paid_on:
                conflicts.append(f'A fatura de {card.name} em {charged_on:%m/%Y} está paga.')
            elif invoice and invoice.manual_amount is not None and s.total(invoice.transactions.all()) + values['amount'] > invoice.manual_amount:
                conflicts.append(f'O total manual da fatura de {card.name} em {charged_on:%m/%Y} não comporta a cobrança.')
        destination = f'Fatura do Cartão · {card.name} de {charged_on:%m/%Y}' if card else f"Conta · {values['account'].name}"
        return Response({'first_charge_date': charged_on, 'month': charged_on.replace(day=1), 'amount': values['amount'], 'destination': destination, 'conflicts': conflicts, 'can_create': not conflicts})
    def _protect_future_paid_invoices(self, subscription):
        blocked = m.Transaction.objects.filter(subscription=subscription, date__gt=timezone.localdate(), invoice__paid_on__isnull=False).select_related('invoice').first()
        if blocked:
            raise ValidationError(f'A fatura de {blocked.month:%m/%Y} está paga. Reabra-a antes de alterar a assinatura.')
    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.instance
        s.materialize(self.request.user)
        self._protect_future_paid_invoices(obj)
        m.Transaction.objects.filter(subscription=obj, date__gt=timezone.localdate()).delete()
        obj = serializer.save()
        s.materialize(self.request.user)
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        obj = self.get_object()
        if obj.is_active:
            s.materialize(request.user)
            self._protect_future_paid_invoices(obj)
            obj.is_active = False
            obj.end_date = timezone.localdate()
            obj.save(update_fields=['is_active', 'end_date'])
            m.Transaction.objects.filter(subscription=obj, date__gt=timezone.localdate()).delete()
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=['post'], url_path='review-first-charge')
    @transaction.atomic
    def review_first_charge(self, request, pk=None):
        obj = self.get_object()
        include = request.data.get('include_start_month', True)
        if not isinstance(include, bool):
            raise ValidationError({'include_start_month': 'Informe verdadeiro ou falso.'})
        candidate = choose_first_charge(obj.start_date, obj.billing_day, include)
        has_history = m.Transaction.objects.filter(subscription=obj).exists()
        can_apply = not has_history
        result = {'subscription': obj.id, 'current_first_charge_date': obj.first_charge_date, 'first_charge_date': candidate, 'can_apply': can_apply, 'reason': '' if can_apply else 'Já existem cobranças registradas; a revisão precisa ser individual para preservar o histórico.'}
        if request.data.get('apply'):
            if request.data.get('confirmation') != 'REVISAR':
                raise ValidationError({'confirmation': 'Digite REVISAR para confirmar.'})
            if not can_apply:
                raise ValidationError({'first_charge_date': result['reason']})
            obj.first_charge_date = candidate
            obj.save(update_fields=['first_charge_date'])
            s.materialize(request.user)
            result['applied'] = True
        return Response(result)


class InstallmentPurchaseViewSet(viewsets.ViewSet):
    queryset = m.InstallmentPurchase.objects.all()
    authentication_classes = AUTH
    permission_classes = [IsAuthenticated]

    def _queryset(self, request):
        return m.InstallmentPurchase.objects.filter(user=request.user).select_related('category', 'account', 'card').prefetch_related('installments')

    def list(self, request):
        return Response([installments.purchase_data(row) for row in self._queryset(request)])

    def retrieve(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        return Response(installments.purchase_data(get_object_or_404(self._queryset(request), pk=pk)))

    @action(detail=False, methods=['post'])
    def preview(self, request):
        serializer = ser.InstallmentPurchaseInputSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        values.pop('request_id', None)
        return Response(installments.preview(request.user, values))

    def create(self, request):
        serializer = ser.InstallmentPurchaseInputSerializer(data=request.data, context={'request': request, 'require_request_id': True})
        serializer.is_valid(raise_exception=True)
        purchase, created = installments.create_purchase(request.user, serializer.validated_data)
        return Response(installments.purchase_data(purchase), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def partial_update(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        purchase = get_object_or_404(self._queryset(request), pk=pk)
        serializer = ser.InstallmentPurchaseUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(installments.purchase_data(installments.update_purchase(purchase, serializer.validated_data)))

    @action(detail=True, methods=['post'], url_path='cancel-remaining')
    def cancel_remaining(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        if request.data.get('confirmation') != 'CANCELAR':
            raise ValidationError({'confirmation': 'Digite CANCELAR para confirmar.'})
        try:
            from_month = date.fromisoformat(request.data.get('from_month', ''))
        except (TypeError, ValueError):
            raise ValidationError({'from_month': 'Informe uma competência válida.'})
        purchase = get_object_or_404(self._queryset(request), pk=pk)
        return Response(installments.purchase_data(installments.cancel_remaining(purchase, from_month)))

class GoalViewSet(BaseViewSet):
    queryset = m.Goal.objects.all()
    serializer_class = ser.GoalSerializer
    @action(detail=False, methods=['get'])
    def summary(self, request):
        return Response(s.goal_summary(request.user, s.parse_month(request.query_params)))
    @action(detail=True, methods=['get', 'post'])
    def contributions(self, request, pk=None):
        goal = self.get_object()
        if request.method == 'GET':
            return Response(ser.ContributionSerializer(goal.contributions.all(), many=True).data)
        serializer = ser.ContributionSerializer(data={**request.data, 'goal': goal.id}, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=201)

@api_view(['POST'])
@authentication_classes(AUTH)
@permission_classes([IsAuthenticated])
def sync(request):
    s.materialize(request.user)
    for name in ['Alimentação', 'Moradia', 'Transporte', 'Saúde', 'Educação', 'Lazer', 'Compras', 'Assinaturas', 'Serviços', 'Outros', 'Salário']:
        m.Category.objects.get_or_create(user=request.user, name=name)
    return Response({'detail': 'Cobranças atualizadas.'})

@api_view(['GET'])
@authentication_classes(AUTH)
@permission_classes([IsAuthenticated])
def dashboard(request, year=None, month=None):
    params = request.query_params.copy()
    if year: params.update({'year': year, 'month': month})
    for key in ['account_id', 'card_id', 'category_id']:
        if params.get(key) and not str(params[key]).isdigit(): raise ValidationError({key: 'Origem inválida.'})
    selected = s.parse_month(params)
    data = s.summary(request.user, selected, params)
    history = []
    for offset in range(5, -1, -1):
        index = selected.year * 12 + selected.month - 1 - offset
        d = date(index // 12, index % 12 + 1, 1)
        row = s.summary(request.user, d, params)
        history.append({k: row[k] for k in ['month', 'net_worth', 'income', 'expenses']})
    data['history'] = history
    if request.path.startswith('/api/v1/planning/'):
        forecast = []
        for offset in range(12):
            index = selected.year * 12 + selected.month - 1 + offset
            selected_month = date(index // 12, index % 12 + 1, 1)
            row = s.summary(request.user, selected_month, params)
            forecast.append({key: row[key] for key in ['month', 'income', 'expenses', 'expenses_registered', 'expenses_forecast_increment', 'installment_total', 'subscription_projected_total', 'free', 'has_income', 'is_forecast']})
        data['forecast'] = forecast
    return Response(data)

@api_view(['GET'])
@authentication_classes(AUTH)
@permission_classes([IsAuthenticated])
def upcoming(request):
    return Response(s.payments(request.user, s.parse_month(request.query_params), request.query_params))


@api_view(['GET'])
@authentication_classes(AUTH)
@permission_classes([IsAuthenticated])
def pending(request):
    return Response(s.pending_payments(request.user, s.parse_month(request.query_params), request.query_params))
