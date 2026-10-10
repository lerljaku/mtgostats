"""Parser for MTGO `Match_GameLog_*.dat` files.

File layout (little-endian, .NET BinaryWriter conventions):
    header:  int16, string(match id), int16, string(match id)
    records: int64 DateTime ticks, string(sender, empty in newer clients), string(text)
Strings are UTF-8 prefixed with a 7-bit varint length.

Text markup: `@P` precedes a player name, `@[Card Name@:catalogId,instanceId:@]`
marks a card, `@i...@i` is italics.
"""
from __future__ import annotations

import glob
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CARD_RE = re.compile(r"@\[(.+?)@:\d+,\d+:@\]")
TURN_RE = re.compile(r"^Turn (\d+): (.+)$")
FORMAT_RE = re.compile(r"^This is an? (.+?) game\.$")
HAND_RE = re.compile(r"begins the game with (\w+) cards? in hand")
JOINED_RE = re.compile(r"^@P@P(.+) joined the game\.$")
ROLLED_RE = re.compile(r"^@P(.+) rolled a (\d+)\.$")
MATCH_WIN_RE = re.compile(r"wins the match (\d+)-(\d+)")

NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
TICKS_MASK = 0x3FFFFFFFFFFFFFFF  # strip DateTimeKind bits
DOTNET_EPOCH = datetime(1, 1, 1)


class LogFormatError(Exception):
    pass


# --------------------------------------------------------------------------- raw reading

def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if i >= len(buf):
            raise LogFormatError("truncated varint")
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return value, i


def _read_string(buf: bytes, i: int) -> tuple[str, int]:
    n, i = _read_varint(buf, i)
    if i + n > len(buf):
        raise LogFormatError("truncated string")
    return buf[i:i + n].decode("utf-8", "replace"), i + n


def read_records(path: str) -> tuple[str, list[tuple[datetime, str]]]:
    """Return (match id, [(timestamp, text), ...]) for one log file."""
    with open(path, "rb") as fh:
        buf = fh.read()
    i = 2
    match_id, i = _read_string(buf, i)
    i += 2
    _, i = _read_string(buf, i)
    records = []
    while i < len(buf):
        if i + 8 > len(buf):
            break  # partially written trailing record
        ticks = int.from_bytes(buf[i:i + 8], "little") & TICKS_MASK
        i += 8
        try:
            _sender, i = _read_string(buf, i)
            text, i = _read_string(buf, i)
        except LogFormatError:
            break
        records.append((DOTNET_EPOCH + timedelta(microseconds=ticks // 10), text))
    return match_id, records


# --------------------------------------------------------------------------- model

@dataclass
class Game:
    number: int
    start: datetime
    end: datetime
    on_play: str | None = None
    winner: str | None = None
    end_reason: str = "unknown"            # win | concede | timeout | unknown
    conceded_by: str | None = None
    turns: int = 0                          # highest turn number reached
    hand_size: dict[str, int] = field(default_factory=dict)
    mulligans: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # player -> {card name -> turn first cast/played}
    cards: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(dict))
    cast_counts: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    lands: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    land_drops: dict[str, dict[int, int]] = field(default_factory=lambda: defaultdict(Counter))
    commanders: dict[str, list[str]] = field(default_factory=dict)
    events: list[tuple[datetime, int, str | None, str]] = field(default_factory=list)

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass
class Match:
    id: str
    path: str
    start: datetime
    end: datetime
    format: str
    players: list[str]
    games: list[Game]
    winner: str | None
    score: tuple[int, int] | None = None   # (winner games, loser games) when known
    rolls: dict[str, int] = field(default_factory=dict)
    # filled in by assign_perspective()
    hero: str | None = None
    opponent: str | None = None
    result: str = "?"                      # W | L | ?
    hero_deck: str = "Unknown"
    opp_deck: str = "Unknown"

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


# --------------------------------------------------------------------------- parsing

def _actor(text: str, players: list[str]) -> tuple[str | None, str]:
    """Split '@P<name> rest' into (name, rest) using the known player list."""
    body = text
    while body.startswith("@P"):
        body = body[2:]
    for name in players:  # sorted longest-first so 'Foo Bar' beats 'Foo'
        if body.startswith(name + " ") or body.startswith(name + "'"):
            return name, body[len(name):].lstrip()
    return None, body


def plain(text: str) -> str:
    """Strip MTGO markup for display."""
    text = CARD_RE.sub(lambda m: m.group(1), text)
    return text.replace("@P", "").replace("@i", "")


def parse_match(path: str) -> Match | None:
    match_id, records = read_records(path)
    if not records:
        return None

    names: list[str] = []
    rolls: dict[str, int] = {}
    for _, text in records:
        if m := JOINED_RE.match(text):
            if m.group(1) not in names:
                names.append(m.group(1))
        elif m := ROLLED_RE.match(text):
            rolls[m.group(1)] = int(m.group(2))
    for name in rolls:
        if name not in names:
            names.append(name)
    by_length = sorted(names, key=len, reverse=True)

    fmt = "Unknown"
    games: list[Game] = []
    game: Game | None = None
    turn = 0
    match_winner = None
    score = None
    timeout_loser = None

    for ts, text in records:
        if m := FORMAT_RE.match(plain(text)):
            fmt = m.group(1)
            game = Game(number=len(games) + 1, start=ts, end=ts)
            games.append(game)
            turn = 0
            continue
        if game is None:  # older logs may lack the format banner
            game = Game(number=1, start=ts, end=ts)
            games.append(game)
        game.end = ts

        actor, rest = _actor(text, by_length)
        game.events.append((ts, turn, actor, plain(text)))

        if text.startswith("@PTurn "):
            if m := TURN_RE.match(text[2:]):
                turn = int(m.group(1))
                game.turns = max(game.turns, turn)
            continue
        if actor is None:
            continue

        if rest.startswith("plays @[") or rest.startswith("casts @["):
            card = CARD_RE.search(rest).group(1)
            game.cards[actor].setdefault(card, turn)
            game.cast_counts[actor][card] += 1
            if rest.startswith("plays"):
                game.lands[actor].add(card)
                game.land_drops[actor][turn] += 1
        elif rest.startswith("chooses to play first"):
            game.on_play = actor
        elif rest.startswith("chooses to draw first"):
            others = [p for p in names if p != actor]
            game.on_play = others[0] if others else None
        elif rest.startswith("mulligans to"):
            game.mulligans[actor] += 1
        elif m := HAND_RE.search(rest):
            game.hand_size[actor] = NUMBER_WORDS.get(m.group(1), 7)
        elif rest.startswith("chooses @[") and "as their commander" in rest:
            game.commanders[actor] = CARD_RE.findall(rest)
        elif rest.startswith("wins the game") or rest == "wins!":
            game.winner = actor
            if game.end_reason == "unknown":
                game.end_reason = "win"
        elif rest.startswith("has conceded"):
            game.conceded_by = actor
            game.end_reason = "concede"
            others = [p for p in names if p != actor]
            if game.winner is None and len(others) == 1:
                game.winner = others[0]
        elif rest.startswith("loses the game"):
            others = [p for p in names if p != actor]
            if game.winner is None and len(others) == 1:
                game.winner = others[0]
                game.end_reason = "win"
        elif rest.startswith("has run out of time"):
            timeout_loser = actor
            if game.winner is None:
                others = [p for p in names if p != actor]
                game.winner = others[0] if len(others) == 1 else None
                game.end_reason = "timeout"
        elif m := MATCH_WIN_RE.search(rest):
            match_winner = actor
            score = (int(m.group(1)), int(m.group(2)))

    # Drop empty shells (lobby join with no play) and work out the match winner.
    games = [g for g in games if g.turns > 0 or g.winner]
    if not games or len(names) < 2:
        return None
    for i, g in enumerate(games, 1):
        g.number = i
    if match_winner is None:
        wins = Counter(g.winner for g in games if g.winner)
        if wins and wins.most_common(1)[0][1] >= 2:
            match_winner = wins.most_common(1)[0][0]
        elif timeout_loser:
            others = [p for p in names if p != timeout_loser]
            match_winner = others[0] if len(others) == 1 else None

    return Match(id=match_id, path=path, start=records[0][0], end=records[-1][0],
                 format=fmt, players=names, games=games, winner=match_winner,
                 score=score, rolls=rolls)


# --------------------------------------------------------------------------- loading

def default_log_roots() -> list[str]:
    roots = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Apps", "2.0"))
    return roots


def find_log_files(roots: list[str]) -> list[str]:
    """All game logs under roots, deduplicated by file name (MTGO keeps copies per
    client version); the largest copy wins since it is the most complete."""
    best: dict[str, str] = {}
    for root in roots:
        for path in glob.glob(os.path.join(root, "**", "Match_GameLog_*.dat"), recursive=True):
            name = os.path.basename(path)
            if name not in best or os.path.getsize(path) > os.path.getsize(best[name]):
                best[name] = path
    return list(best.values())


def load_matches(roots: list[str]) -> tuple[list[Match], list[str]]:
    matches, errors = [], []
    for path in find_log_files(roots):
        try:
            m = parse_match(path)
        except Exception as exc:  # one bad file must not take down the app
            errors.append(f"{os.path.basename(path)}: {exc}")
            continue
        if m:
            matches.append(m)
    matches.sort(key=lambda m: m.start)
    return matches, errors


# --------------------------------------------------------------------------- perspective

def detect_hero(matches: list[Match]) -> str | None:
    counts = Counter(p for m in matches for p in m.players)
    return counts.most_common(1)[0][0] if counts else None


def _deck_label(match: Match, player: str) -> str | None:
    for g in match.games:
        if player in g.commanders:
            return " + ".join(g.commanders[player])
    return None


def _nonland_cards(match: Match, player: str) -> Counter:
    c = Counter()
    for g in match.games:
        for card in g.cards.get(player, {}):
            if card not in g.lands.get(player, set()):
                c[card] += 1
    return c


def _cluster_label(matches: list[Match], player_of) -> dict[str, str]:
    """Greedy Jaccard clustering of card sets for formats without commanders."""
    clusters: list[dict] = []
    labels = {}
    for m in matches:
        cards = set(_nonland_cards(m, player_of(m)))
        if not cards:
            continue
        best, best_score = None, 0.0
        for cl in clusters:
            core = {c for c, n in cl["freq"].items() if n >= max(1, cl["size"] * 0.3)}
            score = len(cards & core) / len(cards | core) if core else 0
            if score > best_score:
                best, best_score = cl, score
        if best is None or best_score < 0.2:
            best = {"freq": Counter(), "size": 0, "ids": []}
            clusters.append(best)
        best["freq"].update(cards)
        best["size"] += 1
        best["ids"].append(m.id)
    for cl in clusters:
        name = " / ".join(c for c, _ in cl["freq"].most_common(3))
        for mid in cl["ids"]:
            labels[mid] = name
    return labels


def assign_perspective(matches: list[Match], hero: str) -> list[Match]:
    """Set hero/opponent/result/deck labels. Matches without the hero are dropped."""
    mine = [m for m in matches if hero in m.players]
    for m in mine:
        m.hero = hero
        m.opponent = next((p for p in m.players if p != hero), "?")
        m.result = "?" if m.winner is None else ("W" if m.winner == hero else "L")
        m.hero_deck = _deck_label(m, hero) or "Unknown"
        m.opp_deck = _deck_label(m, m.opponent) or "Unknown"
    hero_needs = [m for m in mine if m.hero_deck == "Unknown"]
    opp_needs = [m for m in mine if m.opp_deck == "Unknown"]
    for mid, label in _cluster_label(hero_needs, lambda m: m.hero).items():
        next(m for m in hero_needs if m.id == mid).hero_deck = label
    for mid, label in _cluster_label(opp_needs, lambda m: m.opponent).items():
        next(m for m in opp_needs if m.id == mid).opp_deck = label
    return mine
