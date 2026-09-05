# `pages` and `components` are imported for their side effect: each registers its
# classes on `app`. Nothing here refers to them by name.
import components  # noqa: F401
import pages  # noqa: F401
from common import app

app.mount("#app")
