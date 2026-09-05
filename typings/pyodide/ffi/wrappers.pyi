from typing import Any

# Declared as Any rather than as functions: frontage.runtime rebinds these names per
# platform, and the server-side stand-in is an object, not a function.
add_event_listener: Any
remove_event_listener: Any
