from pyscript import document

import frontage
from frontage import h, render_to_string

view = h.p("Hello from the string renderer")
document.getElementById(
    "app"
).textContent = f"Frontage {frontage.__version__} on {frontage.platform}\n{render_to_string(view)}"
