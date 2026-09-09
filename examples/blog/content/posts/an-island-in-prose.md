---
title: An island in prose
date: 2026-09-07
summary: A container in the Markdown becomes a mount with a trigger.
---

A post is prose, and prose is finished when you write it. The words above and below this
line were rendered on a laptop, by CPython, from a file with a `---` fence at the top; the
browser was handed HTML and asked to do the one thing it has always been good at.

Once in a while a paragraph wants something that is not finished: a poll, a calculator, a
chart of the thing it is arguing about, a button that counts how many readers agreed. The
old answer was to send the whole framework down the wire so that one paragraph could have
its button, and to send it to every reader of every post, including the ones who close the
tab after the first line.

The answer here is to say where the exception is and let the page keep its shape. A
container in the Markdown names a component, and a trigger says when it should come alive:

::: island widgets:reactions when="visible" post="an-island-in-prose"
:::

That block is a `::: island` container. `frontage.content` renders the Markdown around it
and puts an island where it stood, so the widget hydrates when a reader scrolls to it and
the rest of the post never asks for anything at all.

The trade is the same one the whole release is about, made one paragraph at a time: the page
is HTML until something on it needs not to be.
