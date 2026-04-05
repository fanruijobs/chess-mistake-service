from django.db import migrations


def seed_default_players(apps, schema_editor):
    PlayerProfile = apps.get_model("mistakes", "PlayerProfile")
    defaults = [
        {
            "name": "Fan Rui",
            "slug": "fanrui89",
            "chesscom_username": "fanrui89",
            "role": "self",
            "ui_mode": "adult",
            "is_active": True,
        },
        {
            "name": "Fan Guo Guo",
            "slug": "fanguoguo123",
            "chesscom_username": "fanguoguo123",
            "role": "daughter",
            "ui_mode": "kid",
            "is_active": True,
        },
    ]
    for item in defaults:
        PlayerProfile.objects.update_or_create(
            chesscom_username=item["chesscom_username"],
            defaults=item,
        )


def unseed_default_players(apps, schema_editor):
    PlayerProfile = apps.get_model("mistakes", "PlayerProfile")
    PlayerProfile.objects.filter(chesscom_username__in=["fanrui89", "fanguoguo123"]).delete()


class Migration(migrations.Migration):
    dependencies = [("mistakes", "0001_initial")]

    operations = [migrations.RunPython(seed_default_players, unseed_default_players)]
