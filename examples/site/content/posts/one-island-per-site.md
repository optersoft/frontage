---
title: One island, on the page that needs it
date: 2026-09-02
summary: Six pages ship no runtime at all; this one boots it when you scroll here.
---

Every other page of this site is HTML and stops there. The home page, the blog index, the
about page, the two posts either side of this one: a browser asks for the document and the
stylesheet, draws them, and has nothing left to do.

That is not a trick and it is not a special mode. It is what a page *is* when nothing on it
changes after it is written, which is what most pages are. The unusual thing about the last
fifteen years is that we stopped noticing.

Sometimes a page is not most pages. A paragraph wants a poll, or a calculator, or a chart of
the thing it is arguing about, or — as here — a button that counts how many readers found it
useful. The old answer was to send the framework to every reader of every page so that this
one paragraph could have its button.

The cost of that answer is not the framework's size, which is a number people argue about.
It is that the reader pays it before they know whether they want to stay, on the connection
they happen to have, on the device they happen to be holding, for a button they may never
press.

The answer here is narrower. This paragraph is followed by a container that is not finished:

::: island widgets:reactions when="visible" post="one-island-per-site"
:::

The build wrote the runtime once, beside the pages, and only because of that block. It is not
on the other five pages, because they do not have one. A reader who never opens this post
never asks for a byte of it, and a reader who opens it and does not scroll this far does not
either.
