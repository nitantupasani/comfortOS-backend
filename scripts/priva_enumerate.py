"""
Priva variable enumerator — populate a building file from scheme metadata.

Instead of hand-copying SignalR `subscribe` frames, this reads the Operator
scheme metadata endpoint (same BFF cookie) which lists every point on a floor
with its name, unit, datatype and whether it's historized:

  GET /operator/api/scheme/metadata/{siteId}/{groupId}/{section}

A building's floors are linked from an index section (e.g. "Ruimteregeling"):
each floor is a separate `buildingsection*` under the same device group. With
--crawl, we start at the index and follow `scheme_link`s to every floor, so one
run captures the whole building. Each temperature variable is tagged with its
floor name (from the index link text).

Results are merged into the per-building config file
(priva_buildings/<name>.json), preserving its identity fields and any `room` /
`location_id` you've already filled in.

Usage (from backend/, cookie comes from .env; identity from the building file):
  python -m scripts.priva_enumerate --crawl                       # whole building
  python -m scripts.priva_enumerate --section buildingsection3     # one floor
  python -m scripts.priva_enumerate --crawl --all-celsius          # keep every °C float
  python -m scripts.priva_enumerate --crawl --dry-run              # print, don't write

Filter default: unit == "°C", datatype == "float", historizable == true, and
`text` matches --match (default "ruimtetemperatuur"). Drops calculated values
(Ber.*, historizable=false) and non-temperature points (enums/ints).
"""

import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from app.config import settings  # noqa: E402  (loads .env)
from app.services.priva_ingestion import load_building, _resolve_path  # noqa: E402

BASE = "https://operator.priva.com/operator/api/scheme/metadata"


def fetch_section(cookie: str, site: str, group: str, section: str) -> dict:
    url = f"{BASE}/{site}/{group}/{section}"
    headers = {"Cookie": cookie, "x-csrf": "1", "Accept": "application/json"}
    r = httpx.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _celsius_float_historized(v: dict) -> bool:
    return (
        v.get("unit") == "°C"
        and v.get("datatype") == "float"
        and bool(v.get("historizable"))
    )


def pick_temps(variables: list[dict], match: re.Pattern,
               fallback: re.Pattern, all_celsius: bool) -> list[dict]:
    """Pick temperature sensors from a floor's variables.

    Prefer the primary name match (e.g. 'Ruimtetemperatuur'); if a floor exposes
    none, fall back to the secondary match (e.g. 'Comset CX' — the raw probe).
    --all-celsius keeps every historized °C float regardless of name.
    """
    base = [v for v in variables if _celsius_float_historized(v)]
    if all_celsius:
        return base
    primary = [v for v in base if match.search(v.get("text", ""))]
    if primary:
        return primary
    return [v for v in base if fallback.search(v.get("text", ""))]


def zone_centers(meta: dict) -> list[tuple[str, float, float]]:
    """Extract (zoneNumber, centerX, centerY) from 'Zone NNN' scheme links.

    The climate-zone label sits a fixed offset from its room's sensor, so each
    sensor's nearest zone identifies its room (NR<number>). Validated against the
    live floorplan values.
    """
    zones = []
    for link in meta.get("links", []):
        if link.get("type") != "scheme_link":
            continue
        m = re.search(r"zone\s*(\d+)", (link.get("text") or ""), re.I)
        if not m:
            continue
        sh = link.get("shape") or {}
        try:
            cx = float(sh["left"]) + float(sh.get("width", 0)) / 2
            cy = float(sh["top"]) + float(sh.get("height", 0)) / 2
        except (KeyError, TypeError, ValueError):
            continue
        zones.append((m.group(1), cx, cy))
    return zones


def _centroid(var: dict):
    c = var.get("centroid") or {}
    try:
        return float(c["x"]), float(c["y"])
    except (KeyError, TypeError, ValueError):
        return None


def assign_rooms(temps: list[dict], zones: list[tuple[str, float, float]]) -> dict[str, str]:
    """Map each temperature variable to a DISTINCT zone (room) by proximity.

    Greedy over all (var, zone) pairs by ascending distance, claiming each var
    and zone at most once. Avoids two sensors collapsing onto one room. Returns
    {variableId: 'NR<zone>'}.
    """
    pairs = []
    for v in temps:
        c = _centroid(v)
        vid = v.get("varid")
        if c is None or not vid:
            continue
        for num, zx, zy in zones:
            pairs.append((math.hypot(c[0] - zx, c[1] - zy), vid, num))
    pairs.sort(key=lambda p: p[0])

    rooms: dict[str, str] = {}
    used_zones: set[str] = set()
    for _dist, vid, num in pairs:
        if vid in rooms or num in used_zones:
            continue
        rooms[vid] = "NR" + num.zfill(2)
        used_zones.add(num)
    return rooms


def floor_links(meta: dict) -> dict[str, str]:
    """section id -> floor name, from scheme_link entries in an index section."""
    out: dict[str, str] = {}
    for link in meta.get("links", []):
        tgt = str(link.get("target", ""))
        if link.get("type") == "scheme_link" and tgt.startswith("buildingsection"):
            out.setdefault(tgt, (link.get("text") or "").strip())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--building", default=settings.priva_building_file,
                    help="building config file to read identity from and merge into")
    ap.add_argument("--root", default="buildingsection2",
                    help="index section to crawl floors from (with --crawl)")
    ap.add_argument("--section", action="append", default=[],
                    help="explicit section id(s) to scan (repeatable; disables crawl)")
    ap.add_argument("--crawl", action="store_true",
                    help="follow scheme_links from --root to every floor")
    ap.add_argument("--match", default="ruimtetemperatuur",
                    help="primary case-insensitive regex on variable text")
    ap.add_argument("--fallback-match", default="comset cx",
                    help="used per-floor only when the primary match finds nothing")
    ap.add_argument("--all-celsius", action="store_true",
                    help="keep every historized float in °C, not just name matches")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cookie = settings.priva_bff_cookie
    building = load_building(args.building)
    site = building.get("siteId", "")
    groups = building.get("groups") or []
    group = groups[0] if groups else ""
    if not (cookie and site and group):
        print("ERROR: need PRIVA_BFF_COOKIE in .env and siteId/groups in the building file.")
        sys.exit(1)

    match = re.compile(args.match, re.IGNORECASE)
    fallback = re.compile(args.fallback_match, re.IGNORECASE)

    # Build the section -> floor-name map and the work list.
    section_floor: dict[str, str] = {}
    if args.section:
        sections = list(args.section)
    elif args.crawl:
        root_meta = fetch_section(cookie, site, group, args.root)
        section_floor = floor_links(root_meta)
        sections = list(section_floor.keys())
        print(f"  {args.root}: {len(sections)} floors -> {sorted(section_floor.values())}")
    else:
        sections = ["buildingsection3"]

    # Existing data to preserve (manual room/location_id labels, known serials).
    existing: dict[str, dict] = building.get("variables", {})
    servers: dict[str, dict] = building.get("servers", {}) or {}

    new_vars: dict[str, dict] = {}
    kept = 0
    for section in sections:
        try:
            meta = fetch_section(cookie, site, group, section)
        except Exception as exc:
            print(f"  ! {section}: {type(exc).__name__}: {exc}")
            continue
        floor = section_floor.get(section, "")
        sect_vars = meta.get("variables", [])
        zones = zone_centers(meta)
        temps = pick_temps(sect_vars, match, fallback, args.all_celsius)
        room_map = assign_rooms(temps, zones)
        print(f"  {section} ({floor or '?'}): {len(sect_vars)} points, "
              f"{len(temps)} temperature, {len(set(room_map.values()))} distinct rooms")
        for v in temps:
            vid = v.get("varid")
            if not vid:
                continue
            prev = existing.get(vid, {})
            srv = v.get("server", "")
            new_vars[vid] = {
                # keep a manual room label if present, else derive from geometry
                "room": prev.get("room") or room_map.get(vid, ""),
                "floor": floor or prev.get("floor", ""),
                "metric": "temperature",
                "unit": "C",
                "location_id": prev.get("location_id"),
                "server": srv,
                "name": v.get("text"),
                "target": v.get("target"),
                "section": section,
                "centroid": v.get("centroid"),
            }
            kept += 1
            # Record the controller; preserve any serial already known.
            entry = servers.setdefault(srv, {"controller": "", "floors": []})
            if floor and floor not in entry["floors"]:
                entry["floors"].append(floor)

    print(f"\nTotal temperature variables: {kept} across {len(sections)} section(s)")
    print(f"Controllers (servers): {len(servers)}")
    for srv, info in servers.items():
        flag = "" if info.get("controller") else "  <-- NEEDS controller serial"
        print(f"  {srv}: floors={info.get('floors')} controller='{info.get('controller','')}'{flag}")

    building["variables"] = new_vars
    building["servers"] = servers

    text = json.dumps(building, indent=2, ensure_ascii=False)
    if args.dry_run:
        print("\n--- dry run, not writing ---\n")
        print(text)
        return

    out_path = _resolve_path(args.building)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
