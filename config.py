"""
Configuration management for webhook server
Loads and validates environment variables
"""
import os
from typing import Optional
from dotenv import load_dotenv
from loguru import logger

# Load .env file if it exists
load_dotenv()


class Config:
    """Application configuration"""

    # Coinbase API Credentials
    COINBASE_API_KEY: str = os.getenv("COINBASE_API_KEY", "")
    COINBASE_API_SECRET: str = os.getenv("COINBASE_API_SECRET", "")

    # Server Settings
    PORT: int = int(os.getenv("PORT", "8000"))
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Trading Settings (defaults, can be overridden by TradingView)
    DEFAULT_POSITION_SIZE_USD: float = float(os.getenv("DEFAULT_POSITION_SIZE_USD", "100.0"))
    DEFAULT_STOP_LOSS_PCT: float = float(os.getenv("DEFAULT_STOP_LOSS_PCT", "1.5"))
    DEFAULT_TAKE_PROFIT_PCT: float = float(os.getenv("DEFAULT_TAKE_PROFIT_PCT", "1.5"))
    DEFAULT_TRAILING_ACTIVATION_PCT: float = float(os.getenv("DEFAULT_TRAILING_ACTIVATION_PCT", "0.8"))
    DEFAULT_TRAILING_DISTANCE_PCT: float = float(os.getenv("DEFAULT_TRAILING_DISTANCE_PCT", "0.75"))
    MAX_LEVERAGE: float = float(os.getenv("MAX_LEVERAGE", "3.0"))

    # Risk Management
    MAX_CONCURRENT_POSITIONS: int = int(os.getenv("MAX_CONCURRENT_POSITIONS", "5"))
    ENABLE_TRADING: bool = os.getenv("ENABLE_TRADING", "false").lower() == "true"

    # Security
    WEBHOOK_SECRET: Optional[str] = os.getenv("WEBHOOK_SECRET")

    # Position persistence
    POSITIONS_FILE: str = os.getenv("POSITIONS_FILE", "positions.json")

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration"""
        errors = []

        # Check required fields
        if not cls.COINBASE_API_KEY:
            errors.append("COINBASE_API_KEY is required")
        if not cls.COINBASE_API_SECRET:
            errors.append("COINBASE_API_SECRET is required")

        # Validate ranges
        if cls.MAX_LEVERAGE < 1.0 or cls.MAX_LEVERAGE > 10.0:
            errors.append("MAX_LEVERAGE must be between 1.0 and 10.0")
        if cls.MAX_CONCURRENT_POSITIONS < 1:
            errors.append("MAX_CONCURRENT_POSITIONS must be at least 1")

        if errors:
            for error in errors:
                logger.error(f"Configuration error: {error}")
            return False

        return True

    @classmethod
    def display(cls):
        """Display current configuration (mask secrets)"""
        logger.info("=" * 60)
        logger.info("Webhook Server Configuration")
        logger.info("=" * 60)
        logger.info(f"Environment: {cls.ENVIRONMENT}")
        logger.info(f"Port: {cls.PORT}")
        logger.info(f"Log Level: {cls.LOG_LEVEL}")
        logger.info(f"Trading Enabled: {cls.ENABLE_TRADING}")
        logger.info(f"Max Concurrent Positions: {cls.MAX_CONCURRENT_POSITIONS}")
        logger.info(f"Max Leverage: {cls.MAX_LEVERAGE}x")
        logger.info(f"API Key: {cls.COINBASE_API_KEY[:20]}..." if cls.COINBASE_API_KEY else "API Key: NOT SET")
        logger.info(f"API Secret: {'*' * 20} (loaded)" if cls.COINBASE_API_SECRET else "API Secret: NOT SET")
        logger.info("=" * 60)


# Validate on import
if not Config.validate():
    logger.warning("Configuration validation failed - some features may not work")
