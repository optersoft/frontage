"""The page that reads the document (`API.md` §6.3).

One file, no CDN and no dependency: it fetches `/openapi.json` and renders it. Swagger UI is
1.4 MB of JavaScript from someone else's host, which is a strange thing to put in front of a
server whose whole argument is that the page should not have to download a runtime to be
useful — and it is exactly the kind of third-party script a private deployment behind the
§5a gate must not make a request to.

What it does not do is "try it out". A form that posts a request from the docs page is a
feature, not a formatting problem, and it belongs in a frontage page with `frontage.schema`
driving the inputs from the same record — which is §4.6's whole point and worth building
properly rather than approximating here.
"""

__all__ = ["page"]

STYLE = """
:root { color-scheme: light dark; --bg:#fff; --fg:#1a1a1a; --muted:#666; --line:#e3e3e3;
        --card:#fafafa; --code:#f4f4f5; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151517; --fg:#e8e8ea; --muted:#9a9aa2; --line:#2b2b30; --card:#1c1c20;
          --code:#232329; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.55 ui-sans-serif,
       -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 2.5rem 1.25rem 6rem; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
.version { color: var(--muted); font-size: .85rem; margin-bottom: 2rem; }
.op { border:1px solid var(--line); border-radius:8px; margin:.6rem 0; background:var(--card); }
.op > summary { cursor:pointer; padding:.7rem .9rem; display:flex; gap:.7rem;
                align-items:baseline; list-style:none; }
.op > summary::-webkit-details-marker { display:none; }
.method { font:600 .72rem/1 ui-monospace, monospace; letter-spacing:.06em; padding:.35rem .5rem;
          border-radius:4px; color:#fff; min-width:4.2rem; text-align:center; }
.get{background:#2563eb} .post{background:#16a34a} .put{background:#c2410c}
.patch{background:#7c3aed} .delete{background:#dc2626} .head,.options{background:#64748b}
.path { font:.95rem ui-monospace, monospace; }
.summary { color:var(--muted); font-size:.85rem; margin-left:auto; text-align:right; }
.body { padding: 0 .9rem 1rem; border-top:1px solid var(--line); }
h3 { font-size:.78rem; text-transform:uppercase; letter-spacing:.07em; color:var(--muted);
     margin:1.1rem 0 .4rem; }
h3 .note { text-transform:none; letter-spacing:0; font-weight:400; }
h2 { font-size:1rem; margin:2.5rem 0 .6rem; }
a.ref { text-decoration:none; }
a.ref code { border-bottom:1px dotted var(--muted); }
table { border-collapse:collapse; width:100%; font-size:.88rem; }
td, th { text-align:left; padding:.3rem .6rem .3rem 0; vertical-align:top;
         border-bottom:1px solid var(--line); }
th { font-weight:600; font-size:.78rem; color:var(--muted); }
code { font-family: ui-monospace, monospace; background:var(--code); padding:.1rem .3rem;
       border-radius:3px; font-size:.85em; }
pre { background:var(--code); padding:.7rem .8rem; border-radius:6px; overflow-x:auto;
      font-size:.8rem; margin:.3rem 0; }
p.desc { white-space: pre-wrap; margin:.6rem 0 0; }
.req { color:#dc2626; font-size:.75rem; }
.empty { color:var(--muted); }
"""

SCRIPT = """
const URL_ = %(url)s;

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v; else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null)
    node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
  return node;
}

// A `$ref` is the only indirection the document uses, and it always points into
// components/schemas.
function refName(schema) {
  const ref = schema && typeof schema === "object" && schema["$ref"];
  return ref ? ref.split("/").pop() : null;
}

function deref(schema, doc) {
  const name = refName(schema);
  if (!name) return schema;
  const found = ((doc.components || {}).schemas || {})[name];
  return found ? Object.assign({ title: name }, found) : schema;
}

function typeOf(schema, doc) {
  schema = deref(schema, doc);
  if (!schema) return "any";
  if (schema.title) return schema.title;
  if (schema.anyOf) return schema.anyOf.map((s) => typeOf(s, doc)).join(" | ");
  if (schema.type === "array") return typeOf(schema.items, doc) + "[]";
  if (!schema.type) return "any";
  let text = schema.type;
  if (schema.format) text += " (" + schema.format + ")";
  const bounds = ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                  "minLength", "maxLength", "pattern"]
    .filter((k) => schema[k] !== undefined)
    .map((k) => k + " " + schema[k]);
  return bounds.length ? text + ", " + bounds.join(", ") : text;
}

// A named schema is shown as its name and defined once, at the bottom. Expanding it at
// every route it appears in buries three lines of route under forty lines of the same
// record — which is what the first version did, and it made the page unreadable.
function schemaBlock(schema, doc) {
  const name = refName(schema);
  if (name) return el("a", { class: "ref", href: "#schema-" + name }, el("code", {}, name));
  if (!schema || !Object.keys(schema).length) return el("p", { class: "empty" }, "any JSON");
  return el("pre", {}, JSON.stringify(schema, null, 2));
}

function operation(path, method, op, doc) {
  const rows = (op.parameters || []).map((p) =>
    el("tr", {}, el("td", {}, el("code", {}, p.name)), el("td", {}, p.in),
       el("td", {}, typeOf(p.schema, doc)),
       el("td", {}, p.required ? el("span", { class: "req" }, "required") : "optional")));
  const body = el("div", { class: "body" });
  if (op.description) body.appendChild(el("p", { class: "desc" }, op.description));
  if (rows.length) {
    body.appendChild(el("h3", {}, "Parameters"));
    body.appendChild(el("table", {},
      el("tr", {}, ["Name", "In", "Type", ""].map((h) => el("th", {}, h))), rows));
  }
  if (op.requestBody) {
    const [media, spec] = Object.entries(op.requestBody.content || {})[0] || ["", {}];
    body.appendChild(el("h3", {}, "Request body \\u00b7 " + media));
    body.appendChild(schemaBlock(spec.schema, doc));
  }
  for (const [status, answer] of Object.entries(op.responses || {})) {
    body.appendChild(el("h3", {}, "Response " + status + " ",
      answer.description ? el("span", { class: "note" }, "\\u00b7 " + answer.description) : null));
    const content = Object.entries(answer.content || {})[0];
    if (content) body.appendChild(schemaBlock(content[1].schema, doc));
  }
  return el("details", { class: "op" },
    el("summary", {},
      el("span", { class: "method " + method }, method.toUpperCase()),
      el("span", { class: "path" }, path),
      op.summary ? el("span", { class: "summary" }, op.summary) : null),
    body);
}

fetch(URL_).then((r) => r.json()).then((doc) => {
  document.title = doc.info.title;
  const main = el("main", {},
    el("h1", {}, doc.info.title),
    el("p", { class: "version" }, "OpenAPI " + doc.openapi + " \\u00b7 version " + doc.info.version));
  if (doc.info.description) main.appendChild(el("p", { class: "desc" }, doc.info.description));
  for (const [path, methods] of Object.entries(doc.paths || {}))
    for (const [method, op] of Object.entries(methods))
      main.appendChild(operation(path, method, op, doc));
  const schemas = Object.entries((doc.components || {}).schemas || {});
  if (schemas.length) {
    main.appendChild(el("h2", {}, "Schemas"));
    for (const [name, schema] of schemas)
      main.appendChild(el("details", { class: "op", id: "schema-" + name },
        el("summary", {}, el("span", { class: "path" }, name)),
        el("div", { class: "body" }, el("pre", {}, JSON.stringify(schema, null, 2)))));
  }
  // A named schema lives in a collapsed <details> at the bottom, so following a link to
  // one has to open it: a fragment that scrolls to something still hidden looks broken.
  main.addEventListener("click", (e) => {
    const link = e.target.closest && e.target.closest("a.ref");
    if (!link) return;
    const target = document.querySelector(link.getAttribute("href"));
    if (target) target.open = true;
  });
  document.body.appendChild(main);
}).catch((e) => {
  document.body.appendChild(el("main", {}, el("h1", {}, "no document"), el("pre", {}, String(e))));
});
"""


def page(openapi_url, title="frontage-api"):
    """The docs page, as one self-contained HTML string."""
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>" + _escape(title) + "</title>"
        "<style>" + STYLE + "</style></head><body>"
        "<script>" + (SCRIPT % {"url": _js_string(openapi_url)}) + "</script>"
        "</body></html>"
    )


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _js_string(text):
    """A URL as a JavaScript literal. `</` is what would end the script element early, and a
    path is the one part of this page that does not come from us."""
    out = text.replace("\\", "\\\\").replace('"', '\\"').replace("</", "<\\/")
    return '"' + out + '"'
