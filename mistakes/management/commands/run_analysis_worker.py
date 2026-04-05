from django.core.management.base import BaseCommand, CommandError

from mistakes.services import (
    EngineConfigurationError,
    StockfishAnalyzer,
    claim_next_analysis_job,
    process_analysis_job,
)


class Command(BaseCommand):
    help = "Process queued async analysis jobs."

    def add_arguments(self, parser):
        parser.add_argument("--max-jobs", type=int, default=1, help="Maximum number of queued jobs to process in this worker run.")
        parser.add_argument("--stockfish-path", help="Override the configured Stockfish path.")
        parser.add_argument("--depth", type=int, help="Override engine depth.")
        parser.add_argument("--worker-name", help="Optional worker identifier for claimed jobs.")

    def handle(self, *args, **options):
        try:
            analyzer = StockfishAnalyzer(
                stockfish_path=options.get("stockfish_path"),
                depth=options.get("depth"),
            )
            analyzer.verify_engine()
        except EngineConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        processed_jobs = 0
        processed_games = 0
        created_turning_points = 0
        for _ in range(options["max_jobs"]):
            job = claim_next_analysis_job(worker_name=options.get("worker_name"))
            if job is None:
                break
            result = process_analysis_job(job, analyzer)
            processed_jobs += 1
            processed_games += result.analyzed
            created_turning_points += result.created
            self.stdout.write(
                f"job={job.id} player={job.player_profile.chesscom_username} "
                f"archive={job.archive_year}-{job.archive_month:02d} "
                f"games={result.analyzed} turning_points={result.created}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"processed_jobs={processed_jobs} analyzed_games={processed_games} turning_points_created={created_turning_points}"
            )
        )
