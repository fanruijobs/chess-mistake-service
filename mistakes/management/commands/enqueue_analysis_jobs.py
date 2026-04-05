from django.core.management.base import BaseCommand, CommandError

from mistakes.models import PlayerProfile
from mistakes.services import enqueue_analysis_jobs


class Command(BaseCommand):
    help = "Queue async analysis jobs grouped by player and year/month."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Limit queueing to one Chess.com username.")
        parser.add_argument("--reanalyze", action="store_true", help="Queue reanalysis jobs even for games with turning points.")

    def handle(self, *args, **options):
        player = None
        if options["username"]:
            try:
                player = PlayerProfile.objects.get(chesscom_username=options["username"].lower())
            except PlayerProfile.DoesNotExist as exc:
                raise CommandError("Player profile not found.") from exc

        summary = enqueue_analysis_jobs(player=player, reanalyze=options["reanalyze"])
        self.stdout.write(
            self.style.SUCCESS(
                f"queued_jobs={summary.created} skipped_existing_jobs={summary.skipped}"
            )
        )
