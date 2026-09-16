from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from . import models as m, services as s
from .installments import split_amount


class InstallmentProjectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('installments')
        self.other = get_user_model().objects.create_user('other-installments')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.account = m.Account.objects.create(user=self.user, name='Conta')
        self.category = m.Category.objects.create(user=self.user, name='Compras')
        self.card = m.Card.objects.create(user=self.user, name='Cartão', account=self.account, due_day=12)
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def payload(self, **changes):
        data = {
            'description': 'Notebook',
            'notes': '',
            'total_amount': '300.00',
            'installment_count': 3,
            'purchase_date': '2026-09-15',
            'first_month': '2026-09-01',
            'category': self.category.id,
            'account': self.account.id,
            'card': None,
            'request_id': 'attempt-1',
        }
        data.update(changes)
        return data

    def create(self, **changes):
        return self.client.post('/api/v1/installment-purchases/', self.payload(**changes), format='json')

    def subscription(self, billing_day=5, card=False):
        return self.client.post('/api/v1/subscriptions/', {
            'name': 'Streaming', 'amount': '20.00', 'category': self.category.id,
            'account': None if card else self.account.id, 'card': self.card.id if card else None,
            'billing_day': billing_day, 'start_date': '2026-09-01',
        }, format='json')

    def test_amount_distribution_and_calendar(self):
        self.assertEqual(split_amount(Decimal('100.00'), 3), [Decimal('33.34'), Decimal('33.33'), Decimal('33.33')])
        self.assertEqual(split_amount(Decimal('0.05'), 3), [Decimal('0.02'), Decimal('0.02'), Decimal('0.01')])
        with patch('django.utils.timezone.localdate', return_value=date(2026, 10, 31)):
            response = self.create(total_amount='100.00', purchase_date='2026-10-31', first_month='2026-10-01')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([row['date'] for row in response.data['schedule']], [date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31)])
        self.assertEqual(sum(Decimal(row['amount']) for row in response.data['schedule']), Decimal('100.00'))

    def test_leap_year_and_explicit_first_month(self):
        with patch('django.utils.timezone.localdate', return_value=date(2028, 1, 31)):
            response = self.create(
                purchase_date='2028-01-31', first_month='2028-02-01',
                installment_count=2, total_amount='2.00', request_id='leap-year',
            )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([row['date'] for row in response.data['schedule']], [date(2028, 2, 29), date(2028, 3, 31)])
        self.assertEqual(s.summary(self.user, date(2028, 1, 1))['expenses'], 0)
        self.assertEqual(s.summary(self.user, date(2028, 2, 1))['expenses'], 1)

    def test_creation_rejects_invalid_limits_origin_and_ownership(self):
        foreign_account = m.Account.objects.create(user=self.other, name='Conta alheia')
        foreign_category = m.Category.objects.create(user=self.other, name='Categoria alheia')
        invalid = [
            {'total_amount': '0'}, {'total_amount': '-1'}, {'total_amount': '0.02', 'installment_count': 3},
            {'installment_count': 0}, {'installment_count': 121}, {'installment_count': 2.5},
            {'account': None, 'card': None}, {'account': self.account.id, 'card': self.card.id},
            {'account': foreign_account.id}, {'category': foreign_category.id}, {'kind': 'income'},
        ]
        for index, changes in enumerate(invalid):
            with self.subTest(changes=changes):
                response = self.create(request_id=f'invalid-{index}', **changes)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(m.InstallmentPurchase.objects.exists())
        self.assertFalse(m.Transaction.objects.exists())

    def test_preview_validates_without_writing(self):
        payload = self.payload(total_amount='0.02')
        payload.pop('request_id')
        response = self.client.post('/api/v1/installment-purchases/preview/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(m.InstallmentPurchase.objects.exists())
        self.assertFalse(m.Transaction.objects.exists())
        self.assertEqual(self.create(first_month='2026-08-01').status_code, 400)

    def test_creation_is_atomic_and_idempotent(self):
        first = self.create()
        self.assertEqual(first.status_code, 201, first.data)
        second = self.create()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(m.InstallmentPurchase.objects.count(), 1)
        self.assertEqual(m.Transaction.objects.count(), 3)
        self.assertEqual(self.create(total_amount='301.00').status_code, 409)
        self.assertEqual([s.summary(self.user, date(2026, month, 1))['expenses'] for month in [9, 10, 11, 12]], [100, 100, 100, 0])

    def test_card_invoice_conflict_rolls_everything_back(self):
        m.Invoice.objects.create(user=self.user, card=self.card, month=date(2026, 11, 1), due_date=date(2026, 11, 12), paid_on=date(2026, 9, 15))
        response = self.create(account=None, card=self.card.id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(m.InstallmentPurchase.objects.exists())
        self.assertFalse(m.Transaction.objects.exists())

    def test_manual_invoice_conflict_in_later_month_rolls_everything_back(self):
        m.Invoice.objects.create(
            user=self.user, card=self.card, month=date(2026, 11, 1),
            due_date=date(2026, 11, 12), manual_amount=Decimal('99.00'),
        )
        response = self.create(account=None, card=self.card.id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(m.InstallmentPurchase.objects.exists())
        self.assertFalse(m.Transaction.objects.exists())
        self.assertEqual(m.Invoice.objects.count(), 1)

    def test_installments_require_purchase_actions(self):
        purchase = self.create().data
        transaction = m.Transaction.objects.get(installment_number=1)
        self.assertEqual(self.client.patch(f'/api/v1/transactions/{transaction.id}/', {'amount': '1'}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(f'/api/v1/transactions/{transaction.id}/').status_code, 400)
        response = self.client.post(f"/api/v1/installment-purchases/{purchase['id']}/cancel-remaining/", {'from_month': '2026-10-01', 'confirmation': 'CANCELAR'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(m.Transaction.objects.count(), 1)
        self.assertEqual([row['cancelled'] for row in response.data['schedule']], [False, True, True])
        self.assertEqual(response.data['cancelled_total'], Decimal('200.00'))

    def test_cancel_remaining_is_atomic_when_an_affected_invoice_is_paid(self):
        purchase = self.create(account=None, card=self.card.id).data
        invoice = m.Invoice.objects.get(month=date(2026, 11, 1))
        invoice.paid_on = date(2026, 9, 15)
        invoice.save(update_fields=['paid_on'])
        response = self.client.post(
            f"/api/v1/installment-purchases/{purchase['id']}/cancel-remaining/",
            {'from_month': '2026-10-01', 'confirmation': 'CANCELAR'}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(m.Transaction.objects.count(), 3)
        self.assertIsNone(m.InstallmentPurchase.objects.get(pk=purchase['id']).cancelled_from_month)

    def test_main_projection_and_cancel_after_charge(self):
        self.create()
        subscription = self.subscription(billing_day=5)
        self.assertEqual(subscription.status_code, 201, subscription.data)
        self.assertEqual([s.summary(self.user, date(2026, month, 1))['expenses'] for month in [9, 10, 11, 12]], [120, 120, 120, 20])
        with patch('django.utils.timezone.localdate', return_value=date(2026, 10, 10)):
            self.client.post(f"/api/v1/subscriptions/{subscription.data['id']}/cancel/")
            self.assertEqual([s.summary(self.user, date(2026, month, 1))['expenses'] for month in [9, 10, 11, 12]], [120, 120, 100, 0])

    def test_cancel_before_charge_removes_current_projection(self):
        self.create()
        subscription = self.subscription(billing_day=20)
        with patch('django.utils.timezone.localdate', return_value=date(2026, 10, 10)):
            response = self.client.post(f"/api/v1/subscriptions/{subscription.data['id']}/cancel/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(s.summary(self.user, date(2026, 10, 1))['expenses'], 100)
            self.assertEqual(s.summary(self.user, date(2026, 11, 1))['expenses'], 100)

    def test_manual_invoice_absorbs_or_warns_about_projection(self):
        self.create(account=None, card=self.card.id)
        self.subscription(card=True)
        october = m.Invoice.objects.get(card=self.card, month=date(2026, 10, 1))
        october.manual_amount = Decimal('150.00')
        october.save()
        row = s.summary(self.user, date(2026, 10, 1))
        self.assertEqual(row['expenses'], 150)
        self.assertEqual(row['expenses_registered'], 150)
        self.assertEqual(row['expenses_forecast_increment'], 0)
        october.manual_amount = Decimal('110.00')
        october.save()
        row = s.summary(self.user, date(2026, 10, 1))
        self.assertEqual(row['expenses'], 120)
        self.assertEqual(row['expenses_forecast_increment'], 10)
        self.assertEqual(len(row['warnings']), 1)
        self.assertEqual(sum(item['amount'] for item in row['categories']), row['expenses'])

    def test_future_installment_is_not_current_liability(self):
        self.create(first_month='2026-11-01', account=None, card=self.card.id)
        row = s.summary(self.user, date(2026, 11, 1))
        self.assertEqual(row['expenses'], 100)
        self.assertEqual(row['liabilities'], 0)
        self.assertEqual(row['payments'][0]['status'], 'forecast')
        invoice = m.Invoice.objects.get(month=date(2026, 11, 1))
        self.assertEqual(self.client.post(f'/api/v1/invoices/{invoice.id}/pay/').status_code, 400)

    def test_monthly_projection_is_virtual_and_filtered(self):
        self.subscription()
        before = (m.Transaction.objects.count(), m.Invoice.objects.count())
        first = self.client.get('/api/v1/transactions/monthly/?year=2026&month=10').data
        second = self.client.get('/api/v1/transactions/monthly/?year=2026&month=10').data
        self.assertEqual(first, second)
        self.assertTrue(first[0]['is_projected'])
        self.assertEqual((m.Transaction.objects.count(), m.Invoice.objects.count()), before)
        self.assertEqual(self.client.get('/api/v1/transactions/monthly/?year=2026&month=10&card_id=999').data, [])

    def test_virtual_subscriptions_are_forecast_payments_only(self):
        self.subscription()
        self.subscription(card=True)
        before = (m.Transaction.objects.count(), m.Invoice.objects.count())
        payments = s.payments(self.user, date(2026, 10, 1))
        forecasts = [row for row in payments if row['status'] == 'forecast']
        self.assertEqual(sorted(row['amount'] for row in forecasts), [Decimal('20.00'), Decimal('20.00')])
        self.assertTrue(all(row['id'] is None for row in forecasts))
        self.assertEqual((m.Transaction.objects.count(), m.Invoice.objects.count()), before)

    def test_subscription_change_is_blocked_by_paid_future_charge(self):
        subscription = self.subscription(billing_day=20)
        transaction = m.Transaction.objects.get(subscription_id=subscription.data['id'])
        transaction.invoice = m.Invoice.objects.create(user=self.user, card=self.card, month=date(2026, 9, 1), due_date=date(2026, 9, 12), paid_on=date(2026, 9, 15))
        transaction.account = None
        transaction.card = self.card
        transaction.save()
        response = self.client.post(f"/api/v1/subscriptions/{subscription.data['id']}/cancel/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(m.Subscription.objects.get(pk=subscription.data['id']).is_active)

    def test_profile_deletion_removes_purchase(self):
        self.create()
        response = self.client.delete('/api/v1/profile/', {'confirmation': 'EXCLUIR'}, format='json')
        self.assertEqual(response.status_code, 204)
        self.assertFalse(m.InstallmentPurchase.objects.exists())


class MonthlyInvoiceCorrectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('monthly-correction')
        self.client = APIClient(); self.client.force_authenticate(self.user)
        self.account = m.Account.objects.create(user=self.user, name='BB')
        self.category = m.Category.objects.create(user=self.user, name='Serviços')
        self.card = m.Card.objects.create(user=self.user, name='Cartão BB', account=self.account, due_day=11)
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 16))
        self.clock.start(); self.addCleanup(self.clock.stop)

    def subscription_payload(self, **changes):
        payload = {'name': 'Google One', 'amount': '20.00', 'category': self.category.id,
                   'account': self.account.id, 'card': None, 'billing_day': 3,
                   'start_date': '2026-09-16', 'include_start_month': True}
        payload.update(changes)
        return payload

    def test_explicit_first_charge_preview_and_creation(self):
        preview = self.client.post('/api/v1/subscriptions/preview/', self.subscription_payload(), format='json')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data['first_charge_date'], date(2026, 9, 16))
        self.assertIn('Conta · BB', preview.data['destination'])
        created = self.client.post('/api/v1/subscriptions/', self.subscription_payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['first_charge_date'], '2026-09-16')
        self.assertEqual(m.Transaction.objects.get().date, date(2026, 9, 16))
        self.assertEqual(s.summary(self.user, date(2026, 9, 1))['expenses'], 20)
        self.assertEqual(s.summary(self.user, date(2026, 10, 1))['expenses'], 20)
        self.assertEqual(s.payments(self.user, date(2026, 9, 1))[0]['status'], 'registered')
        self.assertFalse(s.payments(self.user, date(2026, 9, 1))[0]['can_pay'])

    def test_next_regular_charge_choice_skips_initial_month(self):
        payload = self.subscription_payload(include_start_month=False)
        preview = self.client.post('/api/v1/subscriptions/preview/', payload, format='json')
        self.assertEqual(preview.data['first_charge_date'], date(2026, 10, 3))
        created = self.client.post('/api/v1/subscriptions/', payload, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(m.Transaction.objects.exists())
        self.assertEqual(s.summary(self.user, date(2026, 9, 1))['expenses'], 0)
        self.assertEqual(s.summary(self.user, date(2026, 10, 1))['expenses'], 20)

    def test_regular_day_ahead_and_calendar_edges(self):
        preview = self.client.post('/api/v1/subscriptions/preview/', self.subscription_payload(billing_day=20), format='json')
        self.assertEqual(preview.data['first_charge_date'], date(2026, 9, 20))
        from .subscription_calendar import choose_first_charge
        self.assertEqual(choose_first_charge(date(2028, 1, 31), 31, True), date(2028, 1, 31))
        self.assertEqual(choose_first_charge(date(2028, 2, 1), 31, True), date(2028, 2, 29))
        self.assertEqual(choose_first_charge(date(2026, 12, 31), 3, False), date(2027, 1, 3))

    def test_card_subscription_is_only_one_invoice_component(self):
        purchase = {'description': 'Compra', 'total_amount': '200.00', 'installment_count': 2,
                    'purchase_date': '2026-09-16', 'first_month': '2026-09-01',
                    'category': self.category.id, 'account': None, 'card': self.card.id,
                    'notes': '', 'request_id': 'two-month-card'}
        self.assertEqual(self.client.post('/api/v1/installment-purchases/', purchase, format='json').status_code, 201)
        subscription = self.subscription_payload(account=None, card=self.card.id)
        self.assertEqual(self.client.post('/api/v1/subscriptions/', subscription, format='json').status_code, 201)
        expected = [(9, 120, 1), (10, 120, 1), (11, 20, 1), (12, 20, 1)]
        for month, amount, count in expected:
            with self.subTest(month=month):
                summary = s.summary(self.user, date(2026, month, 1))
                self.assertEqual(summary['expenses'], amount)
                self.assertEqual(len(summary['payments']), count)
                self.assertEqual(len(summary['invoice_forecasts']), count)
                self.assertEqual(summary['payments'][0]['amount'], amount)
        self.client.post(f"/api/v1/subscriptions/{m.Subscription.objects.get().id}/cancel/")
        self.assertEqual(s.summary(self.user, date(2026, 11, 1))['expenses'], 0)

    def test_first_card_charge_respects_manual_and_paid_invoice_atomically(self):
        invoice = m.Invoice.objects.create(user=self.user, card=self.card, month=date(2026, 9, 1), due_date=date(2026, 9, 11), manual_amount=Decimal('10.00'))
        payload = self.subscription_payload(account=None, card=self.card.id)
        preview = self.client.post('/api/v1/subscriptions/preview/', payload, format='json')
        self.assertFalse(preview.data['can_create'])
        response = self.client.post('/api/v1/subscriptions/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(m.Subscription.objects.exists())
        self.assertFalse(m.Transaction.objects.exists())
        invoice.manual_amount = None; invoice.paid_on = date(2026, 9, 16)
        invoice.save(update_fields=['manual_amount', 'paid_on'])
        response = self.client.post('/api/v1/subscriptions/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(m.Subscription.objects.exists())
        self.assertFalse(m.Transaction.objects.exists())

    def test_two_installments_end_without_empty_future_invoices(self):
        purchase = {'description': 'Compra', 'total_amount': '200.00', 'installment_count': 2,
                    'purchase_date': '2026-09-16', 'first_month': '2026-09-01',
                    'category': self.category.id, 'account': None, 'card': self.card.id,
                    'notes': '', 'request_id': 'ends-in-october'}
        self.client.post('/api/v1/installment-purchases/', purchase, format='json')
        for month, expected in [(9, 100), (10, 100), (11, 0), (12, 0)]:
            row = s.summary(self.user, date(2026, month, 1))
            self.assertEqual(row['expenses'], expected)
            self.assertEqual(len(row['payments']), 1 if expected else 0)
        empty = m.Invoice.objects.create(user=self.user, card=self.card, month=date(2026, 11, 1), due_date=date(2026, 11, 11))
        self.assertEqual(s.payments(self.user, date(2026, 11, 1)), [])
        empty.manual_amount = Decimal('12.00'); empty.save(update_fields=['manual_amount'])
        self.assertEqual(s.payments(self.user, date(2026, 11, 1))[0]['amount'], 12)

    def test_monthly_agenda_separates_previous_pending_from_liabilities(self):
        september = m.Invoice.objects.create(user=self.user, card=self.card, month=date(2026, 9, 1), due_date=date(2026, 10, 11), manual_amount=Decimal('61.24'))
        october = m.Invoice.objects.create(user=self.user, card=self.card, month=date(2026, 10, 1), due_date=date(2026, 10, 11), manual_amount=Decimal('86.26'))
        monthly = s.payments(self.user, date(2026, 10, 1))
        self.assertEqual([row['id'] for row in monthly], [october.id])
        self.assertEqual(monthly[0]['month'], date(2026, 10, 1))
        pending = s.pending_payments(self.user, date(2026, 10, 1))
        self.assertEqual([row['id'] for row in pending], [september.id])
        self.assertEqual(s.summary(self.user, date(2026, 10, 1))['liabilities'], Decimal('61.24'))
        self.assertEqual(s.summary(self.user, date(2026, 10, 1))['expenses'], Decimal('86.26'))

    def test_empty_and_same_named_cards_are_not_merged(self):
        second_account = m.Account.objects.create(user=self.user, name='Outra')
        second_card = m.Card.objects.create(user=self.user, name='Cartão BB', account=second_account, due_day=11)
        for card, amount in [(self.card, '10.00'), (second_card, '20.00')]:
            m.Invoice.objects.create(user=self.user, card=card, month=date(2026, 9, 1), due_date=date(2026, 10, 11), manual_amount=amount)
        rows = s.payments(self.user, date(2026, 9, 1))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row['key'] for row in rows}), 2)
        self.assertEqual({row['card_id'] for row in rows}, {self.card.id, second_card.id})

    def test_legacy_subscription_stays_legacy_and_review_is_conservative(self):
        legacy = m.Subscription.objects.create(user=self.user, name='Legado', amount=20,
            category=self.category, account=self.account, billing_day=3, start_date=date(2026, 9, 16))
        s.materialize(self.user)
        self.assertFalse(m.Transaction.objects.exists())
        preview = self.client.post(f'/api/v1/subscriptions/{legacy.id}/review-first-charge/', {'include_start_month': True}, format='json')
        self.assertTrue(preview.data['can_apply'])
        applied = self.client.post(f'/api/v1/subscriptions/{legacy.id}/review-first-charge/', {'include_start_month': True, 'apply': True, 'confirmation': 'REVISAR'}, format='json')
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assertEqual(m.Transaction.objects.get().date, date(2026, 9, 16))
        blocked = self.client.post(f'/api/v1/subscriptions/{legacy.id}/review-first-charge/', {'include_start_month': False}, format='json')
        self.assertFalse(blocked.data['can_apply'])
