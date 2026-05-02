#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RSS de estrenos en plataformas según FilmAffinity.

Genera feeds para:
- Movistar Plus+
- Filmin
- Prime Video España
- HBO Max / Max España

IMPORTANTE:
FilmAffinity no ofrece RSS oficial. Este script lee sus páginas públicas y extrae
los títulos fechados en cada plataforma. No incluye cartelera de cines.
"""

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
    },
    "filmin": {
        "title": "Estrenos Filmin - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_filmin.html",
    },
    "prime-video": {
        "title": "Estrenos Prime Video España - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/rdcat.php?id=new_amazon_es",
    },
    "max-hbo": {
        "title": "Estrenos HBO Max / Max España - FilmAffinity",
        "url": "https://www.filmaffinity.com/es/cat_new_hbo_es.html",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
}

MAX_ITEMS = 80


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def is_date_label(text: str) -> bool:
    text = clean(text).lower()
    return bool(
        re.match(r"^\d{1,2}\s+[a-záéíóúñ]{3,}\.?$", text)
        or re.match(r"^\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}$", text)
        or text == "hoy"
    )


def is_film_url(href: str | None) -> bool:
    if not href:
        return False
    return "/film" in href or "film" in href


def extract_platform_premieres(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    Extrae pares fecha + título desde las páginas de plataforma de FilmAffinity.

    En páginas tipo Movistar/Filmin/HBO:
      <a>30 abr.</a> <a>Película</a>

    En páginas tipo rdcat Prime:
      el patrón sigue siendo de enlaces fechados y enlaces a ficha.
    """
    items = []
    seen = set()
    current_date = ""

    # Trabajamos con todos los enlaces porque FilmAffinity usa el mismo enlace
    # para la fecha y para el título en algunos listados.
    for a in soup.find_all("a"):
        text = clean(a.get_text(" "))
        href = a.get("href")

        if not text:
            continue

        if is_date_label(text):
            current_date = text
            continue

        # Excluye navegación/categorías: queremos fichas de títulos.
        if not is_film_url(href):
            continue

        # Evita falsos positivos: títulos demasiado cortos o duplicados.
        link = urljoin(base_url, href)
        key = (text.lower(), link)

        if key in seen:
            continue

        seen.add(key)

        title = text
        if current_date:
            title = f"{title} — {current_date}"

        items.append({
            "title": title,
            "link": link,
            "date_label": current_date,
            "description": f"Estreno/incorporación en plataforma según FilmAffinity: {current_date}" if current_date else "Estreno/incorporación en plataforma según FilmAffinity",
        })

        if len(items) >= MAX_ITEMS:
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
        items = extract_platform_premieres(soup, cfg["url"])

        out_file = out_dir / f"{slug}.xml"
        out_file.write_text(
            rss_xml(cfg["title"], cfg["url"], items),
            encoding="utf-8",
        )

        print(f"  {len(items)} títulos -> {out_file}")


if __name__ == "__main__":
    main()
