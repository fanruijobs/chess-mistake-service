from django.core.management.base import BaseCommand, CommandError

from mistakes.models import PlayerProfile
from mistakes.services import ChessComSyncService


class Command(BaseCommand):
    help = "Download monthly Chess.com PGNs and persist rapid games for configured players."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Limit sync to one Chess.com username.")
        parser.add_argument("--months", type=int, help="How many recent months to download. Default: 3.")
        parser.add_argument("--inactive", action="store_true", help="Include inactive players.")

    def handle(self, *args, **options):
        queryset = PlayerProfile.objects.all()
        if not options["inactive"]:
            queryset = queryset.filter(is_active=True)
        if options["username"]:
            queryset = queryset.filter(chesscom_username=options["username"].lower())

        players = list(queryset)
        if not players:
            raise CommandError("No matching player profiles found.")

        service = ChessComSyncService()
        for player in players:
            summary = service.sync_player(player, months=options.get("months"))
            self.stdout.write(
                self.style.SUCCESS(
                    f"{player.chesscom_username}: fetched={summary.fetched} created={summary.created} skipped={summary.skipped} failed={summary.failed}"
                )
            )
            for warning in summary.warnings:
                self.stdout.write(self.style.WARNING(f"{player.chesscom_username}: {warning}"))
