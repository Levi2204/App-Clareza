"""Testes de integração estilo request spec (RSpec describe/it) para contabilização
de gastos de cartão no resumo financeiro do mês da compra (gastosCartaoResumoMesAtualTest.md).

Cada teste chama as rotas reais da API (/api/v1/...) com banco de teste SQLite real,
sem mockar banco de dados nem regras de negócio.
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

from . import models as m, services as s


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


class DescribeGastosCartaoResumoMesDaCompra(TestCase):
    """describe: Contabilização de gastos de cartão no resumo financeiro do mês da compra (sem aguardar a fatura do mês seguinte)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_resumo_cartao')
        self.other = get_user_model().objects.create_user('other_resumo_cartao')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.account = m.Account.objects.create(user=self.user, name='Conta Principal')
        self.category = m.Category.objects.create(user=self.user, name='Compras')
        self.card = m.Card.objects.create(
            user=self.user,
            name='Cartão Fecha 4 Vence 11',
            account=self.account,
            closing_day=4,
            due_day=11,
        )

        # Data atual (hoje) = 09/11/2026 conforme especificação
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 11, 9))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    # =========================================================================
    # a. Caminho feliz (Cenários 1, 2, 3 e 4 de gastosCartaoResumoMesAtualTest.md)
    # =========================================================================
    def test_a1_cenario1_quando_registra_compra_simples_em_07_11_apos_fechamento_dia_4_entao_vincula_fatura_dezembro_mas_contabiliza_no_resumo_e_movimentacoes_de_novembro_sem_duplicar_em_dezembro(self):
        """it: quando registra compra simples em 07/11 em cartão que fecha dia 4 e vence dia 11 (hoje=09/11/2026),
        então vincula à fatura 12/2026, contabiliza os R$ 200,00 em expenses/free/net_worth/categories e movimentações
        de novembro (11/2026) e não duplica em expenses de dezembro (12/2026).
        """
        m.Balance.objects.create(account=self.account, month=date(2026, 11, 1), amount=Decimal('2000.00'))
        res_inc = self.client.post('/api/v1/transactions/', {
            'description': 'Salário Novembro',
            'amount': '3000.00',
            'kind': 'income',
            'date': '2026-11-05',
            'month': '2026-11-01',
            'category': self.category.id,
            'account': self.account.id,
        }, format='json')
        self.assertEqual(res_inc.status_code, 201, res_inc.data)

        # Ação: Compra de R$ 200,00 em 07/11/2026 (após fechamento dia 4)
        res_buy = self.client.post('/api/v1/transactions/', {
            'description': 'Compra 07/11 pós-fechamento',
            'amount': '200.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        self.assertEqual(res_buy.status_code, 201, res_buy.data)

        # 1. Vínculo de Fatura (Ciclo do Cartão): Fatura de Dezembro (2026-12-01), fecha 04/12, vence 11/12
        tx = m.Transaction.objects.get(pk=res_buy.data['id'])
        self.assertEqual(tx.month, date(2026, 12, 1))
        self.assertIsNotNone(tx.invoice)
        self.assertEqual(tx.invoice.month, date(2026, 12, 1))
        self.assertEqual(tx.invoice.cycle_closing_date, date(2026, 12, 4))
        self.assertEqual(tx.invoice.due_date, date(2026, 12, 11))
        self.assertFalse(m.Invoice.objects.filter(card=self.card, month=date(2026, 11, 1)).exists())

        # 2. Resumo Financeiro de Novembro via rota GET /api/v1/dashboard/?year=2026&month=11 e s.summary
        dash_nov = self.client.get('/api/v1/dashboard/?year=2026&month=11')
        self.assertEqual(dash_nov.status_code, 200)
        summary_nov = s.summary(self.user, date(2026, 11, 1))

        self.assertEqual(summary_nov['expenses'], Decimal('200.00'))
        self.assertEqual(summary_nov['expenses_registered'], Decimal('200.00'))
        self.assertEqual(summary_nov['free'], Decimal('2800.00'))
        self.assertEqual(summary_nov['net_worth'], Decimal('4800.00'))
        self.assertEqual(Decimal(dash_nov.data['expenses']), Decimal('200.00'))
        self.assertEqual(Decimal(dash_nov.data['free']), Decimal('2800.00'))
        self.assertEqual(Decimal(dash_nov.data['net_worth']), Decimal('4800.00'))

        cats_nov = {c['name']: Decimal(str(c['amount'])) for c in summary_nov['categories']}
        self.assertEqual(cats_nov.get(self.category.name), Decimal('200.00'))

        # 3. Listagem de Movimentações de Novembro (GET /api/v1/transactions/monthly/?year=2026&month=11)
        monthly_nov = self.client.get('/api/v1/transactions/monthly/?year=2026&month=11')
        self.assertEqual(monthly_nov.status_code, 200)
        descriptions_nov = [item['description'] for item in monthly_nov.data]
        self.assertIn('Compra 07/11 pós-fechamento', descriptions_nov)

        # 4. Não duplicação no Resumo Financeiro de Dezembro (12/2026)
        summary_dec = s.summary(self.user, date(2026, 12, 1))
        self.assertEqual(summary_dec['expenses'], Decimal('0.00'))
        self.assertEqual(summary_dec['invoice_total'], Decimal('200.00'))

    def test_a2_cenario2_quando_compra_antes_do_fechamento_03_11_e_depois_do_fechamento_07_11_entao_separa_faturas_mas_soma_ambas_no_resumo_de_novembro(self):
        """it: quando registra compra em 03/11 (R$ 150) e em 07/11 (R$ 250) no cartão que fecha dia 4,
        então ambas somam R$ 400,00 em expenses de novembro (free = R$ 600,00) e aparecem em transactions/monthly de novembro,
        mas as faturas 11/2026 (R$ 150,00) e 12/2026 (R$ 250,00) permanecem separadas.
        """
        self.client.post('/api/v1/transactions/', {
            'description': 'Receita Novembro',
            'amount': '1000.00',
            'kind': 'income',
            'date': '2026-11-01',
            'month': '2026-11-01',
            'category': self.category.id,
            'account': self.account.id,
        }, format='json')

        r1 = self.client.post('/api/v1/transactions/', {
            'description': 'Compra 03/11 antes do fechamento',
            'amount': '150.00',
            'kind': 'expense',
            'date': '2026-11-03',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        r2 = self.client.post('/api/v1/transactions/', {
            'description': 'Compra 07/11 depois do fechamento',
            'amount': '250.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)

        # 1. Ambas contam no resumo financeiro de Novembro (11/2026)
        summary_nov = s.summary(self.user, date(2026, 11, 1))
        self.assertEqual(summary_nov['expenses'], Decimal('400.00'))
        self.assertEqual(summary_nov['free'], Decimal('600.00'))

        monthly_nov = self.client.get('/api/v1/transactions/monthly/?year=2026&month=11').data
        descriptions = {item['description'] for item in monthly_nov}
        self.assertIn('Compra 03/11 antes do fechamento', descriptions)
        self.assertIn('Compra 07/11 depois do fechamento', descriptions)

        # 2. Faturas permanecem separadas (11/2026 com R$ 150 e 12/2026 com R$ 250)
        inv_nov = m.Invoice.objects.get(card=self.card, month=date(2026, 11, 1))
        inv_dec = m.Invoice.objects.get(card=self.card, month=date(2026, 12, 1))
        self.assertEqual(inv_nov.cycle_closing_date, date(2026, 11, 4))
        self.assertEqual(inv_nov.due_date, date(2026, 11, 11))
        self.assertEqual(s.invoice_total(inv_nov), Decimal('150.00'))

        self.assertEqual(inv_dec.cycle_closing_date, date(2026, 12, 4))
        self.assertEqual(inv_dec.due_date, date(2026, 12, 11))
        self.assertEqual(s.invoice_total(inv_dec), Decimal('250.00'))

        self.assertEqual(summary_nov['invoice_total'], Decimal('150.00'))
        self.assertEqual(s.summary(self.user, date(2026, 12, 1))['invoice_total'], Decimal('250.00'))

    def test_a3_cenario3_quando_compra_parcelada_em_07_11_apos_fechamento_dia_4_entao_faturas_em_dez_jan_fev_e_resumo_mensal_em_nov_dez_jan(self):
        """it: quando registra compra parcelada de R$ 300,00 em 3x em 07/11/2026 no cartão que fecha dia 4,
        então as 3 parcelas entram nas faturas 12/2026, 01/2027 e 02/2027, mas os gastos mensais (expenses e installment_total)
        caem em 11/2026, 12/2026 e 01/2027 (e 0,00 em 02/2027).
        """
        self.client.post('/api/v1/transactions/', {
            'description': 'Receita Novembro',
            'amount': '1000.00',
            'kind': 'income',
            'date': '2026-11-01',
            'month': '2026-11-01',
            'category': self.category.id,
            'account': self.account.id,
        }, format='json')

        res = self.client.post('/api/v1/installment-purchases/', {
            'description': 'Monitor 3x',
            'notes': '',
            'total_amount': '300.00',
            'installment_count': 3,
            'purchase_date': '2026-11-07',
            'category': self.category.id,
            'account': None,
            'card': self.card.id,
            'request_id': 'req-cenario-3',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)

        # 1. Faturas do cartão: 12/2026, 01/2027 e 02/2027 com R$ 100,00 cada
        self.assertEqual(
            [row['month'] for row in res.data['schedule']],
            ['2026-12-01', '2027-01-01', '2027-02-01'],
        )
        for inv_month in [date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)]:
            inv = m.Invoice.objects.get(card=self.card, month=inv_month)
            self.assertEqual(s.invoice_total(inv), Decimal('100.00'))

        # 2. Resumo financeiro mensal de cada mês
        sum_nov = s.summary(self.user, date(2026, 11, 1))
        self.assertEqual(sum_nov['expenses'], Decimal('100.00'))
        self.assertEqual(sum_nov['installment_total'], Decimal('100.00'))
        self.assertEqual(sum_nov['free'], Decimal('900.00'))

        sum_dec = s.summary(self.user, date(2026, 12, 1))
        self.assertEqual(sum_dec['expenses'], Decimal('100.00'))
        self.assertEqual(sum_dec['installment_total'], Decimal('100.00'))

        sum_jan = s.summary(self.user, date(2027, 1, 1))
        self.assertEqual(sum_jan['expenses'], Decimal('100.00'))
        self.assertEqual(sum_jan['installment_total'], Decimal('100.00'))

        sum_feb = s.summary(self.user, date(2027, 2, 1))
        self.assertEqual(sum_feb['expenses'], Decimal('0.00'))
        self.assertEqual(sum_feb['installment_total'], Decimal('0.00'))
        self.assertEqual(sum_feb['invoice_total'], Decimal('100.00'))

    def test_a4_cenario4_quando_exclui_compra_avulsa_ou_parcelada_de_07_11_entao_restaura_imediatamente_valor_disponivel_em_novembro(self):
        """it: quando exclui a compra de 07/11/2026 (avulsa ou parcelada), então o resumo de novembro (11/2026)
        volta imediatamente a ter expenses=0.00 e o free/net_worth restaurados ao valor integral.
        """
        m.Balance.objects.create(account=self.account, month=date(2026, 11, 1), amount=Decimal('2000.00'))
        self.client.post('/api/v1/transactions/', {
            'description': 'Salário',
            'amount': '3000.00',
            'kind': 'income',
            'date': '2026-11-05',
            'month': '2026-11-01',
            'category': self.category.id,
            'account': self.account.id,
        }, format='json')

        # 1. Compra avulsa em 07/11 -> exclui -> restaura
        tx_res = self.client.post('/api/v1/transactions/', {
            'description': 'Avulsa 07/11',
            'amount': '200.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        self.assertEqual(s.summary(self.user, date(2026, 11, 1))['expenses'], Decimal('200.00'))

        del_tx = self.client.delete(f"/api/v1/transactions/{tx_res.data['id']}/")
        self.assertEqual(del_tx.status_code, 204)
        sum_after_tx = s.summary(self.user, date(2026, 11, 1))
        self.assertEqual(sum_after_tx['expenses'], Decimal('0.00'))
        self.assertEqual(sum_after_tx['free'], Decimal('3000.00'))
        self.assertEqual(sum_after_tx['net_worth'], Decimal('5000.00'))

        # 2. Compra parcelada em 07/11 -> exclui -> restaura
        inst_res = self.client.post('/api/v1/installment-purchases/', {
            'description': 'Parcelada 07/11',
            'notes': '',
            'total_amount': '300.00',
            'installment_count': 3,
            'purchase_date': '2026-11-07',
            'category': self.category.id,
            'account': None,
            'card': self.card.id,
            'request_id': 'req-cenario-4-del',
        }, format='json')
        self.assertEqual(s.summary(self.user, date(2026, 11, 1))['expenses'], Decimal('100.00'))

        del_inst = self.client.delete(f"/api/v1/installment-purchases/{inst_res.data['id']}/")
        self.assertEqual(del_inst.status_code, 204)
        sum_after_inst = s.summary(self.user, date(2026, 11, 1))
        self.assertEqual(sum_after_inst['expenses'], Decimal('0.00'))
        self.assertEqual(sum_after_inst['free'], Decimal('3000.00'))
        self.assertEqual(sum_after_inst['net_worth'], Decimal('5000.00'))

    def test_a5_quando_filtra_por_conta_cartao_ou_categoria_e_consulta_planning_e_history_em_novembro_entao_mantem_compra_de_07_11_em_novembro(self):
        """it: quando filtra dashboard e transactions/monthly de novembro por account_id, card_id ou category_id
        ou consulta /api/v1/planning/2026/11/ e /api/v1/history/2026/11/, então reflete a compra de 07/11 em novembro.
        """
        other_account = m.Account.objects.create(user=self.user, name='Outra Conta')
        other_card = m.Card.objects.create(
            user=self.user, name='Outro Cartão', account=other_account, closing_day=4, due_day=11
        )
        other_category = m.Category.objects.create(user=self.user, name='Lazer')

        self.client.post('/api/v1/transactions/', {
            'description': 'Compra 07/11 Cartão Principal',
            'amount': '200.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')

        # Filtros que correspondem à compra de 07/11
        for query in [
            f'account_id={self.account.id}',
            f'card_id={self.card.id}',
            f'category_id={self.category.id}',
        ]:
            dash = self.client.get(f'/api/v1/dashboard/?year=2026&month=11&{query}')
            self.assertEqual(dash.status_code, 200)
            self.assertEqual(Decimal(dash.data['expenses']), Decimal('200.00'), query)

            monthly = self.client.get(f'/api/v1/transactions/monthly/?year=2026&month=11&{query}')
            self.assertEqual(monthly.status_code, 200)
            self.assertEqual(len(monthly.data), 1, query)

        # Filtros de outra conta/cartão/categoria retornam 0 em novembro
        for query in [
            f'account_id={other_account.id}',
            f'card_id={other_card.id}',
            f'category_id={other_category.id}',
        ]:
            dash = self.client.get(f'/api/v1/dashboard/?year=2026&month=11&{query}')
            self.assertEqual(Decimal(dash.data['expenses']), Decimal('0.00'), query)
            monthly = self.client.get(f'/api/v1/transactions/monthly/?year=2026&month=11&{query}')
            self.assertEqual(monthly.data, [], query)

        # Rotas de planejamento e histórico também refletem novembro = 200.00
        planning = self.client.get('/api/v1/planning/2026/11/')
        self.assertEqual(planning.status_code, 200)
        self.assertEqual(Decimal(planning.data['expenses']), Decimal('200.00'))
        self.assertEqual(Decimal(planning.data['forecast'][0]['expenses']), Decimal('200.00'))

        history = self.client.get('/api/v1/history/2026/11/')
        self.assertEqual(history.status_code, 200)
        nov_row = next(row for row in history.data['history'] if str(row['month']) == '2026-11-01')
        self.assertEqual(Decimal(nov_row['expenses']), Decimal('200.00'))

    def test_a6_quando_fatura_de_dezembro_tem_manual_amount_maior_que_compra_de_07_11_entao_novembro_conta_compra_e_dezembro_conta_apenas_excedente_sem_detalhamento(self):
        """it: quando registra compra de R$ 200,00 em 07/11 e define manual_amount=R$ 350,00 na fatura 12/2026,
        então novembro contabiliza R$ 200,00 e dezembro contabiliza apenas o excedente sem detalhamento de R$ 150,00,
        sem duplicar os R$ 200,00 entre os dois meses.
        """
        self.client.post('/api/v1/transactions/', {
            'description': 'Compra 07/11 detalhada',
            'amount': '200.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')

        inv_dec = m.Invoice.objects.get(card=self.card, month=date(2026, 12, 1))
        patch_inv = self.client.patch(f'/api/v1/invoices/{inv_dec.id}/', {
            'manual_amount': '350.00',
        }, format='json')
        self.assertEqual(patch_inv.status_code, 200, patch_inv.data)

        sum_nov = s.summary(self.user, date(2026, 11, 1))
        sum_dec = s.summary(self.user, date(2026, 12, 1))

        self.assertEqual(sum_nov['expenses'], Decimal('200.00'))
        self.assertEqual(sum_dec['invoice_total'], Decimal('350.00'))
        self.assertEqual(sum_dec['expenses'], Decimal('150.00'))
        cats_dec = {c['name']: Decimal(str(c['amount'])) for c in sum_dec['categories']}
        self.assertEqual(cats_dec.get('Faturas sem detalhamento'), Decimal('150.00'))

    # =========================================================================
    # b. Erros esperados
    # =========================================================================
    def test_b1_quando_compra_em_07_11_viola_regras_de_fatura_ou_competencia_entao_retorna_400_sem_alterar_resumo_de_novembro(self):
        """it: quando envia month divergente do fechamento em 07/11, ou estoura manual_amount da fatura 12/2026,
        ou tenta excluir compra de 07/11 cuja fatura 12/2026 está paga, então retorna 400.
        """
        # 1. Informar month=2026-11-01 manualmente para compra em 07/11 (fechamento dia 4 exige fatura 12/2026) -> 400
        bad_month = self.client.post('/api/v1/transactions/', {
            'description': 'Mês forçado errado',
            'amount': '100.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'month': '2026-11-01',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        self.assertEqual(bad_month.status_code, 400)
        self.assertEqual(s.summary(self.user, date(2026, 11, 1))['expenses'], Decimal('0.00'))

        # 2. Fatura de 12/2026 com manual_amount=50.00 bloqueia compra de R$ 80,00 feita em 07/11 -> 400
        inv_dec = s.ensure_invoice(self.user, self.card, date(2026, 12, 1))
        inv_dec.manual_amount = Decimal('50.00')
        inv_dec.save(update_fields=['manual_amount'])

        over_manual = self.client.post('/api/v1/transactions/', {
            'description': 'Acima do manual de dezembro',
            'amount': '80.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        self.assertEqual(over_manual.status_code, 400)
        self.assertEqual(s.summary(self.user, date(2026, 11, 1))['expenses'], Decimal('0.00'))

        # 3. Compra válida dentro do manual_amount, mas se a fatura for marcada como paga, bloqueia exclusão -> 400
        ok_buy = self.client.post('/api/v1/transactions/', {
            'description': 'Dentro do manual',
            'amount': '40.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        self.assertEqual(ok_buy.status_code, 201)
        inv_dec.paid_on = date(2026, 11, 9)
        inv_dec.save(update_fields=['paid_on'])

        self.assertEqual(self.client.delete(f"/api/v1/transactions/{ok_buy.data['id']}/").status_code, 400)

    # =========================================================================
    # d. Limites
    # =========================================================================
    def test_d1_quando_compra_ocorrer_no_limite_exato_do_fechamento_04_11_ou_ultimo_dia_30_11_e_gerar_deficit_entao_calcula_corretamente(self):
        """it: quando compra ocorre exatamente no dia do fechamento (04/11) e no último dia do mês (30/11)
        ultrapassando a renda de novembro, então ambas entram no resumo de novembro gerando deficit e feasible=False.
        """
        self.client.post('/api/v1/transactions/', {
            'description': 'Renda Curta',
            'amount': '100.00',
            'kind': 'income',
            'date': '2026-11-01',
            'month': '2026-11-01',
            'category': self.category.id,
            'account': self.account.id,
        }, format='json')

        # Dia exato do fechamento (04/11) -> vai para fatura 12/2026, mas gasto é de novembro
        r_closing = self.client.post('/api/v1/transactions/', {
            'description': 'No dia do fechamento 04/11',
            'amount': '60.00',
            'kind': 'expense',
            'date': '2026-11-04',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        # Último dia de novembro (30/11) -> vai para fatura 12/2026, mas gasto é de novembro
        r_end = self.client.post('/api/v1/transactions/', {
            'description': 'Último dia 30/11',
            'amount': '90.00',
            'kind': 'expense',
            'date': '2026-11-30',
            'category': self.category.id,
            'card': self.card.id,
        }, format='json')
        self.assertEqual(r_closing.status_code, 201)
        self.assertEqual(r_end.status_code, 201)
        self.assertEqual(r_closing.data['month'], '2026-12-01')
        self.assertEqual(r_end.data['month'], '2026-12-01')

        sum_nov = s.summary(self.user, date(2026, 11, 1))
        self.assertEqual(sum_nov['expenses'], Decimal('150.00'))
        self.assertEqual(sum_nov['free'], Decimal('-50.00'))
        self.assertEqual(sum_nov['deficit'], Decimal('50.00'))
        self.assertFalse(sum_nov['feasible'])

    # =========================================================================
    # e. Acesso indevido (Isolamento entre Usuário A e Usuário B)
    # =========================================================================
    def test_e1_quando_usuario_b_registra_compra_pos_fechamento_em_07_11_entao_nao_afeta_resumo_nem_movimentacoes_do_usuario_a(self):
        """it: quando o usuário B registra compra em 07/11, então o resumo de novembro e a listagem mensal
        do usuário A não incluem os gastos de B, e o usuário A recebe 404 ao tentar excluir a compra de B.
        """
        client_b = APIClient()
        client_b.force_authenticate(self.other)
        acc_b = m.Account.objects.create(user=self.other, name='Conta B')
        cat_b = m.Category.objects.create(user=self.other, name='Cat B')
        card_b = m.Card.objects.create(user=self.other, name='Cartão B', account=acc_b, closing_day=4, due_day=11)

        tx_b = client_b.post('/api/v1/transactions/', {
            'description': 'Gasto Secreto B 07/11',
            'amount': '999.00',
            'kind': 'expense',
            'date': '2026-11-07',
            'category': cat_b.id,
            'card': card_b.id,
        }, format='json').data

        sum_a = s.summary(self.user, date(2026, 11, 1))
        self.assertEqual(sum_a['expenses'], Decimal('0.00'))
        self.assertEqual(self.client.get('/api/v1/transactions/monthly/?year=2026&month=11').data, [])
        self.assertEqual(self.client.delete(f"/api/v1/transactions/{tx_b['id']}/").status_code, 404)


class DescribeGastosCartaoResumoConcorrencia(TransactionTestCase):
    """describe: Repetição e Concorrência simultânea em compras pós-fechamento (07/11)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_resumo_conc')
        self.account = m.Account.objects.create(user=self.user, name='Conta')
        self.category = m.Category.objects.create(user=self.user, name='Compras')
        self.card = m.Card.objects.create(
            user=self.user, name='Cartão Fecha 4', account=self.account, closing_day=4, due_day=11
        )

    def test_c1_quando_duas_compras_simultaneas_ocorrem_em_07_11_apos_fechamento_entao_cria_unica_fatura_dezembro_e_soma_ambas_em_novembro(self):
        """it: quando duas requisições simultâneas registram compras em 07/11/2026 no cartão que fecha dia 4,
        então cria uma única fatura em 12/2026 e contabiliza a soma exata das duas compras no resumo de 11/2026.
        """
        def buy(desc, amount):
            def _call():
                c = APIClient()
                c.force_authenticate(self.user)
                return c.post('/api/v1/transactions/', {
                    'description': desc,
                    'amount': amount,
                    'kind': 'expense',
                    'date': '2026-11-07',
                    'category': self.category.id,
                    'card': self.card.id,
                }, format='json')
            return _call

        with patch('django.utils.timezone.localdate', return_value=date(2026, 11, 9)):
            r1, r2 = run_simultaneously(buy('Simultânea 1', '120.00'), buy('Simultânea 2', '80.00'))
            self.assertEqual([r1.status_code, r2.status_code], [201, 201])
            self.assertEqual(m.Invoice.objects.filter(card=self.card, month=date(2026, 12, 1)).count(), 1)

            sum_nov = s.summary(self.user, date(2026, 11, 1))
            self.assertEqual(sum_nov['expenses'], Decimal('200.00'))
            self.assertEqual(s.summary(self.user, date(2026, 12, 1))['expenses'], Decimal('0.00'))
            self.assertEqual(s.summary(self.user, date(2026, 12, 1))['invoice_total'], Decimal('200.00'))
