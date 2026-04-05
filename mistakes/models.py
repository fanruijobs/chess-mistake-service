from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class PlayerProfile(models.Model):
    ROLE_FAMILY = "family"
    ROLE_FRIEND = "friend"
    ROLE_OTHERS = "others"
    ROLE_CHOICES = [
        (ROLE_FAMILY, "Family"),
        (ROLE_FRIEND, "Friend"),
        (ROLE_OTHERS, "Others"),
    ]

    UI_MODE_ADULT = "adult"
    UI_MODE_KID = "kid"
    UI_MODE_CHOICES = [
        (UI_MODE_ADULT, "Adult"),
        (UI_MODE_KID, "Kid"),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, max_length=140)
    chesscom_username = models.CharField(max_length=80, unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OTHERS)
    ui_mode = models.CharField(max_length=20, choices=UI_MODE_CHOICES, default="", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.chesscom_username

    def save(self, *args, **kwargs):
        self.chesscom_username = self.chesscom_username.lower()
        self.name = self.chesscom_username
        if not self.role:
            self.role = self.ROLE_OTHERS
        self.ui_mode = ""
        if not self.slug:
            self.slug = slugify(self.chesscom_username)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("mistakes:player-detail", kwargs={"slug": self.slug})


class Game(models.Model):
    RESULT_WIN = "win"
    RESULT_LOSS = "loss"
    RESULT_DRAW = "draw"
    RESULT_UNKNOWN = "unknown"
    RESULT_CHOICES = [
        (RESULT_WIN, "Win"),
        (RESULT_LOSS, "Loss"),
        (RESULT_DRAW, "Draw"),
        (RESULT_UNKNOWN, "Unknown"),
    ]

    COLOR_WHITE = "white"
    COLOR_BLACK = "black"
    COLOR_CHOICES = [
        (COLOR_WHITE, "White"),
        (COLOR_BLACK, "Black"),
    ]

    player_profile = models.ForeignKey(PlayerProfile, on_delete=models.CASCADE, related_name="games")
    opponent_profile = models.ForeignKey(
        PlayerProfile,
        on_delete=models.SET_NULL,
        related_name="opponent_games",
        null=True,
        blank=True,
    )
    external_game_id = models.CharField(max_length=255)
    url = models.URLField()
    played_at = models.DateTimeField()
    white_username = models.CharField(max_length=80)
    black_username = models.CharField(max_length=80)
    white_rating = models.PositiveIntegerField(null=True, blank=True)
    black_rating = models.PositiveIntegerField(null=True, blank=True)
    owner_color = models.CharField(max_length=5, choices=COLOR_CHOICES)
    result = models.CharField(max_length=10, choices=RESULT_CHOICES, default=RESULT_UNKNOWN)
    time_class = models.CharField(max_length=20)
    pgn = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-played_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["player_profile", "external_game_id"],
                name="unique_game_per_player_external_id",
            )
        ]

    def __str__(self) -> str:
        return f"{self.player_profile.chesscom_username} {self.played_at:%Y-%m-%d} {self.result}"


class TurningPoint(models.Model):
    LABEL_BLUNDER = "blunder"
    LABEL_MISTAKE = "mistake"
    LABEL_MISS = "miss"
    LABEL_CHOICES = [
        (LABEL_BLUNDER, "Blunder"),
        (LABEL_MISTAKE, "Mistake"),
        (LABEL_MISS, "Missed Chance"),
    ]

    player_profile = models.ForeignKey(PlayerProfile, on_delete=models.CASCADE, related_name="turning_points")
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="turning_points")
    turning_index = models.PositiveSmallIntegerField(default=1)
    move_number = models.PositiveIntegerField()
    fen = models.TextField()
    played_move = models.CharField(max_length=20)
    best_move = models.CharField(max_length=20)
    eval_before = models.FloatField()
    eval_after = models.FloatField()
    drop_cp = models.IntegerField()
    label = models.CharField(max_length=20, choices=LABEL_CHOICES, default=LABEL_BLUNDER)
    explanation = models.TextField(blank=True)
    archive_year = models.PositiveSmallIntegerField(default=0)
    archive_month = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-archive_year", "-archive_month", "-game__played_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "turning_index"],
                name="unique_turning_point_slot_per_game",
            )
        ]

    def __str__(self) -> str:
        return f"{self.player_profile.chesscom_username} move {self.move_number} ({self.label})"

    def save(self, *args, **kwargs):
        if self.game_id and self.game and self.game.played_at:
            self.archive_year = self.game.played_at.year
            self.archive_month = self.game.played_at.month
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("mistakes:puzzle-detail", kwargs={"slug": self.player_profile.slug, "pk": self.pk})


class AnalysisJob(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    player_profile = models.ForeignKey(PlayerProfile, on_delete=models.CASCADE, related_name="analysis_jobs")
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="analysis_jobs", null=True, blank=True)
    archive_year = models.PositiveSmallIntegerField(default=0)
    archive_month = models.PositiveSmallIntegerField(default=0)
    reanalyze = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=255, blank=True)
    last_error = models.TextField(blank=True)
    games_targeted = models.PositiveIntegerField(default=0)
    games_analyzed = models.PositiveIntegerField(default=0)
    turning_points_created = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["status", "-archive_year", "-archive_month", "player_profile__chesscom_username", "-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "reanalyze"],
                name="unique_analysis_job_per_game_and_mode",
            )
        ]

    def __str__(self) -> str:
        if self.game_id:
            return f"{self.player_profile.chesscom_username} game {self.game_id} {self.status}"
        return (
            f"{self.player_profile.chesscom_username} "
            f"{self.archive_year}-{self.archive_month:02d} "
            f"{self.status}"
        )

    def save(self, *args, **kwargs):
        if self.game_id and self.game and self.game.played_at:
            self.player_profile = self.game.player_profile
            self.archive_year = self.game.played_at.year
            self.archive_month = self.game.played_at.month
        super().save(*args, **kwargs)
