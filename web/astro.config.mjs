// @ts-check
import { defineConfig } from "astro/config";
import optersoft from "@optersoft/astro/integration";

// frontage.optersoft.com: the landing page, the gallery index and a 404,
// static. `mk site.build` writes src/data/gallery.json from the measured
// gallery, builds this into dist/, then merges dist/ into ../www beside the
// built apps (www/gallery/<name>/), the runtime and the wheels. The playground
// and the runner are static files under public/. The chrome is
// `@optersoft/astro`, the sibling checkout at ../../astro.
//
// Directory-style URLs on purpose (`/gallery/`, `/playground/`): the apps
// live in directories under them, and the academy links to these paths.
export default defineConfig({
  site: "https://frontage.optersoft.com",
  integrations: [optersoft()],
});
