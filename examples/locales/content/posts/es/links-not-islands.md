---
title: Un selector son enlaces
date: 2026-09-03
summary: La compilación conoce todas las URL, así que cambiar de idioma es un enlace, no un runtime.
---

El selector de idioma de esta página son tres elementos: dos `<a>` y un `<span>` para el que
estás leyendo. Sin runtime, sin isla, sin hidratación.

Es posible porque la compilación hizo todas las páginas y conoce sus URL, así que
`site.translate(path, "es")` es una respuesta y no una suposición.
