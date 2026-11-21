"""The lessons file: data/lessons.md.

Plain Markdown so you can read it, and delete a lesson, from your phone.
Each lesson is one line:
- **[Topic]** The lesson text _(seen 2×, since 2026-11-23)_
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path

HEADER = """# Lessons Claude has learned

Written by Claude after reviewing its settled bets. Only **process mistakes** become lessons
(a misread rule, a stale source, missed information), never bad luck. Before researching a
market, Claude reads the lessons for that market's topic plus the ones marked [All].

To remove a lesson, edit this file and delete its line.

"""
LINE = re.compile(r"^- \*\*\[(?P<topic>[^\]]+)\]\*\* (?P<text>.+?)(?: _\(seen (?P<count>\d+)×(?:, since (?P<since>[\d-]+))?\)_)?\s*$")


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        m = LINE.match(line.strip())
        if m:
            out.append({"topic": m["topic"].strip(), "text": m["text"].strip(),
                        "count": int(m["count"] or 1), "since": m["since"] or ""})
    return out


def save(path: Path, lessons: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"- **[{l['topic']}]** {l['text']} _(seen {l['count']}×, since {l['since']})_" for l in lessons]
    body = "\n".join(lines) if lines else "_No lessons yet._"
    path.write_text(HEADER + body + "\n")


def add_or_reinforce(path: Path, topic: str, text: str, reinforces: int, day: str,
                     max_lessons: int = 30) -> str:
    """Returns 'added', 'reinforced' or 'skipped'."""
    lessons = load(path)
    if reinforces and 1 <= reinforces <= len(lessons):
        lessons[reinforces - 1]["count"] += 1
        save(path, lessons)
        return "reinforced"
    text = " ".join(text.split())[:300]
    if not text:
        return "skipped"
    if any(l["text"].lower() == text.lower() for l in lessons):
        return "skipped"
    lessons.append({"topic": (topic or "All").strip()[:40], "text": text, "count": 1, "since": day})
    if len(lessons) > max_lessons:  # drop the least-confirmed, oldest lesson
        weakest = min(range(len(lessons) - 1), key=lambda i: (lessons[i]["count"], lessons[i]["since"]))
        lessons.pop(weakest)
    save(path, lessons)
    return "added"


def numbered(lessons: list[dict]) -> str:
    return "\n".join(f"{i}. [{l['topic']}] {l['text']}" for i, l in enumerate(lessons, 1)) or "(none yet)"


def relevant(lessons: list[dict], topic: str) -> list[dict]:
    t = (topic or "").lower()
    return [l for l in lessons if l["topic"].lower() in ("all", t)]


def uses_lessons(ticker: str, holdout_share: float) -> bool:
    """A fixed ~20% of markets are researched WITHOUT lessons, as a control group."""
    return (zlib.crc32(ticker.encode()) % 100) >= round(holdout_share * 100)


def prompt_block(lessons: list[dict]) -> str:
    if not lessons:
        return ""
    items = "\n".join(f"- {l['text']}" for l in lessons)
    return ("\n\nLessons from reviewing your past settled bets (process lessons; apply where relevant, "
            "and don't let them override clear evidence):\n" + items)
