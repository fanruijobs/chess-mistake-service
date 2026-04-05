from django.db import migrations, models


def backfill_turning_point_archive_fields(apps, schema_editor):
    TurningPoint = apps.get_model("mistakes", "TurningPoint")
    for turning_point in TurningPoint.objects.select_related("game").all():
        if turning_point.game and turning_point.game.played_at:
            turning_point.archive_year = turning_point.game.played_at.year
            turning_point.archive_month = turning_point.game.played_at.month
            turning_point.save(update_fields=["archive_year", "archive_month"])


class Migration(migrations.Migration):
    dependencies = [("mistakes", "0003_use_username_only")]

    operations = [
        migrations.AddField(
            model_name="turningpoint",
            name="archive_month",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="turningpoint",
            name="archive_year",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(backfill_turning_point_archive_fields, migrations.RunPython.noop),
    ]
