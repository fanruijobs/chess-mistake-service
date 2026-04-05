from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PlayerProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=140, unique=True)),
                ("chesscom_username", models.CharField(max_length=80, unique=True)),
                ("role", models.CharField(choices=[("self", "Self"), ("daughter", "Daughter"), ("other", "Other")], default="other", max_length=20)),
                ("ui_mode", models.CharField(choices=[("adult", "Adult"), ("kid", "Kid")], default="adult", max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Game",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_game_id", models.CharField(max_length=255)),
                ("url", models.URLField()),
                ("played_at", models.DateTimeField()),
                ("white_username", models.CharField(max_length=80)),
                ("black_username", models.CharField(max_length=80)),
                ("owner_color", models.CharField(choices=[("white", "White"), ("black", "Black")], max_length=5)),
                ("result", models.CharField(choices=[("win", "Win"), ("loss", "Loss"), ("draw", "Draw"), ("unknown", "Unknown")], default="unknown", max_length=10)),
                ("time_class", models.CharField(max_length=20)),
                ("pgn", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("player_profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="games", to="mistakes.playerprofile")),
            ],
            options={"ordering": ["-played_at"]},
        ),
        migrations.CreateModel(
            name="TurningPoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("move_number", models.PositiveIntegerField()),
                ("fen", models.TextField()),
                ("played_move", models.CharField(max_length=20)),
                ("best_move", models.CharField(max_length=20)),
                ("eval_before", models.FloatField()),
                ("eval_after", models.FloatField()),
                ("drop_cp", models.IntegerField()),
                ("label", models.CharField(choices=[("blunder", "Blunder"), ("mistake", "Mistake"), ("miss", "Missed Chance")], default="blunder", max_length=20)),
                ("explanation", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("game", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="turning_point", to="mistakes.game")),
                ("player_profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="turning_points", to="mistakes.playerprofile")),
            ],
            options={"ordering": ["-game__played_at"]},
        ),
        migrations.AddConstraint(
            model_name="game",
            constraint=models.UniqueConstraint(fields=("player_profile", "external_game_id"), name="unique_game_per_player_external_id"),
        ),
    ]
