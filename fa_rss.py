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
        "id": "new_movistar_f",
    },
    "filmin": {
        "title": "Estrenos Filmin - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_filmin.html",
        "id": "new_filmin",
    },
    "prime-video": {
        "title": "Estrenos Prime Video España - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/rdcat.php?id=new_amazon_es",
        "id": "new_amazon_es",
    },
    "cartelera": {
        "title": "Estrenos en cartelera - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/rdcat.php?id=new_th_es",
},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def is_date(text: str) -> bool:
    t = clean(text).lower()
    return bool(
        re.match(r"^\d{1,2}\s+[a-záéíóúñ]{3,}\.?$", t)
        or re.match(r"^\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}$", t)
        or t == "hoy"
    )


def is_real_film_link(href: str | None) -> bool:
    return bool(href and re.search(r"/film\d+\.html", href))


def extract_items(soup: BeautifulSoup, page_url: str, max_items: int = 80) -> list[dict]:
    items = []
    seen = set()
    current_date = ""

    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" "))
        href = a.get("href")

        if not text:
            continue

        if not is_real_film_link(href):
            continue

        link = urljoin(page_url, href)

        if is_date(text):
            current_date = text
            continue

        if link in seen:
            continue

        seen.add(link)

        title = f"{text} — {current_date}" if current_date else text

        items.append({
            "title": title,
            "link": link,
            "description": f"Estreno/incorporación en plataforma según FilmAffinity{(' — ' + current_date) if current_date else ''}",
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
        items = extract_items(soup, cfg["url"])

        if not items:
            raise RuntimeError(f"No se encontraron títulos para {slug}")

        out_file = out_dir / f"{slug}.xml"
        out_file.write_text(
            rss_xml(cfg["title"], cfg["url"], items),
            encoding="utf-8",
        )

        print(f"OK: {out_file} ({len(items)} items)")


if __name__ == "__main__":
    main()
