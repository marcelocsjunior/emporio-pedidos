import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("intelligence", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="airecommendation",
            name="event",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="recommendations",
                to="intelligence.aievent",
                verbose_name="evento",
            ),
        ),
    ]
