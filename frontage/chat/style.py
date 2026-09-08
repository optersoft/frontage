"""The stylesheet, as a string, so a test can assert every class this package emits exists.

It is also written to `_browser/index.css` at build time, which is what `frontage build` links
from the page. Two copies would drift, so the file is generated from this one — see `mk style`.
"""

STYLESHEET = """\
/* frontage-chat. Tokens first, so an app can restyle without touching a rule. */
.fr-chat-log, .fr-chat-input {
  --fr-line: color-mix(in srgb, currentColor 15%, transparent);
  --fr-muted: color-mix(in srgb, currentColor 60%, transparent);
  --fr-accent: #b3541e;
  --fr-radius: 12px;
}

.fr-chat-log { display: flex; flex-direction: column; gap: .75rem; overflow-y: auto; padding: .5rem 0; }

.fr-msg { display: flex; }
.fr-msg-user { justify-content: flex-end; }
.fr-msg-body {
  max-width: 42ch;
  padding: .5rem .85rem;
  border-radius: var(--fr-radius);
  border: 1px solid var(--fr-line);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.fr-msg-user .fr-msg-body { background: color-mix(in srgb, var(--fr-accent) 12%, transparent); }

/* An empty bubble is the answer before its first token: give it a height so the log does
   not jump when the text arrives. */
.fr-msg-assistant .fr-msg-body:empty::after { content: "…"; color: var(--fr-muted); }

.fr-chat-input { display: flex; gap: .5rem; margin-top: .75rem; }
.fr-chat-text {
  flex: 1;
  padding: .55rem .8rem;
  border: 1px solid var(--fr-line);
  border-radius: var(--fr-radius);
  font: inherit;
  color: inherit;
  background: transparent;
}
.fr-chat-send {
  padding: .55rem 1rem;
  border: 1px solid var(--fr-line);
  border-radius: var(--fr-radius);
  font: inherit;
  cursor: pointer;
}
.fr-chat-send[disabled], .fr-chat-text[disabled] { opacity: .5; cursor: default; }

.fr-feedback { display: flex; gap: .25rem; margin-top: .25rem; }
.fr-rate {
  border: 0;
  background: transparent;
  cursor: pointer;
  font-size: .9rem;
  opacity: .45;
  padding: .1rem .25rem;
}
.fr-rate:hover, .fr-rate.fr-on { opacity: 1; }
"""
