from django.db import migrations


def seed_default_admin(apps, schema_editor):
    User = apps.get_model("auth", "User")
    username = "admin"
    password = "adminadmin"

    admin = User.objects.filter(username=username).first()
    if admin is None:
        User.objects.create_superuser(
            username=username,
            email="",
            password=password,
        )
        return

    updated = False
    if not admin.is_staff:
        admin.is_staff = True
        updated = True
    if not admin.is_superuser:
        admin.is_superuser = True
        updated = True
    if not admin.check_password(password):
        admin.set_password(password)
        updated = True
    if updated:
        admin.save()


def remove_default_admin(apps, schema_editor):
    User = apps.get_model("auth", "User")
    User.objects.filter(username="admin", email="").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("mistakes", "0011_game_opponent_and_ratings"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_default_admin, remove_default_admin),
    ]
