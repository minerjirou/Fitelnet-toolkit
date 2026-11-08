"""Allow `python -m fitelnet_ssh` alongside the installed `fitelnet-ssh` command."""

import sys

from .cli import main

sys.exit(main())
