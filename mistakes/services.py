from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Iterable, Optional
import logging
import math
import os
import re
import shutil
import subprocess

import chess
import chess.engine
import chess.pgn
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

from .models import AnalysisJob, Game, PlayerProfile, TurningPoint


CHESSCOM_ARCHIVE_URL = "https://api.chess.com/pub/player/{username}/games/{year}/{month:02d}"
CHESSCOM_ARCHIVE_PGN_URL = "https://api.chess.com/pub/player/{username}/games/{year}/{month:02d}/pgn"
logger = logging.getLogger("mistakes.sync")


class ChessSyncError(Exception):
    pass


class EngineConfigurationError(Exception):
    pass


@dataclass
class SyncSummary:
    fetched: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: list[str] | None = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class AnalysisResult:
    turning_points: list[TurningPoint]
    reason: str


@dataclass
class EnqueueSummary:
    created: int = 0
    skipped: int = 0


@dataclass
class JobRunResult:
    analyzed: int
    created: int


def month_range_backwards(months: int) -> Iterable[tuple[int, int]]:
    today = timezone.now().date().replace(day=1)
    year = today.year
    month = today.month
    for offset in range(months):
        adjusted_month = month - offset
        adjusted_year = year
        while adjusted_month <= 0:
            adjusted_month += 12
            adjusted_year -= 1
        yield adjusted_year, adjusted_month


def games_to_queue_for_analysis(player: Optional[PlayerProfile] = None, reanalyze: bool = False, queryset=None):
    queryset = queryset if queryset is not None else games_for_analysis(player=player)
    if not reanalyze:
        queryset = queryset.filter(turning_points__isnull=True)
    return queryset.select_related("player_profile").order_by("player_profile__chesscom_username", "played_at", "id")


def enqueue_analysis_jobs(
    player: Optional[PlayerProfile] = None,
    reanalyze: bool = False,
    queryset=None,
) -> EnqueueSummary:
    summary = EnqueueSummary()
    for game in games_to_queue_for_analysis(player=player, reanalyze=reanalyze, queryset=queryset):
        exists = AnalysisJob.objects.filter(game=game, reanalyze=reanalyze).exclude(status=AnalysisJob.STATUS_FAILED).exists()
        if exists:
            summary.skipped += 1
            continue
        AnalysisJob.objects.create(
            player_profile=game.player_profile,
            game=game,
            reanalyze=reanalyze,
        )
        summary.created += 1
    return summary


def claim_next_analysis_job(worker_name: Optional[str] = None) -> Optional[AnalysisJob]:
    worker_name = worker_name or os.getenv("COMPUTERNAME") or os.getenv("HOSTNAME") or "worker"
    while True:
        candidate = AnalysisJob.objects.select_related("player_profile", "game").filter(status=AnalysisJob.STATUS_PENDING).order_by(
            "requested_at", "player_profile__chesscom_username", "archive_year", "archive_month", "game_id"
        ).first()
        if candidate is None:
            return None
        now = timezone.now()
        with transaction.atomic():
            updated = AnalysisJob.objects.filter(pk=candidate.pk, status=AnalysisJob.STATUS_PENDING).update(
                status=AnalysisJob.STATUS_RUNNING,
                started_at=now,
                claimed_by=worker_name,
                last_error="",
            )
        if updated:
            candidate.refresh_from_db()
            return candidate


def games_for_job(job: AnalysisJob):
    queryset = Game.objects.filter(pk=job.game_id).select_related("player_profile")
    if not job.reanalyze:
        queryset = queryset.filter(turning_points__isnull=True)
    return queryset


def process_analysis_job(job: AnalysisJob, analyzer: StockfishAnalyzer) -> JobRunResult:
    queryset = games_for_job(job)
    targeted = queryset.count()
    analyzed = 0
    created = 0

    try:
        for game in queryset:
            analyzed += 1
            if job.reanalyze:
                game.turning_points.all().delete()
            result = analyzer.analyze_game(game)
            created += len(result.turning_points)
    except Exception as exc:
        job.status = AnalysisJob.STATUS_FAILED
        job.finished_at = timezone.now()
        job.last_error = str(exc)
        job.games_targeted = targeted
        job.games_analyzed = analyzed
        job.turning_points_created = created
        job.save(
            update_fields=[
                "status",
                "finished_at",
                "last_error",
                "games_targeted",
                "games_analyzed",
                "turning_points_created",
            ]
        )
        raise

    job.status = AnalysisJob.STATUS_COMPLETED
    job.finished_at = timezone.now()
    job.games_targeted = targeted
    job.games_analyzed = analyzed
    job.turning_points_created = created
    job.save(
        update_fields=[
            "status",
            "finished_at",
            "games_targeted",
            "games_analyzed",
            "turning_points_created",
        ]
    )
    return JobRunResult(analyzed=analyzed, created=created)


def parse_played_at(value: str):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    parsed = parse_datetime(value)
    if parsed is None:
        raise ChessSyncError(f"Could not parse game timestamp: {value}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return parsed


def extract_external_id(game_payload: dict) -> str:
    url = game_payload.get("url", "").rstrip("/")
    if url:
        match = re.search(r"/game/(?:live|daily|computer|analysis)/(?P<game_id>\d+)", url)
        if match:
            return match.group("game_id")
        return url.split("/")[-1]
    return f"{game_payload.get('uuid') or game_payload.get('end_time')}-{game_payload.get('time_control', 'na')}"


def normalize_result(owner_color: str, payload: dict) -> str:
    owner_key = "white" if owner_color == Game.COLOR_WHITE else "black"
    opponent_key = "black" if owner_key == "white" else "white"
    owner_result = payload.get(owner_key, {}).get("result", "")
    opponent_result = payload.get(opponent_key, {}).get("result", "")

    if owner_result == "win":
        return Game.RESULT_WIN
    if opponent_result == "win":
        return Game.RESULT_LOSS
    if owner_result in {"checkmated", "timeout", "resigned", "lose", "abandoned"}:
        return Game.RESULT_LOSS
    if opponent_result in {"checkmated", "timeout", "resigned", "lose", "abandoned"}:
        return Game.RESULT_WIN
    if owner_result in {"agreed", "stalemate", "repetition", "timevsinsufficient", "insufficient", "50move"}:
        return Game.RESULT_DRAW
    return Game.RESULT_UNKNOWN


class ChessComSyncService:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.CHESSCOM_USER_AGENT,
                "Accept": "application/x-chess-pgn, text/plain;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.chess.com/",
            }
        )

    def sync_player(self, player: PlayerProfile, months: Optional[int] = None) -> SyncSummary:
        summary = SyncSummary()
        months = months or settings.SYNC_MONTH_LOOKBACK

        for year, month in month_range_backwards(months):
            archive_pgn_url = CHESSCOM_ARCHIVE_PGN_URL.format(
                username=player.chesscom_username,
                year=year,
                month=month,
            )
            response = self._request(archive_pgn_url, summary, context=f"{year}-{month:02d}", player=player)
            if response is None:
                continue
            for payload in self._parse_month_pgn(response.text):
                summary.fetched += 1
                if payload.get("time_class") != "rapid":
                    summary.skipped += 1
                    continue
                if self._upsert_game_from_pgn(player, payload):
                    summary.created += 1
                else:
                    summary.skipped += 1
        return summary

    def _request(self, url: str, summary: SyncSummary, context: str, player: PlayerProfile):
        logger.info("Requesting Chess.com PGN url=%s player=%s context=%s", url, player.chesscom_username, context)
        try:
            response = self.session.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.warning(
                "Chess.com request failed url=%s player=%s context=%s error=%s",
                url,
                player.chesscom_username,
                context,
                exc,
            )
            return self._curl_request(url, summary, context, player, reason=f"requests exception: {exc}")

        if response.status_code == 404:
            logger.info(
                "Chess.com returned 404 url=%s player=%s context=%s",
                url,
                player.chesscom_username,
                context,
            )
            return None
        if response.status_code in {401, 403, 410, 429}:
            logger.warning(
                "Chess.com returned status=%s url=%s player=%s context=%s",
                response.status_code,
                url,
                player.chesscom_username,
                context,
            )
            return self._curl_request(
                url,
                summary,
                context,
                player,
                reason=f"requests status {response.status_code}",
                initial_status=response.status_code,
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            logger.warning(
                "Chess.com HTTP error url=%s player=%s context=%s error=%s",
                url,
                player.chesscom_username,
                context,
                exc,
            )
            return self._curl_request(url, summary, context, player, reason=f"http error: {exc}")
        logger.info(
            "Chess.com response ok status=%s url=%s player=%s context=%s content_type=%s",
            response.status_code,
            url,
            player.chesscom_username,
            context,
            response.headers.get("Content-Type", ""),
        )
        return response

    def _curl_request(
        self,
        url: str,
        summary: SyncSummary,
        context: str,
        player: PlayerProfile,
        reason: str,
        initial_status: Optional[int] = None,
    ):
        curl_path = shutil.which("curl")
        if not curl_path:
            summary.failed += 1
            if initial_status is not None:
                summary.warnings.append(f"{context}: Chess.com returned {initial_status} for {player.chesscom_username}")
            else:
                summary.warnings.append(f"{context}: request failed ({reason})")
            logger.warning("curl fallback unavailable url=%s player=%s context=%s", url, player.chesscom_username, context)
            return None

        logger.info(
            "Falling back to curl url=%s player=%s context=%s reason=%s curl=%s",
            url,
            player.chesscom_username,
            context,
            reason,
            curl_path,
        )
        command = [
            curl_path,
            "-L",
            "--silent",
            "--show-error",
            "--fail",
            "-A",
            settings.CHESSCOM_USER_AGENT,
            url,
        ]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            summary.failed += 1
            summary.warnings.append(f"{context}: curl fallback failed ({completed.stderr.strip() or completed.returncode})")
            logger.warning(
                "curl fallback failed url=%s player=%s context=%s returncode=%s stderr=%s",
                url,
                player.chesscom_username,
                context,
                completed.returncode,
                completed.stderr.strip(),
            )
            return None

        logger.info(
            "curl fallback succeeded url=%s player=%s context=%s bytes=%s",
            url,
            player.chesscom_username,
            context,
            len(completed.stdout),
        )
        return _CurlResponse(text=completed.stdout)

    def _parse_month_pgn(self, pgn_text: str) -> list[dict]:
        games: list[dict] = []
        handle = StringIO(pgn_text)
        while True:
            game = chess.pgn.read_game(handle)
            if game is None:
                break
            headers = game.headers
            game_url = headers.get("Link") or headers.get("Site", "")
            games.append(
                {
                    "external_game_id": extract_external_id({"url": game_url}),
                    "url": game_url,
                    "played_at": self._played_at_from_headers(headers),
                    "white_username": headers.get("White", "").lower(),
                    "black_username": headers.get("Black", "").lower(),
                    "white_rating": parse_rating(headers.get("WhiteElo")),
                    "black_rating": parse_rating(headers.get("BlackElo")),
                    "result": headers.get("Result", ""),
                    "time_class": self._time_class_from_headers(headers),
                    "pgn": str(game),
                }
            )
        return games

    def _played_at_from_headers(self, headers: chess.pgn.Headers):
        utc_date = headers.get("UTCDate")
        utc_time = headers.get("UTCTime")
        if utc_date and utc_time and utc_date != "????.??.??" and utc_time != "??:??:??":
            return parse_played_at(f"{utc_date.replace('.', '-')}T{utc_time}Z")
        date_value = headers.get("Date", "")
        if date_value and date_value != "????.??.??":
            return parse_played_at(f"{date_value.replace('.', '-')}T00:00:00Z")
        raise ChessSyncError("PGN missing playable date headers.")

    def _time_class_from_headers(self, headers: chess.pgn.Headers) -> str:
        time_control = headers.get("TimeControl", "")
        if not time_control or time_control in {"-", "?"}:
            return ""
        match = re.match(r"(?P<base>\d+)(?:\+(?P<increment>\d+))?$", time_control)
        if not match:
            return ""
        base_seconds = int(match.group("base"))
        if base_seconds < 180:
            return "bullet"
        if base_seconds < 600:
            return "blitz"
        if base_seconds < 3600:
            return "rapid"
        return "daily"

    def _upsert_game_from_pgn(self, player: PlayerProfile, payload: dict) -> bool:
        white_username = payload.get("white_username", "").lower()
        black_username = payload.get("black_username", "").lower()
        if player.chesscom_username == white_username:
            owner_color = Game.COLOR_WHITE
            opponent_username = black_username
        elif player.chesscom_username == black_username:
            owner_color = Game.COLOR_BLACK
            opponent_username = white_username
        else:
            return False

        opponent_profile = None
        if opponent_username:
            opponent_profile, _created = PlayerProfile.objects.get_or_create(
                chesscom_username=opponent_username,
                defaults={
                    "name": opponent_username,
                    "slug": slugify(opponent_username),
                    "role": PlayerProfile.ROLE_OTHERS,
                    "is_active": False,
                },
            )

        _, created = Game.objects.update_or_create(
            player_profile=player,
            external_game_id=payload["external_game_id"],
            defaults={
                "opponent_profile": opponent_profile,
                "url": payload.get("url", ""),
                "played_at": payload["played_at"],
                "white_username": white_username,
                "black_username": black_username,
                "white_rating": payload.get("white_rating"),
                "black_rating": payload.get("black_rating"),
                "owner_color": owner_color,
                "result": self._normalize_pgn_result(owner_color, payload.get("result", "")),
                "time_class": payload.get("time_class", ""),
                "pgn": payload.get("pgn", ""),
            },
        )
        return created

    def _normalize_pgn_result(self, owner_color: str, result_value: str) -> str:
        if result_value == "1/2-1/2":
            return Game.RESULT_DRAW
        if result_value == "1-0":
            return Game.RESULT_WIN if owner_color == Game.COLOR_WHITE else Game.RESULT_LOSS
        if result_value == "0-1":
            return Game.RESULT_WIN if owner_color == Game.COLOR_BLACK else Game.RESULT_LOSS
        return Game.RESULT_UNKNOWN


def score_to_pawns(score: chess.engine.PovScore, color: bool) -> float:
    pov = score.white() if color == chess.WHITE else score.black()
    if pov.is_mate():
        mate_score = pov.mate()
        if mate_score is None:
            return 0.0
        sign = 1 if mate_score > 0 else -1
        return sign * (100.0 - min(abs(mate_score), 99))
    cp = pov.score()
    return 0.0 if cp is None else cp / 100.0


def classify_drop(drop_pawns: float) -> str:
    if drop_pawns >= 4:
        return TurningPoint.LABEL_BLUNDER
    if drop_pawns >= 2.5:
        return TurningPoint.LABEL_MISTAKE
    return TurningPoint.LABEL_MISS


def explain_turning_point(move_number: int, played_move: str, best_move: str, drop_pawns: float) -> str:
    return (
        f"Move {move_number} was the first major collapse. "
        f"You played {played_move}, but the engine preferred {best_move}. "
        f"The position dropped by about {drop_pawns:.1f} pawns."
    )


def parse_rating(value: str) -> Optional[int]:
    if not value:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def move_to_san(board: chess.Board, move: chess.Move) -> str:
    try:
        return board.san(move)
    except ValueError:
        return move.uci()


class StockfishAnalyzer:
    def __init__(self, stockfish_path: Optional[str] = None, depth: Optional[int] = None):
        self.stockfish_path = stockfish_path or settings.STOCKFISH_PATH
        self.depth = depth or settings.CHESS_ANALYSIS_DEPTH
        if not self.stockfish_path:
            raise EngineConfigurationError("STOCKFISH_PATH is not configured.")
        if not Path(self.stockfish_path).exists():
            raise EngineConfigurationError(f"Stockfish binary does not exist: {self.stockfish_path}")

    def verify_engine(self) -> None:
        with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
            engine.configure({})

    def analyze_game(self, game: Game) -> AnalysisResult:
        parsed_game = chess.pgn.read_game(StringIO(game.pgn))
        if parsed_game is None:
            return AnalysisResult([], "invalid_pgn")

        board = parsed_game.board()
        owner_color = chess.WHITE if game.owner_color == Game.COLOR_WHITE else chess.BLACK
        if game.result == Game.RESULT_LOSS:
            target_turn = owner_color
        elif game.result == Game.RESULT_WIN:
            target_turn = chess.BLACK if owner_color == chess.WHITE else chess.WHITE
        else:
            return AnalysisResult([], "unsupported_result")
        moves = list(parsed_game.mainline_moves())
        threshold = settings.TURNING_POINT_THRESHOLD
        created_turning_points: list[TurningPoint] = []

        with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
            for index, move in enumerate(moves):
                if len(created_turning_points) >= 3:
                    break
                if board.turn != target_turn:
                    board.push(move)
                    continue

                before_fen = board.fen()
                before_info = engine.analyse(board, chess.engine.Limit(depth=self.depth))
                pv = before_info.get("pv") or []
                if not pv:
                    board.push(move)
                    continue
                best_move = pv[0]
                played_move_san = move_to_san(board, move)
                best_move_san = move_to_san(board, best_move)
                eval_before = score_to_pawns(before_info["score"], target_turn)

                board.push(move)
                after_info = engine.analyse(board, chess.engine.Limit(depth=self.depth))
                eval_after = score_to_pawns(after_info["score"], target_turn)
                drop_pawns = eval_before - eval_after

                if drop_pawns >= threshold:
                    move_number = math.ceil((index + 1) / 2)
                    turning_point = TurningPoint.objects.create(
                        player_profile=game.player_profile,
                        game=game,
                        turning_index=len(created_turning_points) + 1,
                        move_number=move_number,
                        fen=before_fen,
                        played_move=played_move_san,
                        best_move=best_move_san,
                        eval_before=round(eval_before, 2),
                        eval_after=round(eval_after, 2),
                        drop_cp=int(round(drop_pawns * 100)),
                        label=classify_drop(drop_pawns),
                        explanation=explain_turning_point(move_number, played_move_san, best_move_san, drop_pawns),
                    )
                    created_turning_points.append(turning_point)

        if created_turning_points:
            return AnalysisResult(created_turning_points, f"created_{len(created_turning_points)}")
        return AnalysisResult([], "no_turning_point")


def games_for_analysis(player: Optional[PlayerProfile] = None):
    queryset = Game.objects.filter(result__in=[Game.RESULT_LOSS, Game.RESULT_WIN]).select_related("player_profile")
    if player is not None:
        queryset = queryset.filter(player_profile=player)
    return queryset


@dataclass
class _CurlResponse:
    text: str
