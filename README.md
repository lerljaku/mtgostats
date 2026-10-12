# MTGO Stats

A local web app that reads your Magic: The Gathering Online match history and shows
win-rate, matchup and card-performance statistics.

It reads the game logs MTGO already writes to disk, so there is nothing to export
and no account or internet connection is needed. Everything runs on your machine.

## Quick start

Requires Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Your browser opens at <http://127.0.0.1:5000>. After playing more matches, click
**Rescan logs** in the header to pick them up without restarting.

### Options

| Flag | Purpose |
|---|---|
| `--logs <folder>` | Also scan this folder for logs (searched recursively). Repeatable. |
| `--no-default-logs` | Don't scan the default MTGO install folder; use only `--logs`. |
| `--player <name>` | Your MTGO username. Defaults to the player who appears in the most matches. |
| `--port <n>` | Port to serve on (default `5000`). |
| `--no-browser` | Don't open a browser on start. |

Example: read a backup folder only, as a specific player:

```powershell
.venv\Scripts\python.exe main.py --no-default-logs --logs D:\mtgo-backup --player konviczka
```

## Where the data comes from

MTGO saves one `Match_GameLog_<id>.dat` file per match under

```
%LOCALAPPDATA%\Apps\2.0\Data\...\AppFiles\...\
```

The app finds these automatically. MTGO keeps a separate copy for each client
version, so duplicates are removed by file name (the largest copy is kept).

MTGO may clean up old logs over time. To keep your full history, back up the
`Match_GameLog_*.dat` files now and then and point `--logs` at the backup.

## What you get

All pages share filters for **period**, **my deck** and **opponent deck**.

- **Overview**
  - Match and game win rate with 95% confidence intervals, current streak, average game length, concessions
  - Win rate over time (last 20 matches and all-time)
  - Win rate by: play vs. draw · game 1 vs. post-board games · winning or losing game 1 · die roll ·
    your mulligans · opponent mulligans · game length in turns and minutes · land drops on turns 1–3 ·
    day of week · time of day
- **Decks & matchups** – win rates per deck, per opposing deck and per opponent, split by play/draw.
  Click any row to filter the whole app by it.
- **Cards**
  - *My cards*: win rate in games where you used a card vs. games where you didn't, the difference,
    how many of those games you actually cast it, win rate when used by turn 3, average turn first used,
    win rate in games where you discarded it, and win rate in games where it was in your graveyard
    (discarded, milled, sacrificed, surveilled, or cast/returned from there). The last two are for
    reanimator and other graveyard decks; MTGO doesn't log creatures dying or spells resolving, so
    those don't count toward "in graveyard".
    A card is *used* when it is cast, played, discarded, cycled, triggers, has an ability activated,
    or attacks – so graveyard cards like Poxwalkers count when they return, not only when cast.
  - *Opponents' cards*: your win rate in games where the opponent used each card – which cards beat you.
- **Matches** – every match with result, decks and duration; each opens a page with the cards both
  players used per game and the full game log.

### Deck names

Decks are named after their commander (Duel Commander, etc.). In formats without a
commander, decks are grouped by how much their card lists overlap and named after
their three most-played cards.

## Reading the numbers carefully

- **Small samples lie.** Every win rate shows a 95% Wilson confidence interval
  (the whisker on charts, the *95% CI* column in tables). If it is wide, the number
  can't be trusted yet.
- **Card stats only see cards that did something.** The logs don't show
  what you drew or held in hand. Cards used while already winning, or in long games,
  look better than they are, and discards forced by an opponent's spell count as used.
  Treat a large difference as a hint, not proof.
- **Filter to one deck on the Cards page.** Otherwise "not used" mixes in games
  played with other decks.
- **Turns are counted per round**, the way MTGO does: both players have a "Turn 1".
- Matches where nobody won (e.g. the opponent disconnected and the log has no
  result) are shown as *Unfinished* and left out of win rates.

## Project layout

```
main.py                  command-line entry point
mtgostats/
  logparser.py           reads the binary .dat logs into Match / Game objects
  stats.py               win rates, confidence intervals, card and matchup aggregates
  app.py                 Flask routes and in-memory store
  templates/             Jinja pages
  static/charts.js       dependency-free SVG charts and sortable tables
  static/style.css       styles (light and dark mode follow the OS setting)
```

### Log file format

For anyone extending the parser: the files use .NET `BinaryWriter` conventions
(little-endian; strings are UTF-8 with a 7-bit varint length prefix).

```
header:  int16, string match_id, int16, string match_id
records: int64 DateTime ticks, string sender (empty in newer clients), string text
```

Text markup: `@P` comes before a player name, `@[Card Name@:catalogId,instanceId:@]`
marks a card, and `@i…@i` is italics.
