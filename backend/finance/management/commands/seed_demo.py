from datetime import date
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from finance import models as m, services as s

class Command(BaseCommand):
    help = 'Insere dados fictícios em um usuário vazio. Nunca sobrescreve dados existentes.'
    def add_arguments(self, parser):
        parser.add_argument('--username', default='local')
    @transaction.atomic
    def handle(self, *args, **options):
        user, _ = get_user_model().objects.get_or_create(username=options['username'])
        if any(model.objects.filter(user=user).exists() for model in [m.Account, m.Goal, m.Transaction, m.Subscription, m.Bill]):
            raise CommandError('Este usuário já possui dados. Use um banco vazio para a demonstração.')
        month = s.month_start(timezone.localdate())
        categories = {n: m.Category.objects.get_or_create(user=user, name=n)[0] for n in ['Alimentação', 'Moradia', 'Transporte', 'Saúde', 'Educação', 'Lazer', 'Assinaturas', 'Salário', 'Outros']}
        accounts = [m.Account.objects.create(user=user, name=n, institution=n, account_type=t) for n, t in [('Nubank', 'checking'), ('Inter', 'checking'), ('Reserva de emergência', 'investment')]]
        for a, amount in zip(accounts, [4250, 3150, 8000]):
            for offset in range(5, -1, -1):
                index = month.year * 12 + month.month - 1 - offset
                m.Balance.objects.create(account=a, month=date(index//12,index%12+1,1), amount=max(0, amount - offset * 300))
        card = m.Card.objects.create(user=user, name='Nubank Platinum', account=accounts[0], closing_day=8, due_day=18)
        m.Card.objects.create(user=user, name='Inter Mastercard', account=accounts[1], closing_day=12, due_day=25)
        invoice = s.ensure_invoice(user, card, month)
        for desc, amount, category, day in [('Supermercado', '485.90', 'Alimentação', 4), ('Restaurante', '126.50', 'Alimentação', 8), ('Combustível', '220.00', 'Transporte', 10), ('Livraria', '89.90', 'Educação', 12), ('Cinema', '68.00', 'Lazer', 13)]:
            m.Transaction.objects.create(user=user, description=desc, amount=Decimal(amount), kind='expense', date=s.due(month,day), month=month, category=categories[category], card=card, invoice=invoice)
        m.Transaction.objects.create(user=user, description='Salário', amount=6500, kind='income', date=s.due(month,5), month=month, category=categories['Salário'], account=accounts[0])
        m.Bill.objects.create(user=user, description='Aluguel', amount=1450, account=accounts[0], category=categories['Moradia'], month=month, due_date=s.due(month,10), paid_on=s.due(month,10) if timezone.localdate().day >= 10 else None)
        m.Bill.objects.create(user=user, description='Internet', amount=119.90, account=accounts[1], category=categories['Moradia'], month=month, due_date=s.due(month,20))
        for name, amount in [('Spotify', '21.90'), ('Netflix', '44.90')]:
            m.Subscription.objects.create(user=user, name=name, amount=Decimal(amount), account=accounts[1], category=categories['Assinaturas'], billing_day=10, start_date=month)
        s.materialize(user)
        for name, target, saved, months, term in [('Uma viagem especial', 8000, 3200, 9, 'medium'), ('Meu próximo notebook', 6000, 2400, 6, 'short'), ('Reserva de segurança', 18000, 8000, 18, 'long')]:
            index = month.year * 12 + month.month - 1 + months
            goal = m.Goal.objects.create(user=user, name=name, target_amount=target, start_date=month, target_date=date(index//12,index%12+1,1), term_type=term)
            s.goal_state(goal, month)
            m.Contribution.objects.create(user=user, goal=goal, amount=saved, date=month)
        self.stdout.write(self.style.SUCCESS('Demonstração criada. Todos os valores são fictícios.'))
