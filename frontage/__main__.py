"""`python -m frontage`: the command line (export, tailwind, check, pyscript). Never imported
in the browser."""

import sys

from frontage.cli import main

sys.exit(main())
