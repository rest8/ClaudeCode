"""Entry point for the iFOREX trading bot."""

from iforex_trader.config import Config
from iforex_trader.strategies.base import DummyStrategy
from iforex_trader.bot import TradingBot


def main():
    config = Config()
    strategy = DummyStrategy()  # Replace with your real strategy
    bot = TradingBot(config=config, strategy=strategy)
    bot.start()


if __name__ == "__main__":
    main()
