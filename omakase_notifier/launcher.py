"""Top-level launcher that adjusts sys.path and starts the desktop UI.

The desktop shortcut points to this file. We don't rely on the package
being installed into site-packages, so we add `src/` to sys.path here.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from omakase_notifier.desktop import run  # noqa: E402

if __name__ == "__main__":
    run()
