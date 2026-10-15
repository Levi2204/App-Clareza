from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('finance', '0004_subscription_first_charge_date')]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='cycle_closing_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='cycle_policy',
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
