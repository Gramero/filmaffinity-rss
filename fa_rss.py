#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


SOURCES = {
    "movistar": {
        "title": "Estrenos Movistar Plus+ - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_movistar_f.html",
        "h1": "Movistar Plus+",
    },
    "filmin": {
        "title": "Estrenos Filmin - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_filmin.html",
        "h1": "Filmin",
    },
    "prime-video": {
        "title": "Estrenos Prime Video España - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/rdcat.php?id=new_amazon_es",
        "h1": "Prime Video España",
    },
    "max-hbo": {
        "title": "Estrenos HBO Max / Max España - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_hbo_es.html",
        "h1": "HBO Max España",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def is_date(text: str) -> bool:
    t = clean(text).lower()
    return bool(
        re.match(r"^\d{1,2}\s+[a-záéíóúñ]{3,}\.?$", t)
        or re.match(r"^\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}$", t)
        or t == "hoy"
    )


def is_title_link(href: str | None) -> bool:
    if not href:
        return False
    return bool(re.search(r"/film\d+\.html", href))


def find_start_h1(soup: BeautifulSoup, expected: str):
    expected_l = expected.lower()
    for tag in soup.find_all(["h1", "h2"]):
        if expected_l in clean(tag.get_text(" ")).lower():
            return tag

    for tag in soup.find_all(["h1", "h2"]):
        txt = clean(tag.get_text(" ")).lower()
        if "incorporaciones" in txt or "fecha de lanzamiento" in txt:
            return tag

    return None


def extract_items(soup: BeautifulSoup, page_url: str, expected_h1: str, max_items: int = 80) -> list[dict]:
    start = find_start_h1(soup, expected_h1)
    if start is None:
        return []

    items = []
    seen = set()
    pending_dates = {}

    for node in start.next_elements:
        if getattr(node, "name", None) == "a":
            text = clean(node.get_text(" "))
            href = node.get("href")

            if not text:
                continue

            lower = text.lower()
            if "próx" in lower or "mensaje" in lower or "twitter" in lower:
                break

            if not is_title_link(href):
                continue

            abs_url = urljoin(page_url, href)

            if is_date(text):
                pending_dates[abs_url] = text
                continue

            if abs_url in seen:
                continue

            if len(text) < 2:
                continue

            seen.add(abs_url)
            date_label = pending_dates.get(abs_url, "")
            title = f"{text} — {date_label}" if date_label else text

            items.append({
                "title": title,
                "link": abs_url,
                "description": f"FilmAffinity: estreno/incorporación en plataforma{(' — ' + date_label) if date_label else ''}",
            })

            if len(items) >= max_items:
                break

    return items


def rss_xml(channel_title: str, channel_link: str, items: list[dict]) -> str:
    now = format_datetime(datetime.now(timezone.utc))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '<channel>',
        f'<title>{html.escape(channel_title)}</title>',
        f'<link>{html.escape(channel_link)}</link>',
        f'<description>{html.escape(channel_title)}</description>',
        f'<lastBuildDate>{now}</lastBuildDate>',
    ]

    for item in items:
        lines.extend([
            "<item>",
            f"<title>{html.escape(item['title'])}</title>",
            f"<link>{html.escape(item['link'])}</link>",
            f"<guid isPermaLink=\"true\">{html.escape(item['link'])}</guid>",
            f"<description>{html.escape(item['description'])}</description>",
            f"<pubDate>{now}</pubDate>",
            "</item>",
        ])

    lines.extend(["</channel>", "</rss>"])
    return "\n".join(lines)


def main() -> None:
    out_dir = Path("feeds")
    out_dir.mkdir(exist_ok=True)

    for slug, cfg in SOURCES.items():
        print(f"Generando {slug}...")
        soup = fetch(cfg["url"])
        items = extract_items(soup, cfg["url"], cfg["h1"])

        if not items:
            raise RuntimeError(f"No se han encontrado títulos para {slug}. Puede haber cambiado el HTML de FilmAffinity.")

        out_file = out_dir / f"{slug}.xml"
        out_file.write_text(rss_xml(cfg["title"], cfg["url"], items), encoding="utf-8")
        print(f"  OK: {len(items)} títulos -> {out_file}")


if __name__ == "__main__":
    main()
