# RSS de estrenos en plataformas desde FilmAffinity

Este paquete genera RSS con los estrenos/incorporaciones fechadas que FilmAffinity publica para estas plataformas:

- Movistar Plus+
- Filmin
- Prime Video España
- HBO Max / Max España

## Por qué no está el cuarto enlace que pasaste

El enlace:

```text
https://www.filmaffinity.com/es/rdcat.php?id=new_th_es
```

no es una plataforma. Es cartelera/cines. Para plataformas he usado HBO Max / Max:

```text
https://www.filmaffinity.com/es/cat_new_hbo_es.html
```

## Uso

```bash
pip install requests beautifulsoup4
python fa_rss.py
```

Crea:

```text
feeds/movistar.xml
feeds/filmin.xml
feeds/prime-video.xml
feeds/max-hbo.xml
```

## URLs finales en GitHub Pages

Si tu usuario de GitHub es `Gramero` y el repositorio se llama `filmaffinity-rss`, serán:

```text
https://gramero.github.io/filmaffinity-rss/feeds/movistar.xml
https://gramero.github.io/filmaffinity-rss/feeds/filmin.xml
https://gramero.github.io/filmaffinity-rss/feeds/prime-video.xml
https://gramero.github.io/filmaffinity-rss/feeds/max-hbo.xml
```

## Actualización automática

El workflow incluido actualiza los RSS cada 6 horas.
