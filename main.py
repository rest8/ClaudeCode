"""Entry point for the iFOREX trading bot.

Launches the GUI launcher by default.
Use --no-gui to run headless with a specified strategy.
"""

import sys

if __name__ == "__main__":
    if "--no-gui" in sys.argv:
        from iforex_trader.config import Config
        from iforex_trader.strategies.registry import get_strategy_by_name
        from iforex_trader.bot import TradingBot

        strategy_name = "ダミー（取引なし）"
        for i, arg in enumerate(sys.argv):
            if arg == "--strategy" and i + 1 < len(sys.argv):
                strategy_name = sys.argv[i + 1]

        config = Config()
        strategy = get_strategy_by_name(strategy_name)
        bot = TradingBot(config=config, strategy=strategy)
        bot.start()
    else:
        from launcher import main
        main()
