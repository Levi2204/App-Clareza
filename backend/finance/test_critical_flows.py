"""Testes de integração estilo request spec (RSpec describe/it) para os 8 fluxos críticos do Clareza.

Cada teste bate nas rotas reais da API (/api/v1/...) com banco de teste SQLite real,
sem mockar banco de dados nem regras de negócio.
"""
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import struct
import threading
from unittest.mock import patch
import zlib

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from . import models as m, services as s


def build_valid_png(width=64, height=64, color=6, extra_chunks=None):
    """Gera um PNG válido em memória para testar upload de foto de perfil."""
    def chunk(kind, content):
        return (
            struct.pack('>I', len(content))
            + kind
            + content
            + struct.pack('>I', binascii.crc32(kind + content) & 0xffffffff)
        )

    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, color, 0, 0, 0))
    pixel = b'\x10\x20\x30\xff' if color == 6 else b'\x10\x20\x30'
    raw_scanlines = (b'\x00' + pixel * width) * height
    idat = chunk(b'IDAT', zlib.compress(raw_scanlines))
    parts = [ihdr]
    for kind, body in (extra_chunks or []):
        parts.append(chunk(kind, body))
    parts.extend([idat, chunk(b'IEND', b'')])
    return 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b''.join(parts)).decode()


def run_simultaneously(fn1, fn2):
    """Dispara duas funções exatamente ao mesmo tempo (equivalente a Promise.all em threads)."""
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


# =============================================================================
# FLUXO 1: Autenticação, Perfil e Exclusão/Recriação do Espaço (/api/v1/profile/)
# =============================================================================
class DescribeFluxo1PerfilEAutenticacao(TestCase):
    """describe: POST / GET / PATCH / DELETE /api/v1/profile/ e Autenticação."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a', email='a@example.com')
        self.user_b = get_user_model().objects.create_user('user_b', email='b@example.com')

    # a. Caminho feliz
    def test_a1_quando_acessa_em_modo_local_via_loopback_entao_autentica_automaticamente(self):
        client = APIClient()
        res = client.get('/api/v1/profile/', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['display_name'], 'Meu espaço')
        self.assertEqual(res.data['theme'], 'light')
        self.assertTrue(get_user_model().objects.filter(username='local').exists())

    def test_a2_quando_envia_patch_com_dados_validos_e_foto_png_entao_persiste_e_limpa_metadados(self):
        client = APIClient()
        client.force_authenticate(self.user_a)
        photo_with_text = build_valid_png(32, 32, extra_chunks=[(b'tEXt', b'Comment\x00segredo-exif')])
        res = client.patch('/api/v1/profile/', {
            'display_name': 'Levi Finanças',
            'email': 'levi@clareza.local',
            'phone': '(85) 98888-7777',
            'bio': 'Planejamento financeiro pessoal',
            'theme': 'dark',
            'photo': photo_with_text,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['display_name'], 'Levi Finanças')
        self.assertEqual(res.data['email'], 'levi@clareza.local')
        self.assertEqual(res.data['theme'], 'dark')
        raw_saved = base64.b64decode(res.data['photo'].split(',', 1)[1])
        self.assertNotIn(b'segredo-exif', raw_saved)

    def test_a3_quando_envia_delete_com_excluir_entao_apaga_tudo_em_cascata_e_marca_excluido(self):
        client = APIClient()
        client.get('/api/v1/profile/')
        local_user = get_user_model().objects.get(username='local')
        acc = m.Account.objects.create(user=local_user, name='Conta Local')
        m.Balance.objects.create(account=acc, month=date(2026, 9, 1), amount=Decimal('500.00'))
        cat = m.Category.objects.create(user=local_user, name='Geral')
        card = m.Card.objects.create(user=local_user, name='Cartão Local', account=acc)
        client.post('/api/v1/transactions/', {
            'description': 'Compra', 'amount': '50.00', 'kind': 'expense',
            'date': '2026-09-10', 'category': cat.id, 'card': card.id,
        }, format='json')

        res = client.delete('/api/v1/profile/', {'confirmation': 'EXCLUIR'}, format='json')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(get_user_model().objects.filter(username='local').exists())
        self.assertFalse(m.Account.objects.filter(user=local_user).exists())
        self.assertTrue(m.LocalAccountState.objects.filter(pk=1, deleted=True).exists())

    def test_a4_quando_conta_local_excluida_e_envia_post_criar_entao_recria_espaco_limpo(self):
        client = APIClient()
        client.get('/api/v1/profile/')
        client.delete('/api/v1/profile/', {'confirmation': 'EXCLUIR'}, format='json')
        self.assertEqual(client.get('/api/v1/profile/').data, {'deleted': True})

        recreated = client.post('/api/v1/profile/', {'confirmation': 'CRIAR'}, format='json')
        self.assertEqual(recreated.status_code, 201)
        self.assertEqual(recreated.data['display_name'], 'Meu espaço')
        self.assertEqual(client.get('/api/v1/accounts/').status_code, 200)

    # b. Erros esperados
    def test_b1_quando_envia_patch_com_campos_invalidos_ou_foto_invalida_entao_retorna_400(self):
        client = APIClient()
        client.force_authenticate(self.user_a)
        client.patch('/api/v1/profile/', {'display_name': 'Nome Firme'}, format='json')

        invalid_payloads = [
            {'email': 'email-invalido'},
            {'display_name': ''},
            {'theme': 'neon'},
            {'photo': 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4='},
            {'photo': 'data:image/png;base64,aGVsbG8='},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                res = client.patch('/api/v1/profile/', payload, format='json')
                self.assertEqual(res.status_code, 400)

        self.assertEqual(client.get('/api/v1/profile/').data['display_name'], 'Nome Firme')

    def test_b2_quando_envia_delete_sem_confirmation_excluir_entao_retorna_400_e_preserva_dados(self):
        client = APIClient()
        client.force_authenticate(self.user_a)
        m.Account.objects.create(user=self.user_a, name='Preservada')

        for payload in [{}, {'confirmation': 'excluir'}, {'confirmation': 'CANCELAR'}]:
            res = client.delete('/api/v1/profile/', payload, format='json')
            self.assertEqual(res.status_code, 400)

        self.assertTrue(m.Account.objects.filter(user=self.user_a, name='Preservada').exists())

    def test_b3_quando_acessa_rotas_financeiras_apos_exclusao_local_entao_retorna_403(self):
        client = APIClient()
        client.get('/api/v1/profile/')
        client.delete('/api/v1/profile/', {'confirmation': 'EXCLUIR'}, format='json')

        for path in ['/api/v1/accounts/', '/api/v1/transactions/', '/api/v1/dashboard/']:
            self.assertEqual(client.get(path).status_code, 403)

    def test_b4_quando_envia_post_profile_com_conta_ativa_entao_retorna_400(self):
        client = APIClient()
        client.get('/api/v1/profile/')
        res = client.post('/api/v1/profile/', {'confirmation': 'CRIAR'}, format='json')
        self.assertEqual(res.status_code, 400)

    # d. Limites
    def test_d1_quando_envia_foto_acima_de_512x512_ou_maior_que_400000_chars_entao_retorna_400(self):
        client = APIClient()
        client.force_authenticate(self.user_a)
        oversized_dim = build_valid_png(513, 1)
        self.assertEqual(client.patch('/api/v1/profile/', {'photo': oversized_dim}, format='json').status_code, 400)

        oversized_str = 'data:image/png;base64,' + ('A' * 400000)
        self.assertEqual(client.patch('/api/v1/profile/', {'photo': oversized_str}, format='json').status_code, 400)

    def test_d2_quando_envia_display_name_e_bio_no_limite_exato_aceita_e_acima_rejeita(self):
        client = APIClient()
        client.force_authenticate(self.user_a)
        ok_res = client.patch('/api/v1/profile/', {
            'display_name': 'A' * 100,
            'bio': 'B' * 300,
        }, format='json')
        self.assertEqual(ok_res.status_code, 200)

        self.assertEqual(client.patch('/api/v1/profile/', {'display_name': 'A' * 101}, format='json').status_code, 400)
        self.assertEqual(client.patch('/api/v1/profile/', {'bio': 'B' * 301}, format='json').status_code, 400)

    # e. Acesso indevido
    def test_e1_quando_requisicao_vem_de_origin_externa_ou_ip_externo_entao_rejeita_com_403(self):
        client = APIClient()
        self.assertEqual(client.get('/api/v1/profile/', HTTP_ORIGIN='https://atacante.com').status_code, 403)
        self.assertEqual(client.get('/api/v1/accounts/', HTTP_ORIGIN='https://atacante.com').status_code, 403)
        self.assertEqual(client.get('/api/v1/profile/', REMOTE_ADDR='192.168.1.50').status_code, 403)
        self.assertEqual(client.get('/api/v1/accounts/', REMOTE_ADDR='10.0.0.2').status_code, 403)

    @override_settings(DESKTOP_TOKEN='segredo-desktop-123')
    def test_e2_quando_desktop_token_configurado_e_header_ausente_ou_incorreto_entao_rejeita_com_403(self):
        client = APIClient()
        self.assertEqual(client.get('/api/v1/profile/').status_code, 403)
        self.assertEqual(client.get('/api/v1/profile/', HTTP_X_CLAREZA_TOKEN='errado').status_code, 403)
        self.assertEqual(client.get('/api/v1/profile/', HTTP_X_CLAREZA_TOKEN='segredo-desktop-123').status_code, 200)

    @override_settings(LOCAL_MODE=False)
    def test_e3_quando_local_mode_false_e_sem_sessao_entao_retorna_403(self):
        client = APIClient()
        for path in ['/api/v1/profile/', '/api/v1/accounts/', '/api/v1/transactions/', '/api/v1/dashboard/']:
            self.assertEqual(client.get(path).status_code, 403)

    def test_e4_quando_usuario_a_exclui_seu_perfil_entao_dados_do_usuario_b_permanecem_intactos(self):
        acc_a = m.Account.objects.create(user=self.user_a, name='Conta A')
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        cat_b = m.Category.objects.create(user=self.user_b, name='Cat B')
        tx_b = m.Transaction.objects.create(
            user=self.user_b, description='Receita B', amount=Decimal('1000.00'),
            kind='income', date=date(2026, 9, 10), month=date(2026, 9, 1),
            category=cat_b, account=acc_b,
        )

        client_a = APIClient()
        client_a.force_authenticate(self.user_a)
        res = client_a.delete('/api/v1/profile/', {'confirmation': 'EXCLUIR'}, format='json')
        self.assertEqual(res.status_code, 204)

        self.assertFalse(m.Account.objects.filter(pk=acc_a.pk).exists())
        self.assertTrue(m.Account.objects.filter(pk=acc_b.pk).exists())
        self.assertTrue(m.Transaction.objects.filter(pk=tx_b.pk).exists())


class DescribeFluxo1PerfilConcorrencia(TransactionTestCase):
    """describe: Concorrência em /api/v1/profile/."""

    def test_c1_quando_duas_requisicoes_simultaneas_recriam_perfil_local_entao_cria_apenas_um_usuario_sem_500(self):
        m.LocalAccountState.objects.update_or_create(pk=1, defaults={'deleted': True})

        def call_create():
            c = APIClient()
            return c.post('/api/v1/profile/', {'confirmation': 'CRIAR'}, format='json')

        r1, r2 = run_simultaneously(call_create, call_create)
        self.assertNotIn(500, [r1.status_code, r2.status_code])
        self.assertIn(201, [r1.status_code, r2.status_code])
        self.assertEqual(get_user_model().objects.filter(username='local').count(), 1)
        self.assertEqual(m.Profile.objects.filter(user__username='local').count(), 1)

    def test_c2_quando_duas_requisicoes_simultaneas_excluem_perfil_entao_exclusao_atomica_sem_orfaos_nem_500(self):
        user = get_user_model().objects.create_user('concurrent_del')
        acc = m.Account.objects.create(user=user, name='Conta')
        cat = m.Category.objects.create(user=user, name='Cat')
        m.Transaction.objects.create(
            user=user, description='Gasto', amount=Decimal('10.00'),
            kind='expense', date=date(2026, 9, 10), month=date(2026, 9, 1),
            category=cat, account=acc,
        )

        def call_delete():
            c = APIClient()
            c.force_authenticate(user)
            return c.delete('/api/v1/profile/', {'confirmation': 'EXCLUIR'}, format='json')

        r1, r2 = run_simultaneously(call_delete, call_delete)
        self.assertNotIn(500, [r1.status_code, r2.status_code])
        self.assertIn(204, [r1.status_code, r2.status_code])
        self.assertFalse(m.Account.objects.filter(user_id=user.id).exists())
        self.assertFalse(m.Transaction.objects.filter(user_id=user.id).exists())


# =============================================================================
# FLUXO 2: Contas, Saldos Mensais, Cartões e Categorias
# =============================================================================
class DescribeFluxo2ContasCartoesCategorias(TestCase):
    """describe: CRUD de Contas, Saldos, Cartões e Categorias."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a_f2')
        self.user_b = get_user_model().objects.create_user('user_b_f2')
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    # a. Caminho feliz
    def test_a1_quando_cria_conta_com_balance_e_balance_month_entao_normaliza_para_dia_1(self):
        res = self.client.post('/api/v1/accounts/', {
            'name': 'Conta Principal',
            'institution': 'Banco X',
            'account_type': 'checking',
            'balance': '1500.75',
            'balance_month': '2026-09-18',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        bal = m.Balance.objects.get(account_id=res.data['id'])
        self.assertEqual(bal.month, date(2026, 9, 1))
        self.assertEqual(bal.amount, Decimal('1500.75'))

    def test_a2_quando_atualiza_saldo_em_novo_mes_e_desativa_conta_entao_preserva_historico_anterior(self):
        acc = self.client.post('/api/v1/accounts/', {
            'name': 'Poupança',
            'account_type': 'savings',
            'balance': '1000.00',
            'balance_month': '2026-08-10',
        }, format='json').data

        patch_res = self.client.patch(f"/api/v1/accounts/{acc['id']}/", {
            'balance': '2500.00',
            'balance_month': '2026-09-20',
            'is_active': False,
        }, format='json')
        self.assertEqual(patch_res.status_code, 200)

        sum_aug = self.client.get(f"/api/v1/accounts/{acc['id']}/summary/?year=2026&month=8").data
        sum_sep = self.client.get(f"/api/v1/accounts/{acc['id']}/summary/?year=2026&month=9").data
        self.assertEqual(Decimal(sum_aug['assets']), Decimal('1000.00'))
        self.assertEqual(Decimal(sum_sep['assets']), Decimal('2500.00'))

    def test_a3_quando_cria_cartao_e_categoria_validos_entao_retorna_201(self):
        acc = m.Account.objects.create(user=self.user_a, name='Conta')
        card_res = self.client.post('/api/v1/cards/', {
            'name': 'Visa Infinite', 'account': acc.id, 'closing_day': 10, 'due_day': 20,
        }, format='json')
        self.assertEqual(card_res.status_code, 201)

        cat_res = self.client.post('/api/v1/categories/', {'name': 'Educação'}, format='json')
        self.assertEqual(cat_res.status_code, 201)

    # b. Erros esperados
    def test_b1_quando_tenta_excluir_conta_cartao_ou_categoria_entao_retorna_400_exigindo_desativacao(self):
        acc = m.Account.objects.create(user=self.user_a, name='Conta')
        card = m.Card.objects.create(user=self.user_a, name='Cartão', account=acc)
        cat = m.Category.objects.create(user=self.user_a, name='Categoria')

        self.assertEqual(self.client.delete(f'/api/v1/accounts/{acc.id}/').status_code, 400)
        self.assertEqual(self.client.delete(f'/api/v1/cards/{card.id}/').status_code, 400)
        self.assertEqual(self.client.delete(f'/api/v1/categories/{cat.id}/').status_code, 400)

    def test_b2_quando_tenta_criar_cartao_em_conta_inativa_entao_retorna_400(self):
        inactive_acc = m.Account.objects.create(user=self.user_a, name='Inativa', is_active=False)
        res = self.client.post('/api/v1/cards/', {
            'name': 'Cartão Bloqueado', 'account': inactive_acc.id, 'closing_day': 5, 'due_day': 12,
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_b3_quando_passa_filtros_nao_numericos_na_listagem_entao_retorna_400(self):
        for param in ['account_id=abc', 'card_id=xyz', 'category_id=12a']:
            with self.subTest(param=param):
                self.assertEqual(self.client.get(f'/api/v1/transactions/?{param}').status_code, 400)

    # d. Limites
    def test_d1_quando_informa_saldo_zero_aceita_e_saldo_negativo_retorna_400(self):
        res_zero = self.client.post('/api/v1/accounts/', {'name': 'Zero', 'balance': '0.00'}, format='json')
        self.assertEqual(res_zero.status_code, 201)

        res_neg = self.client.post('/api/v1/accounts/', {'name': 'Negativa', 'balance': '-0.01'}, format='json')
        self.assertEqual(res_neg.status_code, 400)

    def test_d2_quando_informa_closing_day_e_due_day_nos_limites_1_e_31_aceita_e_fora_retorna_400(self):
        acc = m.Account.objects.create(user=self.user_a, name='Conta')
        self.assertEqual(self.client.post('/api/v1/cards/', {
            'name': 'Limites 1-31', 'account': acc.id, 'closing_day': 1, 'due_day': 31,
        }, format='json').status_code, 201)

        for invalid in [{'closing_day': 0}, {'closing_day': 32}, {'due_day': 0}, {'due_day': 32}]:
            payload = {'name': 'Inválido', 'account': acc.id, 'closing_day': 5, 'due_day': 12, **invalid}
            self.assertEqual(self.client.post('/api/v1/cards/', payload, format='json').status_code, 400)

    # e. Acesso indevido
    def test_e1_quando_usuario_a_acessa_recursos_do_usuario_b_entao_nao_lista_e_recebe_404(self):
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        card_b = m.Card.objects.create(user=self.user_b, name='Cartão B', account=acc_b)
        cat_b = m.Category.objects.create(user=self.user_b, name='Cat B')

        self.assertEqual(self.client.get('/api/v1/accounts/').data, [])
        self.assertEqual(self.client.get('/api/v1/cards/').data, [])
        self.assertEqual(self.client.get('/api/v1/categories/').data, [])

        for url in [
            f'/api/v1/accounts/{acc_b.id}/',
            f'/api/v1/accounts/{acc_b.id}/summary/',
            f'/api/v1/accounts/{acc_b.id}/transactions/',
            f'/api/v1/cards/{card_b.id}/',
            f'/api/v1/categories/{cat_b.id}/',
        ]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_e2_quando_usuario_a_cria_cartao_na_conta_do_usuario_b_entao_retorna_400(self):
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        res = self.client.post('/api/v1/cards/', {
            'name': 'Cartão Invasor', 'account': acc_b.id, 'closing_day': 5, 'due_day': 12,
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_e3_quando_usuario_a_cria_categoria_com_mesmo_nome_do_usuario_b_entao_permite(self):
        m.Category.objects.create(user=self.user_b, name='Alimentação')
        res = self.client.post('/api/v1/categories/', {'name': 'Alimentação'}, format='json')
        self.assertEqual(res.status_code, 201)


class DescribeFluxo2ContasCategoriasConcorrencia(TransactionTestCase):
    """describe: Repetição e Concorrência em Contas e Categorias."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_f2_conc')
        self.account = m.Account.objects.create(user=self.user, name='Conta')

    def test_c1_quando_envia_multiplos_patch_de_saldo_simultaneos_para_mesmo_mes_entao_mantem_unico_balance(self):
        def update_balance(val):
            def _call():
                c = APIClient()
                c.force_authenticate(self.user)
                return c.patch(f'/api/v1/accounts/{self.account.id}/', {
                    'balance': val, 'balance_month': '2026-09-15',
                }, format='json')
            return _call

        r1, r2 = run_simultaneously(update_balance('1000.00'), update_balance('2000.00'))
        self.assertNotIn(500, [r1.status_code, r2.status_code])
        self.assertEqual(m.Balance.objects.filter(account=self.account, month=date(2026, 9, 1)).count(), 1)

    def test_c2_quando_cria_duas_categorias_com_mesmo_nome_sequencial_ou_simultaneamente_entao_bloqueia_duplicata(self):
        def create_cat():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.post('/api/v1/categories/', {'name': 'Moradia'}, format='json')

        r1, r2 = run_simultaneously(create_cat, create_cat)
        self.assertEqual(sorted([r1.status_code, r2.status_code]), [201, 400])
        self.assertEqual(m.Category.objects.filter(user=self.user, name='Moradia').count(), 1)


# =============================================================================
# FLUXO 3: Movimentações Simples e Competência de Cartão
# =============================================================================
class DescribeFluxo3MovimentacoesECompetenciaCartao(TestCase):
    """describe: Movimentações em Conta e Compras no Cartão."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a_f3')
        self.user_b = get_user_model().objects.create_user('user_b_f3')
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)
        self.account = m.Account.objects.create(user=self.user_a, name='Conta A')
        self.category = m.Category.objects.create(user=self.user_a, name='Alimentação')
        self.card = m.Card.objects.create(
            user=self.user_a, name='Cartão A', account=self.account, closing_day=25, due_day=12
        )
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    # a. Caminho feliz
    def test_a1_quando_cria_receita_e_despesa_em_conta_entao_registra_sem_fatura_e_atualiza_resumo(self):
        r_inc = self.client.post('/api/v1/transactions/', {
            'description': 'Salário', 'amount': '5000.00', 'kind': 'income',
            'date': '2026-09-05', 'month': '2026-09-01',
            'category': self.category.id, 'account': self.account.id,
        }, format='json')
        r_exp = self.client.post('/api/v1/transactions/', {
            'description': 'Mercado', 'amount': '400.00', 'kind': 'expense',
            'date': '2026-09-10', 'month': '2026-09-01',
            'category': self.category.id, 'account': self.account.id,
        }, format='json')
        self.assertEqual(r_inc.status_code, 201)
        self.assertEqual(r_exp.status_code, 201)
        self.assertIsNone(r_exp.data['invoice'])

        dash = self.client.get('/api/v1/dashboard/?year=2026&month=9').data
        self.assertEqual(Decimal(dash['income']), Decimal('5000.00'))
        self.assertEqual(Decimal(dash['expenses']), Decimal('400.00'))

    def test_a2_quando_compra_no_cartao_antes_do_fechamento_entao_classifica_no_proprio_mes(self):
        res = self.client.post('/api/v1/transactions/', {
            'description': 'Jantar', 'amount': '120.00', 'kind': 'expense',
            'date': '2026-09-24', 'category': self.category.id, 'card': self.card.id,
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['month'], '2026-09-01')
        inv = m.Invoice.objects.get(pk=res.data['invoice'])
        self.assertEqual(inv.month, date(2026, 9, 1))

    def test_a3_quando_compra_no_cartao_no_dia_do_fechamento_ou_apos_entao_classifica_no_mes_seguinte(self):
        res = self.client.post('/api/v1/transactions/', {
            'description': 'Eletrônico', 'amount': '250.00', 'kind': 'expense',
            'date': '2026-09-25', 'category': self.category.id, 'card': self.card.id,
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['month'], '2026-10-01')
        inv = m.Invoice.objects.get(pk=res.data['invoice'])
        self.assertEqual(inv.month, date(2026, 10, 1))

    def test_a4_quando_adiciona_compra_em_fatura_paga_com_manual_amount_entao_mantem_paga_e_incrementa_total(self):
        inv = s.ensure_invoice(self.user_a, self.card, date(2026, 9, 1))
        inv.manual_amount = Decimal('200.00')
        inv.paid_on = date(2026, 9, 15)
        inv.save(update_fields=['manual_amount', 'paid_on'])

        res = self.client.post('/api/v1/transactions/', {
            'description': 'Extra', 'amount': '35.00', 'kind': 'expense',
            'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
        }, format='json')
        self.assertEqual(res.status_code, 201)
        inv.refresh_from_db()
        self.assertEqual(inv.paid_on, date(2026, 9, 15))
        self.assertEqual(inv.manual_amount, Decimal('235.00'))

    def test_a5_quando_exclui_movimentacao_avulsa_em_fatura_aberta_ou_conta_entao_remove_204(self):
        tx = self.client.post('/api/v1/transactions/', {
            'description': 'Lanche', 'amount': '25.00', 'kind': 'expense',
            'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
        }, format='json').data
        res = self.client.delete(f"/api/v1/transactions/{tx['id']}/")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(m.Transaction.objects.filter(pk=tx['id']).exists())

    # b. Erros esperados
    def test_b1_quando_cria_movimentacao_sem_origem_ou_com_ambas_ou_receita_no_cartao_ou_sem_month_em_conta_entao_400(self):
        base = {'description': 'Teste', 'amount': '50.00', 'kind': 'expense', 'date': '2026-09-10', 'category': self.category.id}
        cases = [
            {**base, 'month': '2026-09-01'},  # sem conta nem cartão
            {**base, 'month': '2026-09-01', 'account': self.account.id, 'card': self.card.id},  # ambos
            {**base, 'kind': 'income', 'card': self.card.id},  # receita em cartão
            {**base, 'account': self.account.id},  # conta sem month
            {**base, 'card': self.card.id, 'month': '2026-10-01'},  # month divergente do fechamento
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post('/api/v1/transactions/', payload, format='json').status_code, 400)

    def test_b2_quando_compra_ultrapassa_manual_amount_de_fatura_aberta_entao_retorna_400(self):
        inv = s.ensure_invoice(self.user_a, self.card, date(2026, 9, 1))
        inv.manual_amount = Decimal('100.00')
        inv.save(update_fields=['manual_amount'])

        res = self.client.post('/api/v1/transactions/', {
            'description': 'Compra Grande', 'amount': '100.01', 'kind': 'expense',
            'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
        }, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(m.Transaction.objects.count(), 0)

    def test_b3_quando_tenta_editar_ou_excluir_gasto_em_fatura_paga_ou_parcela_ou_assinatura_entao_retorna_400(self):
        # 1. Gasto em fatura paga
        tx_card = self.client.post('/api/v1/transactions/', {
            'description': 'No Cartão', 'amount': '50.00', 'kind': 'expense',
            'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
        }, format='json').data
        m.Invoice.objects.filter(pk=tx_card['invoice']).update(paid_on=date(2026, 9, 15))
        self.assertEqual(self.client.patch(f"/api/v1/transactions/{tx_card['id']}/", {'amount': '60.00'}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(f"/api/v1/transactions/{tx_card['id']}/").status_code, 400)

        # 2. Cobrança de assinatura
        sub = self.client.post('/api/v1/subscriptions/', {
            'name': 'Netflix', 'amount': '40.00', 'category': self.category.id,
            'account': self.account.id, 'billing_day': 10, 'start_date': '2026-09-01',
        }, format='json').data
        tx_sub = m.Transaction.objects.get(subscription_id=sub['id'])
        self.assertEqual(self.client.patch(f'/api/v1/transactions/{tx_sub.id}/', {'amount': '45.00'}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(f'/api/v1/transactions/{tx_sub.id}/').status_code, 400)

    # d. Limites
    def test_d1_quando_valor_zero_negativo_ou_mais_de_duas_casas_decimais_entao_retorna_400(self):
        for amt in ['0', '0.00', '-1.00', '10.001']:
            res = self.client.post('/api/v1/transactions/', {
                'description': 'Inválido', 'amount': amt, 'kind': 'expense',
                'date': '2026-09-10', 'month': '2026-09-01',
                'category': self.category.id, 'account': self.account.id,
            }, format='json')
            self.assertEqual(res.status_code, 400)

    def test_d2_quando_cartao_fecha_dia_31_em_fevereiro_entao_ajusta_fechamento_para_28_ou_29(self):
        card31 = m.Card.objects.create(user=self.user_a, name='Cartão 31', account=self.account, closing_day=31, due_day=10)
        # 2026 (não bissexto): 27/02 -> fev; 28/02 -> mar
        r1 = self.client.post('/api/v1/transactions/', {
            'description': 'Fev 27', 'amount': '10.00', 'kind': 'expense',
            'date': '2026-02-27', 'category': self.category.id, 'card': card31.id,
        }, format='json')
        r2 = self.client.post('/api/v1/transactions/', {
            'description': 'Fev 28', 'amount': '10.00', 'kind': 'expense',
            'date': '2026-02-28', 'category': self.category.id, 'card': card31.id,
        }, format='json')
        self.assertEqual(r1.data['month'], '2026-02-01')
        self.assertEqual(r2.data['month'], '2026-03-01')

    def test_d3_quando_compra_em_fatura_paga_excede_max_money_entao_retorna_400(self):
        inv = s.ensure_invoice(self.user_a, self.card, date(2026, 9, 1))
        inv.manual_amount = s.MAX_MONEY
        inv.paid_on = date(2026, 9, 15)
        inv.save(update_fields=['manual_amount', 'paid_on'])

        res = self.client.post('/api/v1/transactions/', {
            'description': 'Estouro', 'amount': '0.01', 'kind': 'expense',
            'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
        }, format='json')
        self.assertEqual(res.status_code, 400)

    # e. Acesso indevido
    def test_e1_quando_usuario_a_usa_origem_do_usuario_b_ou_acessa_transacao_de_b_entao_400_e_404(self):
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        cat_b = m.Category.objects.create(user=self.user_b, name='Cat B')
        tx_b = m.Transaction.objects.create(
            user=self.user_b, description='Secreto', amount=Decimal('99.00'),
            kind='expense', date=date(2026, 9, 10), month=date(2026, 9, 1),
            category=cat_b, account=acc_b,
        )

        self.assertEqual(self.client.post('/api/v1/transactions/', {
            'description': 'Invasão', 'amount': '10.00', 'kind': 'expense',
            'date': '2026-09-10', 'month': '2026-09-01',
            'category': self.category.id, 'account': acc_b.id,
        }, format='json').status_code, 400)

        self.assertEqual(self.client.get(f'/api/v1/transactions/{tx_b.id}/').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/v1/transactions/{tx_b.id}/', {'amount': '1.00'}, format='json').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/v1/transactions/{tx_b.id}/').status_code, 404)


class DescribeFluxo3MovimentacoesConcorrencia(TransactionTestCase):
    """describe: Concorrência em Movimentações de Cartão."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_f3_conc')
        self.account = m.Account.objects.create(user=self.user, name='Conta')
        self.category = m.Category.objects.create(user=self.user, name='Cat')
        self.card = m.Card.objects.create(
            user=self.user, name='Cartão', account=self.account, closing_day=25, due_day=12
        )

    def test_c1_quando_duas_compras_simultaneas_no_mesmo_cartao_sem_fatura_entao_cria_unica_fatura_e_vincula_ambas(self):
        def buy(desc):
            def _call():
                c = APIClient()
                c.force_authenticate(self.user)
                return c.post('/api/v1/transactions/', {
                    'description': desc, 'amount': '40.00', 'kind': 'expense',
                    'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
                }, format='json')
            return _call

        r1, r2 = run_simultaneously(buy('Compra 1'), buy('Compra 2'))
        self.assertEqual([r1.status_code, r2.status_code], [201, 201])
        self.assertEqual(m.Invoice.objects.filter(card=self.card, month=date(2026, 9, 1)).count(), 1)
        self.assertEqual(m.Transaction.objects.filter(card=self.card, month=date(2026, 9, 1)).count(), 2)

    def test_c2_quando_duas_compras_simultaneas_disputam_manual_amount_restante_entao_apenas_uma_passa(self):
        inv = s.ensure_invoice(self.user, self.card, date(2026, 9, 1))
        inv.manual_amount = Decimal('100.00')
        inv.save(update_fields=['manual_amount'])

        def buy_60(desc):
            def _call():
                c = APIClient()
                c.force_authenticate(self.user)
                return c.post('/api/v1/transactions/', {
                    'description': desc, 'amount': '60.00', 'kind': 'expense',
                    'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
                }, format='json')
            return _call

        r1, r2 = run_simultaneously(buy_60('Disputa A'), buy_60('Disputa B'))
        self.assertEqual(sorted([r1.status_code, r2.status_code]), [201, 400])
        self.assertEqual(m.Transaction.objects.filter(invoice=inv).count(), 1)


# =============================================================================
# FLUXO 4: Compras Parceladas (/api/v1/installment-purchases/)
# =============================================================================
class DescribeFluxo4ComprasParceladas(TestCase):
    """describe: Compras Parceladas (Prévia, Criação Idempotente, Edição, Cancelamento e Exclusão)."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a_f4')
        self.user_b = get_user_model().objects.create_user('user_b_f4')
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)
        self.account = m.Account.objects.create(user=self.user_a, name='Conta A')
        self.category = m.Category.objects.create(user=self.user_a, name='Compras')
        self.card = m.Card.objects.create(
            user=self.user_a, name='Cartão A', account=self.account, closing_day=25, due_day=12
        )
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def _payload(self, **overrides):
        base = {
            'description': 'Geladeira',
            'notes': 'Inox',
            'total_amount': '100.00',
            'installment_count': 3,
            'purchase_date': '2026-09-10',
            'first_month': '2026-09-01',
            'category': self.category.id,
            'account': self.account.id,
            'card': None,
            'request_id': 'req-f4-1',
        }
        base.update(overrides)
        return base

    # a. Caminho feliz
    def test_a1_quando_solicita_preview_sem_description_e_category_entao_calcula_cronograma_sem_gravar(self):
        res = self.client.post('/api/v1/installment-purchases/preview/', {
            'total_amount': '100.00',
            'installment_count': 3,
            'purchase_date': '2026-09-10',
            'first_month': '2026-09-01',
            'account': self.account.id,
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual([Decimal(r['amount']) for r in res.data['schedule']], [Decimal('33.34'), Decimal('33.33'), Decimal('33.33')])
        self.assertEqual(m.InstallmentPurchase.objects.count(), 0)

    def test_a2_quando_cria_compra_parcelada_entao_distribui_centavos_e_persiste_parcelas_E_patch_propaga(self):
        created = self.client.post('/api/v1/installment-purchases/', self._payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        pid = created.data['id']
        self.assertEqual(m.Transaction.objects.filter(installment_purchase_id=pid).count(), 3)

        patched = self.client.patch(f'/api/v1/installment-purchases/{pid}/', {
            'description': 'Geladeira Frost Free', 'notes': 'Garantia 2 anos',
        }, format='json')
        self.assertEqual(patched.status_code, 200)
        self.assertTrue(all(
            t.description == 'Geladeira Frost Free' and t.notes == 'Garantia 2 anos'
            for t in m.Transaction.objects.filter(installment_purchase_id=pid)
        ))

    def test_a3_quando_cancela_parcelas_restantes_ou_exclui_compra_aberta_entao_atualiza_corretamente(self):
        p1 = self.client.post('/api/v1/installment-purchases/', self._payload(request_id='req-cancel'), format='json').data
        res_cancel = self.client.post(f"/api/v1/installment-purchases/{p1['id']}/cancel-remaining/", {
            'from_month': '2026-10-01', 'confirmation': 'CANCELAR',
        }, format='json')
        self.assertEqual(res_cancel.status_code, 200)
        self.assertEqual(m.Transaction.objects.filter(installment_purchase_id=p1['id']).count(), 1)

        #Repetição idempotente do cancelamento (c4)
        res_cancel_again = self.client.post(f"/api/v1/installment-purchases/{p1['id']}/cancel-remaining/", {
            'from_month': '2026-10-01', 'confirmation': 'CANCELAR',
        }, format='json')
        self.assertEqual(res_cancel_again.status_code, 200)

        p2 = self.client.post('/api/v1/installment-purchases/', self._payload(request_id='req-del'), format='json').data
        res_del = self.client.delete(f"/api/v1/installment-purchases/{p2['id']}/")
        self.assertEqual(res_del.status_code, 204)
        self.assertFalse(m.InstallmentPurchase.objects.filter(pk=p2['id']).exists())

    # b. Erros esperados
    def test_b1_quando_cria_sem_request_id_description_category_ou_kind_income_ou_conflito_fatura_entao_400(self):
        for bad in [
            {'request_id': ''},
            {'description': ''},
            {'category': None},
            {'kind': 'income'},
        ]:
            self.assertEqual(self.client.post('/api/v1/installment-purchases/', self._payload(**bad), format='json').status_code, 400)

        # Conflito de manual_amount em parcela futura faz rollback completo
        inv_oct = s.ensure_invoice(self.user_a, self.card, date(2026, 10, 1))
        inv_oct.manual_amount = Decimal('20.00')
        inv_oct.save(update_fields=['manual_amount'])
        res_conflict = self.client.post('/api/v1/installment-purchases/', self._payload(
            account=None, card=self.card.id, request_id='req-conflict-oct'
        ), format='json')
        self.assertEqual(res_conflict.status_code, 400)
        self.assertEqual(m.InstallmentPurchase.objects.count(), 0)
        self.assertEqual(m.Transaction.objects.count(), 0)

    def test_b2_quando_cancela_ou_exclui_com_fatura_paga_ou_mes_passado_entao_retorna_400_atomico(self):
        p = self.client.post('/api/v1/installment-purchases/', self._payload(
            account=None, card=self.card.id, request_id='req-paid-block'
        ), format='json').data
        m.Invoice.objects.filter(card=self.card, month=date(2026, 10, 1)).update(paid_on=date(2026, 9, 15))

        # Sem confirmação
        self.assertEqual(self.client.post(f"/api/v1/installment-purchases/{p['id']}/cancel-remaining/", {
            'from_month': '2026-10-01', 'confirmation': 'ERRADO',
        }, format='json').status_code, 400)
        # Mês passado
        self.assertEqual(self.client.post(f"/api/v1/installment-purchases/{p['id']}/cancel-remaining/", {
            'from_month': '2026-08-01', 'confirmation': 'CANCELAR',
        }, format='json').status_code, 400)
        # Fatura paga na parcela afetada
        self.assertEqual(self.client.post(f"/api/v1/installment-purchases/{p['id']}/cancel-remaining/", {
            'from_month': '2026-10-01', 'confirmation': 'CANCELAR',
        }, format='json').status_code, 400)
        # Exclusão com fatura paga
        self.assertEqual(self.client.delete(f"/api/v1/installment-purchases/{p['id']}/").status_code, 400)
        self.assertEqual(m.Transaction.objects.filter(installment_purchase_id=p['id']).count(), 3)

    # c. Repetição
    def test_c1_quando_reenvia_mesmo_request_id_com_mesmo_payload_retorna_200_e_com_payload_diferente_retorna_409(self):
        r1 = self.client.post('/api/v1/installment-purchases/', self._payload(request_id='idemp-1'), format='json')
        r2 = self.client.post('/api/v1/installment-purchases/', self._payload(request_id='idemp-1'), format='json')
        r3 = self.client.post('/api/v1/installment-purchases/', self._payload(request_id='idemp-1', total_amount='200.00'), format='json')

        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.data['id'], r2.data['id'])
        self.assertEqual(r3.status_code, 409)
        self.assertEqual(m.InstallmentPurchase.objects.count(), 1)

    # d. Limites
    def test_d1_quando_testa_limites_de_parcelas_centavos_e_datas_entao_valida_corretamente(self):
        # 2 e 120 parcelas aceitos
        self.assertEqual(self.client.post('/api/v1/installment-purchases/', self._payload(
            installment_count=2, total_amount='2.00', request_id='lim-2'
        ), format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/v1/installment-purchases/', self._payload(
            installment_count=120, total_amount='120.00', request_id='lim-120'
        ), format='json').status_code, 201)

        # 1, 0, 121 parcelas, centavos insuficientes, compra no futuro, first_month anterior
        for idx, bad in enumerate([
            {'installment_count': 1},
            {'installment_count': 0},
            {'installment_count': 121},
            {'total_amount': '0.02', 'installment_count': 3},
            {'purchase_date': '2026-09-16'},
            {'purchase_date': '2026-09-10', 'first_month': '2026-08-01'},
        ]):
            res = self.client.post('/api/v1/installment-purchases/', self._payload(request_id=f'bad-{idx}', **bad), format='json')
            self.assertEqual(res.status_code, 400, bad)

    # e. Acesso indevido
    def test_e1_quando_usuario_a_acessa_compra_parcelada_de_b_ou_reutiliza_request_id_de_b_entao_isola_por_usuario(self):
        client_b = APIClient()
        client_b.force_authenticate(self.user_b)
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        cat_b = m.Category.objects.create(user=self.user_b, name='Cat B')

        p_b = client_b.post('/api/v1/installment-purchases/', {
            'description': 'Compra de B', 'total_amount': '100.00', 'installment_count': 2,
            'purchase_date': '2026-09-10', 'first_month': '2026-09-01',
            'category': cat_b.id, 'account': acc_b.id, 'request_id': 'shared-req-id',
        }, format='json').data

        # Usuário A usando mesmo request_id de B funciona normalmente (201)
        res_a = self.client.post('/api/v1/installment-purchases/', self._payload(request_id='shared-req-id'), format='json')
        self.assertEqual(res_a.status_code, 201)

        # Usuário A tentando acessar/editar/cancelar/excluir compra de B -> 404
        self.assertEqual(self.client.get(f"/api/v1/installment-purchases/{p_b['id']}/").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/v1/installment-purchases/{p_b['id']}/", {'description': 'Hack'}, format='json').status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/installment-purchases/{p_b['id']}/cancel-remaining/", {
            'from_month': '2026-10-01', 'confirmation': 'CANCELAR',
        }, format='json').status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/installment-purchases/{p_b['id']}/").status_code, 404)


class DescribeFluxo4ComprasParceladasConcorrencia(TransactionTestCase):
    """describe: Concorrência na criação idempotente de Compras Parceladas."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_f4_conc')
        self.account = m.Account.objects.create(user=self.user, name='Conta')
        self.category = m.Category.objects.create(user=self.user, name='Compras')

    def test_c3_quando_duas_requisicoes_simultaneas_enviam_mesmo_request_id_entao_cria_apenas_uma_compra(self):
        payload = {
            'description': 'TV OLED',
            'notes': '',
            'total_amount': '300.00',
            'installment_count': 3,
            'purchase_date': date.today().isoformat(),
            'first_month': date.today().replace(day=1).isoformat(),
            'category': self.category.id,
            'account': self.account.id,
            'card': None,
            'request_id': 'simultaneous-req-1',
        }

        def send():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.post('/api/v1/installment-purchases/', payload, format='json')

        r1, r2 = run_simultaneously(send, send)
        self.assertNotIn(500, [r1.status_code, r2.status_code])
        self.assertTrue({r1.status_code, r2.status_code}.issubset({200, 201}))
        self.assertEqual(m.InstallmentPurchase.objects.filter(user=self.user, request_id='simultaneous-req-1').count(), 1)
        self.assertEqual(m.Transaction.objects.filter(user=self.user).count(), 3)


# =============================================================================
# FLUXO 5: Faturas de Cartão e Contas a Pagar (/api/v1/invoices/, /api/v1/bills/)
# =============================================================================
class DescribeFluxo5FaturasEContasAPagar(TestCase):
    """describe: Faturas de Cartão e Contas a Pagar (Bills)."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a_f5')
        self.user_b = get_user_model().objects.create_user('user_b_f5')
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)
        self.account = m.Account.objects.create(user=self.user_a, name='Conta A')
        self.category = m.Category.objects.create(user=self.user_a, name='Moradia')
        self.card = m.Card.objects.create(
            user=self.user_a, name='Cartão A', account=self.account, closing_day=25, due_day=10
        )
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    # a. Caminho feliz
    def test_a1_quando_define_manual_amount_paga_e_reabre_fatura_entao_atualiza_status_e_permite_edicao(self):
        tx = self.client.post('/api/v1/transactions/', {
            'description': 'Compra 1', 'amount': '80.00', 'kind': 'expense',
            'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
        }, format='json').data
        inv_id = tx['invoice']

        # Define manual_amount maior que detalhado
        res_manual = self.client.patch(f'/api/v1/invoices/{inv_id}/', {'manual_amount': '150.00'}, format='json')
        self.assertEqual(res_manual.status_code, 200)
        dash = self.client.get('/api/v1/dashboard/?year=2026&month=9').data
        cats = {c['name']: Decimal(c['amount']) for c in dash['categories']}
        self.assertEqual(cats['Faturas sem detalhamento'], Decimal('70.00'))

        # Paga fatura
        res_pay = self.client.post(f'/api/v1/invoices/{inv_id}/pay/')
        self.assertEqual(res_pay.status_code, 200)
        self.assertEqual(res_pay.data['paid_on'], '2026-09-15')

        # Reabre fatura (paid_on=None) e edita transação
        res_reopen = self.client.patch(f'/api/v1/invoices/{inv_id}/', {'paid_on': None}, format='json')
        self.assertEqual(res_reopen.status_code, 200)
        self.assertIsNone(res_reopen.data['paid_on'])
        self.assertEqual(self.client.patch(f"/api/v1/transactions/{tx['id']}/", {'amount': '90.00'}, format='json').status_code, 200)

    def test_a2_quando_cria_e_paga_bill_na_competencia_atual_entao_zera_passivo(self):
        bill = self.client.post('/api/v1/bills/', {
            'description': 'Energia', 'amount': '220.00', 'account': self.account.id,
            'category': self.category.id, 'month': '2026-09-01', 'due_date': '2026-09-20',
        }, format='json').data
        self.assertEqual(Decimal(self.client.get('/api/v1/dashboard/?year=2026&month=9').data['liabilities']), Decimal('220.00'))

        pay_res = self.client.post(f"/api/v1/bills/{bill['id']}/pay/")
        self.assertEqual(pay_res.status_code, 200)
        self.assertEqual(Decimal(self.client.get('/api/v1/dashboard/?year=2026&month=9').data['liabilities']), Decimal('0.00'))

    # b. Erros esperados
    def test_b1_quando_manual_amount_menor_que_detalhado_ou_muda_cartao_mes_com_gastos_entao_400(self):
        tx = self.client.post('/api/v1/transactions/', {
            'description': 'Gasto', 'amount': '100.00', 'kind': 'expense',
            'date': '2026-09-10', 'category': self.category.id, 'card': self.card.id,
        }, format='json').data
        inv_id = tx['invoice']
        card2 = m.Card.objects.create(user=self.user_a, name='Outro', account=self.account)

        self.assertEqual(self.client.patch(f'/api/v1/invoices/{inv_id}/', {'manual_amount': '99.99'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/v1/invoices/{inv_id}/', {'card': card2.id}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/v1/invoices/{inv_id}/', {'month': '2026-10-01'}, format='json').status_code, 400)

    def test_b2_quando_tenta_pagar_fatura_vazia_futura_ou_com_projecao_ou_bill_futuro_entao_400(self):
        # Fatura vazia
        empty_inv = m.Invoice.objects.create(user=self.user_a, card=self.card, month=date(2026, 8, 1), due_date=date(2026, 9, 10))
        self.assertEqual(self.client.post(f'/api/v1/invoices/{empty_inv.id}/pay/').status_code, 400)

        # Fatura futura
        future_inv = m.Invoice.objects.create(
            user=self.user_a, card=self.card, month=date(2026, 10, 1),
            due_date=date(2026, 11, 10), manual_amount=Decimal('50.00'),
        )
        self.assertEqual(self.client.post(f'/api/v1/invoices/{future_inv.id}/pay/').status_code, 400)

        # Fatura atual com assinatura projetada ainda não cobrada (dia 20 > hoje dia 15)
        cur_inv = m.Invoice.objects.create(
            user=self.user_a, card=self.card, month=date(2026, 9, 1),
            due_date=date(2026, 10, 10), manual_amount=Decimal('100.00'),
        )
        self.client.post('/api/v1/subscriptions/', {
            'name': 'Sub Futura no Mês', 'amount': '30.00', 'category': self.category.id,
            'card': self.card.id, 'billing_day': 20, 'start_date': '2026-09-01',
        }, format='json')
        self.assertEqual(self.client.post(f'/api/v1/invoices/{cur_inv.id}/pay/').status_code, 400)

        # Bill futuro e paid_on no futuro
        future_bill = self.client.post('/api/v1/bills/', {
            'description': 'Aluguel Outubro', 'amount': '1000.00', 'account': self.account.id,
            'category': self.category.id, 'month': '2026-10-01', 'due_date': '2026-10-10',
        }, format='json').data
        self.assertEqual(self.client.post(f"/api/v1/bills/{future_bill['id']}/pay/").status_code, 400)
        self.assertEqual(self.client.patch(f"/api/v1/bills/{future_bill['id']}/", {'paid_on': '2026-09-20'}, format='json').status_code, 400)

    # d. Limites
    def test_d1_quando_bill_amount_zero_ou_fatura_manual_negativa_entao_400_E_due_day_menor_que_closing_day_vence_mes_seguinte(self):
        self.assertEqual(self.client.post('/api/v1/bills/', {
            'description': 'Zero', 'amount': '0.00', 'account': self.account.id,
            'category': self.category.id, 'month': '2026-09-01', 'due_date': '2026-09-10',
        }, format='json').status_code, 400)

        inv = s.ensure_invoice(self.user_a, self.card, date(2026, 9, 1))
        # card tem closing_day=25 e due_day=10 -> vencimento deve ser 10/10/2026
        self.assertEqual(inv.due_date, date(2026, 10, 10))
        self.assertEqual(self.client.patch(f'/api/v1/invoices/{inv.id}/', {'manual_amount': '-1.00'}, format='json').status_code, 400)

    # e. Acesso indevido
    def test_e1_quando_usuario_a_acessa_ou_paga_fatura_ou_bill_de_b_entao_retorna_404(self):
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        cat_b = m.Category.objects.create(user=self.user_b, name='Cat B')
        card_b = m.Card.objects.create(user=self.user_b, name='Cartão B', account=acc_b)
        inv_b = m.Invoice.objects.create(user=self.user_b, card=card_b, month=date(2026, 9, 1), due_date=date(2026, 9, 12), manual_amount=Decimal('50.00'))
        bill_b = m.Bill.objects.create(user=self.user_b, description='Bill B', amount=Decimal('50.00'), account=acc_b, category=cat_b, month=date(2026, 9, 1), due_date=date(2026, 9, 12))

        self.assertEqual(self.client.get(f'/api/v1/invoices/{inv_b.id}/').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/v1/invoices/{inv_b.id}/', {'manual_amount': '100.00'}, format='json').status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/invoices/{inv_b.id}/pay/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/bills/{bill_b.id}/pay/').status_code, 404)


class DescribeFluxo5FaturasConcorrencia(TransactionTestCase):
    """describe: Repetição e Concorrência no pagamento de Faturas e Bills."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_f5_conc')
        self.account = m.Account.objects.create(user=self.user, name='Conta')
        self.category = m.Category.objects.create(user=self.user, name='Cat')
        self.card = m.Card.objects.create(user=self.user, name='Cartão', account=self.account)
        self.month = date.today().replace(day=1)
        self.inv = m.Invoice.objects.create(
            user=self.user, card=self.card, month=self.month,
            due_date=date.today(), manual_amount=Decimal('80.00'),
        )
        self.bill = m.Bill.objects.create(
            user=self.user, description='Internet', amount=Decimal('99.00'),
            account=self.account, category=self.category, month=self.month, due_date=date.today(),
        )

    def test_c1_quando_aciona_pay_em_fatura_e_bill_simultaneamente_entao_mantem_pago_sem_erro(self):
        def pay_inv():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.post(f'/api/v1/invoices/{self.inv.id}/pay/')

        def pay_bill():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.post(f'/api/v1/bills/{self.bill.id}/pay/')

        ri1, ri2 = run_simultaneously(pay_inv, pay_inv)
        self.assertEqual([ri1.status_code, ri2.status_code], [200, 200])
        rb1, rb2 = run_simultaneously(pay_bill, pay_bill)
        self.assertEqual([rb1.status_code, rb2.status_code], [200, 200])


# =============================================================================
# FLUXO 6: Assinaturas e Sincronização (/api/v1/subscriptions/, /api/v1/sync/)
# =============================================================================
class DescribeFluxo6AssinaturasESincronizacao(TestCase):
    """describe: Assinaturas Recorrentes e Materialização (/sync/)."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a_f6')
        self.user_b = get_user_model().objects.create_user('user_b_f6')
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)
        self.account = m.Account.objects.create(user=self.user_a, name='Conta A')
        self.category = m.Category.objects.create(user=self.user_a, name='Assinaturas')
        self.card = m.Card.objects.create(user=self.user_a, name='Cartão A', account=self.account, closing_day=25, due_day=12)
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    # a. Caminho feliz
    def test_a1_quando_cria_projeta_atualiza_valor_revisa_e_cancela_assinatura_entao_respeita_ciclo_de_vida(self):
        # Cria com include_start_month=True (billing_day=5 < start_date dia 15 -> cobra em 15/09)
        sub = self.client.post('/api/v1/subscriptions/', {
            'name': 'Spotify', 'amount': '21.90', 'category': self.category.id,
            'account': self.account.id, 'billing_day': 5, 'start_date': '2026-09-15',
            'include_start_month': True,
        }, format='json').data
        self.assertEqual(sub['first_charge_date'], '2026-09-15')
        self.assertEqual(m.Transaction.objects.filter(subscription_id=sub['id']).count(), 1)

        # Projeção virtual em outubro sem gravar no banco
        oct_items = self.client.get('/api/v1/transactions/monthly/?year=2026&month=10').data
        self.assertEqual(len(oct_items), 1)
        self.assertTrue(oct_items[0]['is_projected'])
        self.assertEqual(m.Transaction.objects.filter(subscription_id=sub['id']).count(), 1)

        # Altera valor para 29.90: preserva setembro (21.90) e projeta outubro (29.90)
        self.assertEqual(self.client.patch(f"/api/v1/subscriptions/{sub['id']}/", {'amount': '29.90'}, format='json').status_code, 200)
        self.assertEqual(m.Transaction.objects.get(subscription_id=sub['id'], month=date(2026, 9, 1)).amount, Decimal('21.90'))
        self.assertEqual(Decimal(self.client.get('/api/v1/transactions/monthly/?year=2026&month=10').data[0]['amount']), Decimal('29.90'))

        # Cancela assinatura (e repete cancelamento de forma idempotente - c2)
        c1 = self.client.post(f"/api/v1/subscriptions/{sub['id']}/cancel/")
        c2 = self.client.post(f"/api/v1/subscriptions/{sub['id']}/cancel/")
        self.assertEqual([c1.status_code, c2.status_code], [200, 200])
        self.assertFalse(c2.data['is_active'])
        self.assertEqual(self.client.get('/api/v1/transactions/monthly/?year=2026&month=10').data, [])

        # Revisão da 1ª cobrança em assinatura sem histórico
        sub_no_hist = self.client.post('/api/v1/subscriptions/', {
            'name': 'Anual', 'amount': '50.00', 'category': self.category.id,
            'account': self.account.id, 'billing_day': 5, 'start_date': '2026-09-15',
            'include_start_month': False,
        }, format='json').data
        rev = self.client.post(f"/api/v1/subscriptions/{sub_no_hist['id']}/review-first-charge/", {
            'include_start_month': True, 'apply': True, 'confirmation': 'REVISAR',
        }, format='json')
        self.assertEqual(rev.status_code, 200)
        self.assertTrue(rev.data['applied'])

    # b. Erros esperados
    def test_b1_quando_assinatura_bate_em_fatura_paga_ou_tenta_patch_proibido_ou_review_invalido_entao_400(self):
        inv = s.ensure_invoice(self.user_a, self.card, date(2026, 9, 1))
        inv.paid_on = date(2026, 9, 10)
        inv.save(update_fields=['paid_on'])

        # Criação bloqueada por fatura paga
        res_paid = self.client.post('/api/v1/subscriptions/', {
            'name': 'Bloqueada', 'amount': '30.00', 'category': self.category.id,
            'card': self.card.id, 'billing_day': 5, 'start_date': '2026-09-01',
        }, format='json')
        self.assertEqual(res_paid.status_code, 400)

        # Criação normal em conta para testar PATCH proibido e review inválido
        sub = self.client.post('/api/v1/subscriptions/', {
            'name': 'Ativa', 'amount': '30.00', 'category': self.category.id,
            'account': self.account.id, 'billing_day': 5, 'start_date': '2026-09-01',
        }, format='json').data
        for field in [{'start_date': '2026-08-01'}, {'end_date': '2026-10-01'}, {'is_active': False}]:
            self.assertEqual(self.client.patch(f"/api/v1/subscriptions/{sub['id']}/", field, format='json').status_code, 400)

        # Review sem confirmação ou com histórico já existente
        self.assertEqual(self.client.post(f"/api/v1/subscriptions/{sub['id']}/review-first-charge/", {
            'include_start_month': False, 'apply': True, 'confirmation': 'ERRADO',
        }, format='json').status_code, 400)
        self.assertEqual(self.client.post(f"/api/v1/subscriptions/{sub['id']}/review-first-charge/", {
            'include_start_month': False, 'apply': True, 'confirmation': 'REVISAR',
        }, format='json').status_code, 400)

    # d. Limites
    def test_d1_quando_billing_day_amount_ou_start_date_fora_dos_limites_entao_retorna_400(self):
        for bad in [
            {'billing_day': 0},
            {'billing_day': 32},
            {'amount': '0.00'},
            {'amount': '-10.00'},
            {'start_date': '2015-01-01'},  # > 10 anos no passado
        ]:
            payload = {
                'name': 'Teste', 'amount': '20.00', 'category': self.category.id,
                'account': self.account.id, 'billing_day': 10, 'start_date': '2026-09-01',
                **bad,
            }
            self.assertEqual(self.client.post('/api/v1/subscriptions/', payload, format='json').status_code, 400, bad)

    # e. Acesso indevido
    def test_e1_quando_usuario_a_acessa_assinatura_de_b_ou_chama_sync_entao_nao_afeta_b(self):
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        cat_b = m.Category.objects.create(user=self.user_b, name='Cat B')
        sub_b = m.Subscription.objects.create(
            user=self.user_b, name='Sub B', amount=Decimal('40.00'),
            category=cat_b, account=acc_b, billing_day=1, start_date=date(2026, 9, 1),
            first_charge_date=date(2026, 9, 1),
        )

        self.assertEqual(self.client.get(f'/api/v1/subscriptions/{sub_b.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/subscriptions/{sub_b.id}/cancel/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/subscriptions/{sub_b.id}/review-first-charge/', {'include_start_month': True}, format='json').status_code, 404)

        # Sync de A não materializa assinatura de B
        self.client.post('/api/v1/sync/')
        self.assertFalse(m.Transaction.objects.filter(subscription=sub_b).exists())


class DescribeFluxo6SyncConcorrencia(TransactionTestCase):
    """describe: Concorrência em POST /api/v1/sync/."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_f6_conc')
        self.account = m.Account.objects.create(user=self.user, name='Conta')
        self.category = m.Category.objects.create(user=self.user, name='Serviços')
        self.month = date.today().replace(day=1)
        self.sub = m.Subscription.objects.create(
            user=self.user, name='Cloud', amount=Decimal('15.00'),
            category=self.category, account=self.account,
            billing_day=1, start_date=self.month, first_charge_date=self.month,
        )

    def test_c1_quando_dispara_sync_simultaneamente_entao_nao_duplica_cobrancas_nem_categorias(self):
        def call_sync():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.post('/api/v1/sync/')

        r1, r2 = run_simultaneously(call_sync, call_sync)
        self.assertNotIn(500, [r1.status_code, r2.status_code])
        self.assertEqual(m.Transaction.objects.filter(subscription=self.sub, month=self.month).count(), 1)
        self.assertEqual(m.Category.objects.filter(user=self.user, name='Alimentação').count(), 1)


# =============================================================================
# FLUXO 7: Metas Financeiras e Aportes (/api/v1/goals/)
# =============================================================================
class DescribeFluxo7MetasEAportes(TestCase):
    """describe: Metas Financeiras e Aportes."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a_f7')
        self.user_b = get_user_model().objects.create_user('user_b_f7')
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    # a. Caminho feliz
    def test_a1_quando_cria_meta_aporta_e_edita_entao_calcula_progresso_e_preserva_goalstate_historico(self):
        goal = self.client.post('/api/v1/goals/', {
            'name': 'Reserva', 'target_amount': '1000.00',
            'start_date': '2026-08-01', 'target_date': '2026-11-30',
            'priority': 1,
        }, format='json').data

        # Aporte em setembro
        c_res = self.client.post(f"/api/v1/goals/{goal['id']}/contributions/", {
            'amount': '250.00', 'date': '2026-09-10',
        }, format='json')
        self.assertEqual(c_res.status_code, 201)

        # Atualiza meta em setembro e desativa
        self.client.patch(f"/api/v1/goals/{goal['id']}/", {
            'target_amount': '2000.00', 'is_active': False,
        }, format='json')

        aug_summary = self.client.get('/api/v1/goals/summary/?year=2026&month=8').data[0]
        sep_summary = self.client.get('/api/v1/goals/summary/?year=2026&month=9').data[0]
        self.assertEqual(Decimal(aug_summary['target_amount']), Decimal('1000.00'))
        self.assertTrue(aug_summary['is_active'])
        self.assertEqual(Decimal(sep_summary['target_amount']), Decimal('2000.00'))
        self.assertEqual(Decimal(sep_summary['monthly_required']), Decimal('0.00'))

    # b. Erros esperados
    def test_b1_quando_altera_start_date_ou_aporta_fora_do_intervalo_ou_exclui_meta_entao_400(self):
        goal = self.client.post('/api/v1/goals/', {
            'name': 'Carro', 'target_amount': '5000.00',
            'start_date': '2026-09-05', 'target_date': '2026-12-31',
        }, format='json').data

        self.assertEqual(self.client.patch(f"/api/v1/goals/{goal['id']}/", {'start_date': '2026-08-01'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(f"/api/v1/goals/{goal['id']}/contributions/", {'amount': '100.00', 'date': '2026-09-04'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(f"/api/v1/goals/{goal['id']}/contributions/", {'amount': '100.00', 'date': '2026-09-16'}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(f"/api/v1/goals/{goal['id']}/").status_code, 400)

    # d. Limites
    def test_d1_quando_aportes_ultrapassam_meta_ou_meta_de_mes_unico_ou_valores_invalidos_entao_respeita_limites(self):
        for bad in [
            {'target_amount': '0.00'},
            {'target_amount': '-10.00'},
            {'priority': 0},
            {'priority': 6},
            {'target_date': '2026-08-31'},
        ]:
            payload = {'name': 'Inv', 'target_amount': '100.00', 'start_date': '2026-09-01', 'target_date': '2026-09-30', **bad}
            self.assertEqual(self.client.post('/api/v1/goals/', payload, format='json').status_code, 400)

        # Meta no mesmo mês (start_date == target_date) e aporte acima do target_amount
        goal = self.client.post('/api/v1/goals/', {
            'name': 'Curta', 'target_amount': '100.00',
            'start_date': '2026-09-01', 'target_date': '2026-09-01',
        }, format='json').data
        s1 = self.client.get('/api/v1/goals/summary/?year=2026&month=9').data[0]
        self.assertEqual(Decimal(s1['monthly_required']), Decimal('100.00'))

        self.client.post(f"/api/v1/goals/{goal['id']}/contributions/", {'amount': '150.00', 'date': '2026-09-10'}, format='json')
        s2 = self.client.get('/api/v1/goals/summary/?year=2026&month=9').data[0]
        self.assertEqual(Decimal(s2['remaining']), Decimal('0.00'))
        self.assertEqual(Decimal(s2['monthly_required']), Decimal('0.00'))
        self.assertEqual(Decimal(s2['progress']), Decimal('100.0'))

    # e. Acesso indevido
    def test_e1_quando_usuario_a_acessa_ou_aporta_em_meta_de_b_entao_retorna_404(self):
        goal_b = m.Goal.objects.create(
            user=self.user_b, name='Meta B', target_amount=Decimal('500.00'),
            start_date=date(2026, 9, 1), target_date=date(2026, 12, 1),
        )
        self.assertEqual(self.client.get(f'/api/v1/goals/{goal_b.id}/contributions/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/v1/goals/{goal_b.id}/contributions/', {'amount': '10.00', 'date': '2026-09-10'}, format='json').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/v1/goals/{goal_b.id}/', {'name': 'Hack'}, format='json').status_code, 404)


class DescribeFluxo7MetasConcorrencia(TransactionTestCase):
    """describe: Concorrência na atualização de GoalState no mesmo mês."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_f7_conc')
        self.month = date.today().replace(day=1)
        self.goal = m.Goal.objects.create(
            user=self.user, name='Meta', target_amount=Decimal('1000.00'),
            start_date=self.month, target_date=self.month,
        )
        s.goal_state(self.goal, self.month)

    def test_c1_quando_atualiza_mesma_meta_simultaneamente_no_mesmo_mes_entao_mantem_unico_goalstate(self):
        def patch_goal(amount):
            def _call():
                c = APIClient()
                c.force_authenticate(self.user)
                return c.patch(f'/api/v1/goals/{self.goal.id}/', {'target_amount': amount}, format='json')
            return _call

        r1, r2 = run_simultaneously(patch_goal('1500.00'), patch_goal('2000.00'))
        self.assertNotIn(500, [r1.status_code, r2.status_code])
        self.assertEqual(m.GoalState.objects.filter(goal=self.goal, month=self.month).count(), 1)


# =============================================================================
# FLUXO 8: Dashboard, Planejamento, Histórico e Agenda
# =============================================================================
class DescribeFluxo8ConsultasConsolidadasEAgenda(TestCase):
    """describe: Consultas Consolidadas: Dashboard, Planejamento, Histórico e Agenda."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user('user_a_f8')
        self.user_b = get_user_model().objects.create_user('user_b_f8')
        self.client = APIClient()
        self.client.force_authenticate(self.user_a)
        self.account = m.Account.objects.create(user=self.user_a, name='Conta A')
        self.category = m.Category.objects.create(user=self.user_a, name='Geral')
        self.card = m.Card.objects.create(user=self.user_a, name='Cartão A', account=self.account, closing_day=25, due_day=12)
        self.clock = patch('django.utils.timezone.localdate', return_value=date(2026, 9, 15))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    # a. Caminho feliz
    def test_a1_quando_consulta_dashboard_planning_history_e_payments_entao_consolida_e_separa_pendencias(self):
        m.Balance.objects.create(account=self.account, month=date(2026, 9, 1), amount=Decimal('3000.00'))
        # Obrigação pendente de agosto
        m.Bill.objects.create(
            user=self.user_a, description='Luz Agosto', amount=Decimal('150.00'),
            account=self.account, category=self.category,
            month=date(2026, 8, 1), due_date=date(2026, 8, 20),
        )
        # Obrigação de setembro
        m.Bill.objects.create(
            user=self.user_a, description='Luz Setembro', amount=Decimal('180.00'),
            account=self.account, category=self.category,
            month=date(2026, 9, 1), due_date=date(2026, 9, 20),
        )

        dash = self.client.get('/api/v1/dashboard/?year=2026&month=9').data
        self.assertEqual(len(dash['history']), 6)
        self.assertEqual(Decimal(dash['assets']), Decimal('3000.00'))
        self.assertEqual(Decimal(dash['liabilities']), Decimal('330.00'))

        plan = self.client.get('/api/v1/planning/2026/9/').data
        self.assertEqual(len(plan['forecast']), 12)

        upcoming = self.client.get('/api/v1/payments/upcoming/?year=2026&month=9').data
        pending = self.client.get('/api/v1/payments/pending/?year=2026&month=9').data
        self.assertEqual([r['description'] for r in upcoming], ['Luz Setembro'])
        self.assertEqual([r['description'] for r in pending], ['Luz Agosto'])

    # b. Erros esperados
    def test_b1_quando_informa_year_ou_month_invalidos_ou_filtros_nao_numericos_entao_retorna_400(self):
        for url in [
            '/api/v1/dashboard/?month=0',
            '/api/v1/dashboard/?month=13',
            '/api/v1/dashboard/?year=abc&month=9',
            '/api/v1/dashboard/?account_id=abc',
            '/api/v1/payments/upcoming/?month=99',
            '/api/v1/payments/pending/?month=0',
        ]:
            self.assertEqual(self.client.get(url).status_code, 400, url)

    # d. Limites
    def test_d1_quando_ha_meta_vencida_ou_deficit_entao_feasible_false_E_fatura_vazia_nao_aparece_na_agenda(self):
        # Fatura vazia em setembro
        m.Invoice.objects.create(user=self.user_a, card=self.card, month=date(2026, 9, 1), due_date=date(2026, 10, 12))
        self.assertEqual(self.client.get('/api/v1/payments/upcoming/?year=2026&month=9').data, [])

        # Meta vencida em 10/09/2026 (< hoje 15/09/2026) mesmo com receita alta -> feasible=False
        self.client.post('/api/v1/transactions/', {
            'description': 'Salário', 'amount': '5000.00', 'kind': 'income',
            'date': '2026-09-05', 'month': '2026-09-01',
            'category': self.category.id, 'account': self.account.id,
        }, format='json')
        self.client.post('/api/v1/goals/', {
            'name': 'Meta Vencida', 'target_amount': '500.00',
            'start_date': '2026-09-01', 'target_date': '2026-09-10',
        }, format='json')
        dash = self.client.get('/api/v1/dashboard/?year=2026&month=9').data
        self.assertFalse(dash['feasible'])

    # e. Acesso indevido
    def test_e1_quando_usuario_a_consulta_paineis_filtrando_por_ids_do_usuario_b_entao_retorna_vazio(self):
        acc_b = m.Account.objects.create(user=self.user_b, name='Conta B')
        cat_b = m.Category.objects.create(user=self.user_b, name='Cat B')
        m.Balance.objects.create(account=acc_b, month=date(2026, 9, 1), amount=Decimal('9999.00'))
        m.Transaction.objects.create(
            user=self.user_b, description='Receita B', amount=Decimal('8888.00'),
            kind='income', date=date(2026, 9, 10), month=date(2026, 9, 1),
            category=cat_b, account=acc_b,
        )

        dash = self.client.get(f'/api/v1/dashboard/?year=2026&month=9&account_id={acc_b.id}').data
        self.assertEqual(Decimal(dash['assets']), Decimal('0.00'))
        self.assertEqual(Decimal(dash['income']), Decimal('0.00'))


class DescribeFluxo8ConsultasConcorrencia(TransactionTestCase):
    """describe: Consultas simultâneas em meses futuros não gravam dados especulativos."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('user_f8_conc')
        self.account = m.Account.objects.create(user=self.user, name='Conta')
        self.category = m.Category.objects.create(user=self.user, name='Assinaturas')
        self.month = date.today().replace(day=1)
        m.Subscription.objects.create(
            user=self.user, name='Streaming', amount=Decimal('39.90'),
            category=self.category, account=self.account,
            billing_day=15, start_date=self.month, first_charge_date=self.month,
        )

    def test_c1_quando_consulta_simultaneamente_meses_futuros_entao_nao_persiste_transacoes_nem_faturas(self):
        future_year = self.month.year + 1

        def query_planning():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.get(f'/api/v1/planning/{future_year}/6/')

        def query_monthly():
            c = APIClient()
            c.force_authenticate(self.user)
            return c.get(f'/api/v1/transactions/monthly/?year={future_year}&month=6')

        r1, r2 = run_simultaneously(query_planning, query_monthly)
        self.assertEqual([r1.status_code, r2.status_code], [200, 200])
        self.assertEqual(m.Transaction.objects.count(), 0)
        self.assertEqual(m.Invoice.objects.count(), 0)
