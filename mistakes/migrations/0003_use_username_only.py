from django.db import migrations


def use_username_only(apps, schema_editor):
    PlayerProfile = apps.get_model("mistakes", "PlayerProfile")
    for profile in PlayerProfile.objects.all():
        username = (profile.chesscom_username or "").lower()
        if not username:
            continue
        profile.chesscom_username = username
        profile.name = username
        if not profile.slug:
            profile.slug = username
        profile.save(update_fields=["chesscom_username", "name", "slug"])


class Migration(migrations.Migration):
    dependencies = [("mistakes", "0002_seed_default_players")]

    operations = [migrations.RunPython(use_username_only, migrations.RunPython.noop)]
