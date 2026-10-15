"""``python3 -m appvol.gui`` — run the GUI from a checkout."""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
