from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0002_order_creation_key")]

    operations = [
        migrations.AddField(
            model_name="company",
            name="is_demo",
            field=models.BooleanField(
                default=False,
                help_text="Separa dados de apresentação dos dados reais nas análises.",
                verbose_name="dados de demonstração",
            ),
        ),
    ]
