"""The lazy route. It and `pages.rides`, which nothing else imports, are the chunk."""

from frontage import h

from .rides import RIDES


def page():
    by_hour = {}
    for hour, riders in RIDES:
        by_hour[hour] = by_hour.get(hour, 0) + riders
    hours = sorted(by_hour)
    busiest = max(hours, key=lambda hour: by_hour[hour])
    return h.div(
        h.h1("Report", id="report"),
        h.p(f"{len(RIDES)} rides, busiest at {busiest:02d}:00", id="summary", cls="note"),
        h.table(
            h.thead(h.tr(h.th("Hour"), h.th("Riders"))),
            h.tbody(*[h.tr(h.td(f"{hour:02d}:00"), h.td(str(by_hour[hour]))) for hour in hours]),
        ),
    )
