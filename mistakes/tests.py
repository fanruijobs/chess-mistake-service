from io import StringIO
from unittest.mock import Mock, patch
import subprocess

import chess
import chess.engine
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.contrib.admin.sites import AdminSite
from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils import timezone

from .admin import AnalysisJobAdmin, GameAdmin, PlayerProfileAdmin, TurningPointAdmin, launch_local_analysis_worker
from .board_rendering import render_position_svg
from .models import AnalysisJob, Game, PlayerProfile, TurningPoint
from .services import (
    AnalysisResult,
    ChessComSyncService,
    EnqueueSummary,
    JobRunResult,
    StockfishAnalyzer,
    claim_next_analysis_job,
    classify_drop,
    games_to_queue_for_analysis,
    enqueue_analysis_jobs,
    extract_external_id,
    move_to_san,
    normalize_result,
    parse_played_at,
    process_analysis_job,
)
from .views import puzzle_export_lines


SAMPLE_PGN = """
[Event "Rated Rapid game"]
[Site "Chess.com"]
[Date "2026.04.01"]
[UTCDate "2026.04.01"]
[UTCTime "12:30:00"]
[Round "-"]
[White "fanrui89"]
[Black "other"]
[Result "0-1"]
[TimeControl "1800"]
[Link "https://www.chess.com/analysis/game/live/123456/analysis"]

1. e4 e5 2. Nf3 Nc6 0-1
""".strip()

SAMPLE_BLITZ_PGN = """
[Event "Rated Blitz game"]
[Site "Chess.com"]
[Date "2026.04.02"]
[UTCDate "2026.04.02"]
[UTCTime "08:00:00"]
[Round "-"]
[White "fanrui89"]
[Black "other"]
[Result "0-1"]
[TimeControl "300"]
[Link "https://www.chess.com/analysis/game/live/123457/analysis"]

1. d4 d5 2. c4 e6 0-1
""".strip()

SAMPLE_RATED_PGN = """
[Event "Rated Rapid game"]
[Site "Chess.com"]
[Date "2026.04.05"]
[UTCDate "2026.04.05"]
[UTCTime "10:00:00"]
[Round "-"]
[White "fanrui89"]
[Black "opponent123"]
[Result "1-0"]
[TimeControl "900+10"]
[WhiteElo "1542"]
[BlackElo "1490"]
[Link "https://www.chess.com/analysis/game/live/123460/analysis"]

1. e4 e5 2. Nf3 Nc6 1-0
""".strip()

LONG_SAMPLE_PGN = """
[Event "Rated Rapid game"]
[Site "Chess.com"]
[Date "2026.04.03"]
[UTCDate "2026.04.03"]
[UTCTime "10:00:00"]
[Round "-"]
[White "fanrui89"]
[Black "other"]
[Result "0-1"]
[TimeControl "1800"]
[Link "https://www.chess.com/analysis/game/live/123499/analysis"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. d3 d6 0-1
""".strip()


class SeededPlayersTests(TestCase):
    def test_default_players_exist(self):
        usernames = list(
            PlayerProfile.objects.filter(chesscom_username__in=["fanrui89", "fanguoguo123"])
            .order_by("chesscom_username")
            .values_list("chesscom_username", flat=True)
        )
        self.assertEqual(usernames, ["fanguoguo123", "fanrui89"])

    def test_default_players_are_family(self):
        roles = list(
            PlayerProfile.objects.filter(chesscom_username__in=["fanrui89", "fanguoguo123"])
            .order_by("chesscom_username")
            .values_list("role", flat=True)
        )
        self.assertEqual(roles, ["family", "family"])

    def test_default_admin_exists(self):
        admin = get_user_model().objects.get(username="admin")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.check_password("adminadmin"))


class PlayerProfileModelTests(TestCase):
    def test_profile_normalizes_username_and_slug(self):
        profile = PlayerProfile.objects.create(name="New Player", slug="", chesscom_username="MixedCase")
        self.assertEqual(profile.slug, "mixedcase")
        self.assertEqual(profile.name, "mixedcase")
        self.assertEqual(profile.chesscom_username, "mixedcase")
        self.assertEqual(profile.role, PlayerProfile.ROLE_OTHERS)


class UtilityFunctionTests(TestCase):
    def test_sync_service_overrides_requests_default_user_agent(self):
        service = ChessComSyncService()
        self.assertEqual(service.session.headers["User-Agent"], settings.CHESSCOM_USER_AGENT)
        self.assertIn("application/x-chess-pgn", service.session.headers["Accept"])

    def test_extract_external_id_prefers_url_tail(self):
        self.assertEqual(
            extract_external_id({"url": "https://www.chess.com/game/live/987654321"}),
            "987654321",
        )

    def test_parse_played_at_handles_epoch(self):
        parsed = parse_played_at(1711929600)
        self.assertTrue(timezone.is_aware(parsed))
        self.assertEqual(parsed.year, 2024)

    def test_normalize_result_detects_owner_loss(self):
        payload = {
            "white": {"username": "fanrui89", "result": "checkmated"},
            "black": {"username": "other", "result": "win"},
        }
        self.assertEqual(normalize_result(Game.COLOR_WHITE, payload), Game.RESULT_LOSS)

    def test_classify_drop_uses_expected_bands(self):
        self.assertEqual(classify_drop(4.2), TurningPoint.LABEL_BLUNDER)
        self.assertEqual(classify_drop(2.7), TurningPoint.LABEL_MISTAKE)
        self.assertEqual(classify_drop(1.9), TurningPoint.LABEL_MISS)

    def test_600_second_time_control_counts_as_rapid(self):
        service = ChessComSyncService()
        headers = {
            "TimeControl": "600",
        }
        self.assertEqual(service._time_class_from_headers(headers), "rapid")

    def test_move_to_san_formats_chess_notation(self):
        board = chess.Board()
        self.assertEqual(move_to_san(board, chess.Move.from_uci("g1f3")), "Nf3")

    def test_render_position_svg_varies_with_orientation(self):
        fen = chess.Board().fen()
        white_svg = render_position_svg(fen, orientation="white", size=220)
        black_svg = render_position_svg(fen, orientation="black", size=220)
        self.assertIn("<svg", white_svg)
        self.assertIn("<svg", black_svg)
        self.assertNotEqual(white_svg, black_svg)
        self.assertIn('stroke="transparent"', white_svg)

    def test_puzzle_export_lines_without_best_move(self):
        player = PlayerProfile.objects.get(chesscom_username="fanrui89")
        game = Game.objects.create(
            player_profile=player,
            external_game_id="export-lines-1",
            url="https://www.chess.com/game/live/2001",
            played_at=timezone.now(),
            white_username="fanrui89",
            black_username="other",
            owner_color=Game.COLOR_WHITE,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )
        puzzle = TurningPoint.objects.create(
            player_profile=player,
            game=game,
            turning_index=1,
            move_number=2,
            fen=chess.Board().fen(),
            played_move="Nf3",
            best_move="d4",
            eval_before=0.4,
            eval_after=-1.8,
            drop_cp=220,
            label=TurningPoint.LABEL_MISTAKE,
            explanation="Export formatting",
        )
        self.assertEqual(
            puzzle_export_lines(puzzle, include_best_move=False),
            ["White to move", "Wrong move: Nf3"],
        )

    def test_puzzle_export_lines_with_best_move(self):
        player = PlayerProfile.objects.get(chesscom_username="fanrui89")
        game = Game.objects.create(
            player_profile=player,
            external_game_id="export-lines-2",
            url="https://www.chess.com/game/live/2002",
            played_at=timezone.now(),
            white_username="other",
            black_username="fanrui89",
            owner_color=Game.COLOR_BLACK,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )
        puzzle = TurningPoint.objects.create(
            player_profile=player,
            game=game,
            turning_index=1,
            move_number=2,
            fen="8/8/8/8/8/8/8/8 b - - 0 1",
            played_move="...Nc6",
            best_move="...d5",
            eval_before=0.4,
            eval_after=-1.8,
            drop_cp=220,
            label=TurningPoint.LABEL_MISTAKE,
            explanation="Export formatting",
        )
        self.assertEqual(
            puzzle_export_lines(puzzle, include_best_move=True),
            ["Black to move", "Wrong move: ...Nc6", "Best move: ...d5"],
        )

    @patch("mistakes.admin.subprocess.Popen")
    def test_launch_local_analysis_worker_logs_start(self, mock_popen):
        mock_popen.return_value = Mock(pid=4321)

        with self.assertLogs("mistakes.admin", level="INFO") as captured:
            launch_local_analysis_worker(max_jobs=2)

        self.assertEqual(mock_popen.call_count, 1)
        self.assertTrue(any("Starting local analysis worker" in message for message in captured.output))
        self.assertTrue(any("Local analysis worker started pid=4321" in message for message in captured.output))


class SyncServiceTests(TestCase):
    def setUp(self):
        self.player = PlayerProfile.objects.get(chesscom_username="fanrui89")

    @patch("mistakes.services.requests.Session.get")
    def test_sync_filters_non_rapid_and_deduplicates(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"Content-Type": "application/x-chess-pgn"}
        mock_response.text = "\n\n".join([SAMPLE_BLITZ_PGN, SAMPLE_PGN, SAMPLE_PGN])
        mock_get.return_value = mock_response

        summary = ChessComSyncService().sync_player(self.player, months=1)

        self.assertEqual(summary.fetched, 3)
        self.assertEqual(summary.created, 1)
        self.assertEqual(Game.objects.count(), 1)
        self.assertEqual(Game.objects.first().result, Game.RESULT_LOSS)
        self.assertEqual(Game.objects.first().external_game_id, "123456")
        self.assertEqual(mock_get.call_count, 1)
        requested_url = mock_get.call_args.args[0]
        self.assertIn("/pub/player/fanrui89/games/", requested_url)
        self.assertTrue(requested_url.endswith("/pgn"))

    @patch("mistakes.services.shutil.which", return_value=None)
    @patch("mistakes.services.requests.Session.get")
    def test_sync_handles_403_without_crashing(self, mock_get, _mock_which):
        mock_response = Mock()
        mock_response.status_code = 403
        mock_get.return_value = mock_response

        summary = ChessComSyncService().sync_player(self.player, months=1)

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.created, 0)
        self.assertIn("returned 403", summary.warnings[0])

    @patch("mistakes.services.shutil.which", return_value=None)
    @patch("mistakes.services.requests.Session.get")
    def test_sync_handles_connection_error_without_crashing(self, mock_get, _mock_which):
        mock_get.side_effect = requests.ConnectionError("blocked")

        summary = ChessComSyncService().sync_player(self.player, months=1)

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.created, 0)
        self.assertIn("request failed", summary.warnings[0])

    @patch("mistakes.services.subprocess.run")
    @patch("mistakes.services.shutil.which", return_value="curl")
    @patch("mistakes.services.requests.Session.get")
    def test_sync_falls_back_to_curl_when_requests_is_blocked(self, mock_get, _mock_which, mock_run):
        mock_get.side_effect = requests.ConnectionError("blocked")
        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=SAMPLE_PGN,
            stderr="",
        )

        summary = ChessComSyncService().sync_player(self.player, months=1)

        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.created, 1)
        self.assertEqual(Game.objects.count(), 1)
        self.assertIn("/pub/player/fanrui89/games/", mock_run.call_args.args[0][-1])

    @patch("mistakes.services.requests.Session.get")
    def test_sync_downloads_each_requested_month(self, mock_get):
        april_response = Mock()
        april_response.status_code = 200
        april_response.raise_for_status.return_value = None
        april_response.headers = {"Content-Type": "application/x-chess-pgn"}
        april_response.text = SAMPLE_PGN
        march_response = Mock()
        march_response.status_code = 200
        march_response.raise_for_status.return_value = None
        march_response.headers = {"Content-Type": "application/x-chess-pgn"}
        march_response.text = SAMPLE_PGN.replace("123456", "123458").replace("2026.04.01", "2026.03.01")
        mock_get.side_effect = [april_response, march_response]

        summary = ChessComSyncService().sync_player(self.player, months=2)

        self.assertEqual(summary.fetched, 2)
        self.assertEqual(Game.objects.count(), 2)
        self.assertEqual(mock_get.call_count, 2)

    @patch("mistakes.services.requests.Session.get")
    def test_sync_saves_opponent_profile_and_ratings_from_pgn(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {"Content-Type": "application/x-chess-pgn"}
        mock_response.text = SAMPLE_RATED_PGN
        mock_get.return_value = mock_response

        summary = ChessComSyncService().sync_player(self.player, months=1)

        self.assertEqual(summary.created, 1)
        game = Game.objects.get()
        self.assertEqual(game.white_rating, 1542)
        self.assertEqual(game.black_rating, 1490)
        self.assertIsNotNone(game.opponent_profile)
        self.assertEqual(game.opponent_profile.chesscom_username, "opponent123")
        self.assertEqual(game.opponent_profile.role, PlayerProfile.ROLE_OTHERS)
        self.assertFalse(game.opponent_profile.is_active)

    @patch("mistakes.services.subprocess.run")
    @patch("mistakes.services.shutil.which", return_value="curl")
    @patch("mistakes.services.requests.Session.get")
    def test_sync_falls_back_to_curl_on_403(self, mock_get, _mock_which, mock_run):
        mock_response = Mock()
        mock_response.status_code = 403
        mock_get.return_value = mock_response
        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=SAMPLE_PGN,
            stderr="",
        )

        summary = ChessComSyncService().sync_player(self.player, months=1)

        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.created, 1)


class FakeEngine:
    def __init__(self, infos):
        self.infos = iter(infos)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def configure(self, _options):
        return None

    def analyse(self, board, limit):
        return next(self.infos)


class StockfishAnalyzerTests(TestCase):
    def setUp(self):
        self.player = PlayerProfile.objects.get(chesscom_username="fanrui89")
        self.game = Game.objects.create(
            player_profile=self.player,
            external_game_id="game-1",
            url="https://www.chess.com/game/live/1",
            played_at=timezone.now(),
            white_username="fanrui89",
            black_username="other",
            owner_color=Game.COLOR_WHITE,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )

    @patch("mistakes.services.Path.exists", return_value=True)
    @patch("mistakes.services.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_game_creates_earliest_turning_point(self, mock_popen, _mock_exists):
        infos = [
            {
                "score": chess.engine.PovScore(chess.engine.Cp(50), chess.WHITE),
                "pv": [chess.Move.from_uci("e2e4")],
            },
            {
                "score": chess.engine.PovScore(chess.engine.Cp(20), chess.WHITE),
                "pv": [chess.Move.from_uci("e7e5")],
            },
            {
                "score": chess.engine.PovScore(chess.engine.Cp(40), chess.WHITE),
                "pv": [chess.Move.from_uci("g1f3")],
            },
            {
                "score": chess.engine.PovScore(chess.engine.Cp(-180), chess.WHITE),
                "pv": [chess.Move.from_uci("b8c6")],
            },
        ]
        mock_popen.return_value = FakeEngine(infos)

        analyzer = StockfishAnalyzer(stockfish_path="C:\\stockfish.exe", depth=8)
        result = analyzer.analyze_game(self.game)

        self.assertEqual(result.reason, "created_1")
        turning_point = TurningPoint.objects.get(game=self.game, turning_index=1)
        self.assertEqual(turning_point.move_number, 2)
        self.assertEqual(turning_point.played_move, "Nf3")
        self.assertEqual(turning_point.best_move, "Nf3")
        self.assertEqual(turning_point.drop_cp, 220)
        self.assertEqual(turning_point.archive_year, self.game.played_at.year)
        self.assertEqual(turning_point.archive_month, self.game.played_at.month)
        self.assertEqual(len(result.turning_points), 1)

    @patch("mistakes.services.Path.exists", return_value=True)
    @patch("mistakes.services.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_game_caps_turning_points_at_three(self, mock_popen, _mock_exists):
        self.game.pgn = LONG_SAMPLE_PGN
        self.game.save(update_fields=["pgn"])
        infos = []
        for score_before, score_after, move in [
            (50, -200, "e2e4"),
            (40, -220, "g1f3"),
            (30, -210, "f1c4"),
            (20, -230, "d2d3"),
        ]:
            infos.append(
                {
                    "score": chess.engine.PovScore(chess.engine.Cp(score_before), chess.WHITE),
                    "pv": [chess.Move.from_uci(move)],
                }
            )
            infos.append(
                {
                    "score": chess.engine.PovScore(chess.engine.Cp(score_after), chess.WHITE),
                    "pv": [chess.Move.from_uci("a7a6")],
                }
            )
        mock_popen.return_value = FakeEngine(infos)

        analyzer = StockfishAnalyzer(stockfish_path="C:\\stockfish.exe", depth=8)
        result = analyzer.analyze_game(self.game)

        self.assertEqual(len(result.turning_points), 3)
        self.assertEqual(TurningPoint.objects.filter(game=self.game).count(), 3)
        self.assertEqual(
            list(TurningPoint.objects.filter(game=self.game).order_by("turning_index").values_list("turning_index", flat=True)),
            [1, 2, 3],
        )

    @patch("mistakes.services.Path.exists", return_value=True)
    @patch("mistakes.services.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_game_extracts_turning_point_for_won_game(self, mock_popen, _mock_exists):
        self.game.result = Game.RESULT_WIN
        self.game.owner_color = Game.COLOR_WHITE
        self.game.save(update_fields=["result", "owner_color"])
        infos = [
            {
                "score": chess.engine.PovScore(chess.engine.Cp(20), chess.BLACK),
                "pv": [chess.Move.from_uci("e7e5")],
            },
            {
                "score": chess.engine.PovScore(chess.engine.Cp(-220), chess.BLACK),
                "pv": [chess.Move.from_uci("b8c6")],
            },
            {
                "score": chess.engine.PovScore(chess.engine.Cp(10), chess.BLACK),
                "pv": [chess.Move.from_uci("b8c6")],
            },
            {
                "score": chess.engine.PovScore(chess.engine.Cp(-40), chess.BLACK),
                "pv": [chess.Move.from_uci("a7a6")],
            },
        ]
        mock_popen.return_value = FakeEngine(infos)

        analyzer = StockfishAnalyzer(stockfish_path="C:\\stockfish.exe", depth=8)
        result = analyzer.analyze_game(self.game)

        self.assertEqual(result.reason, "created_1")
        turning_point = TurningPoint.objects.get(game=self.game, turning_index=1)
        self.assertEqual(turning_point.played_move, "e5")
        self.assertEqual(turning_point.best_move, "e5")


class AnalysisQueueTests(TestCase):
    def setUp(self):
        self.player = PlayerProfile.objects.get(chesscom_username="fanrui89")
        self.game = Game.objects.create(
            player_profile=self.player,
            external_game_id="queued-game-1",
            url="https://www.chess.com/game/live/3001",
            played_at=timezone.now().replace(year=2026, month=3, day=12),
            white_username="fanrui89",
            black_username="other",
            owner_color=Game.COLOR_WHITE,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )

    def test_games_to_queue_for_analysis_returns_target_games(self):
        queued_games = list(games_to_queue_for_analysis(player=self.player, reanalyze=False))
        self.assertEqual(queued_games, [self.game])

    def test_enqueue_analysis_jobs_creates_one_pending_job_per_game(self):
        summary = enqueue_analysis_jobs(player=self.player, reanalyze=False)

        self.assertEqual(summary, EnqueueSummary(created=1, skipped=0))
        job = AnalysisJob.objects.get()
        self.assertEqual(job.player_profile, self.player)
        self.assertEqual(job.game, self.game)
        self.assertEqual(job.archive_year, 2026)
        self.assertEqual(job.archive_month, 3)
        self.assertEqual(job.status, AnalysisJob.STATUS_PENDING)

    def test_enqueue_analysis_jobs_skips_existing_pending_jobs(self):
        AnalysisJob.objects.create(
            player_profile=self.player,
            game=self.game,
            archive_year=2026,
            archive_month=3,
            reanalyze=False,
        )

        summary = enqueue_analysis_jobs(player=self.player, reanalyze=False)

        self.assertEqual(summary, EnqueueSummary(created=0, skipped=1))
        self.assertEqual(AnalysisJob.objects.count(), 1)

    def test_claim_next_analysis_job_marks_job_running(self):
        AnalysisJob.objects.create(
            player_profile=self.player,
            game=self.game,
            archive_year=2026,
            archive_month=3,
            reanalyze=False,
        )

        job = claim_next_analysis_job(worker_name="worker-a")

        self.assertIsNotNone(job)
        self.assertEqual(job.status, AnalysisJob.STATUS_RUNNING)
        self.assertEqual(job.claimed_by, "worker-a")

    def test_process_analysis_job_marks_job_completed(self):
        job = AnalysisJob.objects.create(
            player_profile=self.player,
            game=self.game,
            archive_year=2026,
            archive_month=3,
            reanalyze=False,
            status=AnalysisJob.STATUS_RUNNING,
            claimed_by="worker-a",
            started_at=timezone.now(),
        )
        analyzer = Mock()
        analyzer.analyze_game.return_value = AnalysisResult(turning_points=[Mock(), Mock()], reason="created_2")

        result = process_analysis_job(job, analyzer)

        job.refresh_from_db()
        self.assertEqual(result, JobRunResult(analyzed=1, created=2))
        self.assertEqual(job.status, AnalysisJob.STATUS_COMPLETED)
        self.assertEqual(job.games_targeted, 1)
        self.assertEqual(job.games_analyzed, 1)
        self.assertEqual(job.turning_points_created, 2)
        analyzer.analyze_game.assert_called_once_with(self.game)


class ViewTests(TestCase):
    def setUp(self):
        self.player = PlayerProfile.objects.get(chesscom_username="fanrui89")
        self.game = Game.objects.create(
            player_profile=self.player,
            external_game_id="game-2",
            url="https://www.chess.com/game/live/2",
            played_at=timezone.now(),
            white_username="fanrui89",
            black_username="other",
            owner_color=Game.COLOR_WHITE,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )
        self.turning_point = TurningPoint.objects.create(
            player_profile=self.player,
            game=self.game,
            move_number=2,
            fen=chess.Board().fen(),
            played_move="g1f3",
            best_move="d2d4",
            eval_before=0.4,
            eval_after=-1.8,
            drop_cp=220,
            label=TurningPoint.LABEL_MISTAKE,
            explanation="Test explanation",
        )

    def test_player_list_renders_seeded_users(self):
        response = self.client.get(reverse("mistakes:player-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fanrui89")
        self.assertContains(response, "fanguoguo123")
        self.assertNotContains(response, "Daughter")
        self.assertNotContains(response, "Adult")

    def test_player_detail_redirects_to_puzzle_list(self):
        response = self.client.get(reverse("mistakes:player-detail", kwargs={"slug": self.player.slug}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("mistakes:puzzle-list", kwargs={"slug": self.player.slug}))

    def test_puzzle_detail_renders_board_container(self):
        response = self.client.get(
            reverse("mistakes:puzzle-detail", kwargs={"slug": self.player.slug, "pk": self.turning_point.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fen-board")
        self.assertContains(response, "<svg")
        self.assertContains(response, "Open original game")
        self.assertContains(response, self.game.url)
        self.assertContains(response, "Open on Chess.com Analysis")

    def test_puzzle_list_groups_by_archive_month(self):
        response = self.client.get(reverse("mistakes:puzzle-list", kwargs={"slug": self.player.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.turning_point.archive_year}-{self.turning_point.archive_month:02d}")
        self.assertContains(response, "fen-board-mini")

    def test_puzzle_archive_route_filters_by_year_month(self):
        older_game = Game.objects.create(
            player_profile=self.player,
            external_game_id="older-game",
            url="https://www.chess.com/game/live/999",
            played_at=timezone.now().replace(year=max(2000, timezone.now().year - 1), month=1),
            white_username="fanrui89",
            black_username="other",
            owner_color=Game.COLOR_WHITE,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )
        TurningPoint.objects.create(
            player_profile=self.player,
            game=older_game,
            move_number=3,
            fen=chess.Board().fen(),
            played_move="Qxd4",
            best_move="Nf4",
            eval_before=0.1,
            eval_after=-2.0,
            drop_cp=210,
            label=TurningPoint.LABEL_MISTAKE,
            explanation="Older archive",
        )

        response = self.client.get(
            reverse(
                "mistakes:puzzle-archive",
                kwargs={
                    "slug": self.player.slug,
                    "year": self.turning_point.archive_year,
                    "month": self.turning_point.archive_month,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fen-board-mini")
        self.assertContains(response, self.turning_point.played_move)
        self.assertNotContains(response, "Older archive")

    def test_puzzle_detail_uses_black_orientation_for_black_games(self):
        black_game = Game.objects.create(
            player_profile=self.player,
            external_game_id="black-game",
            url="https://www.chess.com/game/live/500",
            played_at=timezone.now(),
            white_username="other",
            black_username="fanrui89",
            owner_color=Game.COLOR_BLACK,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN.replace("fanrui89", "other", 1).replace("[Black \"other\"]", '[Black "fanrui89"]'),
        )
        black_turning_point = TurningPoint.objects.create(
            player_profile=self.player,
            game=black_game,
            move_number=2,
            fen=chess.Board().fen(),
            played_move="...Nc6",
            best_move="...d5",
            eval_before=0.4,
            eval_after=-1.8,
            drop_cp=220,
            label=TurningPoint.LABEL_MISTAKE,
            explanation="Black-side orientation",
        )

        response = self.client.get(
            reverse("mistakes:puzzle-detail", kwargs={"slug": self.player.slug, "pk": black_turning_point.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<svg")

    def test_puzzle_archive_pdf_export_returns_pdf(self):
        response = self.client.get(
            reverse(
                "mistakes:puzzle-archive-pdf",
                kwargs={
                    "slug": self.player.slug,
                    "year": self.turning_point.archive_year,
                    "month": self.turning_point.archive_month,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(".pdf", response["Content-Disposition"])

    def test_puzzle_archive_pdf_export_with_best_move_variant_returns_pdf(self):
        response = self.client.get(
            reverse(
                "mistakes:puzzle-archive-pdf",
                kwargs={
                    "slug": self.player.slug,
                    "year": self.turning_point.archive_year,
                    "month": self.turning_point.archive_month,
                },
            )
            + "?variant=with-best"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("with-best-move", response["Content-Disposition"])

    def test_puzzle_detail_shows_next_position_button(self):
        next_turning_point = TurningPoint.objects.create(
            player_profile=self.player,
            game=self.game,
            turning_index=2,
            move_number=3,
            fen=chess.Board().fen(),
            played_move="Nc3",
            best_move="d4",
            eval_before=0.3,
            eval_after=-1.0,
            drop_cp=130,
            label=TurningPoint.LABEL_MISS,
            explanation="Next puzzle",
        )

        response = self.client.get(
            reverse("mistakes:puzzle-detail", kwargs={"slug": self.player.slug, "pk": self.turning_point.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Next position")
        self.assertContains(response, next_turning_point.get_absolute_url())

    def test_puzzle_detail_shows_previous_and_next_position_buttons(self):
        previous_turning_point = TurningPoint.objects.create(
            player_profile=self.player,
            game=self.game,
            turning_index=0,
            move_number=1,
            fen=chess.Board().fen(),
            played_move="e4",
            best_move="e4",
            eval_before=0.2,
            eval_after=0.1,
            drop_cp=10,
            label=TurningPoint.LABEL_MISS,
            explanation="Previous puzzle",
        )
        next_turning_point = TurningPoint.objects.create(
            player_profile=self.player,
            game=self.game,
            turning_index=2,
            move_number=3,
            fen=chess.Board().fen(),
            played_move="Nc3",
            best_move="d4",
            eval_before=0.3,
            eval_after=-1.0,
            drop_cp=130,
            label=TurningPoint.LABEL_MISS,
            explanation="Next puzzle",
        )

        response = self.client.get(
            reverse("mistakes:puzzle-detail", kwargs={"slug": self.player.slug, "pk": self.turning_point.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Previous position")
        self.assertContains(response, previous_turning_point.get_absolute_url())
        self.assertContains(response, "Next position")
        self.assertContains(response, next_turning_point.get_absolute_url())


class ManagementCommandTests(TestCase):
    def setUp(self):
        self.player = PlayerProfile.objects.get(chesscom_username="fanrui89")
        self.game = Game.objects.create(
            player_profile=self.player,
            external_game_id="game-3",
            url="https://www.chess.com/game/live/3",
            played_at=timezone.now(),
            white_username="fanrui89",
            black_username="other",
            owner_color=Game.COLOR_WHITE,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )

    @patch("mistakes.management.commands.sync_chess_games.ChessComSyncService.sync_player")
    def test_sync_command_can_target_single_user(self, mock_sync_player):
        mock_sync_player.return_value = Mock(fetched=4, created=2, skipped=2, failed=1, warnings=["2026-04: returned 403"])
        output = StringIO()

        call_command("sync_chess_games", username="fanrui89", months=2, stdout=output)

        mock_sync_player.assert_called_once_with(self.player, months=2)
        self.assertIn("fanrui89", output.getvalue())
        self.assertIn("failed=1", output.getvalue())

    @patch.object(StockfishAnalyzer, "verify_engine")
    @patch.object(StockfishAnalyzer, "analyze_game")
    @patch("mistakes.services.Path.exists", return_value=True)
    def test_analyze_command_processes_losses(self, _mock_exists, mock_analyze_game, mock_verify_engine):
        mock_verify_engine.return_value = None
        mock_analyze_game.return_value = AnalysisResult(turning_points=[], reason="no_turning_point")
        output = StringIO()

        call_command(
            "analyze_new_games",
            username="fanrui89",
            stockfish_path="C:\\stockfish.exe",
            stdout=output,
        )

        mock_analyze_game.assert_called_once_with(self.game)
        self.assertIn("analyzed=1", output.getvalue())

    def test_enqueue_analysis_jobs_command_queues_game_jobs(self):
        output = StringIO()

        call_command("enqueue_analysis_jobs", username="fanrui89", stdout=output)

        self.assertIn("queued_jobs=1", output.getvalue())
        self.assertEqual(AnalysisJob.objects.count(), 1)

    @patch.object(StockfishAnalyzer, "verify_engine")
    @patch("mistakes.management.commands.run_analysis_worker.process_analysis_job")
    @patch("mistakes.management.commands.run_analysis_worker.claim_next_analysis_job")
    @patch("mistakes.services.Path.exists", return_value=True)
    def test_run_analysis_worker_processes_claimed_jobs(
        self,
        _mock_exists,
        mock_claim_next_job,
        mock_process_analysis_job,
        mock_verify_engine,
    ):
        mock_verify_engine.return_value = None
        job = AnalysisJob.objects.create(
            player_profile=self.player,
            game=self.game,
            archive_year=self.game.played_at.year,
            archive_month=self.game.played_at.month,
            reanalyze=False,
            status=AnalysisJob.STATUS_RUNNING,
            claimed_by="worker-a",
            started_at=timezone.now(),
        )
        mock_claim_next_job.side_effect = [job, None]
        mock_process_analysis_job.return_value = JobRunResult(analyzed=1, created=2)
        output = StringIO()

        call_command("run_analysis_worker", max_jobs=2, stockfish_path="C:\\stockfish.exe", stdout=output)

        mock_process_analysis_job.assert_called_once()
        self.assertIn("processed_jobs=1", output.getvalue())


class AdminActionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_site = AdminSite()
        self.admin = PlayerProfileAdmin(PlayerProfile, self.admin_site)
        self.game_admin = GameAdmin(Game, self.admin_site)
        self.players = PlayerProfile.objects.filter(chesscom_username__in=["fanrui89", "fanguoguo123"]).order_by(
            "chesscom_username"
        )

    @patch("mistakes.admin.ChessComSyncService.sync_player")
    def test_player_admin_action_syncs_selected_profiles_for_current_month(self, mock_sync_player):
        mock_sync_player.side_effect = [
            Mock(fetched=1, created=1, skipped=0, failed=0, warnings=[]),
            Mock(fetched=2, created=1, skipped=1, failed=0, warnings=[]),
        ]
        request = self.factory.post("/admin/mistakes/playerprofile/")

        with patch.object(self.admin, "message_user") as mock_message_user:
            self.admin.download_archived_games_for_current_month(request, self.players)

        self.assertEqual(mock_sync_player.call_count, 2)
        for call in mock_sync_player.call_args_list:
            self.assertEqual(call.kwargs["months"], 1)
        self.assertEqual(
            [call.args[0].chesscom_username for call in mock_sync_player.call_args_list],
            ["fanguoguo123", "fanrui89"],
        )
        self.assertEqual(mock_message_user.call_count, 3)
        self.assertIn("Selected players synced for current month", mock_message_user.call_args_list[-1].args[1])

    @patch("mistakes.admin.ChessComSyncService.sync_player")
    def test_player_admin_action_syncs_selected_profiles_for_four_months(self, mock_sync_player):
        mock_sync_player.side_effect = [
            Mock(fetched=3, created=1, skipped=2, failed=0, warnings=[]),
            Mock(fetched=4, created=2, skipped=1, failed=1, warnings=["2026-04: returned 403"]),
        ]
        request = self.factory.post("/admin/mistakes/playerprofile/")

        with patch.object(self.admin, "message_user") as mock_message_user:
            self.admin.download_archived_games_for_recent_months(request, self.players)

        self.assertEqual(mock_sync_player.call_count, 2)
        for call in mock_sync_player.call_args_list:
            self.assertEqual(call.kwargs["months"], 4)
        self.assertEqual(
            [call.args[0].chesscom_username for call in mock_sync_player.call_args_list],
            ["fanguoguo123", "fanrui89"],
        )
        self.assertEqual(mock_message_user.call_count, 4)
        self.assertIn("Selected players synced across 4 months", mock_message_user.call_args_list[-1].args[1])

    @patch("mistakes.admin.launch_local_analysis_worker")
    @patch("mistakes.admin.enqueue_analysis_jobs")
    def test_player_admin_action_enqueues_jobs_for_selected_profiles(
        self,
        mock_enqueue_analysis_jobs,
        mock_launch_local_analysis_worker,
    ):
        mock_enqueue_analysis_jobs.side_effect = [
            EnqueueSummary(created=1, skipped=0),
            EnqueueSummary(created=2, skipped=1),
        ]
        request = self.factory.post("/admin/mistakes/playerprofile/")

        with patch.object(self.admin, "message_user") as mock_message_user:
            self.admin.analyze_new_games_for_selected_players(request, self.players)

        self.assertEqual(mock_message_user.call_count, 3)
        self.assertEqual(
            [call.kwargs for call in mock_enqueue_analysis_jobs.call_args_list],
            [
                {"player": self.players[0], "reanalyze": False},
                {"player": self.players[1], "reanalyze": False},
            ],
        )
        mock_launch_local_analysis_worker.assert_called_once_with(max_jobs=3)
        self.assertIn("fanguoguo123: queued_jobs=1", mock_message_user.call_args_list[0].args[1])
        self.assertIn("fanrui89: queued_jobs=2", mock_message_user.call_args_list[1].args[1])
        self.assertIn("worker_started=yes", mock_message_user.call_args_list[2].args[1])

    @patch("mistakes.admin.launch_local_analysis_worker", side_effect=OSError("spawn failed"))
    @patch("mistakes.admin.enqueue_analysis_jobs")
    def test_player_admin_action_logs_worker_start_failures(
        self,
        mock_enqueue_analysis_jobs,
        _mock_launch_local_analysis_worker,
    ):
        mock_enqueue_analysis_jobs.side_effect = [
            EnqueueSummary(created=1, skipped=0),
            EnqueueSummary(created=0, skipped=1),
        ]
        request = self.factory.post("/admin/mistakes/playerprofile/")

        with self.assertLogs("mistakes.admin", level="WARNING") as captured:
            with patch.object(self.admin, "message_user") as mock_message_user:
                self.admin.analyze_new_games_for_selected_players(request, self.players)

        self.assertTrue(any("Failed to start local analysis worker error=spawn failed" in message for message in captured.output))
        self.assertIn("Failed to start local analysis worker: spawn failed", mock_message_user.call_args_list[2].args[1])

    @patch("mistakes.admin.launch_local_analysis_worker")
    @patch("mistakes.admin.enqueue_analysis_jobs")
    def test_player_admin_action_does_not_start_worker_when_no_jobs_created(
        self,
        mock_enqueue_analysis_jobs,
        mock_launch_local_analysis_worker,
    ):
        mock_enqueue_analysis_jobs.side_effect = [
            EnqueueSummary(created=0, skipped=1),
            EnqueueSummary(created=0, skipped=2),
        ]
        request = self.factory.post("/admin/mistakes/playerprofile/")

        with patch.object(self.admin, "message_user") as mock_message_user:
            self.admin.analyze_new_games_for_selected_players(request, self.players)

        mock_launch_local_analysis_worker.assert_not_called()
        self.assertIn("worker_started=no", mock_message_user.call_args_list[2].args[1])

    @patch("mistakes.admin.launch_local_analysis_worker")
    @patch("mistakes.admin.enqueue_analysis_jobs")
    def test_game_admin_action_enqueues_selected_games(
        self,
        mock_enqueue_analysis_jobs,
        mock_launch_local_analysis_worker,
    ):
        player = PlayerProfile.objects.get(chesscom_username="fanrui89")
        game = Game.objects.create(
            player_profile=player,
            external_game_id="admin-game-action",
            url="https://www.chess.com/game/live/4001",
            played_at=timezone.now(),
            white_username="fanrui89",
            black_username="other",
            owner_color=Game.COLOR_WHITE,
            result=Game.RESULT_LOSS,
            time_class="rapid",
            pgn=SAMPLE_PGN,
        )
        mock_enqueue_analysis_jobs.return_value = EnqueueSummary(created=1, skipped=0)
        request = self.factory.post("/admin/mistakes/game/")

        with patch.object(self.game_admin, "message_user") as mock_message_user:
            self.game_admin.analyze_selected_games(request, Game.objects.filter(pk=game.pk))

        mock_enqueue_analysis_jobs.assert_called_once()
        self.assertEqual(mock_enqueue_analysis_jobs.call_args.kwargs["reanalyze"], False)
        self.assertEqual(list(mock_enqueue_analysis_jobs.call_args.kwargs["queryset"]), [game])
        mock_launch_local_analysis_worker.assert_called_once_with(max_jobs=1)
        self.assertIn("queued_jobs=1", mock_message_user.call_args.args[1])


class AdminConfigTests(TestCase):
    def test_player_profile_admin_has_role_filter(self):
        admin = PlayerProfileAdmin(PlayerProfile, AdminSite())
        self.assertIn("role", admin.list_filter)

    def test_game_admin_has_player_profile_filter(self):
        admin = GameAdmin(Game, AdminSite())
        self.assertIn("player_profile", admin.list_filter)

    def test_turning_point_admin_has_player_profile_filter(self):
        admin = TurningPointAdmin(TurningPoint, AdminSite())
        self.assertIn("player_profile", admin.list_filter)

    def test_analysis_job_admin_has_status_filter(self):
        admin = AnalysisJobAdmin(AnalysisJob, AdminSite())
        self.assertIn("status", admin.list_filter)
