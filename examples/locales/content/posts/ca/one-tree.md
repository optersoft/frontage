---
title: Un arbre, tres idiomes
date: 2026-09-08
summary: El directori diu en quin idioma és una pàgina, i el de per defecte no diu res.
---

`pages/[lang]/blog/[slug].py` té dos paràmetres: l'idioma, que ve d'un directori, i el
`slug`, que ve del fitxer. `static_paths()` retorna tots dos i la compilació escriu una
pàgina per parella.

El primer idioma de `LOCALES` és el de per defecte i **no afegeix segment**, així que
l'anglès viu a `/blog/one-tree/` i el català a `/ca/blog/one-tree/`.
