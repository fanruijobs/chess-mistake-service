from django.db import migrations, models


def clear_role_ui_mode(apps, schema_editor):
    PlayerProfile = apps.get_model("mistakes", "PlayerProfile")
    PlayerProfile.objects.exclude(role="").update(role="")
    PlayerProfile.objects.exclude(ui_mode="").update(ui_mode="")


class Migration(migrations.Migration):
    dependencies = [("mistakes", "0004_turning_point_archive_fields")]

    operations = [
        migrations.AlterField(
            model_name="playerprofile",
            name="role",
            field=models.CharField(blank=True, choices=[("self", "Self"), ("daughter", "Daughter"), ("other", "Other")], default="", max_length=20),
        ),
        migrations.AlterField(
            model_name="playerprofile",
            name="ui_mode",
            field=models.CharField(blank=True, choices=[("adult", "Adult"), ("kid", "Kid")], default="", max_length=20),
        ),
        migrations.RunPython(clear_role_ui_mode, migrations.RunPython.noop),
    ]
