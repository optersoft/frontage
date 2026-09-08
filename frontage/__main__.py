"""`python -m frontage`: the command line (build, prerender, serve, check, tailwind). Never imported
in the browser."""

import sys

from frontage.cli import main

sys.exit(main())
