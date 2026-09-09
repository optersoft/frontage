---
title: Un árbol, tres idiomas
date: 2026-09-08
summary: El directorio dice en qué idioma está una página, y el idioma por defecto no dice nada.
---

`pages/[lang]/blog/[slug].py` tiene dos parámetros: el idioma, que viene de un directorio, y
el `slug`, que viene del archivo. `static_paths()` devuelve los dos y la compilación escribe
una página por pareja.

El primer idioma de `LOCALES` es el de por defecto y **no añade segmento**, así que el inglés
vive en `/blog/one-tree/` y el español en `/es/blog/one-tree/`.
