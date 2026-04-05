# Chess Blunder Book System (Django) ¡ª v2

## 1. Project Goal

Build a system that:

- Fetches games from Chess.com (based on username)
- Analyzes only **lost games**
- Analyzes only **the player's own mistakes**
- Extracts **one main turning point per game**
- Generates a **blunder training (puzzle) system**
- Supports **multiple users (via Chess.com usernames)**

---

## 2. Core Principles

### 2.1 Turning Point Definition

A turning point is the **first move that changes the position from ¡°playable¡± to ¡°clearly difficult to save.¡±**

---

### 2.2 Analysis Scope

- Time range: **last 3 months**
- Time control: **blitz**
- Game result: **loss only**
- Per game: **max 1 turning point**

---

## 3. System Architecture

Chess.com API
      ¡ý
Sync Layer
      ¡ý
Game Storage
      ¡ý
Filter Layer (lost games)
      ¡ý
Engine Analysis (Stockfish 18)
      ¡ý
Turning Point Detection
      ¡ý
Classification
      ¡ý
Review System
      ¡ý
Django Admin + Templates UI

---

## 4. Tech Stack

- Backend: Django
- Database: SQLite (initially)
- Engine: Stockfish 18 (local binary)
- Scheduler: cron + Django management commands
- Frontend: Django Templates + JavaScript (chessboard)

---

## 5. PlayerProfile (Core Entity)

- id
- name
- slug
- chesscom_username (unique)
- role (self / daughter / other)
- ui_mode (adult / kid)
- is_active
- created_at

---

## 6. Data Models

### Game

- player_profile
- external_game_id
- url
- played_at
- white_username
- black_username
- owner_color
- result
- time_class
- pgn

### TurningPoint

- player_profile
- game
- move_number
- fen
- played_move
- best_move
- eval_before
- eval_after
- drop_cp
- label
- explanation

---

## 7. Sync Logic

- Fetch last 3 months
- Only blitz games
- Deduplicate by external_game_id

---

## 8. Engine

- Local Stockfish binary
- Absolute path
- Validate via UCI handshake

---

## 9. Turning Point Detection

- Analyze only player moves
- drop = eval_before - eval_after
- threshold >= 1.8
- select earliest collapse move

---

## 10. Scheduling

Commands:

python manage.py sync_chess_games
python manage.py analyze_new_games

Cron: run daily

---

## 11. Frontend

URLs:

/players/<slug>/
/players/<slug>/puzzles/
/players/<slug>/puzzles/<id>/

- Mobile-first
- Responsive layout
- Chessboard via FEN

---

## 12. Summary

Multi-user chess blunder system using Stockfish to generate training puzzles.
