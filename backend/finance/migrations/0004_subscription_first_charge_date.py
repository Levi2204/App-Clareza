from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('finance', '0003_installment_purchase')]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='first_charge_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
