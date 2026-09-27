import decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kiln", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="HearthTempSample",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("seqNo", models.PositiveIntegerField(verbose_name="采样序号")),
                (
                    "tempC",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=6,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal("0.01")
                            )
                        ],
                        verbose_name="灶温摄氏",
                    ),
                ),
                ("sampledAt", models.DateTimeField(verbose_name="采样时刻")),
                (
                    "recorderName",
                    models.CharField(max_length=80, verbose_name="记录人"),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="temp_samples",
                        to="kiln.cookrun",
                        verbose_name="所属值守",
                    ),
                ),
            ],
            options={
                "verbose_name": "灶温采样",
                "verbose_name_plural": "灶温采样",
                "ordering": ["seqNo"],
            },
        ),
        migrations.AddConstraint(
            model_name="hearthtempsample",
            constraint=models.UniqueConstraint(
                fields=("run", "seqNo"),
                name="uniq_temp_sample_seq_per_run",
            ),
        ),
    ]
