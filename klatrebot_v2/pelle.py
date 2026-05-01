"""Pelle location/time formatter. Pure functions; no Discord coupling.

Ported from V1 pelleService.py (2026-04 cleanup snapshot).
The HTTP fetch lives here for now — pure-function refactor deferred to follow-up.
"""
from __future__ import annotations

import datetime
import re

import pytz
import requests
from dateutil.parser import parse


KINDS = {
    "ACCOMMODATION": ":love_hotel:", "DRIVING": ":blue_car:", "FLYING": ":airplane:",
    "HIKING": ":man_running:", "POINTOFINTEREST": ":mount_fuji:", "SIGHTSEEING": ":statue_of_liberty:",
    "WINE": ":wine:", "TAKEOFF": ":airplane:", "LANDING": ":airplane:", "BREAKFAST": ":pancakes:",
    "DINNER": ":sushi:", "SLEEPING": ":sleeping:", "TRANSFER": ":airplane:", "CHILL": ":pepedance:",
    "BUS": ":minibus:",
}
COPENHAGEN = pytz.timezone("Europe/Copenhagen")


def seconds_as_dt_string(total_seconds: float) -> str:
    days, seconds = divmod(total_seconds, 86400)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    days_text = "dag" if days == 1 else "dage"
    hours_text = "time" if hours == 1 else "timer"
    minutes_text = "minut" if minutes == 1 else "minutter"
    seconds_text = "sekund" if seconds == 1 else "sekunder"

    out = "" if days == 0 else f"{days:.0f} {days_text} "
    out += "" if hours == 0 else f"{hours:.0f} {hours_text} "
    out += "" if hours == 0 and minutes == 0 else f"{minutes:.0f} {minutes_text} "
    out += "" if seconds == 0 else f"{seconds:.0f} {seconds_text}"
    return out


def where_the_fuck_is_pelle(arg: str | None = None, debug_ts: str = "") -> str:
    pelle_ctx = "seoul-2026"

    if arg is not None and arg.lower() == "pic":
        try:
            html_url = f"https://pellelauritsen.net/api/html/{pelle_ctx}/newest"
            response = requests.get(html_url, timeout=10)
            response.raise_for_status()
            img_match = re.search(r'<img src="([^"]+)"', response.text)
            return img_match.group(1) if img_match else "Could not find latest Pelle picture"
        except Exception as e:
            return f"Failed to fetch Pelle pic: {e}"

    max_distance = 1_000_000_000
    response = requests.get(f"https://pellelauritsen.net/{pelle_ctx}.json", timeout=10)
    if not response.ok:
        return "Ingen aner hvor Pelle er, men måske er han på vej til klatring."
    fulljs = response.json()

    current_acc, current_act = {}, {}
    last_distance, next_act = max_distance, {}
    now = COPENHAGEN.localize(parse(debug_ts)) if debug_ts else COPENHAGEN.localize(datetime.datetime.now())

    for activity in fulljs.get("activities", []):
        if "begin" not in activity:
            continue
        start = pytz.timezone(activity["begin"]["timezone"]).localize(parse(activity["begin"]["dateTime"]))
        end = pytz.timezone(activity["end"]["timezone"]).localize(parse(activity["end"]["dateTime"]))

        if start < now < end:
            if "kind" in activity and activity["kind"] == "ACCOMMODATION":
                current_acc = activity
            else:
                current_act = activity
            continue

        seconds_until_next = (start - now).total_seconds()
        if last_distance > seconds_until_next > 0:
            last_distance = seconds_until_next
            next_act = activity

    out = ""
    if not current_act:
        if last_distance < 0 or last_distance == max_distance:
            return "Pelle er på vej til klatring..."
        pretty = seconds_as_dt_string(last_distance)
        current_act = next_act
        begin_dt = pytz.timezone(current_act["begin"]["timezone"]).localize(parse(current_act["begin"]["dateTime"]))
        out += f"Om {pretty}: {begin_dt} - "

    out += f"{KINDS[current_act['kind']]} {current_act['title']}"
    if current_act.get("description"):
        out += f" ({current_act['description']})"
    if current_act["kind"] == "FLYING" and current_act.get("description"):
        flight_no = current_act["description"].replace(" ", "")
        out += f"\nhttps://www.flightradar24.com/data/flights/{flight_no}"

    if current_act["begin"]["location"] != current_act["end"]["location"]:
        out += f"\n({current_act['begin']['location']} -> {current_act['end']['location']})"

    end_dt = pytz.timezone(current_act["end"]["timezone"]).localize(parse(current_act["end"]["dateTime"]))
    out += f" færdig om {seconds_as_dt_string((end_dt - now).total_seconds())}"

    if current_acc:
        out += f"\nI mellemtiden chiller Pelle @ {KINDS[current_acc['kind']]} {current_acc['title']}"

    if current_act.get("url"):
        out += f" {current_act['url']}"
    elif current_acc.get("url"):
        out += f" {current_acc['url']}"

    coord = []
    if not next_act and "coordinate" in current_act:
        coord = current_act["coordinate"]
    elif current_acc.get("coordinate"):
        coord = current_acc["coordinate"]
    elif next_act.get("coordinate"):
        coord = next_act["coordinate"]
    if len(coord) == 2:
        out += f" https://www.openstreetmap.org/search?query={coord[0]}%2C%20{coord[1]}"
    return out
