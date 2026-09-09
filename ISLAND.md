# Frontage for sites: static generation and islands — the 0.11 plan

**Status: steps A, B and C shipped in 0.11.0, finished in 0.11.1 (2026-09-09) — `frontage/island.py`,
`_runtime/island.js`, `examples/islands`, `tests/test_island.py` and
`tests/browser/test_island.py`. D through G are unbuilt.** The question this answers is "can
frontage do what Astro does for a content site", and the answer is *most of it, better in
one respect, and three things deliberately not* — with the site you are reading this from
(`web/`, an Astro site) and optersoft.com (`site/`, Astro, three locales, 27 pages) as the
two acceptance tests.

**The measurement that opens §2 now has its other half** (brotli, 2026-09-09): a static page
with nothing interactive is **142 bytes** over the wire and asks for nothing under
`_frontage/`; the islands example is **833 bytes** and carries a **1,341-byte** loader that
fetches nothing until a trigger fires. The prerendered counter's 264,658 bytes of runtime is
still what an *app* costs, and is still the right trade for an app. The gallery publishes
both, measured side by side: **islands, 10 KB, 65 ms, no runtime** against 771–1,199 KB for
the fourteen app cards — and the islands card is measured with everything under `_frontage/`
denied but the loader, so the figure cannot quietly include the runtime.

## 0. The decision, in five sentences

**A page with nothing interactive ships no runtime.** Today a prerendered page is 455
bytes over the wire and then waits for 265 KB of WebAssembly to become interactive; a
content page should be the 455 bytes and stop there. **An island is a `mount` with a
trigger**: `island(view, when="visible")` is prerendered like everything else, and the page
boots the runtime — once, shared by every island — the first time a trigger fires. **Content
is a collection**: Markdown, JSON or YAML with a front matter checked by `frontage.schema`,
rendered on CPython at build time, never in the browser. **Pages are files**: `pages/` with
`index.py`, `[slug].py` and `[...path].py`, layouts as ordinary components, endpoints as
`sitemap.xml.py`, exactly the conventions Astro made familiar and nothing Astro-specific. **No
server, no MDX, no image service**: a frontage site is a directory of files, the way a
frontage app is, and those three would each make it something else.

## 1. What Astro is, and what of it is actually used here

Astro's own description is "the web framework for content-driven websites", and its feature
list is long. The honest way to size the job is to list it and mark what the company's two
Astro sites use, because those are the sites this has to replace to be real.

| Astro feature | `web/` (frontage.optersoft.com) | `site/` (optersoft.com) | here |
|---|---|---|---|
| file-based pages (`src/pages/**`) | 3 pages | `[...slug].astro` + 404 | **§3.4** |
| dynamic routes + `getStaticPaths` | — | every page, from content | **§3.4** |
| layouts and slots | `Site.astro` | `Layout.astro` + the shared chrome | **§3.4** |
| components (`.astro`) | `Card.astro` | the chrome: header, footer, theme toggle, language switcher | ordinary components |
| content collections (`astro:content`) | `data/gallery.json` read by hand | `content/site_*.ts`, typed by hand | **§3.3** |
| Markdown / MDX pages | — | — | Markdown **§3.3**; MDX no, **§4** |
| islands + `client:*` directives | — (the gallery apps are whole pages) | the theme toggle, the language switcher | **§3.2** |
| static endpoints (`*.xml.ts`, `*.json.ts`) | — | `sitemap.xml.ts` | **§3.4** |
| i18n routing | — | `/`, `/es/`, `/ca/` by content module | **§3.5** |
| `<ClientRouter>` view transitions | — | — | done (0.10.5, `Router(view_transition=True)`) |
| prefetch on hover | — | — | done (0.10.3) |
| `astro:assets` (Image, Picture) | — | — | no, **§4** |
| scoped `<style>`, Tailwind | Tailwind | Tailwind | `build --tailwind` (0.10.7) |
| dev server with HMR | yes | yes | done, and it keeps state |
| dev toolbar | — | — | done (devtools, 0.10.6) |
| SSR adapters, middleware, actions, server islands | — | — | no, **§4** |
| integrations (sitemap, rss, …) | the chrome integration | the chrome integration | sitemap and RSS are endpoints; the chrome is a component package |

Two things stand out. **The company uses about a third of Astro**, and every used piece is
on the plan. **The two islands in production are the theme toggle and the language
switcher** — a few lines of state each — and today they cost the *whole* Astro client
runtime for that page. The frontage version of that trade is the subject of §2.

## 2. Where frontage stands, measured

**Prerendering and hydration exist and work.** `frontage prerender` renders each route on
CPython, waits for resources and async memos, writes their values into the page, and writes
the fences hydration reads; the browser adopts the HTML node by node and replays the clicks
made before Python was ready. Per-route titles and meta tags land in `<head>` (0.10.4). The
browser suite covers the counter, a resource that must not refetch, and the tracker's routes.

**The numbers.** Prerendered pages, and what they wait for (brotli, 2026-09-09):

| | raw | over the wire |
|---|---|---|
| `examples/counter`, prerendered page | 1,283 | **455** |
| `examples/tracker`, `/` | 3,396 | 1,151 |
| `examples/tracker`, `/issues` | 4,463 | 1,288 |
| the runtime + the counter's 12 modules | 780,000 | **264,658** |

A visitor to the prerendered counter sees the page at once and then downloads **580× the
page** to make a button work. For an app that is the right trade — the runtime is the app.
For a content page it is the wrong one, and it was the trade every page made before 0.11,
because — the first three of these are what A, B and C fixed:

- **One boot tag, one runtime, one boot.** `boot.js` finds `script[data-fr-boot]`, fetches
  the wasm and every module in the manifest, and runs the entry. A page had no way to say
  "later", "when this is visible" or "never".
- **Hydration is all-or-nothing per page.** Every `mount` hydrated when the entry ran; the
  interactive parts and the static parts were one tree, one boot.
- **The page's Python is one closure.** A route can be a chunk (0.10.3); an *island* could
  not, so a page with a theme toggle and a 40 KB chart module shipped the chart module to
  hydrate the toggle.
- **There is no content pipeline.** No Markdown, no front matter, no collections, no
  `[slug]` pages generated from data. The academy's chapters are Markdown with embedded
  frontage apps — islands in everything but name — and they are rendered by the academy's
  own Rust, not by frontage.
- **Routing is code.** `Router(Route(...))` is right for an app; a content site wants the
  directory to be the site map, and it wants a build to know every URL up front (sitemap,
  redirects, hreflang).

**What is different from Astro's situation, and it matters.** Astro's islands exist because
each island would otherwise ship a JavaScript framework, and three islands from three
frameworks ship three. Here there is exactly one runtime, it is 265 KB, and it is the same
bytes for every page of every site — cached after the first. So the frontage island model
has a different payoff: **defer the one boot until it is needed, and skip it entirely on
pages that never need it.** A content site where one page in ten has a widget ships zero
runtime on nine pages, and the tenth boots it on `visible` — from cache, in 26 ms, after the
reader has already been reading. That is a better story than Astro's, not a worse one, and
it is the reason to build this rather than to keep using Astro for the sites.

## 3. The architecture

### 3.1 Zero by default

`frontage site` (the build, §3.6) renders every page on CPython. A page that mounts nothing
with a trigger gets **no boot tag, no manifest, no runtime**: HTML, its CSS, its images. That
is Astro's "zero JavaScript by default", and it needs no new mechanism — the prerenderer
already produces the HTML; the change is that the boot tag is written only when §3.2 asks
for it.

Gate: a Markdown page from a collection, built, is one HTML file and the stylesheet. The
browser suite asserts the page makes no request under `_frontage/`.

### 3.2 Islands

```py
from frontage import island


def page(post):
    return layout(
        article(post),  # static: rendered once, at build
        island(comments, when="visible", post=post.id),  # interactive: hydrated when seen
        island(theme_toggle, when="idle"),
    )
```

An island is a **mount with a trigger**. At build time it is rendered like any other view,
inside a wrapper the loader can find (`<fr-island data-fr-when="visible" data-fr-module="…"
data-fr-props="…">`). In the browser, a small loader — the only script a page with islands
carries, ~1 KB — watches the triggers:

| `when=` | boots | Astro's |
|---|---|---|
| `"load"` | at once | `client:load` |
| `"idle"` | `requestIdleCallback`, else a short timeout | `client:idle` |
| `"visible"` | `IntersectionObserver` | `client:visible` |
| `"media:(max-width: 50em)"` | when the query matches | `client:media` |
| `"never"` | rendered at build, never hydrated | *(no directive: plain HTML)* |
| `"only"` | not rendered at build; boots on load | `client:only` |

The first trigger to fire boots the runtime — **once**; every island on the page shares it,
which is the thing three React islands cannot do. Each island then hydrates its own wrapper
with its own module, so a page with a theme toggle and a chart fetches the chart's chunk
only when the chart is seen. The islands' modules are chunks (0.10.3's machinery, with the
island's module as the chunk root); the manifest gains `islands: {name: [modules]}`.

Props cross as JSON written into the wrapper at build time, the way resources' values do
today — which means the same rule: **an island's props must be JSON**. A `Signal` shared
between two islands is the one real question (§6): the answer proposed is that islands on
one page share one interpreter and so may share module-level state by import, which is
what a Solid or Svelte developer expects and a React one does not get.

`mount(view, "#app")` stays exactly what it is: an app's whole-page mount, hydrated on load.
`island` is `mount` with a trigger and a wrapper; the prerenderer and the loader are what
know the difference.

Gates: a page with one `visible` island makes no `_frontage/` request until it is scrolled
into view, then exactly the runtime plus that island's modules; two islands share one
runtime (one wasm fetch); an island's early clicks replay, as today.

### 3.3 Content

```py
from frontage.content import collection
from frontage.schema import iso_date, record, text

Post = record(("title", text(min=1)), ("date", iso_date()), ("summary", text(), None))
posts = collection("posts", Post)  # content/posts/*.md, front matter checked

for post in posts.entries():  # sorted by date if the schema has one
    post.slug, post.data["title"], post.html()
```

A **collection** is a directory of Markdown, JSON or YAML files whose front matter is checked
by a `frontage.schema` record — which is exactly Astro's `defineCollection({ schema })`,
and the schema module already exists and already runs on CPython. `entries()` is typed data
with a slug from the file name; `html()` is the Markdown rendered at build time. Everything
here runs on CPython inside the build; **none of it ships**. A page that lists posts is a
plain function over `posts.entries()`, rendered once.

Markdown rendering is a dependency choice (§6): `markdown-it-py` (CommonMark, plugins,
the one the Python ecosystem converged on) with the `:::` container directive the academy
already uses for its cards — so a Markdown page can hold an island:

```markdown
::: island comments when="visible"
:::
```

This is the place to say **no MDX** (§4). A Markdown page that needs a component says so
with a directive; a page that needs Python is a `.py` page.

### 3.4 Pages, layouts, endpoints

```
site/
  pages/
    index.py                 → /
    about.py                 → /about/
    blog/index.py            → /blog/
    blog/[slug].py           → /blog/<slug>/, one per static_paths()
    docs/[...path].py        → /docs/<anything>/
    sitemap.xml.py           → /sitemap.xml, an endpoint
  layouts/site.py
  content/posts/*.md
  public/                    → copied as is
```

A page module defines `page(**params)` returning a view, and a dynamic page defines
`static_paths()` returning the params to build — Astro's `getStaticPaths`, in Python:

```py
from frontage.content import collection

posts = collection("posts", Post)


def static_paths():
    return [{"slug": post.slug} for post in posts.entries()]


def page(slug):
    post = posts.get(slug)
    return site(title=post.data["title"], children=article(post))
```

A layout is an ordinary component taking `children` — no new concept; `Route(root=)` already
is one. An endpoint is a module with `get()` returning `(bytes_or_str, content_type)`, which
covers `sitemap.xml`, `rss.xml`, `search.json`. Redirects are a `_redirects` file the build
writes from a `redirects()` in `site.py`, since every static host reads that shape.

The file-routing walk reuses `cli/graph.py`: pages are modules, and their import closure is
what an island needs, which the chunk machinery already computes.

### 3.5 Locales

optersoft.com is `/`, `/es/`, `/ca/` with the same page tree under each. The plan is Astro's
routing shape with none of its config: a `pages/[lang]/…` tree whose `static_paths()` lists
the locales, a `content/<collection>/<lang>/` layout for translated entries, and a
`hreflang()` helper the layout calls to write the alternates. Nothing about locales needs to
be in the framework beyond that helper; it is a convention the two sites already follow.

### 3.6 The build, the dev server, and what changes

`frontage site DIR` is the new command; `prerender` stays for an *app* with routes. It:

1. walks `pages/`, calls each dynamic page's `static_paths()`, and renders every URL on
   CPython with `HtmlRenderer(hydration_markers=True)`;
2. renders each island into its wrapper, records its module and props;
3. writes each page as `<url>/index.html`; the boot tag and manifest **only** on pages with an
   island whose `when` is not `"never"`;
4. compiles each island's closure as chunks, hashed, with the runtime beside them once;
5. runs endpoints, copies `public/`, writes `_headers`, `_redirects`, and `--tailwind`.

The dev server already reloads on a change and swaps modules in a running page; for a site
it renders a page on request the way it compiles a module on request today, so an edit to
Markdown shows on reload with nothing to build.

## 4. What Astro has that this will not, deliberately

- **SSR adapters, middleware, actions, server islands.** The framework owns no server
  (`COMPONENTS.md` §8) and a site is a directory. A form that needs a server posts to one —
  `frontage.remote`, PostgREST, Supabase — from an island.
- **MDX.** A Markdown page with components is a `:::` directive; a page that is mostly
  Python is a `.py` page. MDX is a third language between the two, and its whole value is
  letting JSX into prose, which t-strings already are.
- **An image service** (`astro:assets`). Responsive images are a build step on files, not a
  framework feature; if it comes it comes as an endpoint-style build hook, later.
- **An integrations ecosystem.** Sitemap and RSS are one endpoint each. The Optersoft chrome
  becomes a component package the two sites import, which is what `@optersoft/astro` is
  today with the Astro-specific half removed.
- **`.astro` files.** A frontage page is Python and its markup is a t-string; there is no
  reason to invent a fourth template syntax.

## 5. The plan, in order, with its gates

| step | ships | gate |
|---|---|---|
| ✅ **A. islands in the loader** (0.11.0) | `island(when=)`, the `<fr-island>` wrapper, the loader (1,341 bytes brotli), deferred boot, one runtime per page | a `visible` island fetches nothing until seen; two islands, one wasm fetch |
| ✅ **B. islands as chunks** (0.11.0) | `island("mod:name")` is a chunk root, props as JSON on the wrapper | a page with a toggle and a chart fetches the chart's modules only when the chart is seen |
| ✅ **C. zero-runtime pages** (0.11.0) | `mount(…, when="never")`; the boot tag and its preload hints written only where an island is | a built content page makes no `_frontage/` request |
| **D. content** | `frontage.content`: collections, front matter through `frontage.schema`, Markdown with `:::` | a collection with a bad front matter fails the build naming the file and the field |
| **E. pages** | `frontage site`, file routing, `static_paths`, layouts, endpoints, `_redirects` | `web/` rebuilt from frontage, byte-comparable HTML, the gallery cards as `never` islands |
| **F. locales** | the `[lang]` convention, `hreflang()` | `site/` rebuilt: 27 pages, three locales, the theme toggle and language switcher as `idle` islands, sitemap from an endpoint |
| **G. the chrome** | `@optersoft/astro` → a frontage component package the two sites share | both sites on it, `astro/` retired for them |

A is the whole idea and stands alone; C is a one-line consequence of A; B makes A honest for
a page with more than one island; D and E are the content site; F and G are the acceptance
test. Each step is a release. The academy's chapters — Markdown with embedded apps — are the
third site, and the one with the most islands per page, once D lands.

**What A–C settled that §6 had left open**, now that they are built:

- **The wrapper cannot be what an `IntersectionObserver` watches.** `<fr-island>` is
  `display: contents`, so it generates no box and an observer on it never fires — the
  island's own elements are what is on screen, and the loader observes those. This cost an
  afternoon and is the one thing about the design that is not obvious from the design.
- **A static page's entry is never run in the browser**, so `frontage.island` is what the
  boot runs as `__main__`. That is why every import in it is absolute: a relative import in a
  module running as `__main__` resolves against `__main__` and fails.
- **`when="never"` is one call with two readings**, and the page itself says which: a page
  the loader drives has no boot tag, so `mount(…, when="never")` does nothing there, while
  under `frontage serve` — where there is a boot tag and the entry does run — it mounts as
  usual and the islands render live. Nothing had to be configured to get both.
- **An island does not get the page's hydration data, it gets its own.** Each is rendered in
  a pass of its own, with its own resource registry, its own memo ordinals and its own
  `unique_id` scope, and its settled values are written beside its wrapper — because in the
  browser each is its own `mount`, and a shared data block would be read by whichever island
  hydrated first.
- **Every island on a page must share one renderer.** Delegated events go through a single
  dispatcher registered with the runtime, so a second `DomRenderer` replaces the first and
  every island that mounted before it stops hearing its own clicks — with nothing on the
  console and a DOM that looks correctly hydrated. Two islands hydrating in the same frame is
  the ordinary case; the bug only surfaced when a test used three. (0.11.1)
- **The early-click replay is per island, not per page.** `__frontage_replay(root)` dispatches
  only what happened inside `root` and keeps capturing until no wrapper is left waiting, so a
  click on an island whose trigger fires a minute later still arrives. The first version was
  the page's, and the first island to hydrate ate the queue. (0.11.1)
- **`only` really means "not rendered at build".** It leaves an empty wrapper, and that is
  the point: it is for a component with no server-side meaning — one that reads the document,
  a canvas, a clock — where prerendering it puts something on screen the first frame throws
  away. (0.11.1)
- **The naming question answered itself.** `island(view, when=)` and `mount(view, target,
  when=)` are two names because they take different second arguments; `when=` is the same
  word in both, and `"never"` on a mount is what makes the page static.

## 6. Risks, and the decisions to take

- **State between islands.** Astro islands are isolated because they may be different
  frameworks. Here they share one interpreter, so module-level signals are shared by
  import, which is simpler and more powerful — and means an island's *props* and an island's
  *shared state* are different things. Decision: props are JSON and immutable; shared state
  is a module; the docs say so once.
- **Boot latency on the first trigger.** 26 ms from cache, 200–400 ms cold on a slow
  connection. `idle` is the right default for anything above the fold; the loader should
  `preload` the wasm on `visible` islands' first approach (`rootMargin`) so the fetch is
  already in flight. Measure, then decide the default.
- **Markdown renderer.** `markdown-it-py` for CommonMark plus directives, or `mistune` for
  speed. The academy already renders `:::` containers in Rust; the frontage renderer needs
  the same grammar for the same content, which argues for markdown-it-py's directive plugin
  and a shared conformance test over the academy's chapters.
- **`hydrate` for an island that changed.** A `never` island is HTML; a `visible` island's
  markup at build must match what the module renders in the browser, or hydration rebuilds
  it — `frontage.debug`'s report already names the mismatch. The dev server should render
  islands the built way, so the mismatch shows up in development.
- **Naming.** `island(view, when=)` versus `mount(view, when=)`. An island is a mount with a
  trigger, and one name for both is tempting; the proposal keeps two, because "mount" is
  what an app does once and "island" is what a page does many times, and a reader of either
  should not have to know the other.
- **How much of `site/` is copy.** Twenty-seven pages in three locales as TypeScript content
  modules. Porting them to YAML collections is a day; it is also the moment to find out
  whether a content model designed for Astro is right for anything else.
