# Chess Mistake Service

Version: `0.0.7`

Django service for downloading monthly Chess.com PGNs, extracting turning-point positions with Stockfish, and serving those positions back as review puzzles with archive browsing and PDF export.

## What It Does

- Syncs monthly Chess.com PGN archives for selected players
- Saves only rapid games using `TimeControl >= 600`
- Falls back to `curl` when Python `requests` is blocked or rejected
- Stores both the tracked player and the opponent as `PlayerProfile` records
- Imports `WhiteElo` and `BlackElo` from PGN headers when available
- Analyzes games with Stockfish and creates up to 3 turning points per game
- Extracts turning points from both lost games and won games
  - losses: analyzes the tracked player's mistakes
  - wins: analyzes the opponent's mistakes
- Groups turning points by archive year/month
- Renders puzzle boards as server-side SVG
- Orients the board by the tracked player's side
- Supports previous/next puzzle navigation
- Supports reveal/hide for the best move
- Exports archive positions to PDF in 2 columns x 3 rows per page
- Supports two PDF modes:
  - wrong move only
  - wrong move plus best move
- Provides Django admin actions for sync and analysis workflows
- Supports queued async analysis jobs with local or multi-machine workers
- Includes Docker Compose support for a SQLite-based deployment
- Serves collected static CSS and JavaScript in Docker through WhiteNoise
- Seeds a default development admin account on migrate

## Main Pages

- `/players/`
- `/players/<slug>/puzzles/`
- `/players/<slug>/puzzles/<year>/<month>/`
- `/players/<slug>/puzzles/<id>/`
- `/players/<slug>/puzzles/export/pdf/`
- `/players/<slug>/puzzles/<year>/<month>/export/pdf/`

## Admin Features

### PlayerProfile admin

- default list view shows only `family` and `friend`
- filter by `role`
- filter by `is_active`
- action: download archived rapid games for current month
- action: download archived rapid games for current month and previous 3 months
- action: queue new analysis jobs for selected players

### Game admin

- filter by tracked player
- action: queue analysis for selected games

### TurningPoint admin

- filter by tracked player

### AnalysisJob admin

- inspect pending/running/completed/failed jobs
- filter by player, status, reanalyze flag, and archive year/month

## Async Analysis Flow

Analysis is queue-based.

- Admin actions enqueue `AnalysisJob` records
- The admin trigger can also start a local worker automatically
- Workers claim pending jobs from the database
- Multiple machines can process jobs if they share the same database and Stockfish access

Commands:

```powershell
python manage.py enqueue_analysis_jobs
python manage.py run_analysis_worker --max-jobs 10
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

The project can use a local Stockfish binary through `STOCKFISH_PATH`. If you bundle Stockfish in the repo, keep the path local and configurable through environment variables.

After `migrate`, the default development admin account is:

- username: `admin`
- password: `adminadmin`

Change this for any environment beyond local development.

## Docker Compose

The repo includes:

- [Dockerfile](C:/Users/ricky/workspace/chess-mistake-service/Dockerfile)
- [docker-compose.yml](C:/Users/ricky/workspace/chess-mistake-service/docker-compose.yml)

Container behavior:

- runs Django through `gunicorn`
- uses `config.wsgi:application`
- binds to `0.0.0.0:8000`
- uses `2` workers
- installs Linux `stockfish` inside the image
- runs `collectstatic --noinput` during container startup
- serves static files through WhiteNoise when `DJANGO_DEBUG=0`
- keeps the current SQLite setup
- seeds the default admin during `migrate`

Bring it up:

```powershell
docker compose up --build
```

Access it from the local network at:

```text
http://<host-192.168.x.x>:8000/
```

Because the container binds to `0.0.0.0:8000`, it can be reached by other devices on the same LAN if your firewall allows port `8000`.

The compose service is configured with:

- memory limit: `1 GB`
- storage cap: `20 GB`

Note: Docker disk quota support depends on the host storage driver and platform. The compose file declares the requested cap, but actual enforcement can vary by environment.

## Environment Variables

Example values belong in `.env.example`. Do not commit real secrets, tokens, or third-party credentials.

- `DJANGO_DEBUG`
- `DJANGO_TIME_ZONE`
- `DJANGO_ALLOWED_HOSTS`
- `STOCKFISH_PATH`
- `CHESSCOM_USER_AGENT`
- `SYNC_MONTH_LOOKBACK`
- `CHESS_ANALYSIS_DEPTH`
- `TURNING_POINT_THRESHOLD`

## Commands

### Sync monthly PGNs

```powershell
python manage.py sync_chess_games
python manage.py sync_chess_games --username someplayer
python manage.py sync_chess_games --username someplayer --months 1
```

### Direct analysis

```powershell
python manage.py analyze_new_games
python manage.py analyze_new_games --username someplayer
python manage.py analyze_new_games --limit 10
python manage.py analyze_new_games --reanalyze
```

### Queue and run async jobs

```powershell
python manage.py enqueue_analysis_jobs
python manage.py enqueue_analysis_jobs --username someplayer
python manage.py enqueue_analysis_jobs --reanalyze
python manage.py run_analysis_worker --max-jobs 10
```

## Data Model Summary

### PlayerProfile

- Chess.com username
- role: `family`, `friend`, `others`
- active/inactive flag
- landing-page turning-point counts are shown only for `family` and `friend`

### Game

- tracked player
- opponent profile
- Chess.com game id and URL
- played timestamp
- white/black usernames
- white/black ratings when present
- owner color
- result
- time class
- source PGN

### TurningPoint

- linked player and game
- move number and position FEN
- played move and best move in SAN
- eval before/after and eval drop
- label and explanation
- archive year/month

### AnalysisJob

- linked player and game
- pending/running/completed/failed status
- reanalyze flag
- claim metadata
- processed game and turning-point counts

## Notes For Public Repos

- Remove or override local-only paths before publishing
- Do not commit `.env` files with real values
- Do not commit third-party credentials, tokens, or private service endpoints
- Seeded player usernames, personal accounts, and local machine-specific values should stay out of public documentation

## Version History

See [CHANGELOG.md](C:/Users/ricky/workspace/chess-mistake-service/CHANGELOG.md).
