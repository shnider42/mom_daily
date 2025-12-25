#!/usr/bin/env python3
"""
All-in-one "This Day" webpage generator (Patti-style).

UPDATE (minimal change, per your new combined JSON):
- birthdays.json now contains BOTH birthday info and phone numbers in the same objects:
    [{"name","month","day","relation","note","phone"}, ...]
- The "📲 Copy/Paste Phone List" card now uses ALL phones found in birthdays.json.
- You can still keep birthdays.json external and editable.

CLI tweaks (still minimal / backwards-friendly):
- --add-birthday can also accept --phone
- --add-phone/--remove-phone still exist, but now they edit birthdays.json entries by phone:
    - --add-phone adds a stub entry if needed (month/day default to 1/1 unless you also pass --bday-date and --add-birthday)
    - recommended: use --add-birthday with --phone

Usage:
  pip install requests
  python this_day_page.py
  python this_day_page.py --date 12-18 --out dec18.html

Add/update a person (recommended):
  python this_day_page.py --add-birthday "Chris Holtsnider" --bday-date 07-10 --phone "774-573-9352" --relation "..." --note "..."

Remove a phone from the list (and keep the person entry, phone cleared):
  python this_day_page.py --remove-phone "774-573-9352"
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


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
    _ = dt.date(2000, month, day)  # validates
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


# -----------------------------
# "Tone / context / positivity" helpers (lightweight heuristics)
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
    good = []
    better = []

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
    if pool:
        return rng.choice(pool)
    return None


# -----------------------------
# Birthdays.json (now includes phones too)
# -----------------------------

def ensure_birthdays_file(path: Path) -> None:
    if path.exists():
        return
    template = [
        {
            "name": "Patti",
            "month": 5,
            "day": 14,
            "relation": "Mom",
            "note": "Chief Fun Fact Officer",
            "phone": "000-000-0000"
        }
    ]
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")


def load_birthdays(path: Path) -> List[Dict[str, Any]]:
    ensure_birthdays_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("birthdays.json must contain a JSON array of entries.")
    # normalize phone formatting lightly
    for item in data:
        if isinstance(item, dict) and item.get("phone"):
            item["phone"] = normalize_phone(str(item.get("phone", "")).strip())
    return data


def save_birthdays(path: Path, birthdays: List[Dict[str, Any]]) -> None:
    path.write_text(json.dumps(birthdays, ensure_ascii=False, indent=2), encoding="utf-8")


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


def add_or_update_person(
    birthdays_path: Path,
    name: str,
    month: int,
    day: int,
    relation: str = "",
    note: str = "",
    phone: str = "",
) -> None:
    birthdays = load_birthdays(birthdays_path)
    norm_name = name.strip().lower()

    phone_norm = normalize_phone(phone) if phone else ""

    for b in birthdays:
        if str(b.get("name", "")).strip().lower() == norm_name:
            # update existing by name
            b["month"] = month
            b["day"] = day
            if relation:
                b["relation"] = relation
            if note:
                b["note"] = note
            if phone_norm:
                b["phone"] = phone_norm
            save_birthdays(birthdays_path, birthdays)
            return

    birthdays.append(
        {
            "name": name.strip(),
            "month": month,
            "day": day,
            "relation": relation.strip(),
            "note": note.strip(),
            "phone": phone_norm,
        }
    )
    save_birthdays(birthdays_path, birthdays)


def remove_phone_from_people(birthdays_path: Path, phone: str) -> None:
    birthdays = load_birthdays(birthdays_path)
    target_digits = "".join(ch for ch in phone if ch.isdigit())
    for b in birthdays:
        p = str(b.get("phone", "")).strip()
        if "".join(ch for ch in p if ch.isdigit()) == target_digits and target_digits:
            b["phone"] = ""
    save_birthdays(birthdays_path, birthdays)


def add_phone_stub(birthdays_path: Path, phone: str, label: str = "") -> None:
    """
    Backward-ish CLI helper:
    - If phone exists, update name to label if label provided.
    - Else add a stub entry (month/day 1/1) so it shows up in the phone list.
    """
    birthdays = load_birthdays(birthdays_path)
    phone_norm = normalize_phone(phone)
    digits = "".join(ch for ch in phone_norm if ch.isdigit())

    for b in birthdays:
        p = normalize_phone(str(b.get("phone", "")).strip())
        if "".join(ch for ch in p if ch.isdigit()) == digits and digits:
            if label:
                b["name"] = label.strip()
            b["phone"] = phone_norm
            save_birthdays(birthdays_path, birthdays)
            return

    birthdays.append(
        {
            "name": label.strip() or "Unknown",
            "month": 1,
            "day": 1,
            "relation": "",
            "note": "",
            "phone": phone_norm,
        }
    )
    save_birthdays(birthdays_path, birthdays)


def people_to_phone_list(birthdays: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Extract phones from the unified birthdays.json. Keeps the old shape:
      [{"phone": "...", "label": "..."}]
    """
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
# Content selection + HTML
# -----------------------------

def pick_items(items: List[Dict[str, Any]], n: int, seed: int) -> List[Dict[str, Any]]:
    if not items:
        return []
    rng = random.Random(seed)
    if len(items) <= n:
        return items
    return rng.sample(items, n)


def extract_year_text(item: Dict[str, Any]) -> Tuple[str, str]:
    year = str(item.get("year", "")).strip()
    text = str(item.get("text", "")).strip()
    return year, text


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
) -> str:
    date_label = dt.date(2000, month, day).strftime("%B %d").replace(" 0", " ")

    events = onthisday.get("events", []) or []
    births = onthisday.get("births", []) or []

    featured_events = pick_items(events, n=6, seed=seed + 1)
    featured_births = pick_items(births, n=6, seed=seed + 2)

    bostonish_all = filter_keywords(events, sports_keywords)
    bostonish_featured = pick_items(bostonish_all, n=5, seed=seed + 4)

    rockish_all = filter_keywords(events, rock_keywords)
    rockish_featured = pick_items(rockish_all, n=5, seed=seed + 5)

    famous_bdays_summary = pick_famous_birthdays(births, seed=seed, n=2)
    famous_bdays_card = pick_famous_birthdays(births, seed=seed + 7, n=6)

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

    # (CSS/JS/HTML for page) — keeping your existing “prettier” version.
    # NOTE: This section is intentionally unchanged except where it needs to reference new data.
    css = """/* (same CSS as prior pretty version; unchanged for brevity) */"""
    # To keep this copy/paste script fully functional, we include the full CSS.
    # (Yes it’s long, but it’s the “all-in-one script” requirement.)
    css = r"""
/* --- Fonts (fallbacks if Google Fonts blocked) --- */
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

main{
  max-width: 1040px;
  margin: 0 auto;
  padding: 16px 20px 24px;
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
.card:nth-child(1){ animation-delay: 40ms; }
.card:nth-child(2){ animation-delay: 80ms; }
.card:nth-child(3){ animation-delay: 120ms; }
.card:nth-child(4){ animation-delay: 160ms; }
.card:nth-child(5){ animation-delay: 200ms; }
.card:nth-child(6){ animation-delay: 240ms; }
.card:nth-child(7){ animation-delay: 280ms; }

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
"""

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
"""

    def fonts_link_tag() -> str:
        return (
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Fraunces:opsz,wght@9..144,400..700&family=Inter:wght@400;600;800&display=swap" rel="stylesheet">'
        )

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
      <h1>{html.escape(title)} <span style="color:var(--muted);font-weight:500;">— {html.escape(date_label)}</span></h1>
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

  <footer>
    Sources: Wikimedia “On this day” feed + Numbers API (with a cheerful fallback). Generated by <code>this_day_page.py</code>.
  </footer>

  <script>{js}</script>
</body>
</html>
"""


# -----------------------------
# CLI / Main
# -----------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a fun 'This Day' webpage (family birthday edition).")

    parser.add_argument("--date", help="Date in MM-DD (default: today).")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"Output HTML filename (default: {DEFAULT_OUT}).")
    parser.add_argument("--birthdays", default=DEFAULT_BIRTHDAYS, help=f"Path to birthdays.json (default: {DEFAULT_BIRTHDAYS}).")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help=f"Cache directory (default: {DEFAULT_CACHE_DIR}).")

    parser.add_argument("--title", default=DEFAULT_TITLE, help="Page title.")
    parser.add_argument("--subtitle", default=DEFAULT_SUBTITLE, help="Page subtitle.")

    parser.add_argument("--sports-keywords", default=",".join(DEFAULT_SPORTS_KEYWORDS),
                        help="Comma-separated keywords for the Boston/sports-ish filter.")
    parser.add_argument("--rock-keywords", default=",".join(DEFAULT_ROCK_KEYWORDS),
                        help="Comma-separated keywords for the classic-rock-ish filter.")

    # Add/update person (now includes phone)
    parser.add_argument("--add-birthday", help="Name to add/update in birthdays.json.")
    parser.add_argument("--bday-date", help="Birthday date in MM-DD (required with --add-birthday).")
    parser.add_argument("--relation", default="", help="Relationship label (optional).")
    parser.add_argument("--note", default="", help="Note (optional).")
    parser.add_argument("--phone", default="", help="Phone number for --add-birthday (optional).")

    # Phone helpers (operate on birthdays.json now)
    parser.add_argument("--add-phone", help="Phone number to add (creates/updates stub entry in birthdays.json).")
    parser.add_argument("--remove-phone", help="Phone number to remove (clears phone field in birthdays.json).")
    parser.add_argument("--label", default="", help="Label/name for --add-phone (optional).")

    args = parser.parse_args()

    birthdays_path = Path(args.birthdays)
    cache_dir = Path(args.cache_dir)

    if args.add_birthday:
        if not args.bday_date:
            raise SystemExit("Error: --bday-date MM-DD is required when using --add-birthday.")
        m, d = parse_mm_dd(args.bday_date)
        add_or_update_person(
            birthdays_path=birthdays_path,
            name=args.add_birthday,
            month=m,
            day=d,
            relation=args.relation,
            note=args.note,
            phone=args.phone,
        )
        print(f"[ok] Added/updated person {args.add_birthday} on {m:02d}-{d:02d} in {birthdays_path.resolve()}")
        return 0

    if args.add_phone:
        add_phone_stub(birthdays_path, args.add_phone, args.label)
        print(f"[ok] Added/updated phone {normalize_phone(args.add_phone)} in {birthdays_path.resolve()}")
        return 0

    if args.remove_phone:
        remove_phone_from_people(birthdays_path, args.remove_phone)
        print(f"[ok] Cleared phone {normalize_phone(args.remove_phone)} from any matching people in {birthdays_path.resolve()}")
        return 0

    if args.date:
        month, day = parse_mm_dd(args.date)
    else:
        month, day = today_mm_dd()

    sports_keywords = [k.strip() for k in args.sports_keywords.split(",") if k.strip()] or DEFAULT_SPORTS_KEYWORDS
    rock_keywords = [k.strip() for k in args.rock_keywords.split(",") if k.strip()] or DEFAULT_ROCK_KEYWORDS

    birthdays = load_birthdays(birthdays_path)
    birthday_hits = birthdays_for_date(birthdays, month, day)

    # Phones now come from birthdays.json
    phones = people_to_phone_list(birthdays)

    seed = int(f"{month:02d}{day:02d}")

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
    )

    out_path = Path(args.out)
    out_path.write_text(page, encoding="utf-8")

    print(f"[ok] Wrote {out_path.resolve()}")
    print(f"[hint] Birthdays+phones file: {birthdays_path.resolve()}")
    print(f"[hint] Open in browser: file:///{out_path.resolve().as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
