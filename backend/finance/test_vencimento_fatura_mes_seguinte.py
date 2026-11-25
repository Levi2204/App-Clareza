"""Testes de integração estilo request spec (RSpec describe/it) para vencimento de fatura
no mês seguinte sem falso atraso e contabilização de gastos no "Seu mês, planejado"
(vencimentoFaturaMesSeguinteSemFalsoAtrasoTest.md).

Cada teste chama as rotas reais da API (/api/v1/...) com banco de teste SQLite real,
sem mockar banco de dados nem regras de negócio (controlando apenas localdate).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from . import models as m


def run_simultaneously(fn1, fn2):
    """Dispara duas requisições exatamente ao mesmo tempo (equivalente a Promise.all)."""
    barrier = threading.Barrier(2)

    def wrapper(fn):
        try:
            barrier.wait(timeout=5)
            return fn()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(wrapper, fn1)
        f2 = executor.submit(wrapper, fn2)
        return f1.result(timeout=15), f2.result(timeout=15)


class DescribeVencimentoFaturaMesSeguinteSemFalsoAtraso(TestCase):
    """describe: Vencimento de fatura no mês seguinte sem falso atraso e gastos no 'Seu mês, planejado'."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_bb_vencimento')
        self.other = get_user_model().objects.create_user('other_bb_vencimento')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.account = m.Account.objects.create(user=self.user, name='Banco do Brasil')
        self.category = m.Category.objects.create(user=self.user, name='Compras')
        self.card = m.Card.objects.create(
            user=self.user,
            name='BB Ourocard',
            account=self.account,
            closing_day=30,
            due_day=11,
        )

    # =========================================================================
    # a. Caminho feliz (Cenários 1 a 6 de vencimentoFaturaMesSeguinteSemFalsoAtrasoTest.md)
    # =========================================================================
    def test_a1_cenario1_quando_cartao_bb_fecha_30_vence_11_em_25_11_com_gastos_assinatura_parcela_e_manual_entao_planejamento_novembro_soma_tudo_sem_falso_atraso_e_sem_duplicar_em_dezembro(self):
        """it: quando registra assinatura (R$ 50), compra à vista (R$ 200), parcelada 2x (R$ 300)
        e manual_amount (R$ 600) no cartão BB (fecha 30, vence 11) em 25/11/2026,
        então novembro contabiliza R$ 600,00 (free=3400, net_worth=4900), fatura 11/2026 vence em 11/12/2026
        com status 'pending' (days_until=16, nunca 'overdue') e dezembro contabiliza apenas R$ 200,00.
        """
        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 25)):
            m.Balance.objects.create(account=self.account, month=date(2026, 11, 1), amount=Decimal('1500.00'))
            res_inc = self.client.post('/api/v1/transactions/', {
                'description': 'Salário Novembro',
                'amount': '4000.00',
                'kind': 'income',
                'date': '2026-11-05',
                'month': '2026-11-01',
                'category': self.category.id,
                'account': self.account.id,
            }, format='json')
            self.assertEqual(res_inc.status_code, 201, res_inc.data)

            # 1. Assinatura ativa de R$ 50,00 (billing_day=10, start_date=2026-11-01) + sync
            res_sub = self.client.post('/api/v1/subscriptions/', {
                'name': 'Streaming BB',
                'amount': '50.00',
                'billing_day': 10,
                'start_date': '2026-11-01',
                'category': self.category.id,
                'card': self.card.id,
            }, format='json')
            self.assertEqual(res_sub.status_code, 201, res_sub.data)
            self.assertEqual(self.client.post('/api/v1/sync/').status_code, 200)

            # 2. Compra à vista de R$ 200,00 em 15/11/2026
            res_buy = self.client.post('/api/v1/transactions/', {
                'description': 'Compra à vista 15/11',
                'amount': '200.00',
                'kind': 'expense',
                'date': '2026-11-15',
                'category': self.category.id,
                'card': self.card.id,
            }, format='json')
            self.assertEqual(res_buy.status_code, 201, res_buy.data)

            # 3. Compra parcelada de R$ 300,00 em 2x em 20/11/2026
            res_inst = self.client.post('/api/v1/installment-purchases/', {
                'description': 'Compra 2x 20/11',
                'notes': '',
                'total_amount': '300.00',
                'installment_count': 2,
                'purchase_date': '2026-11-20',
                'category': self.category.id,
                'account': None,
                'card': self.card.id,
                'request_id': 'req-bb-cenario-1',
            }, format='json')
            self.assertEqual(res_inst.status_code, 201, res_inst.data)

            # 4. Definir manual_amount = '600.00' na fatura 11/2026
            inv_nov = m.Invoice.objects.get(card=self.card, month=date(2026, 11, 1))
            res_patch = self.client.patch(f'/api/v1/invoices/{inv_nov.id}/', {
                'manual_amount': '600.00',
            }, format='json')
            self.assertEqual(res_patch.status_code, 200, res_patch.data)

            # Verificação 1: "Seu mês, planejado" em Novembro (dashboard e planning)
            dash_nov = self.client.get('/api/v1/dashboard/?year=2026&month=11')
            plan_nov = self.client.get('/api/v1/planning/2026/11/')
            self.assertEqual(dash_nov.status_code, 200)
            self.assertEqual(plan_nov.status_code, 200)

            for payload in [dash_nov.data, plan_nov.data]:
                self.assertEqual(Decimal(payload['expenses']), Decimal('600.00'))
                self.assertEqual(Decimal(payload['expenses_registered']), Decimal('600.00'))
                self.assertEqual(Decimal(payload['free']), Decimal('3400.00'))
                self.assertEqual(Decimal(payload['net_worth']), Decimal('4900.00'))
                cats = {c['name']: Decimal(str(c['amount'])) for c in payload['categories']}
                self.assertEqual(sum(cats.values(), Decimal('0.00')), Decimal('600.00'))
                self.assertEqual(cats.get('Faturas sem detalhamento'), Decimal('200.00'))

            # Verificação 2: Vencimento e status da fatura 11/2026
            inv_nov.refresh_from_db()
            self.assertEqual(inv_nov.cycle_closing_date, date(2026, 11, 30))
            self.assertEqual(inv_nov.due_date, date(2026, 12, 11))

            upcoming = self.client.get('/api/v1/payments/upcoming/?year=2026&month=11')
            consolidated = self.client.get('/api/v1/invoices/consolidated/?year=2026&month=11')
            self.assertEqual(upcoming.status_code, 200)
            self.assertEqual(consolidated.status_code, 200)

            for payment_list in [dash_nov.data['payments'], upcoming.data, consolidated.data['payments']]:
                self.assertFalse(any(item['status'] == 'overdue' for item in payment_list))
                bb_item = next(item for item in payment_list if item.get('card_id') == self.card.id)
                self.assertEqual(bb_item['status'], 'pending')
                self.assertEqual(bb_item['days_until'], 16)
                self.assertEqual(str(bb_item['due_date']), '2026-12-11')

            # Verificação 3: Não duplicação em Dezembro
            dash_dec = self.client.get('/api/v1/dashboard/?year=2026&month=12')
            self.assertEqual(dash_dec.status_code, 200)
            self.assertEqual(Decimal(dash_dec.data['expenses']), Decimal('200.00'))

    def test_a2_cenario2_quando_compra_ocorre_no_dia_exato_do_fechamento_30_11_entao_fatura_dezembro_vence_11_01_mas_gasto_entra_em_novembro_sem_atraso(self):
        """it: quando registra compra de R$ 120,00 em 30/11/2026 (hoje=30/11/2026, fecha=30, vence=11),
        então a compra vai para a fatura 12/2026 (vence 11/01/2027), mas entra em expenses de novembro (120.00)
        e nenhuma fatura aparece como 'overdue'.
        """
        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 30)):
            res = self.client.post('/api/v1/transactions/', {
                'description': 'Compra no fechamento 30/11',
                'amount': '120.00',
                'kind': 'expense',
                'date': '2026-11-30',
                'category': self.category.id,
                'card': self.card.id,
            }, format='json')
            self.assertEqual(res.status_code, 201, res.data)

            tx = m.Transaction.objects.get(pk=res.data['id'])
            self.assertEqual(tx.month, date(2026, 12, 1))
            self.assertEqual(tx.invoice.month, date(2026, 12, 1))
            self.assertEqual(tx.invoice.cycle_closing_date, date(2026, 12, 30))
            self.assertEqual(tx.invoice.due_date, date(2027, 1, 11))
            self.assertFalse(m.Invoice.objects.filter(card=self.card, month=date(2026, 11, 1)).exists())

            dash_nov = self.client.get('/api/v1/dashboard/?year=2026&month=11')
            self.assertEqual(dash_nov.status_code, 200)
            self.assertEqual(Decimal(dash_nov.data['expenses']), Decimal('120.00'))
            self.assertFalse(any(p['status'] == 'overdue' for p in dash_nov.data['payments']))

    def test_a3_cenario3_quando_assinatura_materializada_ou_apenas_projetada_usa_cartao_due_day_menor_igual_closing_day_entao_vence_no_mes_seguinte(self):
        """it: quando assinatura é materializada antes de compras ou apenas projetada (sem fatura persistida),
        então a fatura criada ou projetada respeita due_date no mês seguinte (11/12/2026 e 11/01/2027).
        """
        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 25)):
            # 1. Assinatura materializada antes de qualquer compra (billing_day=5)
            res_sub_mat = self.client.post('/api/v1/subscriptions/', {
                'name': 'Assinatura Materializada',
                'amount': '45.00',
                'billing_day': 5,
                'start_date': '2026-11-01',
                'category': self.category.id,
                'card': self.card.id,
            }, format='json')
            self.assertEqual(res_sub_mat.status_code, 201, res_sub_mat.data)
            self.assertEqual(self.client.post('/api/v1/sync/').status_code, 200)

            inv_nov = m.Invoice.objects.get(card=self.card, month=date(2026, 11, 1))
            self.assertEqual(inv_nov.due_date, date(2026, 12, 11))
            self.assertEqual(inv_nov.cycle_closing_date, date(2026, 11, 30))
            self.assertEqual(inv_nov.cycle_policy, 'closing-day-v1')

            dash_nov = self.client.get('/api/v1/dashboard/?year=2026&month=11')
            self.assertEqual(dash_nov.data['payments'][0]['status'], 'pending')

            # Compra avulsa em 18/11/2026 entra na mesma fatura sem conflito de ciclo
            res_buy = self.client.post('/api/v1/transactions/', {
                'description': 'Compra 18/11 após assinatura',
                'amount': '80.00',
                'kind': 'expense',
                'date': '2026-11-18',
                'category': self.category.id,
                'card': self.card.id,
            }, format='json')
            self.assertEqual(res_buy.status_code, 201, res_buy.data)

            # 2. Assinatura apenas projetada em cartão separado (sem fatura persistida no banco)
            card_proj = m.Card.objects.create(
                user=self.user, name='BB Projetado', account=self.account, closing_day=30, due_day=11
            )
            res_sub_proj = self.client.post('/api/v1/subscriptions/', {
                'name': 'Assinatura Futura',
                'amount': '60.00',
                'billing_day': 28,
                'start_date': '2026-11-28',
                'category': self.category.id,
                'card': card_proj.id,
            }, format='json')
            self.assertEqual(res_sub_proj.status_code, 201, res_sub_proj.data)
            self.assertFalse(m.Invoice.objects.filter(card=card_proj).exists())

            dash_proj_nov = self.client.get(f'/api/v1/dashboard/?year=2026&month=11&card_id={card_proj.id}')
            dash_proj_dec = self.client.get(f'/api/v1/dashboard/?year=2026&month=12&card_id={card_proj.id}')
            self.assertEqual(str(dash_proj_nov.data['invoice_forecasts'][0]['due_date']), '2026-12-11')
            self.assertEqual(str(dash_proj_dec.data['invoice_forecasts'][0]['due_date']), '2027-01-11')

    def test_a4_cenario4_quando_existe_fatura_aberta_legada_com_due_date_errado_e_paga_anterior_entao_leitura_ja_corrige_e_sync_repara_apenas_a_aberta(self):
        """it: quando existe fatura aberta legada de 11/2026 com due_date=10/11/2026 e fatura paga de 10/2026,
        então mesmo antes do sync o dashboard retorna pending e 2026-12-11 (expenses=450.00), o sync repara
        permanentemente a fatura aberta preservando manual_amount=450.00 e deixa a paga de 10/2026 intocada.
        """
        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 25)):
            inv_open = m.Invoice.objects.create(
                user=self.user,
                card=self.card,
                month=date(2026, 11, 1),
                due_date=date(2026, 11, 10),
                cycle_closing_date=date(2026, 11, 30),
                cycle_policy='',
                manual_amount=Decimal('450.00'),
                paid_on=None,
            )
            inv_paid = m.Invoice.objects.create(
                user=self.user,
                card=self.card,
                month=date(2026, 10, 1),
                due_date=date(2026, 10, 10),
                cycle_closing_date=date(2026, 10, 30),
                cycle_policy='',
                manual_amount=Decimal('300.00'),
                paid_on=date(2026, 10, 10),
            )

            # 1. Antes do sync, leitura já corrige status e due_date
            dash_before = self.client.get('/api/v1/dashboard/?year=2026&month=11')
            self.assertEqual(dash_before.status_code, 200)
            self.assertEqual(Decimal(dash_before.data['expenses']), Decimal('450.00'))
            bb_before = next(p for p in dash_before.data['payments'] if p['card_id'] == self.card.id)
            self.assertEqual(bb_before['status'], 'pending')
            self.assertEqual(str(bb_before['due_date']), '2026-12-11')

            # 2. Sync repara permanentemente a fatura aberta
            self.assertEqual(self.client.post('/api/v1/sync/').status_code, 200)
            inv_open.refresh_from_db()
            self.assertEqual(inv_open.due_date, date(2026, 12, 11))
            self.assertEqual(inv_open.cycle_closing_date, date(2026, 11, 30))
            self.assertEqual(inv_open.cycle_policy, 'closing-day-v1')
            self.assertEqual(inv_open.manual_amount, Decimal('450.00'))

            # 3. Fatura paga de 10/2026 permanece 100% intocada
            inv_paid.refresh_from_db()
            self.assertEqual(inv_paid.due_date, date(2026, 10, 10))
            self.assertEqual(inv_paid.paid_on, date(2026, 10, 10))
            self.assertEqual(inv_paid.manual_amount, Decimal('300.00'))

    def test_a5_cenario5_quando_transita_em_dezembro_de_05_12_para_12_12_entao_muda_de_pending_para_overdue(self):
        """it: quando a fatura 11/2026 (vence 11/12/2026) está em aberto, então em 05/12/2026
        payments/pending retorna status='pending' e days_until=6, e em 12/12/2026 retorna status='overdue'.
        """
        m.Invoice.objects.create(
            user=self.user,
            card=self.card,
            month=date(2026, 11, 1),
            due_date=date(2026, 12, 11),
            cycle_closing_date=date(2026, 11, 30),
            cycle_policy='closing-day-v1',
            manual_amount=Decimal('250.00'),
        )

        with patch('django.utils.timezone.localdate', return_value=date(2026, 12, 5)):
            pending_before = self.client.get('/api/v1/payments/pending/?year=2026&month=12')
            self.assertEqual(pending_before.status_code, 200)
            self.assertEqual(len(pending_before.data), 1)
            self.assertEqual(pending_before.data[0]['status'], 'pending')
            self.assertEqual(pending_before.data[0]['days_until'], 6)

        with patch('django.utils.timezone.localdate', return_value=date(2026, 12, 12)):
            pending_after = self.client.get('/api/v1/payments/pending/?year=2026&month=12')
            self.assertEqual(pending_after.status_code, 200)
            self.assertEqual(len(pending_after.data), 1)
            self.assertEqual(pending_after.data[0]['status'], 'overdue')

    def test_a6_cenario6_quando_edita_closing_day_e_due_day_do_cartao_ou_cria_fatura_sem_due_date_entao_calcula_vencimento_no_mes_seguinte(self):
        """it: quando altera closing_day/due_day do cartão de (5, 12) para (30, 11), então a fatura aberta
        de 11/2026 atualiza due_date para 2026-12-11 e aceita novas compras em novembro; e quando cria fatura
        via POST /api/v1/invoices/ omitindo due_date, retorna 201 com due_date='2026-12-11'.
        """
        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 25)):
            card_edit = m.Card.objects.create(
                user=self.user, name='Cartão Editável', account=self.account, closing_day=5, due_day=12
            )
            res_buy1 = self.client.post('/api/v1/transactions/', {
                'description': 'Compra 02/11',
                'amount': '100.00',
                'kind': 'expense',
                'date': '2026-11-02',
                'category': self.category.id,
                'card': card_edit.id,
            }, format='json')
            self.assertEqual(res_buy1.status_code, 201)
            inv = m.Invoice.objects.get(card=card_edit, month=date(2026, 11, 1))
            self.assertEqual(inv.due_date, date(2026, 11, 12))

            # 1. PATCH do cartão para closing_day=30, due_day=11
            res_patch = self.client.patch(f'/api/v1/cards/{card_edit.id}/', {
                'closing_day': 30,
                'due_day': 11,
            }, format='json')
            self.assertEqual(res_patch.status_code, 200, res_patch.data)

            inv.refresh_from_db()
            self.assertEqual(inv.due_date, date(2026, 12, 11))
            self.assertEqual(inv.cycle_closing_date, date(2026, 11, 30))

            # Nova compra em 20/11 entra na fatura 11/2026 sem erro de conflito
            res_buy2 = self.client.post('/api/v1/transactions/', {
                'description': 'Compra 20/11 pós edição',
                'amount': '90.00',
                'kind': 'expense',
                'date': '2026-11-20',
                'category': self.category.id,
                'card': card_edit.id,
            }, format='json')
            self.assertEqual(res_buy2.status_code, 201, res_buy2.data)

            # 2. POST /api/v1/invoices/ omitindo due_date no cartão BB (30, 11)
            res_inv = self.client.post('/api/v1/invoices/', {
                'card': self.card.id,
                'month': '2026-11-01',
                'manual_amount': '500.00',
            }, format='json')
            self.assertEqual(res_inv.status_code, 201, res_inv.data)
            self.assertEqual(str(res_inv.data['due_date']), '2026-12-11')

    # =========================================================================
    # b. Erros esperados
    # =========================================================================
    def test_b1_quando_envia_manual_amount_negativo_ou_dias_invalidos_no_cartao_entao_retorna_400(self):
        """it: quando envia manual_amount negativo, month inválido ou closing_day/due_day fora de 1..31, retorna 400."""
        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 25)):
            bad_amount = self.client.post('/api/v1/invoices/', {
                'card': self.card.id,
                'month': '2026-11-01',
                'due_date': '2026-12-11',
                'manual_amount': '-10.00',
            }, format='json')
            self.assertEqual(bad_amount.status_code, 400)

            bad_days = self.client.patch(f'/api/v1/cards/{self.card.id}/', {
                'closing_day': 32,
                'due_day': 0,
            }, format='json')
            self.assertEqual(bad_days.status_code, 400)

    # =========================================================================
    # d. Limites
    # =========================================================================
    def test_d1_quando_cartao_tem_closing_day_e_due_day_31_em_mes_curto_entao_ajusta_para_ultimo_dia_do_mes_seguinte(self):
        """it: quando cartão tem closing_day=31 e due_day=31 na competência 01/2027,
        então due_date da fatura 01/2027 é ajustado para 28/02/2027 (mês seguinte sem estourar calendário).
        """
        with patch('django.utils.timezone.localdate', return_value=date(2027, 1, 20)):
            card_31 = m.Card.objects.create(
                user=self.user, name='Cartão 31/31', account=self.account, closing_day=31, due_day=31
            )
            res = self.client.post('/api/v1/invoices/', {
                'card': card_31.id,
                'month': '2027-01-01',
                'manual_amount': '300.00',
            }, format='json')
            self.assertEqual(res.status_code, 201, res.data)
            self.assertEqual(str(res.data['due_date']), '2027-02-28')

    # =========================================================================
    # e. Acesso indevido
    # =========================================================================
    def test_e1_quando_usuario_b_tem_fatura_legada_ou_edita_cartao_entao_usuario_a_nao_acessa_nem_altera_fatura_de_b(self):
        """it: quando usuário A tenta consultar ou alterar fatura/cartão do usuário B, recebe 404."""
        acc_b = m.Account.objects.create(user=self.other, name='Conta B')
        card_b = m.Card.objects.create(user=self.other, name='Cartão B', account=acc_b, closing_day=30, due_day=11)
        inv_b = m.Invoice.objects.create(
            user=self.other,
            card=card_b,
            month=date(2026, 11, 1),
            due_date=date(2026, 12, 11),
            manual_amount=Decimal('900.00'),
        )

        self.assertEqual(self.client.patch(f'/api/v1/invoices/{inv_b.id}/', {'manual_amount': '1.00'}, format='json').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/v1/cards/{card_b.id}/', {'due_day': 15}, format='json').status_code, 404)


class DescribeVencimentoFaturaMesSeguinteConcorrencia(TransactionTestCase):
    """describe: Repetição e Concorrência no auto-reparo de faturas legadas via POST /api/v1/sync/."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_bb_conc')
        self.account = m.Account.objects.create(user=self.user, name='Banco do Brasil')
        self.card = m.Card.objects.create(
            user=self.user, name='BB Ourocard', account=self.account, closing_day=30, due_day=11
        )

    def test_c1_quando_dispara_sync_simultaneamente_com_fatura_legada_aberta_entao_repara_sem_erro_nem_duplicacao(self):
        """it: quando duas requisições simultâneas chamam POST /api/v1/sync/ com fatura legada aberta,
        então ambas respondem 200 e mantêm uma única fatura reparada para 11/2026 com due_date=2026-12-11.
        """
        inv = m.Invoice.objects.create(
            user=self.user,
            card=self.card,
            month=date(2026, 11, 1),
            due_date=date(2026, 11, 10),
            cycle_closing_date=date(2026, 11, 30),
            cycle_policy='',
            manual_amount=Decimal('450.00'),
        )

        def call_sync():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.post('/api/v1/sync/')

        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 25)):
            r1, r2 = run_simultaneously(call_sync, call_sync)
            self.assertEqual([r1.status_code, r2.status_code], [200, 200])
            self.assertEqual(m.Invoice.objects.filter(card=self.card, month=date(2026, 11, 1)).count(), 1)
            inv.refresh_from_db()
            self.assertEqual(inv.due_date, date(2026, 12, 11))
            self.assertEqual(inv.manual_amount, Decimal('450.00'))
