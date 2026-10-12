"""Aggregate statistics over parsed matches, always from the hero's perspective."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .logparser import Game, Match


# --------------------------------------------------------------------------- record helpers

def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval - honest error bars for small samples."""
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class Record:
    wins: int = 0
    losses: int = 0

    def add(self, won: bool):
        if won:
            self.wins += 1
        else:
            self.losses += 1

    @property
    def n(self) -> int:
        return self.wins + self.losses

    @property
    def wr(self) -> float | None:
        return self.wins / self.n if self.n else None

    @property
    def ci(self) -> tuple[float, float]:
        return wilson(self.wins, self.n)

    def as_dict(self, label: str = "") -> dict:
        lo, hi = self.ci
        return {"label": label, "wins": self.wins, "losses": self.losses, "n": self.n,
                "wr": self.wr, "lo": lo, "hi": hi}


def decided_games(m: Match):
    return [g for g in m.games if g.winner in (m.hero, m.opponent)]


def hero_won(m: Match, g: Game) -> bool:
    return g.winner == m.hero


# --------------------------------------------------------------------------- filtering

PERIODS = {"all": None, "7d": 7, "30d": 30, "90d": 90, "365d": 365}


def filter_matches(matches: list[Match], deck: str = "", opp_deck: str = "",
                   period: str = "all", fmt: str = "", opponent: str = "") -> list[Match]:
    out = matches
    if fmt:
        out = [m for m in out if m.format == fmt]
    if deck:
        out = [m for m in out if m.hero_deck == deck]
    if opp_deck:
        out = [m for m in out if m.opp_deck == opp_deck]
    if opponent:
        out = [m for m in out if m.opponent == opponent]
    days = PERIODS.get(period)
    if days:
        cutoff = datetime.now() - timedelta(days=days)
        out = [m for m in out if m.start >= cutoff]
    return out


# --------------------------------------------------------------------------- overview

def overview(matches: list[Match]) -> dict:
    match_rec, game_rec = Record(), Record()
    play, draw = Record(), Record()
    by_game_no = defaultdict(Record)
    roll_won, roll_lost = Record(), Record()
    hero_mull = defaultdict(Record)
    opp_mull = defaultdict(Record)
    length = defaultdict(Record)
    weekday = defaultdict(Record)
    hour = defaultdict(Record)
    duration = defaultdict(Record)
    conceded_by_hero = conceded_by_opp = 0
    turns, minutes = [], []
    after_g1 = {"W": Record(), "L": Record()}  # match WR after winning/losing G1

    for m in matches:
        if m.result in "WL":
            match_rec.add(m.result == "W")
            weekday[m.start.strftime("%a")].add(m.result == "W")
            hour[_hour_bucket(m.start.hour)].add(m.result == "W")
        if m.hero in m.rolls and m.opponent in m.rolls and m.result in "WL":
            (roll_won if m.rolls[m.hero] > m.rolls[m.opponent] else roll_lost).add(m.result == "W")
        games = decided_games(m)
        if games and m.result in "WL":
            after_g1["W" if hero_won(m, games[0]) else "L"].add(m.result == "W")
        for g in games:
            won = hero_won(m, g)
            game_rec.add(won)
            by_game_no["Game 1" if g.number == 1 else "Games 2-3 (post-board)"].add(won)
            if g.on_play == m.hero:
                play.add(won)
            elif g.on_play == m.opponent:
                draw.add(won)
            hero_mull[_mull_label(g.mulligans.get(m.hero, 0))].add(won)
            opp_mull[_mull_label(g.mulligans.get(m.opponent, 0))].add(won)
            length[_turn_bucket(g.turns)].add(won)
            duration[_minute_bucket(g.minutes)].add(won)
            turns.append(g.turns)
            minutes.append(g.minutes)
            if g.conceded_by == m.hero:
                conceded_by_hero += 1
            elif g.conceded_by == m.opponent:
                conceded_by_opp += 1

    def rows(d: dict, order: list[str]) -> list[dict]:
        return [d[k].as_dict(k) for k in order if k in d and d[k].n]

    mull_order = ["No mulligan", "Mull to 6", "Mull to 5", "Mull to 4 or less"]
    return {
        "match": match_rec.as_dict("Matches"),
        "game": game_rec.as_dict("Games"),
        "incomplete": sum(1 for m in matches if m.result == "?"),
        "play_draw": [play.as_dict("On the play"), draw.as_dict("On the draw")],
        "game_no": rows(by_game_no, ["Game 1", "Games 2-3 (post-board)"]),
        "after_g1": [after_g1["W"].as_dict("Won game 1"), after_g1["L"].as_dict("Lost game 1")],
        "roll": [roll_won.as_dict("Won the die roll"), roll_lost.as_dict("Lost the die roll")],
        "hero_mull": rows(hero_mull, mull_order),
        "opp_mull": rows(opp_mull, mull_order),
        "length": rows(length, TURN_BUCKETS),
        "duration": rows(duration, MINUTE_BUCKETS),
        "weekday": rows(weekday, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        "hour": rows(hour, HOUR_BUCKETS),
        "avg_turns": sum(turns) / len(turns) if turns else 0,
        "avg_minutes": sum(minutes) / len(minutes) if minutes else 0,
        "conceded_by_hero": conceded_by_hero,
        "conceded_by_opp": conceded_by_opp,
        "streaks": streaks(matches),
    }


TURN_BUCKETS = ["Turns 1-4", "Turns 5-6", "Turns 7-8", "Turns 9-11", "Turns 12+"]
MINUTE_BUCKETS = ["< 5 min", "5-10 min", "10-20 min", "20+ min"]
HOUR_BUCKETS = ["Night (0-6)", "Morning (6-12)", "Afternoon (12-18)", "Evening (18-24)"]


def _mull_label(n: int) -> str:
    return ["No mulligan", "Mull to 6", "Mull to 5"][n] if n < 3 else "Mull to 4 or less"


def _turn_bucket(t: int) -> str:
    # MTGO numbers turns per round: both players have a "Turn 1".
    if t <= 4:
        return TURN_BUCKETS[0]
    if t <= 6:
        return TURN_BUCKETS[1]
    if t <= 8:
        return TURN_BUCKETS[2]
    if t <= 11:
        return TURN_BUCKETS[3]
    return TURN_BUCKETS[4]


def _minute_bucket(mins: float) -> str:
    if mins < 5:
        return MINUTE_BUCKETS[0]
    if mins < 10:
        return MINUTE_BUCKETS[1]
    if mins < 20:
        return MINUTE_BUCKETS[2]
    return MINUTE_BUCKETS[3]


def _hour_bucket(h: int) -> str:
    return HOUR_BUCKETS[h // 6]


def streaks(matches: list[Match]) -> dict:
    best_w = best_l = cur = 0
    cur_kind = None
    for m in matches:
        if m.result not in "WL":
            continue
        if m.result == cur_kind:
            cur += 1
        else:
            cur_kind, cur = m.result, 1
        if cur_kind == "W":
            best_w = max(best_w, cur)
        else:
            best_l = max(best_l, cur)
    return {"current": f"{cur}{cur_kind}" if cur_kind else "-", "best_win": best_w, "worst_loss": best_l}


def trend(matches: list[Match], window: int = 20) -> list[dict]:
    """Rolling match win rate, one point per decided match."""
    points, results = [], []
    for m in matches:
        if m.result not in "WL":
            continue
        results.append(1 if m.result == "W" else 0)
        recent = results[-window:]
        points.append({"x": m.start.isoformat(timespec="minutes"),
                       "rolling": sum(recent) / len(recent),
                       "cumulative": sum(results) / len(results),
                       "n": len(results), "result": m.result,
                       "label": f"{m.result} vs {m.opponent} ({m.opp_deck})"})
    return points


# --------------------------------------------------------------------------- decks & matchups

def group_records(matches: list[Match], key) -> list[dict]:
    """Match + game records grouped by key(match), with play/draw splits."""
    groups: dict[str, dict] = defaultdict(lambda: {"match": Record(), "game": Record(),
                                                   "play": Record(), "draw": Record(),
                                                   "last": None})
    for m in matches:
        grp = groups[key(m)]
        grp["last"] = max(grp["last"] or m.start, m.start)
        if m.result in "WL":
            grp["match"].add(m.result == "W")
        for g in decided_games(m):
            won = hero_won(m, g)
            grp["game"].add(won)
            if g.on_play == m.hero:
                grp["play"].add(won)
            elif g.on_play == m.opponent:
                grp["draw"].add(won)
    rows = []
    for label, grp in groups.items():
        row = grp["match"].as_dict(label)
        row.update(game=grp["game"].as_dict(), play=grp["play"].as_dict(),
                   draw=grp["draw"].as_dict(), last=grp["last"])
        rows.append(row)
    rows.sort(key=lambda r: (-r["n"], r["label"]))
    return rows


# --------------------------------------------------------------------------- cards

def card_stats(matches: list[Match], side: str = "hero", min_games: int = 1) -> list[dict]:
    """Per-card game win rate (hero's perspective).

    side='hero': the hero's cards. 'Used' = the card did something that game (cast,
    played, discarded, cycled, triggered, activated, attacked), compared with games in
    the same filtered set where it did not.
    side='opp': the opponent's cards - which cards beat you.
    """
    games = [(m, g) for m in matches for g in decided_games(m)]
    total = Record()
    for m, g in games:
        total.add(hero_won(m, g))

    seen = defaultdict(Record)
    early = defaultdict(Record)  # first used on or before turn 3
    first_turn = defaultdict(list)
    casts = defaultdict(int)
    cast_games = defaultdict(int)
    discarded = defaultdict(Record)
    in_graveyard = defaultdict(Record)
    is_land = set()
    for m, g in games:
        player = m.hero if side == "hero" else m.opponent
        won = hero_won(m, g)
        cast = g.cards.get(player, {})
        for card, turn in g.used.get(player, {}).items():
            seen[card].add(won)
            first_turn[card].append(turn)
            if turn <= 3:
                early[card].add(won)
            if card in cast:
                cast_games[card] += 1
                casts[card] += g.cast_counts[player][card]
        for card in g.discarded.get(player, {}):
            discarded[card].add(won)
        for card in g.graveyard.get(player, {}):
            in_graveyard[card].add(won)
        is_land |= g.lands.get(player, set())

    rows = []
    for card, rec in seen.items():
        if rec.n < min_games:
            continue
        not_seen = Record(total.wins - rec.wins, total.losses - rec.losses)
        lo, hi = rec.ci
        rows.append({
            "card": card, "land": card in is_land, "games": rec.n,
            "share": rec.n / total.n if total.n else 0,
            "casts": casts[card], "cast_games": cast_games[card], "wins": rec.wins, "wr": rec.wr, "lo": lo, "hi": hi,
            "wr_not": not_seen.wr, "n_not": not_seen.n,
            "delta": (rec.wr - not_seen.wr) if not_seen.wr is not None else None,
            "early_wr": early[card].wr, "early_n": early[card].n,
            "discard_wr": discarded[card].wr, "discard_n": discarded[card].n,
            "gy_wr": in_graveyard[card].wr, "gy_n": in_graveyard[card].n,
            "avg_turn": sum(first_turn[card]) / len(first_turn[card]),
        })
    rows.sort(key=lambda r: (-r["games"], r["card"]))
    return rows


# --------------------------------------------------------------------------- mana

def land_drop_stats(matches: list[Match]) -> list[dict]:
    """Win rate by whether the hero hit their land drops on turns 1-4 of their own turns."""
    recs = defaultdict(Record)
    order = ["Hit 3 land drops by turn 3", "Missed a land drop by turn 3"]
    for m in matches:
        for g in decided_games(m):
            if g.turns < 4:  # game ended before both players finished turn 3
                continue
            drops = g.land_drops.get(m.hero, {})
            hit = sum(drops.get(t, 0) for t in (1, 2, 3)) >= 3
            recs[order[0] if hit else order[1]].add(hero_won(m, g))
    return [recs[k].as_dict(k) for k in order if recs[k].n]
