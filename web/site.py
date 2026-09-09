"""frontage.optersoft.com: what the whole site knows about itself.

Built by `frontage site` — the framework's own site, on the framework. The chrome is
`optersoft_brand`, a sibling checkout consumed by path like every other dependency here.
"""

import optersoft_brand

BASE = "https://frontage.optersoft.com"

#: The chrome's stylesheets, fonts and mark, at `/brand/` — where `brand.css` and the
#: `head()` icons look for them.
STATIC = [(optersoft_brand.static, "brand")]
