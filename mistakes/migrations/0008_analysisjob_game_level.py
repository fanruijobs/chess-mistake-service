from django.db import migrations, models
import django.db.models.deletion


def forwards_copy_jobs(apps, schema_editor):
    AnalysisJob = apps.get_model("mistakes", "AnalysisJob")
    Game = apps.get_model("mistakes", "Game")

    existing_jobs = list(AnalysisJob.objects.all().order_by("id"))
    for job in existing_jobs:
        matching_games = Game.objects.filter(
            player_profile_id=job.player_profile_id,
            played_at__year=job.archive_year,
            played_at__month=job.archive_month,
            result="loss",
        ).order_by("played_at", "id")
        for game in matching_games:
            AnalysisJob.objects.create(
                player_profile_id=job.player_profile_id,
                game_id=game.id,
                archive_year=job.archive_year,
                archive_month=job.archive_month,
                reanalyze=job.reanalyze,
                status=job.status,
                requested_at=job.requested_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                claimed_by=job.claimed_by,
                last_error=job.last_error,
                games_targeted=1 if job.games_targeted else 0,
                games_analyzed=1 if job.games_analyzed else 0,
                turning_points_created=job.turning_points_created,
            )
        job.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("mistakes", "0007_analysisjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysisjob",
            name="game",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="analysis_jobs", to="mistakes.game"),
        ),
        migrations.AlterField(
            model_name="analysisjob",
            name="archive_month",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="analysisjob",
            name="archive_year",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(forwards_copy_jobs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="analysisjob",
            constraint=models.UniqueConstraint(fields=("game", "reanalyze"), name="unique_analysis_job_per_game_and_mode"),
        ),
    ]
