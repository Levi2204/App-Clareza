from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from . import models as m, services as s


class FinanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('tester')
        self.other = get_user_model().objects.create_user('other')
        self.client = APIClient(); self.client.force_authenticate(self.user)
        self.account = m.Account.objects.create(user=self.user, name='Nubank')
        self.account2 = m.Account.objects.create(user=self.user, name='Inter')
        self.category = m.Category.objects.create(user=self.user, name='Alimentação')
        self.card = m.Card.objects.create(user=self.user, name='Crédito', account=self.account)
        self.month = date(2026, 9, 1)
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15)); self.clock.start(); self.addCleanup(self.clock.stop)
    def post(self, resource, data):
        return self.client.post(f'/api/v1/{resource}/', data, format='json')
    def expense(self, **extra):
        payload = {'description': 'Mercado', 'amount': '100.50', 'kind': 'expense', 'date': '2026-09-10', 'month': '2026-09-01', 'category': self.category.id, 'account': self.account.id}
        payload.update(extra)
        return self.post('transactions', payload)
    def goal(self, **kwargs):
        payload = {'name': 'Viagem', 'target_amount': '1200.00', 'start_date': '2026-09-01', 'target_date': '2026-12-31'}
        payload.update(kwargs)
        return self.post('goals', payload)
    def subscription(self, **extra):
        payload = {'name': 'Serviço', 'amount': '30.00', 'category': self.category.id, 'account': self.account.id, 'billing_day': 10, 'start_date': '2026-08-01'}
        payload.update(extra)
        return self.post('subscriptions', payload)
    def test_invalid_money_dates_and_relationships(self):
        foreign = m.Account.objects.create(user=self.other, name='Outra pessoa')
        for changes in [{'amount': '-1'}, {'amount': 'abc'}, {'amount': '0'}, {'amount': '1.001'}, {'date': '2026-02-31'}, {'account': 999}, {'account': foreign.id}, {'account': None}, {'card': self.card.id}]:
            with self.subTest(changes=changes): self.assertEqual(self.expense(**changes).status_code, 400)
    def test_create_update_filter_and_sum(self):
        response = self.expense(); self.assertEqual(response.status_code, 201, response.data)
        self.expense(account=self.account2.id, amount='49.50')
        self.expense(month='2026-08-01', amount='70')
        rows = self.client.get(f'/api/v1/transactions/?year=2026&month=9&account_id={self.account.id}').data
        self.assertEqual(len(rows), 1)
        self.assertEqual(s.summary(self.user, self.month)['expenses'], Decimal('150.00'))
        new_category = m.Category.objects.create(user=self.user, name='Outros')
        update = self.client.patch(f"/api/v1/transactions/{response.data['id']}/", {'amount': '200', 'category': new_category.id}, format='json')
        self.assertEqual(update.status_code, 200)
        self.assertEqual(s.summary(self.user, self.month)['expenses'], Decimal('249.50'))
        self.assertEqual(s.summary(self.user, self.month)['categories'][0]['name'], 'Outros')
    def test_accounts_history_survives_archival(self):
        m.Balance.objects.create(account=self.account, month=date(2026, 8, 1), amount=1000)
        self.client.patch(f'/api/v1/accounts/{self.account.id}/', {'balance': '2500', 'balance_month': '2026-09-01', 'is_active': False}, format='json')
        self.assertEqual(s.summary(self.user, date(2026, 8, 1))['assets'], 1000)
        self.assertEqual(s.summary(self.user, self.month)['assets'], 2500)
    def test_invoice_manual_total_not_duplicated(self):
        r = self.expense(account=None, card=self.card.id)
        self.assertEqual(r.status_code, 201, r.data)
        invoice = m.Invoice.objects.get()
        self.assertEqual(s.invoice_total(invoice), Decimal('100.50'))
        response = self.client.patch(f'/api/v1/invoices/{invoice.id}/', {'manual_amount': '300.00'}, format='json')
        self.assertEqual(response.status_code, 200)
        summary = s.summary(self.user, self.month)
        self.assertEqual(summary['expenses'], 300)
        self.assertEqual(sum(c['amount'] for c in summary['categories']), 300)
        self.assertEqual(summary['liabilities'], 300)
        self.assertEqual(self.expense(account=None, card=self.card.id, amount='300').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/v1/invoices/{invoice.id}/', {'manual_amount': '10'}, format='json').status_code, 400)
    def test_two_cards_consolidation_and_account_isolation(self):
        card2 = m.Card.objects.create(user=self.user, name='Inter Crédito', account=self.account2)
        self.expense(account=None, card=self.card.id, amount='120')
        self.expense(account=None, card=card2.id, amount='80')
        self.assertEqual(s.summary(self.user, self.month)['invoice_total'], 200)
        self.assertEqual(s.summary(self.user, self.month, {'account_id': self.account.id})['invoice_total'], 120)
    def test_assets_liabilities_and_payment_history(self):
        m.Balance.objects.create(account=self.account, month=date(2026, 8, 1), amount=1000)
        bill = m.Bill.objects.create(user=self.user, description='Internet', amount=120, account=self.account, category=self.category, month=date(2026, 8, 1), due_date=date(2026, 8, 20))
        self.assertEqual(s.summary(self.user, self.month)['net_worth'], 1000)
        self.assertEqual(self.client.post(f'/api/v1/bills/{bill.id}/pay/').status_code, 200)
        self.assertEqual(s.summary(self.user, self.month)['net_worth'], 1000)
        self.assertEqual(s.summary(self.user, date(2026, 8, 1))['liabilities'], 120)
    def test_subscriptions_idempotence_and_cancel(self):
        response = self.subscription(); self.assertEqual(response.status_code, 201, response.data)
        s.materialize(self.user); s.materialize(self.user)
        self.assertEqual(m.Transaction.objects.count(), 2)
        self.assertEqual(s.summary(self.user, self.month)['expenses'], 30)
        self.assertEqual(self.client.post(f"/api/v1/subscriptions/{response.data['id']}/cancel/").status_code, 200)
        with patch('django.utils.timezone.localdate', return_value=date(2026, 10, 15)):
            s.materialize(self.user)
        self.assertEqual(m.Transaction.objects.count(), 2)
        self.assertEqual(s.summary(self.user, date(2026, 10, 1))['expenses'], 0)
        self.assertEqual(s.summary(self.user, date(2026, 8, 1))['expenses'], 30)
    def test_cancel_future_charge(self):
        sub = self.subscription(start_date='2026-09-01', billing_day=25)
        self.assertEqual(m.Transaction.objects.count(), 1)
        self.client.post(f"/api/v1/subscriptions/{sub.data['id']}/cancel/")
        s.materialize(self.user)
        self.assertEqual(m.Transaction.objects.count(), 0)
    def test_subscription_changes_preserve_old_amount(self):
        sub = self.subscription()
        self.client.patch(f"/api/v1/subscriptions/{sub.data['id']}/", {'amount': '50'}, format='json')
        self.assertEqual(s.summary(self.user, date(2026, 8, 1))['expenses'], 30)
        with patch('django.utils.timezone.localdate', return_value=date(2026, 10, 15)):
            s.materialize(self.user)
        self.assertEqual(s.summary(self.user, date(2026, 10, 1))['expenses'], 50)
    def test_goal_validation_and_contributions(self):
        for changes in [{'target_amount': '0'}, {'target_amount': '-1'}, {'target_date': '2026-08-01'}]:
            self.assertEqual(self.goal(**changes).status_code, 400)
        goal = self.goal(); self.assertEqual(goal.status_code, 201, goal.data)
        endpoint = f"goals/{goal.data['id']}/contributions"
        self.assertEqual(self.post(endpoint, {'amount': '-20', 'date': '2026-09-10'}).status_code, 400)
        self.assertEqual(self.post(endpoint, {'amount': '200', 'date': '2026-09-10'}).status_code, 201)
        row = s.goal_summary(self.user, self.month)[0]
        self.assertEqual(row['accumulated'], 200)
        self.assertEqual(row['remaining'], 1000)
        self.assertEqual(row['monthly_required'], 250)
        self.assertEqual(row['progress'], Decimal('16.7'))
    def test_planning_positive_deficit_and_multiple_goals(self):
        self.goal(); self.goal(name='Notebook', target_amount='800')
        self.expense(kind='income', amount='1000')
        self.expense(amount='200')
        row = s.summary(self.user, self.month)
        self.assertEqual(row['goal_required'], 500)
        self.assertEqual(row['free'], 300)
        self.assertTrue(row['feasible'])
        self.expense(amount='400')
        row = s.summary(self.user, self.month)
        self.assertEqual(row['deficit'], 100)
        self.assertFalse(row['feasible'])
    def test_goal_history_after_change_and_archive(self):
        response = self.goal(start_date='2026-08-01')
        self.client.patch(f"/api/v1/goals/{response.data['id']}/", {'target_amount': '2400', 'is_active': False}, format='json')
        past = s.goal_summary(self.user, date(2026, 8, 1))[0]
        self.assertEqual(past['target_amount'], 1200)
        self.assertTrue(past['is_active'])
        self.assertEqual(s.goal_summary(self.user, self.month)[0]['monthly_required'], 0)
    def test_due_day_clamped_and_overdue(self):
        self.assertEqual(s.due(date(2026, 2, 1), 31), date(2026, 2, 28))
        self.expense(account=None, card=self.card.id)
        rows = s.payments(self.user, self.month)
        self.assertEqual(rows[0]['status'], 'overdue')
        self.assertEqual(rows[0]['due_date'], date(2026, 9, 12))
    def test_api_authentication_filters_and_history(self):
        self.expense()
        for url in ['/api/v1/dashboard/?year=2026&month=9', '/api/v1/history/2026/9/', '/api/v1/planning/2026/9/', '/api/v1/invoices/consolidated/']:
            self.assertEqual(self.client.get(url).status_code, 200)
        for url in ['/api/v1/dashboard/?month=13', '/api/v1/transactions/?account_id=nope']:
            self.assertEqual(self.client.get(url).status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/transactions/').data, [])
        self.client.force_authenticate(None)
        with override_settings(LOCAL_MODE=False):
            self.assertEqual(self.client.get('/api/v1/accounts/').status_code, 403)
    def test_foreign_web_origin_rejected(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/v1/accounts/', HTTP_ORIGIN='https://untrusted.example').status_code, 403)


class ProfileTests(TestCase):
    setUp = FinanceTests.setUp
    post = FinanceTests.post
    expense = FinanceTests.expense
    goal = FinanceTests.goal
    subscription = FinanceTests.subscription
    def test_profile_edit_and_theme_persist(self):
        response = self.client.patch('/api/v1/profile/', {'display_name': 'Levi', 'email': 'levi@example.com', 'phone': '(85) 99999-9999', 'bio': 'Meus planos', 'theme': 'dark'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.get('/api/v1/profile/').data['display_name'], 'Levi')
        self.assertEqual(self.client.get('/api/v1/profile/').data['theme'], 'dark')
        self.assertEqual(self.client.get('/api/v1/profile/').data['email'], 'levi@example.com')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/profile/').data['display_name'], 'Meu espaço')

    def test_profile_invalid_fields_and_photo(self):
        for data in [{'email': 'invalido'}, {'display_name': ''}, {'theme': 'purple'}, {'photo': 'data:image/svg+xml;base64,xxx'}, {'photo': 'data:image/png;base64,aGVsbG8='}]:
            self.assertEqual(self.client.patch('/api/v1/profile/', data, format='json').status_code, 400)

    def test_photo_upload_and_removal(self):
        import base64, struct, zlib, binascii
        def chunk(kind, content):
            return struct.pack('>I',len(content))+kind+content+struct.pack('>I',binascii.crc32(kind+content)&0xffffffff)
        png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00\xff'))+chunk(b'IEND',b'')
        photo = 'data:image/png;base64,'+base64.b64encode(png).decode()
        self.assertEqual(self.client.patch('/api/v1/profile/', {'photo':photo},format='json').status_code,200)
        self.assertEqual(self.client.get('/api/v1/profile/').data['photo'],photo)
        self.client.patch('/api/v1/profile/', {'photo':''},format='json')
        self.assertEqual(self.client.get('/api/v1/profile/').data['photo'],'')

    def test_delete_requires_confirmation_and_removes_only_owner(self):
        self.expense(account=None,card=self.card.id)
        self.subscription()
        goal = self.goal()
        self.post(f"goals/{goal.data['id']}/contributions", {'amount':'20','date':'2026-09-10'})
        m.Balance.objects.create(account=self.account,month=self.month,amount=100)
        other_account=m.Account.objects.create(user=self.other,name='Preservar')
        self.assertEqual(self.client.delete('/api/v1/profile/',{},format='json').status_code,400)
        self.assertTrue(m.Account.objects.filter(user=self.user).exists())
        self.assertEqual(self.client.delete('/api/v1/profile/',{'confirmation':'EXCLUIR'},format='json').status_code,204)
        self.assertFalse(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertTrue(m.Account.objects.filter(pk=other_account.pk).exists())

    def test_local_deletion_survives_reloads_until_explicit_creation(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/v1/profile/').status_code,200)
        self.assertEqual(self.client.delete('/api/v1/profile/',{'confirmation':'EXCLUIR'},format='json').status_code,204)
        self.assertEqual(self.client.get('/api/v1/profile/').data,{'deleted':True})
        self.assertEqual(self.client.get('/api/v1/accounts/').status_code,403)
        self.assertFalse(get_user_model().objects.filter(username='local').exists())
        self.assertEqual(self.client.post('/api/v1/profile/',{'confirmation':'CRIAR'},format='json').status_code,201)
        self.assertEqual(self.client.get('/api/v1/accounts/').data,[])

    def test_profile_rejects_external_origin(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/v1/profile/',HTTP_ORIGIN='https://other.example').status_code,403)
