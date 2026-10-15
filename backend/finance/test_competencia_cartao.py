"""Tests for credit card statement closing competence and invoice due dates.

Specified in markdowns/competenciaFechamentoCartaoTest.md.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from . import models as m, services as s
from .installments import split_amount

try:
    from .card_cycle import (
        card_competence,
        effective_closing_day,
        effective_closing_date,
        calculate_due_date,
    )
except ImportError:
    try:
        from .services import (
            card_competence,
            effective_closing_day,
            effective_closing_date,
            calculate_due_date,
        )
    except ImportError:
        card_competence = None
        effective_closing_day = None
        effective_closing_date = None
        calculate_due_date = None


class CardClosingCalendarTests(TestCase):
    """Section 3: Calendar table tests before integrating the interface."""

    def test_calendar_competence_table(self):
        """Validates all boundary conditions from the specification table:

        | Compra     | Fechamento            | Competência esperada |
        | 01/02/2027 | 2                     | Janeiro/2027         |
        | 02/02/2027 | 2                     | Fevereiro/2027       |
        | 03/02/2027 | 2                     | Fevereiro/2027       |
        | 01/01/2027 | 2                     | Dezembro/2026        |
        | 01/02/2027 | 1                     | Fevereiro/2027       |
        | 27/02/2027 | 31 (ajustado para 28) | Janeiro/2027         |
        | 28/02/2027 | 31 (ajustado para 28) | Fevereiro/2027       |
        | 28/02/2028 | 31 (ajustado para 29) | Janeiro/2028         |
        | 29/02/2028 | 31 (ajustado para 29) | Fevereiro/2028       |
        """
        if card_competence is None:
            self.fail("card_competence ainda não implementado no backend.")

        cases = [
            (date(2027, 2, 1), 2, date(2027, 1, 1)),
            (date(2027, 2, 2), 2, date(2027, 2, 1)),
            (date(2027, 2, 3), 2, date(2027, 2, 1)),
            (date(2027, 1, 1), 2, date(2026, 12, 1)),
            (date(2027, 2, 1), 1, date(2027, 2, 1)),
            (date(2027, 2, 27), 31, date(2027, 1, 1)),
            (date(2027, 2, 28), 31, date(2027, 2, 1)),
            (date(2028, 2, 28), 31, date(2028, 1, 1)),
            (date(2028, 2, 29), 31, date(2028, 2, 1)),
        ]

        for purchase_date, closing_day, expected_month in cases:
            with self.subTest(purchase=purchase_date, closing=closing_day):
                result = card_competence(purchase_date, closing_day)
                self.assertEqual(
                    result,
                    expected_month,
                    f"Compra {purchase_date} com fechamento dia {closing_day} deveria ter competência {expected_month}, obteve {result}",
                )

    def test_calendar_competence_independent_of_current_date_or_screen_month(self):
        """Result must remain identical regardless of whether today is in March or another month."""
        if card_competence is None:
            self.fail("card_competence ainda não implementado no backend.")

        for simulated_today in [date(2027, 2, 3), date(2027, 3, 15), date(2027, 12, 31)]:
            with patch("django.utils.timezone.localdate", return_value=simulated_today):
                self.assertEqual(card_competence(date(2027, 2, 1), 2), date(2027, 1, 1))
                self.assertEqual(card_competence(date(2027, 2, 2), 2), date(2027, 2, 1))


class SimpleCardPurchaseTests(TestCase):
    """Section 4: Simple card purchase and contracts."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("tester_competence")
        self.other = get_user_model().objects.create_user("other_competence")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.account = m.Account.objects.create(user=self.user, name="Conta Corrente")
        self.category = m.Category.objects.create(user=self.user, name="Alimentação")
        self.card = m.Card.objects.create(
            user=self.user,
            name="Cartão A",
            account=self.account,
            closing_day=2,
            due_day=11,
        )

        # Controlled clock at 03/02/2027
        self.clock = patch("django.utils.timezone.localdate", return_value=date(2027, 2, 3))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_card_purchase_before_closing_saves_previous_month(self):
        """Ao cadastrar 01/02 no Cartão A, salvar date=2027-02-01, month=2027-01-01 e vínculo com a fatura de janeiro."""
        payload = {
            "description": "Mercado",
            "amount": "100.00",
            "kind": "expense",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }
        res = self.client.post("/api/v1/transactions/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        tx = m.Transaction.objects.get(pk=res.data["id"])
        self.assertEqual(tx.date, date(2027, 2, 1))
        self.assertEqual(tx.month, date(2027, 1, 1))
        self.assertIsNotNone(tx.invoice)
        self.assertEqual(tx.invoice.month, date(2027, 1, 1))
        self.assertEqual(tx.invoice.card, self.card)

    def test_purchase_summed_in_january_not_in_february(self):
        """Em janeiro, a compra soma R$ 100,00 nas despesas e na fatura. Em fevereiro, não soma novamente."""
        payload = {
            "description": "Mercado",
            "amount": "100.00",
            "kind": "expense",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }
        res = self.client.post("/api/v1/transactions/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        sum_jan = s.summary(self.user, date(2027, 1, 1))
        self.assertEqual(sum_jan["expenses"], Decimal("100.00"))
        self.assertEqual(sum_jan["invoice_total"], Decimal("100.00"))

        sum_feb = s.summary(self.user, date(2027, 2, 1))
        self.assertEqual(sum_feb["expenses"], Decimal("0.00"))
        self.assertEqual(sum_feb["invoice_total"], Decimal("0.00"))

    def test_omitted_month_calculated_and_mismatched_month_rejected(self):
        """O servidor calcula a competência quando omitida. Mês divergente deve gerar erro 400."""
        # 1. Mês omitido -> servidor calcula 2027-01-01
        payload_no_month = {
            "description": "Farmácia",
            "amount": "50.00",
            "kind": "expense",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }
        res1 = self.client.post("/api/v1/transactions/", payload_no_month, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res1.data["month"], "2027-01-01")

        # 2. Mês divergente enviado (2027-02-01 em vez de 2027-01-01) -> erro 400 claro
        payload_wrong_month = {
            "description": "Farmácia 2",
            "amount": "50.00",
            "kind": "expense",
            "date": "2027-02-01",
            "month": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }
        res2 = self.client.post("/api/v1/transactions/", payload_wrong_month, format="json")
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("month", res2.data)

    def test_account_purchase_preserves_manual_month(self):
        """Compra em conta preserva a competência manual e não usa o fechamento de nenhum cartão."""
        payload = {
            "description": "Luz",
            "amount": "120.00",
            "kind": "expense",
            "date": "2027-02-01",
            "month": "2027-02-01",
            "category": self.category.id,
            "account": self.account.id,
        }
        res = self.client.post("/api/v1/transactions/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        tx = m.Transaction.objects.get(pk=res.data["id"])
        self.assertEqual(tx.date, date(2027, 2, 1))
        self.assertEqual(tx.month, date(2027, 2, 1))
        self.assertIsNone(tx.invoice)

    def test_card_income_and_other_user_card_rejected(self):
        """Receita em cartão e vínculos de outro usuário continuam rejeitados."""
        foreign_card = m.Card.objects.create(
            user=self.other,
            name="Cartão Estranho",
            account=m.Account.objects.create(user=self.other, name="Conta Estranha"),
            closing_day=5,
            due_day=12,
        )
        # Receita em cartão
        res_income = self.client.post("/api/v1/transactions/", {
            "description": "Estorno",
            "amount": "50.00",
            "kind": "income",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }, format="json")
        self.assertEqual(res_income.status_code, status.HTTP_400_BAD_REQUEST)

        # Cartão de outro usuário
        res_foreign = self.client.post("/api/v1/transactions/", {
            "description": "Compra Outro",
            "amount": "50.00",
            "kind": "expense",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": foreign_card.id,
        }, format="json")
        self.assertEqual(res_foreign.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_date_transfers_transaction_between_invoices_atomically(self):
        """Alterar data de 01/02 para 03/02 transfere a transação de janeiro para fevereiro atomicamente."""
        res = self.client.post("/api/v1/transactions/", {
            "description": "Compra teste",
            "amount": "100.00",
            "kind": "expense",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }, format="json")
        tx_id = res.data["id"]

        # Alterar para 03/02 (dia 3 >= fechamento dia 2 -> vai para fevereiro)
        up = self.client.patch(f"/api/v1/transactions/{tx_id}/", {"date": "2027-02-03"}, format="json")
        self.assertEqual(up.status_code, status.HTTP_200_OK)

        tx = m.Transaction.objects.get(pk=tx_id)
        self.assertEqual(tx.date, date(2027, 2, 3))
        self.assertEqual(tx.month, date(2027, 2, 1))
        self.assertEqual(tx.invoice.month, date(2027, 2, 1))

        # Janeiro agora tem 0 despesas, Fevereiro tem 100
        self.assertEqual(s.summary(self.user, date(2027, 1, 1))["expenses"], Decimal("0.00"))
        self.assertEqual(s.summary(self.user, date(2027, 2, 1))["expenses"], Decimal("100.00"))

    def test_update_card_recalculates_but_description_preserves_competence(self):
        """Alterar cartão recalcula com fechamento do novo cartão; alterar somente descrição preserva."""
        card2 = m.Card.objects.create(
            user=self.user,
            name="Cartão Fechamento 1",
            account=self.account,
            closing_day=1,
            due_day=10,
        )
        res = self.client.post("/api/v1/transactions/", {
            "description": "Compra inicial",
            "amount": "100.00",
            "kind": "expense",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }, format="json")
        tx_id = res.data["id"]
        self.assertEqual(m.Transaction.objects.get(pk=tx_id).month, date(2027, 1, 1))

        # Alterar descrição não mexe no mês
        self.client.patch(f"/api/v1/transactions/{tx_id}/", {"description": "Nova descrição"}, format="json")
        self.assertEqual(m.Transaction.objects.get(pk=tx_id).month, date(2027, 1, 1))

        # Alterar cartão para card2 (fechamento 1: compra dia 1 >= fechamento 1 -> mês vira 2027-02-01)
        up_card = self.client.patch(f"/api/v1/transactions/{tx_id}/", {"card": card2.id}, format="json")
        self.assertEqual(up_card.status_code, status.HTTP_200_OK)
        tx = m.Transaction.objects.get(pk=tx_id)
        self.assertEqual(tx.month, date(2027, 2, 1))
        self.assertEqual(tx.card, card2)

    def test_paid_invoice_or_insufficient_manual_total_blocks_transfer(self):
        """Se a fatura estiver paga ou o total manual for insuficiente, nenhuma alteração parcial é salva."""
        res = self.client.post("/api/v1/transactions/", {
            "description": "Compra inicial",
            "amount": "100.00",
            "kind": "expense",
            "date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }, format="json")
        tx_id = res.data["id"]
        tx = m.Transaction.objects.get(pk=tx_id)
        inv_jan = tx.invoice

        # Marcar fatura de janeiro como paga
        inv_jan.paid_on = date(2027, 2, 2)
        inv_jan.save()

        # Tentar alterar data deve falhar porque a fatura de origem está paga
        up = self.client.patch(f"/api/v1/transactions/{tx_id}/", {"date": "2027-02-03"}, format="json")
        self.assertEqual(up.status_code, status.HTTP_400_BAD_REQUEST)
        tx.refresh_from_db()
        self.assertEqual(tx.date, date(2027, 2, 1))
        self.assertEqual(tx.month, date(2027, 1, 1))


class CardInstallmentTests(TestCase):
    """Section 5: Installment purchases."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("tester_installments")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.account = m.Account.objects.create(user=self.user, name="Conta")
        self.category = m.Category.objects.create(user=self.user, name="Compras")
        self.card = m.Card.objects.create(
            user=self.user,
            name="Cartão A",
            account=self.account,
            closing_day=2,
            due_day=11,
        )

        self.clock = patch("django.utils.timezone.localdate", return_value=date(2027, 2, 3))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_installment_schedule_derived_from_closing(self):
        """Compra em 01/02/2027, fechamento dia 2, R$ 300,00 em 3 parcelas:

        Parcela 1/3: 01/02/2027, competência Janeiro/2027, R$ 100,00
        Parcela 2/3: 01/03/2027, competência Fevereiro/2027, R$ 100,00
        Parcela 3/3: 01/04/2027, competência Março/2027, R$ 100,00
        A primeira data nunca é inventada como 01/01.
        """
        payload = {
            "description": "Notebook",
            "total_amount": "300.00",
            "installment_count": 3,
            "purchase_date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
            "request_id": "req-installments-1",
        }
        res = self.client.post("/api/v1/installment-purchases/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)

        schedule = res.data["schedule"]
        self.assertEqual(len(schedule), 3)

        expected = [
            {"number": 1, "date": "2027-02-01", "month": "2027-01-01", "amount": "100.00"},
            {"number": 2, "date": "2027-03-01", "month": "2027-02-01", "amount": "100.00"},
            {"number": 3, "date": "2027-04-01", "month": "2027-03-01", "amount": "100.00"},
        ]
        for item, exp in zip(schedule, expected):
            self.assertEqual(item["number"], exp["number"])
            self.assertEqual(item["date"], exp["date"])
            self.assertEqual(item["month"], exp["month"])
            self.assertEqual(Decimal(item["amount"]), Decimal(exp["amount"]))

        # Verificar que Abril não recebeu 4ª parcela
        self.assertFalse(m.Transaction.objects.filter(month=date(2027, 4, 1)).exists())

    def test_preview_matches_creation_result(self):
        """A prévia e o resultado salvo devem ser iguais."""
        payload = {
            "description": "Móvel",
            "total_amount": "300.00",
            "installment_count": 3,
            "purchase_date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
        }
        preview_res = self.client.post("/api/v1/installment-purchases/preview/", payload, format="json")
        self.assertEqual(preview_res.status_code, status.HTTP_200_OK, preview_res.data)

        create_res = self.client.post(
            "/api/v1/installment-purchases/",
            {**payload, "request_id": "req-preview-match"},
            format="json",
        )
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)

        preview_schedule = preview_res.data["schedule"]
        create_schedule = create_res.data["schedule"]
        self.assertEqual(preview_schedule, create_schedule)

    def test_account_installment_preserves_manual_choice_and_validation(self):
        """Parcelamento em conta preserva a validação e a escolha manual atuais."""
        payload_invalid = {
            "description": "Curso",
            "total_amount": "200.00",
            "installment_count": 2,
            "purchase_date": "2027-02-01",
            "first_month": "2027-01-01",  # Anterior ao mês civil em conta deve continuar proibido
            "category": self.category.id,
            "account": self.account.id,
            "request_id": "req-account-invalid",
        }
        res = self.client.post("/api/v1/installment-purchases/", payload_invalid, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_split_amount_precision_maintained(self):
        """A distribuição de R$ 100,00 em 3 parcelas continua exata (33.34, 33.33, 33.33)."""
        self.assertEqual(
            split_amount(Decimal("100.00"), 3),
            [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")],
        )

    def test_conflict_in_any_invoice_rolls_back_entire_creation(self):
        """Conflito em qualquer fatura desfaz toda a criação."""
        # Criar fatura de março paga
        inv_mar = s.ensure_invoice(self.user, self.card, date(2027, 3, 1))
        inv_mar.paid_on = date(2027, 3, 5)
        inv_mar.save()

        payload = {
            "description": "Notebook",
            "total_amount": "300.00",
            "installment_count": 3,
            "purchase_date": "2027-02-01",  # Parcelas em jan, fev, mar. Março está paga!
            "category": self.category.id,
            "card": self.card.id,
            "request_id": "req-conflict-rollback",
        }
        res = self.client.post("/api/v1/installment-purchases/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        # Nenhuma parcela criada
        self.assertEqual(m.InstallmentPurchase.objects.count(), 0)
        self.assertEqual(m.Transaction.objects.count(), 0)

    def test_idempotency_resend_preserves_saved_schedule(self):
        """Reenvio com mesmo request_id não cria nova compra nem recalcula cronograma após mudança de fechamento."""
        payload = {
            "description": "Sofá",
            "total_amount": "300.00",
            "installment_count": 3,
            "purchase_date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
            "request_id": "req-idempotent-1",
        }
        res1 = self.client.post("/api/v1/installment-purchases/", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Alterar fechamento do cartão
        self.card.closing_day = 1
        self.card.save()

        # Reenviar com mesmo request_id
        res2 = self.client.post("/api/v1/installment-purchases/", payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["schedule"], res2.data["schedule"])
        self.assertEqual(m.InstallmentPurchase.objects.count(), 1)

    def test_different_payload_same_request_id_conflicts(self):
        """Mesmo identificador com outros dados gera erro 409."""
        payload = {
            "description": "Sofá",
            "total_amount": "300.00",
            "installment_count": 3,
            "purchase_date": "2027-02-01",
            "category": self.category.id,
            "card": self.card.id,
            "request_id": "req-conflict-diff",
        }
        self.client.post("/api/v1/installment-purchases/", payload, format="json")
        conflict_res = self.client.post(
            "/api/v1/installment-purchases/",
            {**payload, "total_amount": "400.00"},
            format="json",
        )
        self.assertEqual(conflict_res.status_code, status.HTTP_409_CONFLICT)


class InvoiceDueAndLifecycleTests(TestCase):
    """Section 6: Due date, existing invoices, and historical liabilities."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("tester_invoices")
        self.account = m.Account.objects.create(user=self.user, name="Conta")
        self.category = m.Category.objects.create(user=self.user, name="Despesas")
        self.clock = patch("django.utils.timezone.localdate", return_value=date(2027, 2, 3))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_automatic_invoice_due_date_calculation(self):
        """Fatura de competência janeiro, fechamento 02/02 e vencimento dia 11:

        vencimento automático deve ser 11/02, não 11/01.
        """
        card = m.Card.objects.create(
            user=self.user,
            name="Cartão Due",
            account=self.account,
            closing_day=2,
            due_day=11,
        )
        invoice = s.ensure_invoice(self.user, card, date(2027, 1, 1))
        self.assertEqual(
            invoice.due_date,
            date(2027, 2, 11),
            f"Vencimento para competência janeiro deveria ser 11/02/2027, obteve {invoice.due_date}",
        )

    def test_due_date_strictly_after_closing(self):
        """Se vencimento for dia 1 e fechamento for dia 2 (02/02), o vencimento após fechamento é 01/03.

        Se vencimento e fechamento coincidirem (dia 2), vencimento deve ser 02/03.
        """
        # Caso 1: due_day=1, closing_day=2
        card1 = m.Card.objects.create(
            user=self.user,
            name="Cartão Vence 1",
            account=self.account,
            closing_day=2,
            due_day=1,
        )
        inv1 = s.ensure_invoice(self.user, card1, date(2027, 1, 1))
        self.assertEqual(inv1.due_date, date(2027, 3, 1))

        # Caso 2: due_day=2, closing_day=2 (coincidem)
        card2 = m.Card.objects.create(
            user=self.user,
            name="Cartão Vence Coincidente",
            account=self.account,
            closing_day=2,
            due_day=2,
        )
        inv2 = s.ensure_invoice(self.user, card2, date(2027, 1, 1))
        self.assertEqual(inv2.due_date, date(2027, 3, 2))

    def test_day_clamping_for_short_months(self):
        """Ajustar dias inexistentes ao último dia do respectivo mês (ex: dia 31 em fevereiro)."""
        card = m.Card.objects.create(
            user=self.user,
            name="Cartão Dia 31",
            account=self.account,
            closing_day=31,
            due_day=31,
        )
        # Competência janeiro/2027: fechamento no mês seguinte é clamped para 28/02.
        # Vencimento dia 31 deve ser estritamente posterior -> vai para março -> 31/03/2027.
        inv = s.ensure_invoice(self.user, card, date(2027, 1, 1))
        self.assertEqual(inv.due_date, date(2027, 3, 31))

    def test_existing_invoice_conserves_due_date_and_manual_total(self):
        """Fatura existente conserva vencimento informado, total manual e pagamento."""
        card = m.Card.objects.create(
            user=self.user,
            name="Cartão Preservar",
            account=self.account,
            closing_day=2,
            due_day=11,
        )
        inv = m.Invoice.objects.create(
            user=self.user,
            card=card,
            month=date(2027, 1, 1),
            due_date=date(2027, 2, 20),
            manual_amount=Decimal("500.00"),
            paid_on=date(2027, 2, 21),
        )
        # Re-ensure invoice deve devolver a mesma instância intacta
        ensured = s.ensure_invoice(self.user, card, date(2027, 1, 1))
        self.assertEqual(ensured.pk, inv.pk)
        self.assertEqual(ensured.due_date, date(2027, 2, 20))
        self.assertEqual(ensured.manual_amount, Decimal("500.00"))
        self.assertEqual(ensured.paid_on, date(2027, 2, 21))

    def test_changing_closing_day_does_not_move_past_transactions(self):
        """Alterar closing_day não move transações antigas nem recalcula parcelas já criadas."""
        card = m.Card.objects.create(
            user=self.user,
            name="Cartão Dinâmico",
            account=self.account,
            closing_day=2,
            due_day=11,
        )
        tx = m.Transaction.objects.create(
            user=self.user,
            description="Antiga",
            amount=Decimal("100.00"),
            kind="expense",
            date=date(2027, 2, 1),
            month=date(2027, 1, 1),
            category=self.category,
            card=card,
            invoice=s.ensure_invoice(self.user, card, date(2027, 1, 1)),
        )

        card.closing_day = 1
        card.save()

        tx.refresh_from_db()
        self.assertEqual(tx.month, date(2027, 1, 1))
