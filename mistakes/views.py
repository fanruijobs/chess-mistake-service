from django.db.models import Case, Count, IntegerField, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views.generic import DetailView, ListView
from itertools import groupby
from io import BytesIO

import chess
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg

from .board_rendering import render_position_svg
from .models import PlayerProfile, TurningPoint


def puzzle_export_lines(puzzle: TurningPoint, include_best_move: bool) -> list[str]:
    board = chess.Board(puzzle.fen)
    lines = [
        f"{'White' if board.turn == chess.WHITE else 'Black'} to move",
        f"Wrong move: {puzzle.played_move}",
    ]
    if include_best_move:
        lines.append(f"Best move: {puzzle.best_move}")
    return lines


class PlayerListView(ListView):
    model = PlayerProfile
    template_name = "mistakes/player_list.html"
    context_object_name = "players"

    def get_queryset(self):
        return (
            PlayerProfile.objects.filter(is_active=True)
            .annotate(
                puzzle_count=Case(
                    When(role=PlayerProfile.ROLE_OTHERS, then=Value(0)),
                    default=Count("turning_points"),
                    output_field=IntegerField(),
                )
            )
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        archive_rows = (
            TurningPoint.objects.filter(player_profile__in=context["players"]).exclude(
                player_profile__role=PlayerProfile.ROLE_OTHERS
            )
            .values("player_profile_id", "archive_year", "archive_month")
            .order_by("player_profile_id", "-archive_year", "-archive_month")
            .distinct()
        )
        archive_map = {}
        for row in archive_rows:
            archive_map.setdefault(row["player_profile_id"], []).append(
                {"year": row["archive_year"], "month": row["archive_month"]}
            )
        for player in context["players"]:
            player.archive_links = archive_map.get(player.id, [])[:6]
        return context


class PlayerDetailView(DetailView):
    model = PlayerProfile
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get(self, request, *args, **kwargs):
        player = get_object_or_404(PlayerProfile, slug=kwargs["slug"], is_active=True)
        return redirect("mistakes:puzzle-list", slug=player.slug)


class PuzzleListView(ListView):
    model = TurningPoint
    template_name = "mistakes/puzzle_list.html"
    context_object_name = "puzzles"
    paginate_by = 24

    def dispatch(self, request, *args, **kwargs):
        self.player = get_object_or_404(PlayerProfile, slug=kwargs["slug"], is_active=True)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = self.player.turning_points.select_related("game").order_by("-archive_year", "-archive_month", "-game__played_at")
        year = self.kwargs.get("year")
        month = self.kwargs.get("month")
        if year is not None and month is not None:
            queryset = queryset.filter(archive_year=year, archive_month=month)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["player"] = self.player
        context["selected_year"] = self.kwargs.get("year")
        context["selected_month"] = self.kwargs.get("month")
        context["archive_links"] = list(
            self.player.turning_points.values("archive_year", "archive_month")
            .order_by("-archive_year", "-archive_month")
            .distinct()
        )
        archive_groups = []
        for (year, month), items in groupby(context["puzzles"], key=lambda item: (item.archive_year, item.archive_month)):
            archive_groups.append(
                {
                    "year": year,
                    "month": month,
                    "puzzles": list(items),
                }
            )
        context["archive_groups"] = archive_groups
        return context


class PuzzleDetailView(DetailView):
    model = TurningPoint
    template_name = "mistakes/puzzle_detail.html"
    context_object_name = "puzzle"
    pk_url_kwarg = "pk"

    def get_queryset(self):
        return TurningPoint.objects.select_related("player_profile", "game").filter(
            player_profile__slug=self.kwargs["slug"],
            player_profile__is_active=True,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ordered_ids = list(
            self.object.player_profile.turning_points.order_by(
                "-archive_year",
                "-archive_month",
                "-game__played_at",
                "turning_index",
                "pk",
            ).values_list("pk", flat=True)
        )
        try:
            current_index = ordered_ids.index(self.object.pk)
        except ValueError:
            current_index = -1
        previous_puzzle = None
        if current_index > 0:
            previous_puzzle = self.object.player_profile.turning_points.get(pk=ordered_ids[current_index - 1])
        next_puzzle = None
        if current_index != -1 and current_index + 1 < len(ordered_ids):
            next_puzzle = self.object.player_profile.turning_points.get(pk=ordered_ids[current_index + 1])
        context["previous_puzzle"] = previous_puzzle
        context["next_puzzle"] = next_puzzle
        return context


class PuzzleListPdfView(ListView):
    model = TurningPoint

    def dispatch(self, request, *args, **kwargs):
        self.player = get_object_or_404(PlayerProfile, slug=kwargs["slug"], is_active=True)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = self.player.turning_points.select_related("game").order_by("-archive_year", "-archive_month", "-game__played_at")
        year = self.kwargs.get("year")
        month = self.kwargs.get("month")
        if year is not None and month is not None:
            queryset = queryset.filter(archive_year=year, archive_month=month)
        return queryset

    def render_to_response(self, context, **response_kwargs):
        puzzles = list(context["object_list"])
        include_best_move = self.request.GET.get("variant") == "with-best"
        buffer = BytesIO()
        page_width, page_height = A4
        pdf = canvas.Canvas(buffer, pagesize=A4)

        margin_x = 36
        margin_top = 42
        cols = 2
        rows = 3
        cell_width = (page_width - (margin_x * 2)) / cols
        cell_height = (page_height - margin_top - 36) / rows
        board_size = min(cell_width - 20, cell_height - 56)
        pdf.setFont("Helvetica", 10)

        for index, puzzle in enumerate(puzzles):
            slot = index % (cols * rows)
            if index and slot == 0:
                pdf.showPage()
                pdf.setFont("Helvetica", 10)

            col = slot % cols
            row = slot // cols
            origin_x = margin_x + (col * cell_width)
            origin_y = page_height - margin_top - ((row + 1) * cell_height)

            svg = render_position_svg(
                puzzle.fen,
                orientation=puzzle.game.owner_color,
                size=int(board_size),
            )
            drawing = svg2rlg(BytesIO(svg.encode("utf-8")))
            board_x = origin_x + ((cell_width - board_size) / 2)
            board_y = origin_y + cell_height - board_size - 16
            renderPDF.draw(drawing, pdf, board_x, board_y)

            text_y = board_y - 8
            for line in puzzle_export_lines(puzzle, include_best_move=include_best_move):
                pdf.drawCentredString(origin_x + (cell_width / 2), text_y, line)
                text_y -= 12

        if not puzzles:
            pdf.setFont("Helvetica", 12)
            pdf.drawString(72, page_height - 72, "No turning point positions available for export.")

        pdf.save()
        filename_parts = [self.player.chesscom_username, "turning-points"]
        if self.kwargs.get("year") and self.kwargs.get("month"):
            filename_parts.append(f"{self.kwargs['year']}-{int(self.kwargs['month']):02d}")
        filename_parts.append("with-best-move" if include_best_move else "without-best-move")
        filename = slugify("-".join(filename_parts)) + ".pdf"
        return HttpResponse(
            buffer.getvalue(),
            content_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
