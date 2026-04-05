from django.db import migrations, models
import django.db.models.deletion


def backfill_opponent_profiles(apps, schema_editor):
    PlayerProfile = apps.get_model("mistakes", "PlayerProfile")
    Game = apps.get_model("mistakes", "Game")

    for game in Game.objects.select_related("player_profile").all():
        if game.player_profile.chesscom_username == game.white_username:
            opponent_username = game.black_username
        else:
            opponent_username = game.white_username
        if not opponent_username:
            continue
        opponent_profile, _created = PlayerProfile.objects.get_or_create(
            chesscom_username=opponent_username,
            defaults={
                "name": opponent_username,
                "slug": opponent_username,
                "role": "others",
                "is_active": False,
            },
        )
        game.opponent_profile_id = opponent_profile.id
        game.save(update_fields=["opponent_profile"])


class Migration(migrations.Migration):

    dependencies = [
        ("mistakes", "0010_update_profile_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="game",
            name="opponent_profile",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="opponent_games", to="mistakes.playerprofile"),
        ),
        migrations.AddField(
            model_name="game",
            name="white_rating",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="game",
            name="black_rating",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_opponent_profiles, migrations.RunPython.noop),
    ]
