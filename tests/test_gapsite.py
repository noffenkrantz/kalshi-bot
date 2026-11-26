"""Offline tests for the results page: the simulated real-money account built from gap-tracker data."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from bot.gaps import available_at, size_bet
from bot.gapsite import build_data, render, write_site

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
T = lambda h: (NOW + timedelta(hours=h)).isoformat()
CFG = {"gaps": {"bankroll_usd": 100.0, "stake_usd": 10.0, "min_edge": 0.03}}


def bet(ticker, ts, price, fair, available, side="yes", starts=-20, team="Bromley"):
    return {"ts": T(ts), "ticker": ticker, "event": ticker.rsplit("-", 1)[0], "series": "KXEFLL2GAME",
            "league": "England - League 2", "team": team, "side": side, "price": price, "fair": fair,
            "edge": round(fair - price - 0.017, 4), **size_bet(10.0, price, available), "starts": T(starts),
            "pin_id": 1, "pin_teams": "Bromley vs Gillingham"}


def write(tmp, name, rows):
    (tmp / "data" / name).write_text("".join(json.dumps(r) + "\n" for r in rows))


def setup(tmp_path):
    (tmp_path / "data").mkdir()
    write(tmp_path, "gap_bets.jsonl", [
        bet("A-BRO", -30, 0.40, 0.45, 12),                       # 12 of 25 wanted: won
        bet("B-BRO", -29, 0.50, 0.55, 500),                      # 20 contracts: lost
        bet("C-BRO", -28, 0.30, 0.35, 0),                        # nothing for sale: left out
        bet("D-BRO", -27, 0.30, 0.35, None),                     # order book unreadable: left out
        bet("E-BRO", -2, 0.20, 0.26, 500, starts=6),             # still open
        {**bet("E-GIL", -2, 0.70, 0.76, 500, side="no", starts=6, team="Gillingham"), "event": "E"},  # same game again
    ])
    write(tmp_path, "gap_outcomes.jsonl", [{"ts": T(-10), "ticker": "A-BRO", "result": "yes"},
                                           {"ts": T(-8), "ticker": "B-BRO", "result": "no"}])
    write(tmp_path, "gap_snaps.jsonl", [
        {"ts": T(-30), "ticker": "A-BRO", "league": "England - League 2", "fair": 0.45, "bid": 0.38, "ask": 0.40, "vol24": 50},
        {"ts": T(-21), "ticker": "A-BRO", "league": "England - League 2", "fair": 0.48, "bid": 0.46, "ask": 0.48, "vol24": 50},
        {"ts": T(-2), "ticker": "E-BRO", "league": "England - League 2", "fair": 0.26, "bid": 0.18, "ask": 0.20, "vol24": 5},
        {"ts": T(-1), "ticker": "E-BRO", "league": "England - League 2", "fair": 0.30, "bid": 0.27, "ask": 0.29, "vol24": 5},
        {"ts": T(-1), "ticker": "X-ITF", "league": "ITF Men", "fair": 0.50, "bid": 0.10, "ask": 0.90, "vol24": 0},
    ])


def test_account_counts_only_fillable_contracts_with_kalshis_fee(tmp_path):
    setup(tmp_path)
    d = build_data(tmp_path, CFG, NOW)
    A = d["account"]
    # A: 12 x 40c = 4.80 + fee ceil(0.07*12*.4*.6)=0.21 -> cost 5.01, pays 12 -> +6.99
    # B: 20 x 50c = 10.00 + fee ceil(0.07*20*.25)=0.35 -> cost 10.35, lost -> -10.35
    assert A["settled_n"] == 2 and A["wins"] == 1 and A["losses"] == 1
    assert A["realized"] == round(6.99 - 10.35, 2) and A["balance"] == round(100 + 6.99 - 10.35, 2)
    assert A["missed_n"] == 1 and A["unknown_n"] == 1 and A["placed_n"] == 3 and A["same_game_n"] == 1
    (o,) = d["open"]
    assert o["n"] == 50 and o["fair_now"] == 0.30 and o["ev"] == round(50 * 0.30 - o["cost"], 2)
    assert A["projected"] == round(A["balance"] + o["ev"], 2) and d["proj_line"] == [[T(-8), 96.64], [NOW.isoformat(), A["projected"]]]
    assert [p[1] for p in d["real_line"]] == [100.0, 106.99, 96.64, 96.64]
    assert d["settled"][0]["won"] is False
    assert d["scan"]["rows"] == 5
    V = d["verdict"]
    assert V["state"] == "early" and V["n"] == 2 and V["settled"] == 2 and V["profit"] == -3.36


def test_cash_runs_out(tmp_path):
    setup(tmp_path)
    d = build_data(tmp_path, {"gaps": {**CFG["gaps"], "bankroll_usd": 12.0}}, NOW)
    assert d["account"]["no_cash_n"] >= 1          # B (10.35) didn't fit after A (5.01) out of $12


def test_page_is_written_and_injection_safe(tmp_path):
    setup(tmp_path)
    rows = (tmp_path / "data" / "gap_bets.jsonl").read_text().replace("Bromley vs Gillingham", "</script><img src=x onerror=alert(1)>")
    (tmp_path / "data" / "gap_bets.jsonl").write_text(rows)
    write_site(tmp_path, CFG, NOW)
    html = (tmp_path / "site" / "index.html").read_text()
    assert "/*__DATA__*/" not in html and "</script><img" not in html and "\\u003c/script\\u003e" in html
    assert json.loads((tmp_path / "site" / "gaps.json").read_text())["account"]["settled_n"] == 2
    write_site(tmp_path, CFG, NOW + timedelta(hours=1), page=False)        # data only: the page is untouched
    assert (tmp_path / "site" / "index.html").read_text() == html


class Book:
    def __init__(self, ob):
        self.ob = ob

    def request(self, method, path, params=None):
        return self.ob


def test_available_at_reads_both_order_book_formats():
    fp = {"orderbook_fp": {"yes_dollars": [["0.3800", "70.00"], ["0.3500", "30.00"]], "no_dollars": [["0.6000", "12.00"], ["0.5900", "40.00"]]}}
    assert available_at(Book(fp), "T", "yes", 0.40) == 12          # NO bids at 60c+ = YES offers at 40c or less
    assert available_at(Book(fp), "T", "yes", 0.41) == 52
    assert available_at(Book(fp), "T", "no", 0.62) == 70           # YES bids at 38c+ = NO offers at 62c or less
    legacy = {"orderbook": {"yes": [[38, 70]], "no": [[60, 12]]}}
    assert available_at(Book(legacy), "T", "yes", 0.40) == 12
    assert size_bet(10, 0.40, 12) == {"contracts": 25, "available": 12, "filled": 12}
    assert size_bet(10, 0.40, None)["filled"] is None


def test_verdict_reads():
    from bot.gapsite import verdict
    mk = lambda clv, i: {"ts": f"2026-11-{10 + i // 24:02d}T{i % 24:02d}:00", "clv": clv}
    assert verdict([mk(0.03, i) for i in range(5)], [])["state"] == "early"                  # fewer than 10 bets
    good = [mk(0.03 + (0.01 if i % 2 else -0.01), i) for i in range(30)]                  # steady +3c
    v = verdict(good, [])
    assert v["state"] == "promising" and v["beat"] == 30 and v["profit_state"] == "early"
    noisy = [mk(0.10 if i % 2 else -0.09, i) for i in range(20)]                           # +0.5c but all over the place
    assert verdict(noisy, [])["state"] == "leaning"
    assert verdict([mk(-0.02, i) for i in range(20)], [])["state"] == "not_working"
    old_bad = [mk(-0.05, i) for i in range(60)] + [mk(0.03 + (0.01 if i % 2 else -0.01), 60 + i) for i in range(50)]
    assert verdict(old_bad, [])["state"] == "promising"          # reads the latest 50 bets
    done = [{"profit": 1.0, "result": "yes", "side": "yes"}] * 400
    assert verdict(good, done)["profit_state"] == "ahead"


def test_page_carries_its_design_version(tmp_path):
    from bot.gapsite import page_version
    setup(tmp_path)
    d = write_site(tmp_path, CFG, NOW)
    assert d["page"] == page_version() and len(d["page"]) == 10
    assert json.loads((tmp_path / "site" / "gaps.json").read_text())["page"] == d["page"]
    assert f'"page":"{d["page"]}"' in (tmp_path / "site" / "index.html").read_text()
