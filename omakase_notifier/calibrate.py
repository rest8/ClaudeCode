"""Convenience wrapper so you can run the crawler calibration without
setting PYTHONPATH:

    python calibrate.py list https://omakase.in/ja
    python calibrate.py availability https://omakase.in/ja/r/<id>
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from omakase_notifier.crawler.calibrate import main  # noqa: E402

if __name__ == "__main__":
    main()
