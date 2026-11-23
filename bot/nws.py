"""National Weather Service data (api.weather.gov): station observations and hourly forecasts.

Free and keyless. NWS asks every app to send a User-Agent that identifies it.
Rain amounts come from the raw METAR report's hourly "P" group (hundredths of an inch),
which is what the station itself reported, rather than from a decoded field.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.weather.gov"
USER_AGENT = "kalshi-bot (github.com/noffenkrantz/kalshi-bot)"


class NWSError(RuntimeError):
    pass


@dataclass
class Station:
    id: str             # ICAO, e.g. "KNYC"
    name: str
    tz: str             # IANA time zone, e.g. "America/New_York"
    lat: float
    lon: float


@dataclass
class Obs:
    time: datetime      # UTC
    raw: str            # raw METAR text
    precip_in: float | None   # rain since the previous hourly report, inches (0.0 = trace or none reported)
    report_type: str    # "METAR" (hourly) or "SPECI" (special)


_P_GROUP = re.compile(r"(?:^|\s)P(\d{4}|////)(?=\s|$)")


def metar_hourly_precip(raw: str) -> float | None:
    """Hourly precipitation from a METAR's remarks: P0012 = 0.12 in, P0000 = a trace.
    Returns None when the report has no P group (US stations omit it when nothing fell)."""
    rmk = raw.split(" RMK ", 1)[1] if " RMK " in raw else ""
    m = _P_GROUP.search(rmk)
    if not m or m.group(1) == "////":
        return None
    return int(m.group(1)) / 100.0


def climate_day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """NWS climate reports cover midnight to midnight LOCAL STANDARD TIME, all year
    (so 1 AM to 1 AM clock time during daylight saving). Returns (start, end) in UTC."""
    tz = ZoneInfo(tz_name)
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=tz)
    std_offset = noon.utcoffset() - (noon.dst() or timedelta(0))
    start = datetime(day.year, day.month, day.day, tzinfo=timezone(std_offset))
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


class NWSClient:
    def __init__(self, session: requests.Session | None = None, timeout: float = 20.0,
                 min_interval: float = 0.3):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.min_interval = min_interval
        self._last = 0.0
        self._stations: dict[str, Station] = {}
        self._hourly_url: dict[str, str] = {}

    def get(self, url: str, params: dict | None = None) -> dict:
        if not url.startswith("http"):
            url = BASE + url
        for attempt in range(3):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.session.get(url, params=params, timeout=self.timeout,
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"})
            except requests.RequestException as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise NWSError(f"GET {url}: network error: {e}") from e
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt + 1)
                continue
            if r.status_code >= 400:
                raise NWSError(f"GET {url} -> HTTP {r.status_code}: {r.text[:300]}")
            return r.json()
        raise NWSError(f"GET {url}: gave up after retries")

    def station(self, sid: str) -> Station:
        sid = sid.upper()
        if sid not in self._stations:
            d = self.get(f"/stations/{sid}")
            p = d.get("properties", {})
            lon, lat = (d.get("geometry") or {}).get("coordinates", [None, None])[:2]
            if not p.get("timeZone") or lat is None:
                raise NWSError(f"station {sid}: missing time zone or location")
            self._stations[sid] = Station(sid, p.get("name") or sid, p["timeZone"], float(lat), float(lon))
        return self._stations[sid]

    def observations(self, sid: str, start: datetime, end: datetime | None = None) -> list[Obs]:
        params = {"start": start.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
        if end:
            params["end"] = end.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        d = self.get(f"/stations/{sid.upper()}/observations", params)
        out = []
        for f in d.get("features", []):
            p = f.get("properties", {})
            raw = (p.get("rawMessage") or "").strip()
            ts = p.get("timestamp")
            if not ts:
                continue
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            out.append(Obs(t, raw, metar_hourly_precip(raw) if raw else None,
                           "SPECI" if raw.startswith("SPECI") else "METAR"))
        return sorted(out, key=lambda o: o.time)

    def hourly_pop(self, sid: str) -> list[tuple[datetime, datetime, float]]:
        """Hourly chance of precipitation at the station: [(start UTC, end UTC, 0..1)]."""
        st = self.station(sid)
        if sid not in self._hourly_url:
            pt = self.get(f"/points/{st.lat:.4f},{st.lon:.4f}")
            url = pt.get("properties", {}).get("forecastHourly")
            if not url:
                raise NWSError(f"no hourly forecast for {sid}")
            self._hourly_url[sid] = url
        d = self.get(self._hourly_url[sid])
        out = []
        for p in d.get("properties", {}).get("periods", []):
            s = datetime.fromisoformat(p["startTime"]).astimezone(timezone.utc)
            e = datetime.fromisoformat(p["endTime"]).astimezone(timezone.utc)
            pop = ((p.get("probabilityOfPrecipitation") or {}).get("value") or 0) / 100.0
            out.append((s, e, pop))
        return out
