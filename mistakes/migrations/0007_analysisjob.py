from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("mistakes", "0006_turning_point_slots"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnalysisJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("archive_year", models.PositiveSmallIntegerField()),
                ("archive_month", models.PositiveSmallIntegerField()),
                ("reanalyze", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("claimed_by", models.CharField(blank=True, max_length=255)),
                ("last_error", models.TextField(blank=True)),
                ("games_targeted", models.PositiveIntegerField(default=0)),
                ("games_analyzed", models.PositiveIntegerField(default=0)),
                ("turning_points_created", models.PositiveIntegerField(default=0)),
                (
                    "player_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analysis_jobs",
                        to="mistakes.playerprofile",
                    ),
                ),
            ],
            options={
                "ordering": [
                    "status",
                    "-archive_year",
                    "-archive_month",
                    "player_profile__chesscom_username",
                    "-requested_at",
                ],
            },
        ),
    ]
