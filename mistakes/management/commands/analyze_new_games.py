from django.core.management.base import BaseCommand, CommandError

from mistakes.models import PlayerProfile
from mistakes.services import EngineConfigurationError, StockfishAnalyzer, games_for_analysis


class Command(BaseCommand):
    help = "Analyze lost games and extract one turning point per game."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Limit analysis to one Chess.com username.")
        parser.add_argument("--limit", type=int, help="Limit the number of games to analyze.")
        parser.add_argument("--stockfish-path", help="Override the configured Stockfish path.")
        parser.add_argument("--depth", type=int, help="Override engine depth.")
        parser.add_argument("--reanalyze", action="store_true", help="Reanalyze games with an existing turning point.")

    def handle(self, *args, **options):
        player = None
        if options["username"]:
            try:
                player = PlayerProfile.objects.get(chesscom_username=options["username"].lower())
            except PlayerProfile.DoesNotExist as exc:
                raise CommandError("Player profile not found.") from exc

        queryset = games_for_analysis(player=player)
        if not options["reanalyze"]:
            queryset = queryset.filter(turning_points__isnull=True)
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        try:
            analyzer = StockfishAnalyzer(
                stockfish_path=options.get("stockfish_path"),
                depth=options.get("depth"),
            )
            analyzer.verify_engine()
        except EngineConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        analyzed = 0
        created = 0
        for game in queryset:
            analyzed += 1
            if options["reanalyze"]:
                game.turning_points.all().delete()
            result = analyzer.analyze_game(game)
            created += len(result.turning_points)
            self.stdout.write(f"{game.id}: {result.reason}")

        self.stdout.write(self.style.SUCCESS(f"analyzed={analyzed} turning_points_created_or_updated={created}"))
