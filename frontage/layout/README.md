# frontage.layout

The parts that make a frontage app look like an app: `columns`, `tabs`, `expander`,
`container`, `metric`, `progress`, `spinner`, `divider`.

Pure Python and CSS — no JavaScript, no WebAssembly, no third-party dependency. It is the
cheapest answer there is to the layout half of Streamlit's surface.

```sh
pip install frontage
```

```py
from frontage import Signal, h, mount
from frontage.layout import columns, metric, tabs

revenue = Signal(1_240_000)

mount(
    lambda: columns(
        metric("Revenue", lambda: f"€{revenue():,}", delta="+4.1%"),
        metric("Churn", "1.8%", delta="-0.3%"),
        widths=[2, 1],
    ),
    "#app",
)
```

`frontage build` finds it, copies its stylesheet, and packs its Python. Nothing to configure.

Everything returns an `Element`, so it composes with `h`, with `html(t"…")` and with the `with`
form, and a hole anywhere inside stays a hole: a `metric` over a signal updates its own text
node rather than rebuilding the card.
