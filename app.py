#  I don't think this works.
# don't forget to change it anyway to app.py
# STILL this will not be what we want, no sign in page, and this day in doesnt work
# could also be a render issue

#!/usr/bin/env python3
"""
Patti-style "This Day" page + Basic Auth + Mini Calendar (birthdays highlighted)

What you asked for (minimal-risk / cautious load):
- A mini calendar card right below the hero.
- Month nav arrows (prev/next).
- Clickable days.
- Days with birthdays from birthdays.json are highlighted.
- A "Generate" button loads the facts for the selected day (so the page doesn't auto-load everything).
  - Implemented as a simple navigation to: /?date=MM-DD&show=1
  - If show != 1, the page renders ONLY the hero + calendar (no API calls, no “big content”)

Deploy on Render:
- Web Service
- Build: pip install -r requirements.txt
- Start: gunicorn app:app
- Env vars: APP_USER, APP_PASS
- Keep birthdays.json in repo root (or set BIRTHDAYS_FILE)

Local run:
  APP_USER=you APP_PASS=secret python app.py --serve --port 5000
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, Response, request

# -----------------------------
# Flask + Basic Auth
# -----------------------------
app = Flask(__name__)


def _basic_auth_required() -> Optional[Response]:
    expected_user = os.environ.get("APP_USER", "")
    expected_pass = os.environ.get("APP_PASS", "")
    if not expected_user or not expected_pass:
        return Response(
            "Server misconfigured: set APP_USER and APP_PASS environment variables.",
            status=500,
            mimetype="text/plain",
        )

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return Response(
            "Auth required",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Family Birthday Page"'},
        )

    try:
        decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        user, pw = decoded.split(":", 1)
    except Exception:
        return Response(
            "Bad auth header",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Family Birthday Page"'},
        )

    if user != expected_user or pw != expected_pass:
        return Response(
            "Unauthorized",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Family Birthday Page"'},
        )

    return None


# -----------------------------
# Constants
# -----------------------------
WIKIMEDIA_ONTHISDAY = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/all/{month}/{day}"
NUMBERSAPI_DATE = "http://numbersapi.com/{month}/{day}/date?json"

DEFAULT_SPORTS_KEYWORDS = [
    "Boston", "Red Sox", "Celtics", "Bruins", "Patriots", "Revolution",
    "Fenway", "TD Garden", "Gillette", "New England",
]

DEFAULT_ROCK_KEYWORDS = [
    "album", "single", "released", "release", "chart", "Billboard", "concert", "tour", "festival",
    "recorded", "recording", "debut", "hit", "band", "rock",
    "The Beatles", "Beatles", "Rolling Stones", "Stones", "Led Zeppelin", "Zeppelin",
    "Pink Floyd", "Floyd", "The Who", "Queen", "David Bowie", "Bowie",
    "Elton John", "AC/DC", "Aerosmith", "Bruce Springsteen", "Springsteen",
    "Tom Petty", "Nirvana", "Fleetwood Mac", "The Doors", "Jimi Hendrix", "Hendrix",
]

DEFAULT_TITLE = "Patti’s This Day Fun Facts"
DEFAULT_SUBTITLE = "History, sports-ish chaos, classic rock vibes, and family birthdays."
DEFAULT_OUT = "this_day.html"
DEFAULT_BIRTHDAYS = "birthdays.json"
DEFAULT_CACHE_DIR = ".cache_this_day"


# -----------------------------
# Helpers
# -----------------------------
def parse_mm_dd(s: str) -> Tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2})-(\d{1,2})\s*", s)
    if not m:
        raise ValueError("Date must be in MM-DD format, e.g. 12-18")
    month = int(m.group(1))
    day = int(m.group(2))
    _ = dt.date(2000, month, day)  # validate
    return month, day


def today_mm_dd() -> Tuple[int, int]:
    t = dt.date.today()
    return t.month, t.day


def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def ends_with_punct(s: str) -> bool:
    return s.strip().endswith((".", "!", "?"))


def sentence(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    return s if ends_with_punct(s) else (s + ".")


def normalize_phone(s: str) -> str:
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    return s.strip()


def extract_birth_name(birth_item: Dict[str, Any]) -> str:
    text = str(birth_item.get("text", "")).strip()
    if not text:
        return ""
    return text.split(",", 1)[0].strip()


def extract_year_text(item: Dict[str, Any]) -> Tuple[str, str]:
    year = str(item.get("year", "")).strip()
    text = str(item.get("text", "")).strip()
    return year, text


def pick_items(items: List[Dict[str, Any]], n: int, seed: int) -> List[Dict[str, Any]]:
    if not items:
        return []
    rng = random.Random(seed)
    if len(items) <= n:
        return items
    return rng.sample(items, n)


def filter_keywords(items: List[Dict[str, Any]], keywords: List[str]) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        _, text = extract_year_text(it)
        t = text.lower()
        if any(k.lower() in t for k in keywords):
            out.append(it)
    return out


def join_names_nicely(names: List[str]) -> str:
    names = [n.strip() for n in names if n.strip()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


# -----------------------------
# Tone / positivity heuristics
# -----------------------------
NEGATIVE_HINTS = [
    "war", "battle", "invasion", "massacre", "terror", "terrorist", "attack", "bomb",
    "assassination", "assassinated", "murder", "killed", "death", "died", "deadly",
    "execution", "genocide", "riot", "shooting",
    "earthquake", "tsunami", "hurricane", "tornado", "flood", "wildfire", "fire",
    "explosion", "crash", "derail", "disaster", "catastrophe",
    "outbreak", "epidemic", "plague", "pandemic", "cholera",
    "arrest", "convicted", "sentenced",
]

POSITIVE_HINTS = [
    "won", "wins", "victory", "champion", "championship", "title",
    "founded", "opens", "opened", "launch", "launched",
    "released", "debut", "premiere",
    "first", "record", "breakthrough",
    "discovered", "invented", "created",
    "celebration", "festival", "concert",
]


def is_positiveish_text(text: str) -> bool:
    t = text.lower()
    if any(h in t for h in NEGATIVE_HINTS):
        return False
    return True


def pick_positiveish_item(items: List[Dict[str, Any]], seed: int) -> Optional[Dict[str, Any]]:
    if not items:
        return None
    rng = random.Random(seed)
    good, better = [], []
    for it in items:
        _, txt = extract_year_text(it)
        if not txt:
            continue
        if not is_positiveish_text(txt):
            continue
        good.append(it)
        t = txt.lower()
        if any(h in t for h in POSITIVE_HINTS):
            better.append(it)
    pool = better or good
    return rng.choice(pool) if pool else None


def pick_famous_birthdays(births: List[Dict[str, Any]], seed: int, n: int = 2) -> List[str]:
    if not births:
        return []
    rng = random.Random(seed + 4242)

    candidates = []
    for b in births:
        _, text = extract_year_text(b)
        if not text:
            continue
        if not is_positiveish_text(text):
            continue
        name = extract_birth_name(b)
        if name:
            candidates.append(name)

    seen = set()
    uniq = []
    for name in candidates:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(name)

    if not uniq:
        return []
    if len(uniq) <= n:
        return uniq
    return rng.sample(uniq, n)


# -----------------------------
# birthdays.json (unified entries incl phone)
# -----------------------------
def ensure_birthdays_file(path: Path) -> None:
    if path.exists():
        return
    template = [
        {"name": "Patti", "month": 5, "day": 14, "relation": "Mom", "note": "Chief Fun Fact Officer", "phone": "000-000-0000"},
    ]
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")


def load_birthdays(path: Path) -> List[Dict[str, Any]]:
    ensure_birthdays_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("birthdays.json must contain a JSON array of entries.")
    for item in data:
        if isinstance(item, dict) and item.get("phone"):
            item["phone"] = normalize_phone(str(item.get("phone", "")).strip())
    return data


def birthdays_for_date(birthdays: List[Dict[str, Any]], month: int, day: int) -> List[Dict[str, Any]]:
    hits = []
    for b in birthdays:
        if safe_int(b.get("month")) == month and safe_int(b.get("day")) == day:
            hits.append(b)

    def sort_key(x: Dict[str, Any]) -> str:
        name = str(x.get("name", "")).strip()
        parts = name.split()
        last = parts[-1] if parts else ""
        return f"{last}|{name}".lower()

    return sorted(hits, key=sort_key)


def people_to_phone_list(birthdays: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for b in birthdays:
        if not isinstance(b, dict):
            continue
        phone = normalize_phone(str(b.get("phone", "")).strip())
        if not phone:
            continue
        label = str(b.get("name", "")).strip()
        out.append({"phone": phone, "label": label})

    # de-dupe by digits
    seen = set()
    uniq = []
    for p in out:
        d = "".join(ch for ch in p["phone"] if ch.isdigit())
        if d and d not in seen:
            seen.add(d)
            uniq.append(p)
    return uniq


def phones_to_to_field_text(phones: List[Dict[str, str]]) -> str:
    nums = [p.get("phone", "").strip() for p in phones if p.get("phone", "").strip()]
    return ", ".join(nums)


def build_birthday_index(birthdays: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Return:
      {"MM-DD": ["Name A", "Name B"], ...}
    Used by the calendar UI to highlight days and show tooltips.
    """
    idx: Dict[str, List[str]] = {}
    for b in birthdays:
        m = safe_int(b.get("month"))
        d = safe_int(b.get("day"))
        if m <= 0 or d <= 0 or m > 12 or d > 31:
            continue
        key = f"{m:02d}-{d:02d}"
        name = str(b.get("name", "")).strip()
        if not name:
            continue
        idx.setdefault(key, []).append(name)

    # sort names for nicer tooltips
    for k in list(idx.keys()):
        idx[k] = sorted(idx[k], key=lambda s: s.lower())
    return idx


# -----------------------------
# Simple cache (JSON)
# -----------------------------
def cache_get(cache_dir: Path, key: str) -> Optional[Dict[str, Any]]:
    p = cache_dir / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def cache_put(cache_dir: Path, key: str, obj: Dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{key}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# -----------------------------
# Web fetchers
# -----------------------------
def fetch_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> Dict[str, Any]:
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def wiki_on_this_day(month: int, day: int, cache_dir: Path) -> Dict[str, Any]:
    cache_key = f"wikimedia_onthisday_{month:02d}_{day:02d}"
    cached = cache_get(cache_dir, cache_key)
    if cached:
        return cached

    headers = {"User-Agent": "ThisDayPage/1.0 (family birthday generator)"}
    url = WIKIMEDIA_ONTHISDAY.format(month=month, day=day)
    data = fetch_json(url, headers=headers)
    cache_put(cache_dir, cache_key, data)
    return data


def fallback_fun_fact(month: int, day: int) -> str:
    date = dt.date(2000, month, day)
    day_of_year = int(date.strftime("%j"))
    date_label = date.strftime("%B %d").replace(" 0", " ")
    options = [
        f"{date_label} is day #{day_of_year} of the year — which means we’re {day_of_year} days into this year’s nonsense (and excellence).",
        f"On {date_label}, the calendar is basically shouting “main character energy” — use it responsibly.",
        f"Fun calendar magic: {date_label} happens exactly once per year. Statistically rare. Emotionally elite.",
        "Did you know? The best birthdays tend to land on days that end in “today.” Science-ish.",
    ]
    return random.choice(options)


def numbersapi_fun_fact(month: int, day: int, cache_dir: Path) -> str:
    cache_key = f"numbersapi_{month:02d}_{day:02d}"
    cached = cache_get(cache_dir, cache_key)
    if cached and isinstance(cached.get("text"), str) and cached["text"].strip():
        return cached["text"].strip()

    try:
        url = NUMBERSAPI_DATE.format(month=month, day=day)
        data = fetch_json(url)
        cache_put(cache_dir, cache_key, data)
        text = str(data.get("text", "")).strip()
        if text:
            return text
    except Exception:
        pass

    return fallback_fun_fact(month, day)


# -----------------------------
# Summary + HTML
# -----------------------------
def make_sms_summary(
    date_label: str,
    fun_fact: str,
    featured_events: List[Dict[str, Any]],
    bostonish_featured: List[Dict[str, Any]],
    rock_featured: List[Dict[str, Any]],
    birthday_hits: List[Dict[str, Any]],
    famous_bdays: List[str],
    seed: int,
) -> str:
    rng = random.Random(seed + 999)

    headline_it = pick_positiveish_item(featured_events, seed + 1)
    sports_it = pick_positiveish_item(bostonish_featured, seed + 2)
    rock_it = pick_positiveish_item(rock_featured, seed + 3)

    openers = [
        f"🎉 Hear ye, hear ye: it’s {date_label} and the vibes are birthday-shaped.",
        f"✨ Family bulletin! {date_label} just walked in wearing confetti and demanding cake.",
        f"🎈Okay team: {date_label} fun facts incoming — helmets optional, joy required.",
        f"💌 A cheerful {date_label} dispatch from the ‘this day’ department of whimsy (now with extra sparkle).",
    ]
    s1 = sentence(rng.choice(openers))

    if headline_it:
        y, t = extract_year_text(headline_it)
        s2 = sentence(f"On this day in {y}: {t}")
    else:
        s2 = sentence("On this day in history: something interesting definitely happened, and we’re choosing to focus on the sparkle")

    s3 = sentence(f"Did you know? {fun_fact.strip()}")

    extras = []
    if sports_it:
        y, t = extract_year_text(sports_it)
        extras.append(sentence(f"🏟️ Boston sports corner: {y} — {t}"))
    if rock_it:
        y, t = extract_year_text(rock_it)
        extras.append(sentence(f"🎸 Classic rock time machine: {y} — {t}"))

    if famous_bdays:
        extras.append(sentence(f"⭐ Famous birthday roll call: {join_names_nicely(famous_bdays)} share this date too"))
        extras.append(sentence("So yes, today’s theme is: ‘legendary company, acceptable levels of chaos.’"))

    rituals = [
        "Today’s tiny mission: send one nice text, eat one good snack, and do one dramatic “ta-da!” for no reason.",
        "Birthday protocol: deploy emojis, deliver compliments, and do not let the cake-to-fun ratio fall below 1:1.",
        "Your assignment (should you choose to accept it): be kind, be goofy, and pretend you’re in a celebratory montage.",
        "Mandatory holiday for the soul: laugh once, hype someone up, and consider a second dessert purely on principle.",
    ]
    s4 = sentence(rng.choice(rituals))

    if birthday_hits:
        names = [str(x.get("name", "someone")).strip() for x in birthday_hits]
        names_joined = join_names_nicely(names)

        bday_lines = [
            f"🎂 And MOST importantly: happy birthday to {names_joined}! May your day be fun, your cake be generous, and your group chat be appropriately chaotic.",
            f"🥳 Birthday alert for {names_joined}! Wishing you big laughs, good food, and absolutely zero responsibilities (except enjoying yourself).",
            f"🎉 It’s {names_joined}’s birthday! Everyone send love, memes, and possibly a ridiculous amount of cake emojis. 🎂🎂🎂",
            f"🎈 Today we celebrate {names_joined}! Hope your day is a highlight reel and your year is even better.",
        ]
        s5 = sentence(rng.choice(bday_lines))
        s6 = sentence("Everybody say happy birthday right now (yes, even the lurkers) 🎊")
    else:
        s5 = sentence("And if it’s secretly your birthday and you didn’t tell us… congrats on the stealth mission. 😄")
        s6 = sentence("Still: you deserve a cookie for surviving today. 🍪")

    signoffs = [
        "Love you all — now go forth and be delightful.",
        "End of bulletin. Please celebrate responsibly (or at least enthusiastically).",
        "This message was brought to you by the Spirit of Patti™ and the Department of Good Vibes.",
        "Alright, that’s the report. Somebody cue the birthday playlist!",
    ]
    s7 = sentence(rng.choice(signoffs))

    parts = [s1, s2, s3]
    parts.extend(extras)
    parts.extend([s4, s5, s6, s7])
    return " ".join(p.strip() for p in parts if p.strip())


def html_page(
    title: str,
    subtitle: str,
    month: int,
    day: int,
    onthisday: Dict[str, Any],
    fun_fact: str,
    birthday_hits: List[Dict[str, Any]],
    phones: List[Dict[str, str]],
    sports_keywords: List[str],
    rock_keywords: List[str],
    seed: int,
    # NEW inputs for calendar gating
    birthdays_index: Dict[str, List[str]],
    show_facts: bool,
    debug_error: str = "",
) -> str:
    date_label = dt.date(2000, month, day).strftime("%B %d").replace(" 0", " ")

    # If we're not showing facts yet, keep these empty and avoid using them.
    events = (onthisday.get("events", []) or []) if show_facts else []
    births = (onthisday.get("births", []) or []) if show_facts else []

    featured_events = pick_items(events, n=6, seed=seed + 1) if show_facts else []
    featured_births = pick_items(births, n=6, seed=seed + 2) if show_facts else []

    bostonish_all = filter_keywords(events, sports_keywords) if show_facts else []
    bostonish_featured = pick_items(bostonish_all, n=5, seed=seed + 4) if show_facts else []

    rockish_all = filter_keywords(events, rock_keywords) if show_facts else []
    rockish_featured = pick_items(rockish_all, n=5, seed=seed + 5) if show_facts else []

    famous_bdays_summary = pick_famous_birthdays(births, seed=seed, n=2) if show_facts else []
    famous_bdays_card = pick_famous_birthdays(births, seed=seed + 7, n=6) if show_facts else []

    sms_summary = ""
    if show_facts:
        sms_summary = make_sms_summary(
            date_label=date_label,
            fun_fact=fun_fact,
            featured_events=featured_events,
            bostonish_featured=bostonish_featured,
            rock_featured=rockish_featured,
            birthday_hits=birthday_hits,
            famous_bdays=famous_bdays_summary,
            seed=seed,
        )

    to_field_text = phones_to_to_field_text(phones)

    def li_year_text(items_list: List[Dict[str, Any]]) -> str:
        if not items_list:
            return "<li><em>Nothing to show here (or the internet gremlins intervened).</em></li>"
        rows = []
        for it in items_list:
            year, text = extract_year_text(it)
            rows.append(f"<li><span class='year'>{html.escape(year)}</span> {html.escape(text)}</li>")
        return "\n".join(rows)

    def famous_bday_list(names: List[str]) -> str:
        if not names:
            return "<div class='sub' style='margin-top:8px;'><em>No famous birthdays surfaced today — which means the family gets the spotlight. 😄</em></div>"
        items = "".join(f"<li>{html.escape(n)}</li>" for n in names)
        return f"""
          <div class="sub" style="margin-top:10px;">⭐ <strong>Famous birthdays</strong> (aka “you’re in good company”):</div>
          <ul style="margin-top:6px;">{items}</ul>
          <div class="sub" style="margin-top:6px;">If any of these are your favorite, you’re allowed to claim “same birthday energy.”</div>
        """

    def birthday_block(hits: List[Dict[str, Any]]) -> str:
        if not hits:
            return "<p><em>No family birthdays listed for this date (yet).</em></p>"
        cards = []
        for h in hits:
            name = html.escape(str(h.get("name", "Someone Awesome")))
            relation = str(h.get("relation", "")).strip()
            relation_html = f"<div class='meta'>{html.escape(relation)}</div>" if relation else ""
            note = str(h.get("note", "")).strip()
            note_html = f"<div class='note'>{html.escape(note)}</div>" if note else ""
            phone = str(h.get("phone", "")).strip()
            phone_html = f"<div class='meta'>📱 {html.escape(phone)}</div>" if phone else ""
            cards.append(
                f"""
                <div class="bday-card">
                  <div class="bday-name">🎂 {name}</div>
                  {relation_html}
                  {phone_html}
                  {note_html}
                </div>
                """
            )
        return "\n".join(cards)

    if birthday_hits:
        names = [str(x.get("name", "someone")).strip() for x in birthday_hits]
        closer = f"And also, {join_names_nicely(names)} {'was' if len(names)==1 else 'were'} born on this day. Everybody say happy birthday! 🎉"
    else:
        closer = "And also: if someone in the family was born on this day, add them to birthdays.json and I’ll start bragging about it. 😄"

    # --- CSS (original pretty version) + NEW calendar styles ---
    css = r"""
:root{
  --font-hero: "Bebas Neue", ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
  --font-body: "Inter", ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
  --font-sms: "Fraunces", ui-serif, Georgia, "Times New Roman", serif;

  --bg:#0b1220;
  --card:#111b2e;
  --text:#e8edf7;
  --muted:#a7b4cc;

  --sox-red:#BD3039;
  --sox-navy:#0C2340;

  --celtics:#007A33;
  --bruins:#FFB81C;
  --pats-navy:#002244;
  --pats-red:#C60C30;

  --accent: color-mix(in srgb, var(--bruins) 55%, var(--sox-red) 45%);
  --accent2: color-mix(in srgb, var(--celtics) 55%, var(--pats-red) 45%);

  --scrollY: 0px;
}

*{ box-sizing:border-box; }
html,body{ height:100%; }
body{
  margin:0;
  font-family: var(--font-body);
  color:var(--text);
  background: var(--bg);
  overflow-x:hidden;
}

body::before{
  content:"";
  position:fixed;
  inset:-20vh -20vw;
  z-index:-3;
  background:
    radial-gradient(900px 480px at 18% 8%, rgba(120,220,232,0.12) 0%, rgba(11,18,32,0) 60%),
    radial-gradient(700px 420px at 88% 10%, rgba(255,184,28,0.10) 0%, rgba(11,18,32,0) 60%),
    radial-gradient(650px 420px at 20% 96%, rgba(189,48,57,0.10) 0%, rgba(11,18,32,0) 60%),
    radial-gradient(850px 520px at 78% 92%, rgba(0,122,51,0.10) 0%, rgba(11,18,32,0) 60%),
    linear-gradient(180deg, #0b1220 0%, #0b1220 100%);
  transform: translateY(calc(var(--scrollY) * -0.06)) scale(1.03);
  filter: saturate(1.05) contrast(1.05);
}

header{
  padding: 34px 20px 14px;
  max-width: 1040px;
  margin: 0 auto;
  position:relative;
}
.hero{
  border-radius: 22px;
  padding: 22px 20px 18px;
  border: 1px solid rgba(255,255,255,0.10);
  background:
    linear-gradient(135deg,
      rgba(17,27,46,0.92) 0%,
      rgba(17,27,46,0.74) 45%,
      rgba(17,27,46,0.90) 100%);
  box-shadow: 0 18px 50px rgba(0,0,0,0.45);
  overflow:hidden;
}
.hero::before{
  content:"";
  position:absolute;
  inset:-40%;
  background:
    radial-gradient(closest-side at 30% 40%, rgba(255,184,28,0.16), rgba(0,0,0,0) 60%),
    radial-gradient(closest-side at 75% 55%, rgba(189,48,57,0.14), rgba(0,0,0,0) 62%),
    radial-gradient(closest-side at 45% 95%, rgba(0,122,51,0.14), rgba(0,0,0,0) 64%);
  transform: translateY(calc(var(--scrollY) * -0.04)) rotate(-6deg);
  pointer-events:none;
}
h1{
  margin:0;
  font-family: var(--font-hero);
  font-size: 46px;
  letter-spacing: 0.7px;
  line-height: 1.0;
}
.hero-date{
  font-family: var(--font-body);
  font-size: 14px;
  color: var(--muted);
  margin-top: 8px;
}
.sub{
  margin-top: 10px;
  color: var(--muted);
  font-size: 15px;
  line-height: 1.35;
}
.badges{
  display:flex;
  flex-wrap:wrap;
  gap:10px;
  margin-top: 14px;
}
.badge{
  font-size:12px;
  color: rgba(232,237,247,0.95);
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(6px);
}
.badge.sox{ border-color: rgba(189,48,57,0.45); }
.badge.celtics{ border-color: rgba(0,122,51,0.45); }
.badge.bruins{ border-color: rgba(255,184,28,0.45); }
.badge.pats{ border-color: rgba(0,34,68,0.55); }

/* NEW: top strip for calendar card below hero */
.top-strip{
  max-width: 1040px;
  margin: 0 auto;
  padding: 0 20px 6px;
  display: grid;
  grid-template-columns: 1fr;
  gap: 14px;
}
@media (min-width: 960px){
  .top-strip{ grid-template-columns: 1.15fr 0.85fr; }
}

/* Main content grid */
main{
  max-width: 1040px;
  margin: 0 auto;
  padding: 10px 20px 24px;
  display: grid;
  gap: 14px;
  grid-template-columns: 1fr;
}
@media (min-width: 960px){
  main { grid-template-columns: 1.15fr 0.85fr; }
}

.card{
  position:relative;
  background: color-mix(in srgb, var(--card) 92%, black 8%);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 18px;
  padding: 16px 16px 14px;
  box-shadow: 0 12px 34px rgba(0,0,0,0.35);
  transform: translateY(10px);
  opacity: 0;
  animation: cardIn 650ms ease forwards;
}
@keyframes cardIn{ to { transform: translateY(0); opacity: 1; } }

.card:hover{
  transform: translateY(-4px);
  box-shadow: 0 18px 44px rgba(0,0,0,0.45);
  border-color: rgba(255,255,255,0.14);
  transition: transform 140ms ease, box-shadow 140ms ease, border-color 140ms ease;
}

h2{
  margin: 0 0 10px;
  font-size: 18px;
  color: var(--accent);
  letter-spacing: 0.2px;
}
h2::after{
  content:"";
  display:block;
  height:2px;
  width: 54px;
  margin-top: 8px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), rgba(120,220,232,0));
  opacity: 0.9;
}

ul{ margin:0; padding-left:18px; }
li{ margin: 8px 0; line-height: 1.35; }
.year{
  display:inline-block;
  min-width: 54px;
  color: var(--muted);
}
.funfact{
  font-size: 16px;
  line-height: 1.45;
  color: #f3f7ff;
}

/* Birthday cards */
.bday-card{
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px;
  padding: 12px;
  margin: 10px 0;
}
.bday-name{ font-weight: 750; font-size: 16px; }
.meta{ color: var(--muted); margin-top: 4px; }
.note{ margin-top: 6px; color: #d9e4ff; }
.closer{
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.08);
  color: #f6fbff;
}

/* "To:" card */
.to-title{
  color: var(--accent2);
  font-weight: 800;
  margin: 0 0 10px;
  font-size: 16px;
}
.to-text{
  width: 100%;
  min-height: 90px;
  resize: vertical;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.14);
  background: rgba(0,0,0,0.18);
  color: var(--text);
  padding: 14px;
  line-height: 1.45;
  font-size: 15px;
  font-family: var(--font-body);
}

/* SMS summary box */
.sms-wrap{ max-width: 1040px; margin: 0 auto; padding: 0 20px 44px; }
.sms-card{
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 18px;
  padding: 16px;
  box-shadow: 0 16px 44px rgba(0,0,0,0.42);
  position:relative;
  overflow:hidden;
}
.sms-card::before{
  content:"";
  position:absolute;
  inset:-40%;
  background:
    radial-gradient(closest-side at 20% 30%, rgba(255,184,28,0.20), rgba(0,0,0,0) 60%),
    radial-gradient(closest-side at 85% 45%, rgba(189,48,57,0.18), rgba(0,0,0,0) 62%),
    radial-gradient(closest-side at 45% 95%, rgba(0,122,51,0.18), rgba(0,0,0,0) 64%);
  transform: translateY(calc(var(--scrollY) * -0.03));
  pointer-events:none;
  opacity: 0.9;
}
.sms-title{
  color: var(--accent2);
  font-weight: 800;
  margin: 0 0 10px;
  font-size: 16px;
  position:relative;
}
.sms-text{
  width: 100%;
  min-height: 200px;
  resize: vertical;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.14);
  background: rgba(0,0,0,0.18);
  color: var(--text);
  padding: 14px;
  line-height: 1.5;
  font-size: 15px;
  font-family: var(--font-sms);
  position:relative;
}
.sms-actions{
  margin-top: 10px;
  display:flex;
  gap:10px;
  align-items:center;
  flex-wrap:wrap;
  position:relative;
}
.btn{
  border: 1px solid rgba(255,255,255,0.16);
  background: rgba(255,255,255,0.09);
  color: var(--text);
  padding: 9px 12px;
  border-radius: 12px;
  cursor: pointer;
}
.btn:hover{ background: rgba(255,255,255,0.13); }
.hint{ color: var(--muted); font-size: 12px; }

footer{
  max-width: 1040px;
  margin: 0 auto;
  padding: 10px 20px 30px;
  color: var(--muted);
  font-size: 12px;
}
code{ color: #c7f0ff; }

/* -----------------------------
   NEW: Mini Calendar styles
------------------------------ */
.cal-head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
}
.cal-title{
  font-weight: 800;
  color: var(--accent2);
  letter-spacing: 0.2px;
}
.cal-nav{
  display:flex;
  gap:8px;
}
.iconbtn{
  width: 34px;
  height: 34px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.16);
  background: rgba(255,255,255,0.08);
  color: var(--text);
  cursor:pointer;
  display:flex;
  align-items:center;
  justify-content:center;
}
.iconbtn:hover{ background: rgba(255,255,255,0.12); }

.calendar{
  margin-top: 10px;
  width:100%;
  border-collapse: collapse;
}
.calendar th{
  text-align:center;
  font-size: 12px;
  color: var(--muted);
  padding: 6px 0;
}
.calendar td{
  padding: 0;
}
.cal-day{
  width: 100%;
  height: 36px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.06);
  background: rgba(0,0,0,0.12);
  color: var(--text);
  cursor:pointer;
  display:flex;
  align-items:center;
  justify-content:center;
  margin: 3px 0;
  user-select:none;
  position:relative;
}
.cal-day:hover{
  background: rgba(255,255,255,0.10);
  border-color: rgba(255,255,255,0.12);
}
.cal-day.muted{
  opacity: 0.35;
  cursor: default;
}
.cal-day.today{
  outline: 2px solid rgba(120,220,232,0.45);
}
.cal-day.has-bday{
  background: color-mix(in srgb, rgba(189,48,57,0.22) 50%, rgba(255,184,28,0.16) 50%);
  border-color: rgba(255,184,28,0.35);
}
.cal-day.selected{
  outline: 2px solid rgba(255,184,28,0.55);
}
.cal-dot{
  position:absolute;
  bottom: 6px;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: rgba(255,184,28,0.85);
  box-shadow: 0 0 10px rgba(255,184,28,0.35);
}

.cal-controls{
  margin-top: 10px;
  display:flex;
  gap:10px;
  align-items:center;
  flex-wrap: wrap;
}
.cal-selected{
  color: var(--muted);
  font-size: 13px;
}
"""

    # --- JS: copy buttons + parallax + NEW calendar logic ---
    js = r"""
function copyTextArea(id, statusId) {
  const el = document.getElementById(id);
  el.focus();
  el.select();
  try {
    document.execCommand('copy');
    const status = document.getElementById(statusId);
    status.textContent = "Copied ✅";
    setTimeout(() => status.textContent = "", 1500);
  } catch (e) {
    const status = document.getElementById(statusId);
    status.textContent = "Select + Ctrl+C";
    setTimeout(() => status.textContent = "", 2000);
  }
}
function copySms(){ copyTextArea('smsText', 'copyStatus'); }
function copyToList(){ copyTextArea('toText', 'copyToStatus'); }

// Subtle parallax driver
let ticking = false;
window.addEventListener('scroll', () => {
  if (!ticking) {
    window.requestAnimationFrame(() => {
      document.documentElement.style.setProperty('--scrollY', window.scrollY + 'px');
      ticking = false;
    });
    ticking = true;
  }
}, { passive: true });
document.documentElement.style.setProperty('--scrollY', window.scrollY + 'px');

/* -----------------------------
   Mini Calendar logic
------------------------------ */
const BDAY_INDEX = window.__BDAY_INDEX__ || {};
const INIT = window.__INIT__ || {};
let viewYear = INIT.viewYear;
let viewMonth = INIT.viewMonth;  // 1-12
let selected = INIT.selected || null; // {year, month, day}

const monthNames = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const dow = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

function pad2(n){ return String(n).padStart(2,'0'); }
function keyMMDD(m,d){ return pad2(m) + "-" + pad2(d); }
function daysInMonth(y,m){ return new Date(y, m, 0).getDate(); } // m: 1-12
function firstDow(y,m){ return new Date(y, m-1, 1).getDay(); } // 0=Sun
function sameDate(a,b){ return a && b && a.year===b.year && a.month===b.month && a.day===b.day; }

function setTitle(){
  const el = document.getElementById("calTitle");
  el.textContent = monthNames[viewMonth-1] + " " + viewYear;
}

function renderCalendar(){
  setTitle();
  const tbody = document.getElementById("calBody");
  tbody.innerHTML = "";

  const fd = firstDow(viewYear, viewMonth);
  const dim = daysInMonth(viewYear, viewMonth);

  const today = new Date();
  const isThisMonth = (today.getFullYear()===viewYear && (today.getMonth()+1)===viewMonth);

  let dayNum = 1;
  for (let r=0; r<6; r++){
    const tr = document.createElement("tr");
    for (let c=0; c<7; c++){
      const td = document.createElement("td");
      if (r===0 && c<fd){
        td.innerHTML = "<div class='cal-day muted'></div>";
      } else if (dayNum>dim){
        td.innerHTML = "<div class='cal-day muted'></div>";
      } else {
        const btn = document.createElement("div");
        btn.className = "cal-day";
        btn.textContent = String(dayNum);

        const k = keyMMDD(viewMonth, dayNum);
        const has = Array.isArray(BDAY_INDEX[k]) && BDAY_INDEX[k].length>0;

        if (has){
          btn.classList.add("has-bday");
          const dot = document.createElement("div");
          dot.className = "cal-dot";
          btn.appendChild(dot);
          btn.title = "Birthdays: " + BDAY_INDEX[k].join(", ");
        }

        if (isThisMonth && dayNum===today.getDate()){
          btn.classList.add("today");
        }

        const candidate = {year:viewYear, month:viewMonth, day:dayNum};
        if (sameDate(candidate, selected)){
          btn.classList.add("selected");
        }

        btn.addEventListener("click", () => {
          selected = candidate;
          updateSelectedUI();
          renderCalendar(); // re-render for selected outline
        });

        td.appendChild(btn);
        dayNum++;
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
    if (dayNum>dim) break;
  }
}

function updateSelectedUI(){
  const label = document.getElementById("calSelectedLabel");
  const genBtn = document.getElementById("calGenerateBtn");
  const genHint = document.getElementById("calGenerateHint");

  if (!selected){
    label.textContent = "Pick a day to generate the fun facts.";
    genBtn.disabled = true;
    genHint.textContent = "";
    return;
  }
  const mm = pad2(selected.month);
  const dd = pad2(selected.day);
  const pretty = monthNames[selected.month-1] + " " + dd;
  label.textContent = "Selected: " + pretty + " (click Generate)";
  genBtn.disabled = false;

  const k = mm + "-" + dd;
  if (BDAY_INDEX[k] && BDAY_INDEX[k].length){
    genHint.textContent = "🎂 Birthdays: " + BDAY_INDEX[k].join(", ");
  } else {
    genHint.textContent = "";
  }
}

function goMonth(delta){
  // Keep year consistent
  let m = viewMonth + delta;
  let y = viewYear;
  if (m<1){ m=12; y--; }
  if (m>12){ m=1; y++; }
  viewMonth = m;
  viewYear = y;

  // auto-select first of month only if nothing selected
  if (!selected){
    selected = {year:viewYear, month:viewMonth, day:1};
  } else {
    // clamp selected day to month length if same month is being displayed
    if (selected.year===viewYear && selected.month===viewMonth){
      const dim = daysInMonth(viewYear, viewMonth);
      if (selected.day>dim) selected.day = dim;
    }
  }

  updateSelectedUI();
  renderCalendar();
}

function generate(){
  if (!selected) return;
  const mm = pad2(selected.month);
  const dd = pad2(selected.day);
  window.location.href = "/?date=" + mm + "-" + dd + "&show=1";
}

document.addEventListener("DOMContentLoaded", () => {
  // DOW header
  const head = document.getElementById("calHeadRow");
  head.innerHTML = "";
  for (const d of dow){
    const th = document.createElement("th");
    th.textContent = d;
    head.appendChild(th);
  }

  document.getElementById("calPrev").addEventListener("click", () => goMonth(-1));
  document.getElementById("calNext").addEventListener("click", () => goMonth(1));
  document.getElementById("calGenerateBtn").addEventListener("click", generate);

  // If no selected day, default to "today" in view month
  if (!selected){
    const t = new Date();
    selected = {year:viewYear, month:viewMonth, day: t.getDate()};
  }

  updateSelectedUI();
  renderCalendar();
});
"""

    def fonts_link_tag() -> str:
        return (
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Fraunces:opsz,wght@9..144,400..700&family=Inter:wght@400;600;800&display=swap" rel="stylesheet">'
        )

    # Determine initial calendar view (use selected date month)
    view_year = dt.date.today().year
    view_month = month  # show the chosen month
    selected_obj = {"year": view_year, "month": month, "day": day}

    # If show_facts is false, default selected to today (in current view month) for convenience
    if not show_facts:
        t = dt.date.today()
        view_year = t.year
        view_month = t.month
        selected_obj = {"year": t.year, "month": t.month, "day": t.day}

    # Safe JSON embeds
    bday_index_json = json.dumps(birthdays_index, ensure_ascii=False)
    init_json = json.dumps(
        {
            "viewYear": view_year,
            "viewMonth": view_month,
            "selected": selected_obj,
        },
        ensure_ascii=False,
    )

    # Fact sections are gated behind show_facts
    facts_html = ""
    sms_html = ""
    if show_facts:
        facts_html = f"""
  <main>
    <section class="card">
      <div class="to-title">📲 Copy/Paste Phone List (for iMessage “To:”)</div>
      <textarea id="toText" class="to-text" readonly>{html.escape(to_field_text)}</textarea>
      <div class="sms-actions">
        <button class="btn" onclick="copyToList()">Copy</button>
        <span id="copyToStatus" class="hint"></span>
        <span class="hint">Tip: paste into a new iMessage “To:” field (comma-separated).</span>
      </div>
    </section>

    <section class="card">
      <h2>🎂 Family birthdays</h2>
      <div class="sub" style="margin-top:-2px;">Today’s official job: hype the birthday humans. 🎉</div>
      {birthday_block(birthday_hits)}
      {famous_bday_list(famous_bdays_card)}
      <div class="closer">{html.escape(closer)}</div>
    </section>

    <section class="card">
      <h2>📜 On this day in history</h2>
      <ul>{li_year_text(featured_events)}</ul>
    </section>

    <section class="card">
      <h2>🏟️ Boston sports-ish highlights</h2>
      <div class="sub" style="margin:-6px 0 8px;">(Filtered by: {html.escape(", ".join(sports_keywords))})</div>
      <ul>{li_year_text(bostonish_featured)}</ul>
      {"<div class='sub' style='margin-top:8px;'><em>No obvious Boston hits today — still counts as content. 😄</em></div>" if not bostonish_all else ""}
    </section>

    <section class="card">
      <h2>🎸 This day in classic rock history</h2>
      <div class="sub" style="margin:-6px 0 8px;">(Filtered by: {html.escape(", ".join(rock_keywords[:10]))}{'…' if len(rock_keywords) > 10 else ''})</div>
      <ul>{li_year_text(rockish_featured)}</ul>
      {"<div class='sub' style='margin-top:8px;'><em>No rock hits found today — add more keywords and we’ll summon them. 🎶</em></div>" if not rockish_all else ""}
    </section>

    <section class="card">
      <h2>🧠 Did you know?</h2>
      <div class="funfact">{html.escape(fun_fact)}</div>
    </section>

    <section class="card">
      <h2>👶 Notable births</h2>
      <ul>{li_year_text(featured_births)}</ul>
    </section>
  </main>
"""
        sms_html = f"""
  <div class="sms-wrap">
    <div class="sms-card">
      <div class="sms-title">📩 Copy/Paste Text Message</div>
      <textarea id="smsText" class="sms-text" readonly>{html.escape(sms_summary)}</textarea>
      <div class="sms-actions">
        <button class="btn" onclick="copySms()">Copy</button>
        <span id="copyStatus" class="hint"></span>
        <span class="hint">Positive-only-ish summary: avoids darker events when composing this paragraph.</span>
      </div>
    </div>
  </div>
"""
    else:
        # gentle placeholder card area (no heavy content)
        facts_html = f"""
  <main>
    <section class="card">
      <h2>🗓️ Ready when you are</h2>
      <div class="sub">Pick a date on the mini calendar and hit <strong>Generate</strong>. This page intentionally waits so it doesn’t spam-load everything at once.</div>
      <div class="sub" style="margin-top:8px;">Tip: birthdays are highlighted. Click one for instant “today’s mission.”</div>
    </section>
  </main>
"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} — {html.escape(date_label)}</title>
  {fonts_link_tag()}
  <style>{css}</style>
</head>
<body>
  <header>
    <div class="hero">
      <h1>{html.escape(title)} <span style="color:var(--muted);font-weight:500;">— {html.escape(date_label if show_facts else "Pick a date")}</span></h1>
      <div class="hero-date">{html.escape(subtitle)}</div>

      <div class="badges">
        <div class="badge sox">Red Sox</div>
        <div class="badge celtics">Celtics</div>
        <div class="badge bruins">Bruins</div>
        <div class="badge pats">Patriots</div>
        <div class="badge">Family birthdays 🎂</div>
      </div>
    </div>
  </header>
  
  <div class="sub" style="margin-top:8px;">
    <span style="opacity:.85">debug:</span>
        date=<strong>{month:02d}-{day:02d}</strong>,
        show=<strong>{"1" if show_facts else "0"}</strong>,
        events=<strong>{len(onthisday.get("events", []) or [])}</strong>,
        births=<strong>{len(onthisday.get("births", []) or [])}</strong>
        {f"<div style='margin-top:6px;color:#ffb81c;'>{html.escape(debug_error)}</div>" if debug_error else ""}
  </div>

  <!-- NEW: Mini calendar strip directly below hero -->
  <div class="top-strip">
    <div></div>
    <section class="card" style="animation-delay: 60ms;">
      <div class="cal-head">
        <div class="cal-title" id="calTitle">Month YYYY</div>
        <div class="cal-nav">
          <button class="iconbtn" id="calPrev" aria-label="Previous month">‹</button>
          <button class="iconbtn" id="calNext" aria-label="Next month">›</button>
        </div>
      </div>

      <table class="calendar">
        <thead>
          <tr id="calHeadRow"></tr>
        </thead>
        <tbody id="calBody"></tbody>
      </table>

      <div class="cal-controls">
        <button class="btn" id="calGenerateBtn" disabled>Generate</button>
        <div>
          <div class="cal-selected" id="calSelectedLabel">Pick a day to generate the fun facts.</div>
          <div class="hint" id="calGenerateHint"></div>
        </div>
      </div>
    </section>
  </div>

  {facts_html}

  {sms_html}

  <footer>
    Sources: Wikimedia “On this day” feed + Numbers API (with a cheerful fallback). Generated by <code>app.py</code>.
  </footer>

  <script>
    window.__BDAY_INDEX__ = {bday_index_json};
    window.__INIT__ = {init_json};
  </script>
  <script>{js}</script>
</body>
</html>
"""


# -----------------------------
# Web route (protected)
# -----------------------------
@app.get("/")
def render_page() -> Response:
    auth_resp = _basic_auth_required()
    if auth_resp:
        return auth_resp

    birthdays_path = Path(os.environ.get("BIRTHDAYS_FILE", DEFAULT_BIRTHDAYS))
    cache_dir = Path(os.environ.get("CACHE_DIR", DEFAULT_CACHE_DIR))
    title = os.environ.get("PAGE_TITLE", DEFAULT_TITLE)
    subtitle = os.environ.get("PAGE_SUBTITLE", DEFAULT_SUBTITLE)

    # show gating
    show = request.args.get("show", "").strip()
    show_facts = (show == "1" or show.lower() in {"true", "yes", "y"})

    # date selection
    qdate = request.args.get("date", "").strip()
    if qdate:
        month, day = parse_mm_dd(qdate)
    else:
        month, day = today_mm_dd()

    sports_keywords = [k.strip() for k in os.environ.get("SPORTS_KEYWORDS", ",".join(DEFAULT_SPORTS_KEYWORDS)).split(",") if k.strip()]
    rock_keywords = [k.strip() for k in os.environ.get("ROCK_KEYWORDS", ",".join(DEFAULT_ROCK_KEYWORDS)).split(",") if k.strip()]

    birthdays = load_birthdays(birthdays_path)
    birthday_hits = birthdays_for_date(birthdays, month, day)
    phones = people_to_phone_list(birthdays)
    bday_index = build_birthday_index(birthdays)

    seed = int(f"{month:02d}{day:02d}")

    # IMPORTANT: If not show_facts, do NOT hit external APIs.
    onthisday = {"events": [], "births": []}
    fun_fact = ""
    debug_error = ""

    if show_facts:
        try:
            onthisday = wiki_on_this_day(month, day, cache_dir)
        except Exception as e:
            onthisday = {"events": [], "births": []}
            debug_error = f"Wikimedia fetch failed: {type(e).__name__}: {e}"

        try:
            fun_fact = numbersapi_fun_fact(month, day, cache_dir)
        except Exception as e:
            fun_fact = ""
            debug_error = (debug_error + " | " if debug_error else "") + f"NumbersAPI failed: {type(e).__name__}: {e}"

    page = html_page(
        title=title,
        subtitle=subtitle,
        month=month,
        day=day,
        onthisday=onthisday,
        fun_fact=fun_fact,
        birthday_hits=birthday_hits,
        phones=phones,
        sports_keywords=sports_keywords,
        rock_keywords=rock_keywords,
        seed=seed,
        birthdays_index=bday_index,
        show_facts=show_facts,
        debug_error=debug_error,
    )
    return Response(page, mimetype="text/html")


# -----------------------------
# CLI (optional static export + local dev serve)
# -----------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a fun 'This Day' webpage (family birthday edition).")

    parser.add_argument("--date", help="Date in MM-DD (default: today).")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"Output HTML filename (default: {DEFAULT_OUT}).")
    parser.add_argument("--birthdays", default=DEFAULT_BIRTHDAYS, help=f"Path to birthdays.json (default: {DEFAULT_BIRTHDAYS}).")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help=f"Cache directory (default: {DEFAULT_CACHE_DIR}).")

    parser.add_argument("--title", default=DEFAULT_TITLE, help="Page title.")
    parser.add_argument("--subtitle", default=DEFAULT_SUBTITLE, help="Page subtitle.")
    parser.add_argument("--sports-keywords", default=",".join(DEFAULT_SPORTS_KEYWORDS))
    parser.add_argument("--rock-keywords", default=",".join(DEFAULT_ROCK_KEYWORDS))

    parser.add_argument("--serve", action="store_true", help="Run a local web server (requires APP_USER/APP_PASS env vars).")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--show", action="store_true", help="When exporting static HTML, include facts immediately (no gating).")

    args = parser.parse_args()

    if args.serve:
        app.run(host="0.0.0.0", port=args.port, debug=False)
        return 0

    if args.date:
        month, day = parse_mm_dd(args.date)
    else:
        month, day = today_mm_dd()

    sports_keywords = [k.strip() for k in args.sports_keywords.split(",") if k.strip()] or DEFAULT_SPORTS_KEYWORDS
    rock_keywords = [k.strip() for k in args.rock_keywords.split(",") if k.strip()] or DEFAULT_ROCK_KEYWORDS

    birthdays_path = Path(args.birthdays)
    cache_dir = Path(args.cache_dir)

    birthdays = load_birthdays(birthdays_path)
    birthday_hits = birthdays_for_date(birthdays, month, day)
    phones = people_to_phone_list(birthdays)
    bday_index = build_birthday_index(birthdays)

    seed = int(f"{month:02d}{day:02d}")

    onthisday = {"events": [], "births": []}
    fun_fact = ""
    show_facts = bool(args.show)
    if show_facts:
        try:
            onthisday = wiki_on_this_day(month, day, cache_dir)
        except Exception as e:
            onthisday = {"events": [], "births": []}
            print(f"[warn] Failed to fetch Wikimedia data: {e}")
        fun_fact = numbersapi_fun_fact(month, day, cache_dir)

    page = html_page(
        title=args.title,
        subtitle=args.subtitle,
        month=month,
        day=day,
        onthisday=onthisday,
        fun_fact=fun_fact,
        birthday_hits=birthday_hits,
        phones=phones,
        sports_keywords=sports_keywords,
        rock_keywords=rock_keywords,
        seed=seed,
        birthdays_index=bday_index,
        show_facts=show_facts,
    )

    out_path = Path(args.out)
    out_path.write_text(page, encoding="utf-8")
    print(f"[ok] Wrote {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
