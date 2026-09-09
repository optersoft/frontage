// The loader a static page with islands carries, and the only script on it: about a
// kilobyte, no imports of its own, and nothing fetched until a trigger fires.
//
//     <script type="module" src="./_frontage/island.js"></script>
//
// `frontage prerender` writes it beside the wrappers it rendered:
//
//     <fr-island id="fr-island-0" data-fr-island="posts:comments" data-fr-when="visible"
//                data-fr-props='{"post":"hello"}' data-fr-hydrate>…the HTML…</fr-island>
//
// The first trigger to fire boots the runtime — once, shared by every island on the page —
// and hands the queue to `frontage.island`, which mounts each wrapper over the HTML that is
// already there. Triggers keep firing while the runtime downloads, which is why there is a
// queue at all: the page must not lose an island a reader has already scrolled to.

const bridge = { queue: [], hydrate: null };
window.__frontageIslands = bridge;

let booting = null;

function boot() {
  if (booting) return booting;
  // Dynamic, so a page that never fires a trigger never fetches the boot or the glue.
  booting = import(new URL("./boot.js", import.meta.url).href)
    .then((m) => m.startIslands())
    .catch((error) => {
      booting = null;
      throw error;
    });
  return booting;
}

function ready(element) {
  if (element.hasAttribute("data-fr-queued")) return;
  element.setAttribute("data-fr-queued", "");
  bridge.queue.push(element);
  if (bridge.hydrate) bridge.hydrate(element);
  else boot();
}

const idle =
  window.requestIdleCallback ||
  ((fn) => setTimeout(fn, 200));

let observer = null;
// The wrapper is laid out as if it were not there (`display: contents`), so it generates no
// box and an IntersectionObserver would never see it — the island's own elements are what is
// on screen, and what has to be watched. An island with no element of its own (bare text,
// or `only`, which has no build-time content at all) has nothing to observe, so it is ready.
function whenVisible(element) {
  const watched = element.children;
  if (!window.IntersectionObserver || watched.length === 0) return ready(element);
  if (!observer) {
    // 200px early: the boot is a download, and starting it as the island comes into
    // approach is what makes it feel like it was already there.
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            observer.unobserve(entry.target);
            ready(entry.target.closest("fr-island"));
          }
        }
      },
      { rootMargin: "200px" },
    );
  }
  for (const child of watched) observer.observe(child);
}

function whenMedia(element, query) {
  const list = window.matchMedia(query);
  if (list.matches) return ready(element);
  const on = () => {
    if (list.matches) {
      list.removeEventListener("change", on);
      ready(element);
    }
  };
  list.addEventListener("change", on);
}

function arm(element) {
  const when = element.getAttribute("data-fr-when") || "load";
  if (when === "never") return;
  if (when === "visible") return whenVisible(element);
  if (when === "idle") return idle(() => ready(element));
  if (when.startsWith("media:")) return whenMedia(element, when.slice(6));
  ready(element); // "load", "only", and anything a newer build wrote that this loader predates
}

function scan() {
  for (const element of document.querySelectorAll("fr-island[data-fr-island]")) arm(element);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scan, { once: true });
else scan();

// A page that adds islands after load (a client-side route, a dev swap) can say so.
export { scan, boot };
