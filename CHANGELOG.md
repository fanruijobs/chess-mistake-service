# Changelog

## 0.0.7 - 2026-04-05

- Fixed Docker deployment static asset loading with WhiteNoise under `gunicorn`
- Added `collectstatic --noinput` to container startup so CSS and JavaScript are published on boot
- Added `whitenoise` to Python dependencies and enabled compressed manifest static file storage
- Added native Cairo build dependencies to the Docker image so image builds succeed with the PDF/static rendering stack

## 0.0.6 - 2026-04-05

- Added a default Django admin superuser seed with username `admin` and password `adminadmin`
- Added Docker support with a project `Dockerfile` and `.dockerignore`
- Added `docker-compose.yml` for the current SQLite-based deployment
- Configured container startup to run Django through `gunicorn` using `config.wsgi:application`
- Configured the service to bind to `0.0.0.0:8000` for access from the local network, including `192.168.x.x`
- Set the container runtime to use `2` gunicorn workers
- Declared deployment resource targets of `1 GB` RAM and `20 GB` storage in the compose setup
- Updated environment examples and public documentation for the new deployment flow

## 0.0.5 - 2026-04-05

- Added a `Next position` button on puzzle detail pages to move through a player's turning points in sequence
- Added a `Previous position` button on puzzle detail pages for two-way navigation through turning points
- Extended turning-point extraction to won games by analyzing the opponent's losing moves with the same Stockfish logic
- Added `Game.opponent_profile` as a foreign key to `PlayerProfile` and backfilled existing games with opponent profiles
- Imported `WhiteElo` and `BlackElo` from monthly Chess.com PGNs into `Game.white_rating` and `Game.black_rating` when present
- Added a role filter to the `PlayerProfile` admin changelist
- Added a `PlayerProfile` admin action to sync archived rapid games for the current month only

## 0.0.4 - 2026-04-05

- Split PDF export into two modes: wrong move only, and wrong move plus best move
- Added side-to-move and wrong-move text under exported positions
- Moved long-running analysis into queued async jobs at game granularity
- Kept admin actions as the triggers, but changed them to enqueue distributed analysis jobs
- Added a game admin action to queue analysis for selected games directly
- Added worker commands to process queued analysis jobs on one or more machines
- Made admin-triggered analysis auto-start a local background worker after queueing jobs
- Added logging for locally started analysis workers, including command and process id
- Updated player roles to `family`, `friend`, and `others`
- Backfilled `fanrui89` and `fanguoguo123` to `family`, with all other users defaulting to `others`

## 0.0.3 - 2026-04-04

- Removed hint text from exported PDFs so exported pages contain positions only
- Allowed up to 3 turning points per lost game instead of only 1
- Updated analysis flow and schema to support multi-turning-point games
- Added admin bulk actions to sync the current month plus previous 3 months for selected player profiles
- Added admin bulk actions to analyze new lost games for selected player profiles
- Added player filters to the game and turning-point admin changelists
- Added direct links from puzzle detail pages to both the original Chess.com game and the Chess.com analysis page
- Switched puzzle board rendering to server-generated SVG boards for reliable piece rendering
- Fixed board orientation so Black-owned positions render with Black at the bottom
- Made the outer board frame transparent instead of rendering a dark border

## 0.0.2 - 2026-04-04

- Switched sync to monthly Chess.com PGN downloads with request logging and curl fallback
- Filtered saved games to rapid games using `TimeControl >= 600`
- Added a bundled local Stockfish 18 binary and default engine path
- Saved analyzed moves in SAN notation instead of UCI
- Added year/month archive fields for turning points and archive-grouped puzzle browsing
- Added direct year/month archive navigation from landing and player pages
- Replaced archive list items with clickable board thumbnails
- Added reveal/hide best-move interaction on puzzle detail pages
- Changed user-facing identity to Chess.com usernames only
- Cleared stored `role` / `ui_mode` values and removed those labels from the UI
- Added PDF export for archived positions with a 2 columns x 3 rows per page layout
- Added versioned changelog tracking and updated README to version `0.0.2`

## 0.0.1

- Initial Django-based chess mistake service
- Monthly Chess.com PGN sync
- Stockfish turning point analysis
- Puzzle review UI
