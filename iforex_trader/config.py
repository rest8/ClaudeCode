"""Configuration management for iFOREX trader."""

import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


class Config(BaseModel):
    email: str = os.getenv("IFOREX_EMAIL", "")
    password: str = os.getenv("IFOREX_PASSWORD", "")
    headless: bool = os.getenv("HEADLESS", "false").lower() == "true"
    trade_interval_seconds: int = int(os.getenv("TRADE_INTERVAL_SECONDS", "60"))
    default_lot_size: int = int(os.getenv("DEFAULT_LOT_SIZE", "1000"))
    login_url: str = "https://www.iforex.jp/login"
    trading_url: str = "https://trading.iforex.jp/"
