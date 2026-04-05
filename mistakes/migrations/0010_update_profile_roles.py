from django.db import migrations, models


def assign_new_roles(apps, schema_editor):
    PlayerProfile = apps.get_model("mistakes", "PlayerProfile")
    family_usernames = {"fanrui89", "fanguoguo123"}

    PlayerProfile.objects.filter(chesscom_username__in=family_usernames).update(role="family")
    PlayerProfile.objects.exclude(chesscom_username__in=family_usernames).update(role="others")


class Migration(migrations.Migration):

    dependencies = [
        ("mistakes", "0009_alter_turningpoint_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="playerprofile",
            name="role",
            field=models.CharField(
                choices=[("family", "Family"), ("friend", "Friend"), ("others", "Others")],
                default="others",
                max_length=20,
            ),
        ),
        migrations.RunPython(assign_new_roles, migrations.RunPython.noop),
    ]
