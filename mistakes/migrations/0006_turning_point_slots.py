from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("mistakes", "0005_clear_role_ui_mode")]

    operations = [
        migrations.AlterField(
            model_name="turningpoint",
            name="game",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="turning_points", to="mistakes.game"),
        ),
        migrations.AddField(
            model_name="turningpoint",
            name="turning_index",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddConstraint(
            model_name="turningpoint",
            constraint=models.UniqueConstraint(fields=("game", "turning_index"), name="unique_turning_point_slot_per_game"),
        ),
    ]
