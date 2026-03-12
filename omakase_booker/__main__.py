"""Allow running as: python -m omakase_booker

Launches the GUI application by default.
Use --cli flag for headless CLI mode.
"""

import sys


def main():
    if "--cli" in sys.argv:
        from .main import main as cli_main
        cli_main()
    else:
        from .gui.launcher import launch
        launch()


main()
