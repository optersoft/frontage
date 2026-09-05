"""Forms: two-way bindings, a Switch on a select, and an Action for the submit."""

import asyncio

from frontage import Action, Match, Show, Signal, Switch, component, h, mount


async def save(data):
    await asyncio.sleep(0.2)
    return f"saved {data['name']} ({data['plan']}, newsletter={'yes' if data['news'] else 'no'})"


@component
def app():
    name = Signal("")
    plan = Signal("free")
    news = Signal(False)
    submit = Action(save)

    def on_submit(ev):
        ev.preventDefault()
        submit.dispatch({"name": name(), "plan": plan(), "news": news()})

    return h.form(
        h.label("Name ", h.input(bind_value=name, id="name", placeholder="your name")),
        h.fieldset(
            h.legend("Plan"),
            h.label(h.input(type_="radio", name="plan", value="free", bind_group=plan), " free"),
            h.label(h.input(type_="radio", name="plan", value="pro", bind_group=plan), " pro"),
        ),
        h.label(h.input(type_="checkbox", bind_checked=news, id="news"), " newsletter"),
        h.p(
            Switch(
                [
                    Match(lambda: plan() == "pro", h.b("Pro: everything, billed monthly.", id="plan-pro")),
                    Match(lambda: plan() == "free", h.i("Free: the basics.", id="plan-free")),
                ]
            )
        ),
        h.button(
            lambda: "Saving…" if submit.pending() else "Save",
            type_="submit",
            id="save",
            disabled=lambda: submit.pending() or not name().strip(),
        ),
        h.p(Show(submit.value, lambda v: h.span(v, id="result"))),
        on_submit=on_submit,
    )


mount(app, "#app")
