"""Balance-over-time chart for the dashboard, drawn as a plain SVG image.

The real balance (settled bets only) is the solid line, stepping when a bet settles, with an
end dot, a surface ring and a direct value label. The projection (open bets that have moved,
at today's prices) is a thin dashed line in a quieter color, labeled at its end. Hairline
gridlines and a labeled reference line at the starting balance. Light and dark versions use the same roles stepped for each surface. It's a static
image in the README, so there's no hover layer; the trade tables carry the detail.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

THEMES = {
    "light": {"surface": "#fcfcfb", "text": "#0b0b0b", "text2": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "baseline": "#c3c2b7", "series": "#2a78d6", "proj": "#7c7b76"},
    "dark": {"surface": "#1a1a19", "text": "#f0efec", "text2": "#c3c2b7", "muted": "#898781",
             "grid": "#2c2c2a", "baseline": "#383835", "series": "#3987e5", "proj": "#a3a29c"},
}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
W, H = 720, 280
LEFT, RIGHT, TOP, BOTTOM = 72, 104, 20, 36


def _nice_step(span: float, target_ticks: int = 4) -> float:
    raw = max(span, 1e-9) / target_ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _signed(v: float) -> str:
    return ("+" if v >= 0 else "−") + f"${abs(v):,.0f}"


def _x_ticks(t0: datetime, t1: datetime, tz: ZoneInfo) -> list[tuple[datetime, str]]:
    span_days = (t1 - t0).total_seconds() / 86400
    if span_days < 1.5:   # short history: label each end with its time
        fmt = lambda d: d.strftime("%I %p").lstrip("0")
        return [(t0, fmt(t0.astimezone(tz))), (t1, fmt(t1.astimezone(tz)))]
    every = max(1, math.ceil(span_days / 6))
    d = (t0.astimezone(tz) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    while d <= t1.astimezone(tz):
        out.append((d, f"{d:%b} {d.day}"))
        d += timedelta(days=every)
    return out


def balance_svg(points: list[tuple[datetime, float]], start: float, theme: str = "light",
                tz: ZoneInfo | None = None, projected: list[tuple[datetime, float]] | None = None) -> str:
    c = THEMES[theme]
    tz = tz or ZoneInfo("America/New_York")
    points = sorted(points)
    if not points:
        points = [(datetime.now(tz), start)]
    proj = sorted(projected or [])
    show_proj = any(abs(v - points[-1][1]) >= 0.01 for _, v in proj[-1:]) or any(
        abs(v - start) >= 0.01 for _, v in proj)
    t0 = min([points[0][0]] + [t for t, _ in proj])
    t1 = max([points[-1][0]] + [t for t, _ in proj])
    if t1 <= t0:                          # a single point sits at the right edge, by its label
        t0 = t1 - timedelta(hours=4)
    values = [v for _, v in points] + [start] + ([v for _, v in proj] if show_proj else [])
    lo, hi = min(values), max(values)
    if hi - lo < 400:                     # bets are $100, so show at least a $400 window
        mid = (hi + lo) / 2
        lo, hi = mid - 200, mid + 200
    step = _nice_step(hi - lo)
    y_lo, y_hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
    if y_hi - y_lo < 2 * step:
        y_hi += step
    pw, ph = W - LEFT - RIGHT, H - TOP - BOTTOM

    def x(t: datetime) -> float:
        return LEFT + (t - t0).total_seconds() / (t1 - t0).total_seconds() * pw

    def y(v: float) -> float:
        return TOP + (y_hi - v) / (y_hi - y_lo) * ph

    now_v = points[-1][1]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-labelledby="t d" font-family="{FONT}">',
        f'<title id="t">Simulated balance over time</title>',
        f'<desc id="d">Balance {_money(now_v)}, {_signed(now_v - start)} since the {_money(start)} start, '
        f'across {len(points)} runs.</desc>',
        f'<rect width="{W}" height="{H}" rx="12" fill="{c["surface"]}"/>',
    ]
    # gridlines + y labels
    v = y_lo
    while v <= y_hi + 1e-9:
        yy = round(y(v)) + 0.5
        parts.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{yy}" y2="{yy}" stroke="{c["grid"]}" stroke-width="1"/>')
        parts.append(f'<text x="{LEFT - 10}" y="{yy + 4}" text-anchor="end" font-size="12" fill="{c["muted"]}" '
                     f'style="font-variant-numeric: tabular-nums">{_money(v)}</text>')
        v += step
    # x labels
    for t, label in _x_ticks(t0, t1, tz):
        anchor = "start" if t == t0 else ("end" if t == t1 else "middle")
        parts.append(f'<text x="{x(t):.1f}" y="{H - 12}" text-anchor="{anchor}" font-size="12" '
                     f'fill="{c["muted"]}">{label}</text>')
    # starting-balance reference line, labeled
    ys = round(y(start)) + 0.5
    parts.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{ys}" y2="{ys}" stroke="{c["baseline"]}" stroke-width="1.5"/>')
    label_y = ys - 6 if y(start) - TOP > 18 else ys + 15
    parts.append(f'<text x="{LEFT + 6}" y="{label_y}" font-size="11" fill="{c["text2"]}">'
                 f'Start {_money(start)}</text>')
    # projection: dashed, quieter, labeled at its end
    if show_proj and len(proj) > 1:
        d = " ".join(f'{"M" if i == 0 else "L"}{x(t):.1f},{y(val):.1f}' for i, (t, val) in enumerate(proj))
        parts.append(f'<path d="{d}" fill="none" stroke="{c["proj"]}" stroke-width="1.5" stroke-dasharray="5 4" '
                     f'stroke-linejoin="round"/>')
    # the real line, stepping when a bet settles
    if len(points) > 1:
        d = f"M{x(points[0][0]):.1f},{y(points[0][1]):.1f}" + "".join(
            f" H{x(t):.1f} V{y(val):.1f}" for t, val in points[1:])
        parts.append(f'<path d="{d}" fill="none" stroke="{c["series"]}" stroke-width="2.5" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
    # end dot with surface ring + direct label
    ex, ey = x(points[-1][0]), y(now_v)
    if show_proj:
        pv = proj[-1][1]
        px, py = x(proj[-1][0]), y(pv)
        # the real line's labels take ey-10..ey+21; keep the projection's label clear of them
        label_y = py + 4 if abs(py - ey) >= 34 else (ey + 36 if py >= ey else ey - 16)
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{c["surface"]}" stroke="{c["proj"]}" stroke-width="1.5"/>')
        parts.append(f'<text x="{px + 10:.1f}" y="{label_y:.1f}" font-size="11" fill="{c["text2"]}" '
                     f'style="font-variant-numeric: tabular-nums">Projected {_money(pv)}</text>')
    parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="5" fill="{c["series"]}" stroke="{c["surface"]}" stroke-width="2"/>')
    parts.append(f'<text x="{ex + 10:.1f}" y="{ey + 1:.1f}" font-size="14" font-weight="600" fill="{c["text"]}" '
                 f'style="font-variant-numeric: tabular-nums">{_money(now_v)}</text>')
    parts.append(f'<text x="{ex + 10:.1f}" y="{ey + 17:.1f}" font-size="12" fill="{c["text2"]}" '
                 f'style="font-variant-numeric: tabular-nums">{_signed(now_v - start)}</text>')
    if len(points) == 1:
        parts.append(f'<text x="{LEFT + pw / 2:.0f}" y="{TOP + ph / 2 + 30:.0f}" text-anchor="middle" font-size="12" '
                     f'fill="{c["muted"]}">The line grows with each run</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def write_balance_charts(points: list[tuple[datetime, float]], start: float, out_dir, tz: ZoneInfo,
                         projected: list[tuple[datetime, float]] | None = None) -> None:
    for theme in ("light", "dark"):
        (out_dir / f"balance-{theme}.svg").write_text(balance_svg(points, start, theme, tz, projected))
