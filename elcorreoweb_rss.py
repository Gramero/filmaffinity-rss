#!/usr/bin/env python3
"""Generate El Correo Sevilla and Andalucía RSS feeds via FreeNewsAPI.

The El Correo site returns HTTP 403 to GitHub Actions, so this script uses the
public structured feed index instead. It keeps the established output names
consumed by Protopage and classifies entries by canonical URL section, falling
back to the publisher section labels returned as `categories`.
"""

from __future__ import annotations

import email.utils
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


API_URL = "https://freenewsapi.ai/v1/search"
PUBLISHER_HOST = "www.elcorreoweb.es"
OUT_DIR = Path("feeds")
PAGE_SIZE = 100
MAX_PAGES = 12
ITEMS_PER_FEED = 50
USER_AGENT = "ElCorreoRSS/2.0 (RSS feed builder)"

SOURCES = {
    "sevilla": {
        "title": "El Correo de Andalucía - Sevilla",
        "description": "Últimas noticias de Sevilla - El Correo de Andalucía",
        "section_label": "sevilla",
        "section_path": "/sevilla/",
        "feed_url": "https://www.elcorreoweb.es/sevilla/",
        "filename": "elcorreoweb-sevilla.xml",
    },
    "andalucia": {
        "title": "El Correo de Andalucía - Andalucía",
        "description": "Últimas noticias de Andalucía - El Correo de Andalucía",
        "section_label": "andalucía",
        "section_path": "/andalucia/",
        "feed_url": "https://www.elcorreoweb.es/andalucia/",
        "filename": "elcorreoweb-andalucia.xml",
    },
}


def fetch_page(offset: int) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "host": PUBLISHER_HOST,
            "size": PAGE_SIZE,
            "offset": offset,
            "sort": "date",
            "fields": "title,url,published_at,description,categories",
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo consultar la fuente de noticias: {exc}") from exc

    results = data.get("results")
    if not isinstance(results, list):
        raise RuntimeError("La respuesta de la fuente no contiene la lista esperada de noticias.")
    return [entry for entry in results if isinstance(entry, dict)]


def section_of(entry: dict) -> str | None:
    """Use the article URL's section path; publisher categories are fallback."""
    parsed = urllib.parse.urlsplit(str(entry.get("url", "")))
    path = urllib.parse.unquote(parsed.path).lower()
    if parsed.hostname and parsed.hostname.lower() in {PUBLISHER_HOST, "elcorreoweb.es"}:
        for name, cfg in SOURCES.items():
            prefix = cfg["section_path"]
            if path.startswith(prefix) and re.match(r"^/[^/]+/\d{4}/\d{2}/\d{2}/", path):
                return name

    categories = entry.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    normalized = {str(category).strip().casefold() for category in categories}
    for name, cfg in SOURCES.items():
        if cfg["section_label"] in normalized:
            return name
    return None


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def collect_articles() -> dict[str, list[dict]]:
    collected = {name: [] for name in SOURCES}
    seen = {name: set() for name in SOURCES}
    for page_number in range(MAX_PAGES):
        entries = fetch_page(page_number * PAGE_SIZE)
        if not entries:
            break
        for entry in entries:
            section = section_of(entry)
            if section not in SOURCES:
                continue
            url = str(entry.get("url", "")).strip()
            title = re.sub(r"\s+", " ", str(entry.get("title", ""))).strip()
            published = parse_datetime(entry.get("published_at"))
            if not url or not title or not published or url in seen[section]:
                continue
            seen[section].add(url)
            collected[section].append(
                {
                    "url": url,
                    "title": title,
                    "description": re.sub(r"\s+", " ", str(entry.get("description", ""))).strip(),
                    "published": published,
                }
            )
        if all(len(items) >= ITEMS_PER_FEED for items in collected.values()):
            break
        if len(entries) < PAGE_SIZE:
            break

    for name, items in collected.items():
        items.sort(key=lambda article: article["published"], reverse=True)
        collected[name] = items[:ITEMS_PER_FEED]
        if not collected[name]:
            raise RuntimeError(
                f"La fuente no devolvió noticias identificables para {SOURCES[name]['title']}; "
                "se conserva el XML publicado anterior."
            )
    return collected


def make_xml(section: str, articles: list[dict]) -> bytes:
    cfg = SOURCES[section]
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = cfg["title"]
    ET.SubElement(channel, "link").text = cfg["feed_url"]
    ET.SubElement(channel, "description").text = cfg["description"]
    ET.SubElement(channel, "language").text = "es-ES"
    ET.SubElement(channel, "lastBuildDate").text = email.utils.format_datetime(
        datetime.now(timezone.utc), usegmt=True
    )

    for article in articles:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = article["url"]
        ET.SubElement(item, "description").text = article["description"] or article["title"]
        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(
            article["published"], usegmt=True
        )

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(contents)
    temporary.replace(path)


def main() -> None:
    feeds = collect_articles()
    # Build both documents before writing either, so a partial API failure
    # cannot publish one fresh section beside one stale section.
    outputs = {
        OUT_DIR / SOURCES[name]["filename"]: make_xml(name, articles)
        for name, articles in feeds.items()
    }
    for path, contents in outputs.items():
        atomic_write(path, contents)
        print(f"{path}: generado con {len(feeds[path.stem.removeprefix('elcorreoweb-')])} noticias")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
