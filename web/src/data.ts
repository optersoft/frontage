// The measured gallery, as tools/gallery.py writes it to src/data/gallery.json
// (gitignored) — the same document the site serves at /gallery/gallery.json.
// Absent (`astro dev` before `mk gallery` has run) the gallery page renders
// empty rather than failing the build; `import.meta.glob` is what makes a
// missing file an empty map instead of an error.

export interface App {
  name: string;
  title: string;
  /** HTML — a blurb may write `<code>`. Authored in gallery.py, never from input. */
  blurb: string;
  bytes: number;
  ms?: number;
  /**
   * A static page: prerendered, with no boot tag. `bytes` and `ms` are what a reader pays to
   * see it — the runtime is fetched later, when an island's trigger fires, and gallery.py
   * measures the card with it denied so the figure cannot quietly include it.
   */
  deferred?: boolean;
}

export interface Gallery {
  apps: App[];
  measured: boolean;
  /** `YYYY-MM-DD` of the measurement. */
  when: string;
  /** KB every app downloads identically: the interpreter, the loader, the framework. */
  shared_kb: number;
}

const files = import.meta.glob<{ default: Gallery }>("./data/gallery.json", { eager: true });

export const gallery = (): Gallery | null => files["./data/gallery.json"]?.default ?? null;
