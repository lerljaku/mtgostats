"""Flask web UI for MTGO match statistics."""
from __future__ import annotations

import threading
from collections import Counter
from datetime import datetime

from flask import Flask, abort, redirect, render_template, request, url_for

from . import logparser, stats


class Store:
    """Parsed matches held in memory; re-parsed on demand (hundreds of logs parse in ~1s)."""

    def __init__(self, roots: list[str], hero: str | None):
        self.roots = roots
        self.hero_override = hero
        self.lock = threading.Lock()
        self.reload()

    def reload(self):
        with self.lock:
            raw, self.errors = logparser.load_matches(self.roots)
            self.hero = self.hero_override or logparser.detect_hero(raw)
            self.matches = logparser.assign_perspective(raw, self.hero) if self.hero else []
            self.loaded_at = datetime.now()
            self.by_id = {m.id: m for m in self.matches}


def create_app(roots: list[str], hero: str | None = None) -> Flask:
    app = Flask(__name__)
    store = Store(roots, hero)

    def current_filters() -> dict:
        return {k: request.args.get(k, "") for k in ("deck", "opp_deck", "period", "fmt", "opponent")}

    def filtered() -> list:
        f = current_filters()
        return stats.filter_matches(store.matches, f["deck"], f["opp_deck"],
                                    f["period"] or "all", f["fmt"], f["opponent"])

    @app.context_processor
    def inject():
        decks = Counter(m.hero_deck for m in store.matches)
        opp_decks = Counter(m.opp_deck for m in store.matches)
        return {
            "store": store,
            "filters": current_filters(),
            "deck_options": [d for d, _ in decks.most_common()],
            "opp_deck_options": [d for d, _ in opp_decks.most_common()],
            "format_options": sorted({m.format for m in store.matches}),
            "periods": list(stats.PERIODS),
            "pct": lambda v: "-" if v is None else f"{v * 100:.0f}%",
            "args_with": lambda **kw: {**{k: v for k, v in current_filters().items() if v}, **kw},
        }

    @app.route("/")
    def overview():
        ms = filtered()
        return render_template("overview.html", ov=stats.overview(ms), trend=stats.trend(ms),
                               lands=stats.land_drop_stats(ms), n_matches=len(ms))

    @app.route("/decks")
    def decks():
        ms = filtered()
        return render_template("decks.html",
                               decks=stats.group_records(ms, lambda m: m.hero_deck),
                               matchups=stats.group_records(ms, lambda m: m.opp_deck),
                               opponents=stats.group_records(ms, lambda m: m.opponent))

    @app.route("/cards")
    def cards():
        ms = filtered()
        side = request.args.get("side", "hero")
        min_games = request.args.get("min", 3, type=int)
        show_lands = request.args.get("lands") == "1"
        rows = stats.card_stats(ms, side=side, min_games=min_games)
        if not show_lands:
            rows = [r for r in rows if not r["land"]]
        baseline = stats.overview(ms)["game"]
        return render_template("cards.html", rows=rows, side=side, min_games=min_games,
                               show_lands=show_lands, baseline=baseline)

    @app.route("/matches")
    def matches():
        return render_template("matches.html", matches=list(reversed(filtered())))

    @app.route("/match/<match_id>")
    def match(match_id):
        m = store.by_id.get(match_id)
        if not m:
            abort(404)
        return render_template("match.html", m=m)

    @app.post("/rescan")
    def rescan():
        store.reload()
        return redirect(request.referrer or url_for("overview"))

    return app
