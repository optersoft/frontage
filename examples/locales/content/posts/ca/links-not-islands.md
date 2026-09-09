---
title: Un selector són enllaços
date: 2026-09-03
summary: La compilació coneix totes les URL, així que canviar d'idioma és un enllaç, no un runtime.
---

El selector d'idioma d'aquesta pàgina són tres elements: dos `<a>` i un `<span>` per al que
estàs llegint. Sense runtime, sense illa, sense hidratació.

És possible perquè la compilació va fer totes les pàgines i en coneix les URL, així que
`site.translate(path, "ca")` és una resposta i no una suposició.
