# The frontage variant freezes only the port's asyncio (its scheduler is the JavaScript
# event loop). Everything a page needs beyond that is a C module or ships in app.tar.
include("$(PORT_DIR)/variants/manifest.py")
