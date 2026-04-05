from django.urls import path

from .views import PlayerDetailView, PlayerListView, PuzzleDetailView, PuzzleListPdfView, PuzzleListView


urlpatterns = [
    path("players/", PlayerListView.as_view(), name="player-list"),
    path("players/<slug:slug>/", PlayerDetailView.as_view(), name="player-detail"),
    path("players/<slug:slug>/puzzles/", PuzzleListView.as_view(), name="puzzle-list"),
    path("players/<slug:slug>/puzzles/export/pdf/", PuzzleListPdfView.as_view(), name="puzzle-pdf"),
    path("players/<slug:slug>/puzzles/<int:year>/<int:month>/", PuzzleListView.as_view(), name="puzzle-archive"),
    path("players/<slug:slug>/puzzles/<int:year>/<int:month>/export/pdf/", PuzzleListPdfView.as_view(), name="puzzle-archive-pdf"),
    path("players/<slug:slug>/puzzles/<int:pk>/", PuzzleDetailView.as_view(), name="puzzle-detail"),
]
