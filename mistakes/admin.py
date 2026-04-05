from pathlib import Path
import logging
import subprocess
import sys

from django.contrib import admin, messages
from django.conf import settings

from .models import AnalysisJob, Game, PlayerProfile, TurningPoint
from .services import ChessComSyncService, enqueue_analysis_jobs

logger = logging.getLogger("mistakes.admin")


def launch_local_analysis_worker(max_jobs: int) -> subprocess.Popen:
    command = [
        sys.executable,
        str(Path(settings.BASE_DIR) / "manage.py"),
        "run_analysis_worker",
        "--max-jobs",
        str(max_jobs),
        "--worker-name",
        "admin-trigger",
    ]
    popen_kwargs = {
        "cwd": str(settings.BASE_DIR),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    logger.info(
        "Starting local analysis worker max_jobs=%s command=%s cwd=%s",
        max_jobs,
        command,
        settings.BASE_DIR,
    )
    process = subprocess.Popen(command, **popen_kwargs)
    logger.info(
        "Local analysis worker started pid=%s max_jobs=%s command=%s",
        process.pid,
        max_jobs,
        command,
    )
    return process


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    actions = (
        "download_archived_games_for_current_month",
        "download_archived_games_for_recent_months",
        "analyze_new_games_for_selected_players",
    )
    list_display = ("name", "chesscom_username", "is_active", "created_at")
    list_filter = ("role", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "chesscom_username")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "role__exact" in request.GET:
            return queryset
        return queryset.filter(role__in=[PlayerProfile.ROLE_FAMILY, PlayerProfile.ROLE_FRIEND])

    @admin.action(description="Download archived rapid games for current month")
    def download_archived_games_for_current_month(self, request, queryset):
        service = ChessComSyncService()
        total_fetched = 0
        total_created = 0
        total_skipped = 0
        total_failed = 0

        for player in queryset.order_by("chesscom_username"):
            summary = service.sync_player(player, months=1)
            total_fetched += summary.fetched
            total_created += summary.created
            total_skipped += summary.skipped
            total_failed += summary.failed

            self.message_user(
                request,
                (
                    f"{player.chesscom_username}: fetched={summary.fetched} "
                    f"created={summary.created} skipped={summary.skipped} failed={summary.failed}"
                ),
            )
            for warning in summary.warnings:
                self.message_user(request, f"{player.chesscom_username}: {warning}", level=messages.WARNING)

        self.message_user(
            request,
            (
                f"Selected players synced for current month: fetched={total_fetched} "
                f"created={total_created} skipped={total_skipped} failed={total_failed}"
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description="Download archived rapid games for current month and previous 3 months")
    def download_archived_games_for_recent_months(self, request, queryset):
        service = ChessComSyncService()
        total_fetched = 0
        total_created = 0
        total_skipped = 0
        total_failed = 0

        for player in queryset.order_by("chesscom_username"):
            summary = service.sync_player(player, months=4)
            total_fetched += summary.fetched
            total_created += summary.created
            total_skipped += summary.skipped
            total_failed += summary.failed

            self.message_user(
                request,
                (
                    f"{player.chesscom_username}: fetched={summary.fetched} "
                    f"created={summary.created} skipped={summary.skipped} failed={summary.failed}"
                ),
            )
            for warning in summary.warnings:
                self.message_user(request, f"{player.chesscom_username}: {warning}", level=messages.WARNING)

        self.message_user(
            request,
            (
                f"Selected players synced across 4 months: fetched={total_fetched} "
                f"created={total_created} skipped={total_skipped} failed={total_failed}"
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description="Analyze new lost games for selected players")
    def analyze_new_games_for_selected_players(self, request, queryset):
        total_created = 0
        for player in queryset.order_by("chesscom_username"):
            summary = enqueue_analysis_jobs(player=player, reanalyze=False)
            total_created += summary.created
            self.message_user(
                request,
                (
                    f"{player.chesscom_username}: queued_jobs={summary.created} "
                    f"skipped_existing_jobs={summary.skipped}"
                ),
            )

        worker_started = False
        if total_created:
            try:
                launch_local_analysis_worker(max_jobs=total_created)
                worker_started = True
            except OSError as exc:
                logger.warning("Failed to start local analysis worker error=%s", exc)
                self.message_user(request, f"Failed to start local analysis worker: {exc}", level=messages.WARNING)

        total_pending = AnalysisJob.objects.filter(status=AnalysisJob.STATUS_PENDING).count()
        self.message_user(
            request,
            (
                f"Selected players queued for async analysis. pending_jobs={total_pending} "
                f"worker_started={'yes' if worker_started else 'no'}"
            ),
            level=messages.SUCCESS,
        )


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    actions = ("analyze_selected_games",)
    list_display = ("player_profile", "played_at", "result", "time_class", "owner_color")
    list_filter = ("player_profile", "result", "time_class", "owner_color")
    search_fields = ("url", "external_game_id", "white_username", "black_username")

    @admin.action(description="Analyze selected games")
    def analyze_selected_games(self, request, queryset):
        summary = enqueue_analysis_jobs(queryset=queryset.select_related("player_profile"), reanalyze=False)
        worker_started = False
        if summary.created:
            try:
                launch_local_analysis_worker(max_jobs=summary.created)
                worker_started = True
            except OSError as exc:
                logger.warning("Failed to start local analysis worker error=%s", exc)
                self.message_user(request, f"Failed to start local analysis worker: {exc}", level=messages.WARNING)

        self.message_user(
            request,
            (
                f"Selected games queued for async analysis. queued_jobs={summary.created} "
                f"skipped_existing_jobs={summary.skipped} worker_started={'yes' if worker_started else 'no'}"
            ),
            level=messages.SUCCESS,
        )


@admin.register(TurningPoint)
class TurningPointAdmin(admin.ModelAdmin):
    list_display = ("player_profile", "game", "move_number", "label", "drop_cp", "created_at")
    list_filter = ("player_profile", "label",)
    search_fields = ("played_move", "best_move", "game__url")


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = (
        "player_profile",
        "game",
        "archive_year",
        "archive_month",
        "status",
        "reanalyze",
        "games_analyzed",
        "turning_points_created",
        "claimed_by",
        "requested_at",
    )
    list_filter = ("player_profile", "status", "reanalyze", "archive_year", "archive_month")
    search_fields = ("player_profile__chesscom_username", "claimed_by", "last_error")
