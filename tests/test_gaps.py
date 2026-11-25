"""Offline tests for the Pinnacle vs Kalshi gap tracker: fake pinnapi and fake Kalshi."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from bot.gaps import PinnAPI, PinnError, edges, event_when, name_score, no_vig, score_bets, snapshot

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
CFG = {"gaps": {"sports": ["soccer", "basketball", "hockey"], "daily_requests": 95}}


def test_no_vig_and_edges():
    f = no_vig({"home": 1.9, "away": 1.9})
    assert f == {"home": 0.5, "away": 0.5}
    f = no_vig({"home": 2.0, "draw": 3.5, "away": 3.6})
    assert abs(sum(f.values()) - 1) < 1e-9 and round(f["home"], 3) == 0.470
    e = edges(0.47, 0.38, 0.40)
    assert round(e["yes"][1], 4) == round(0.47 - 0.40 - 0.07 * 0.4 * 0.6, 4) and e["no"][1] < 0


def test_name_matching():
    assert name_score("Teodor Davidov", "Davidov T.") >= 0.8
    assert name_score("New York G", "New York Giants") >= 0.8
    assert name_score("Lowen Frankfurt", "Löwen Frankfurt") == 1.0 and name_score("Iserlohn", "Iserlohn Roosters") >= 0.8
    assert name_score("HC Sparta", "Sparta Prague") >= 0.8 and name_score("J. Smith", "John Smith") >= 0.8
    assert name_score("AC Milan", "Inter Milan") < 0.8 and name_score("Atletico Madrid", "Real Madrid") < 0.8
    assert name_score("A. Smith", "John Smith") < 0.8 and name_score("Sporting CP", "Sporting Gijon") < 0.8
    assert name_score("Manchester United", "Manchester City") < 0.8
    assert name_score("Bromley", "Gillingham") < 0.5


def test_event_when():
    d, t = event_when("KXINLGAME-26NOV251145BNEMAC")
    assert str(d) == "2026-11-25" and t == datetime(2026, 11, 25, 16, 45, tzinfo=timezone.utc)
    d, t = event_when("KXEFLL2GAME-26NOV25BROGIL")
    assert str(d) == "2026-11-25" and t is None


class FakeResp:
    def __init__(self, code, body, headers=None):
        self.status_code, self._body, self.headers = code, body, headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.seen = list(responses), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.seen.append((url, params, headers))
        return self.responses.pop(0)


def test_pinnapi_client_retries_once_and_never_leaks_the_key():
    s = FakeSession([FakeResp(429, {"error": "rate_limited"}, {"Retry-After": "2"}), FakeResp(200, {"events": []})])
    slept = []
    c = PinnAPI("SECRET-KEY", session=s, sleep=slept.append)
    assert c.prematch(1) == {"events": []} and slept == [2.0] and c.calls == 2
    url, params, headers = s.seen[0]
    assert "SECRET" not in url and params == {"sport_id": 1, "event_type": "prematch"}
    assert headers["x-portal-apikey"] == "SECRET-KEY"
    c = PinnAPI("SECRET-KEY", session=FakeSession([FakeResp(401, {"error": "invalid_key"})]))
    with pytest.raises(PinnError) as e:
        c.health()
    assert "SECRET" not in str(e.value) and "rejected" in str(e.value)


def ev(eid, league, home, away, starts, ml, parent=None):
    return {"event_id": eid, "league_name": league, "home": home, "away": away, "starts": starts.isoformat(),
            "parent_id": parent, "periods": {"num_0": {"money_line": ml}}}


class FakePinn:
    def __init__(self):
        self.calls, self.home_odds = 0, 2.0

    def prematch(self, sport_id):
        self.calls += 1
        start = NOW + timedelta(hours=5)
        if sport_id == 1:
            return {"events": [ev(10, "England - League Two", "Bromley", "Gillingham", start,
                                  {"home": self.home_odds, "draw": 3.5, "away": 3.6}),
                               ev(11, "England - League Two", "Bromley (Corners)", "Gillingham (Corners)", start,
                                  {"home": 1.8, "away": 2.0}, parent=10)]}
        if sport_id == 3:
            return {"events": [ev(20, "Israel - National League", "Bnei Herzliya", "Maccabi Ramat Gan",
                                  NOW + timedelta(hours=4, minutes=45), {"home": 1.70, "away": 2.20})]}
        return {"events": [ev(30, "Germany - DEL", "Iserlohn Roosters", "Lowen Frankfurt", start,
                              {"home": 2.3, "draw": 4.2, "away": 2.6})]}


def km(ticker, name, bid, ask):
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "yes_sub_title": name,
            "yes_bid_dollars": f"{bid:.4f}", "yes_ask_dollars": f"{ask:.4f}", "volume_24h_fp": "120.00"}


class FakeKalshi:
    def __init__(self):
        self.bro = (0.38, 0.40)
        self.results = {}

    def iter_markets(self, max_markets=1000, **p):
        assert p["status"] == "open"
        s = p["series_ticker"]
        if s == "KXEFLL2GAME":
            yield from [km("KXEFLL2GAME-26NOV25BROGIL-BRO", "Bromley", *self.bro),
                        km("KXEFLL2GAME-26NOV25BROGIL-GIL", "Gillingham", 0.25, 0.28),
                        km("KXEFLL2GAME-26NOV25BROGIL-TIE", "Tie", 0.24, 0.27)]
        elif s == "KXINLGAME":
            yield from [km("KXINLGAME-26NOV251145BNEMAC-BNE", "Bnei Herzliya", 0.55, 0.58),
                        km("KXINLGAME-26NOV251145BNEMAC-MAC", "Maccabi Ramat Gan", 0.41, 0.44)]
        elif s == "KXDELGAME":         # Kalshi counts overtime, Pinnacle's line is regulation only
            yield from [km("KXDELGAME-26NOV25ISELOW-ISE", "Iserlohn", 0.45, 0.48),
                        km("KXDELGAME-26NOV25ISELOW-LOW", "Lowen Frankfurt", 0.50, 0.53)]
        else:
            raise AssertionError(f"unexpected series {s}")

    def request(self, method, path, params=None):
        t = path.split("/")[-1]
        return {"market": {"ticker": t, "result": self.results.get(t, "")}}


def test_snapshot_bets_scores_and_settles(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "niche_survey.json").write_text(json.dumps({"series": [
        {"series": s, "category": "Sports"} for s in ("KXEFLL2GAME", "KXINLGAME", "KXDELGAME", "KXESOCCERGAME")]
        + [{"series": "KXEFLL2TOTAL", "category": "Sports"}, {"series": "KXHIGHNY", "category": "Climate and Weather"}]}))
    kalshi, pinn, quiet = FakeKalshi(), FakePinn(), (lambda *_: None)
    r = snapshot(kalshi, pinn, tmp_path, CFG, now=NOW, say=quiet)
    assert r == {"pinnacle_games": 3, "kalshi_games": 3, "matched": 2, "snaps": 5, "bets": 1, "settled": 0}
    (bet,) = [json.loads(l) for l in (tmp_path / "data" / "gap_bets.jsonl").read_text().splitlines()]
    assert bet["side"] == "yes" and bet["team"] == "Bromley" and bet["price"] == 0.40 and bet["contracts"] == 25
    assert 0.05 < bet["edge"] < 0.06

    # an hour before kick-off Pinnacle shortened Bromley and Kalshi followed: positive closing value
    pinn.home_odds, kalshi.bro = 1.85, (0.46, 0.48)
    r = snapshot(kalshi, pinn, tmp_path, CFG, now=NOW + timedelta(hours=4), say=quiet)
    assert r["bets"] == 0                                    # no second bet on the same outcome
    assert json.loads((tmp_path / "data" / "gap_state.json").read_text())["calls"] == 6

    kalshi.results["KXEFLL2GAME-26NOV25BROGIL-BRO"] = "yes"
    r = snapshot(kalshi, pinn, tmp_path, CFG, now=NOW + timedelta(hours=9), say=quiet)
    assert r["settled"] == 1 and r["pinnacle_games"] == 0    # the game has started: nothing new to compare
    (s,) = score_bets(tmp_path / "data")
    assert s["clv"] > 0.05 and s["kalshi_move"] > 0 and s["pinnacle_move"] > 0
    assert s["profit"] == round(25 * 0.6 - 25 * 0.07 * 0.4 * 0.6, 2)
    text = (tmp_path / "GAPS.md").read_text()
    assert "1 simulated bets so far" in text and "England - League Two" in text and "won $+14.58" in text


def test_budget_stops_requests(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "gap_state.json").write_text(json.dumps({"day": "2026-11-25", "calls": 94}))
    pinn = FakePinn()
    snapshot(FakeKalshi(), pinn, tmp_path, CFG, now=NOW, say=lambda *_: None)
    assert pinn.calls == 1                                   # only one request left of 95
