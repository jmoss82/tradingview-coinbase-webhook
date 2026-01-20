"""
Webhook Server - FastAPI application
Receives TradingView alerts and executes trades on Coinbase
"""
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from loguru import logger

from models import TradingViewAlert, Position, Action, PositionStatus
from coinbase_client import CoinbaseClient
from position_manager import PositionManager
from config import Config

# Global instances
coinbase_client: CoinbaseClient = None
position_manager: PositionManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic"""
    global coinbase_client, position_manager

    # Startup
    logger.info("Starting webhook server...")
    Config.display()

    # Initialize Coinbase client
    coinbase_client = CoinbaseClient(
        api_key=Config.COINBASE_API_KEY,
        api_secret=Config.COINBASE_API_SECRET
    )

    # Initialize Position Manager
    position_manager = PositionManager(coinbase_client)

    # Start monitoring
    await position_manager.start_monitoring()

    logger.success("Server started successfully")

    yield

    # Shutdown
    logger.info("Shutting down webhook server...")
    await position_manager.stop_monitoring()
    logger.info("Server shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="TradingView Coinbase Webhook",
    description="Automated trading system connecting TradingView alerts to Coinbase",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "TradingView Coinbase Webhook",
        "status": "running",
        "version": "1.0.0",
        "trading_enabled": Config.ENABLE_TRADING
    }


@app.get("/health")
async def health_check():
    """Health check for Railway"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "monitoring": position_manager.monitoring if position_manager else False,
        "active_positions": len(position_manager.positions) if position_manager else 0
    }


@app.get("/status")
async def get_status():
    """Get current system status and positions"""
    if not position_manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    positions = [
        {
            "position_id": pos.position_id,
            "product_id": pos.product_id,
            "side": pos.side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "current_price": pos.current_price,
            "pnl": pos.pnl,
            "pnl_pct": pos.pnl_pct,
            "status": pos.status.value,
            "trailing_active": pos.trailing_active,
            "stop_loss": pos.stop_loss_price,
            "take_profit": pos.take_profit_price,
            "trailing_stop": pos.trailing_stop_price if pos.trailing_active else None,
            "opened_at": pos.opened_at.isoformat()
        }
        for pos in position_manager.get_all_positions()
    ]

    return {
        "trading_enabled": Config.ENABLE_TRADING,
        "monitoring": position_manager.monitoring,
        "active_positions": len(positions),
        "max_positions": Config.MAX_CONCURRENT_POSITIONS,
        "positions": positions
    }


@app.post("/webhook")
async def webhook(alert: TradingViewAlert, request: Request):
    """
    Main webhook endpoint for TradingView alerts

    Receives alerts and executes trades based on action type
    """
    try:
        logger.info("=" * 60)
        logger.info(f"Webhook received: {alert.action.value} on {alert.symbol}")
        logger.info(f"Alert data: {alert.dict()}")

        # Check if trading is enabled
        if not Config.ENABLE_TRADING:
            logger.warning("[PAPER TRADE MODE] Trade not executed")
            return {
                "success": True,
                "message": "Paper trade mode - no real execution",
                "action": alert.action.value,
                "symbol": alert.symbol
            }

        # Route to appropriate handler
        if alert.action == Action.LONG:
            return await handle_long_entry(alert)
        elif alert.action == Action.SHORT:
            return await handle_short_entry(alert)
        elif alert.action == Action.EXIT_LONG:
            return await handle_exit(alert, "LONG")
        elif alert.action == Action.EXIT_SHORT:
            return await handle_exit(alert, "SHORT")
        elif alert.action == Action.CLOSE_ALL:
            return await handle_close_all()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {alert.action}")

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_long_entry(alert: TradingViewAlert) -> Dict[str, Any]:
    """Handle LONG entry signal"""
    try:
        # Check position limits
        if len(position_manager.positions) >= Config.MAX_CONCURRENT_POSITIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Max positions reached ({Config.MAX_CONCURRENT_POSITIONS})"
            )

        # Check if already have position in this product
        for pos in position_manager.get_all_positions():
            if pos.product_id == alert.symbol:
                logger.warning(f"Already have position in {alert.symbol}")
                raise HTTPException(status_code=400, detail=f"Already have position in {alert.symbol}")

        # Place market BUY order
        logger.info(f"Placing LONG order: ${alert.position_size_usd} of {alert.symbol}")

        order = coinbase_client.place_market_order(
            product_id=alert.symbol,
            side="BUY",
            size=str(alert.position_size_usd)
        )

        # Get actual fill price
        fill_price = coinbase_client.get_current_price(alert.symbol)

        # Calculate position size in base currency
        position_size = alert.position_size_usd / fill_price

        # Calculate stop/target prices
        stop_loss_price = fill_price * (1 - alert.stop_loss_pct / 100)
        take_profit_price = fill_price * (1 + alert.take_profit_pct / 100)
        trailing_activation_price = fill_price * (1 + alert.trailing_activation_pct / 100)

        # Create position
        position = Position(
            position_id=str(uuid.uuid4()),
            product_id=alert.symbol,
            side="LONG",
            size=position_size,
            entry_price=fill_price,
            current_price=fill_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_activation_price=trailing_activation_price,
            trailing_distance_pct=alert.trailing_distance_pct,
            status=PositionStatus.ACTIVE
        )

        # Add to position manager
        position_manager.add_position(position)

        # Re-subscribe to WebSocket with updated products
        active_products = position_manager.get_active_products()
        await coinbase_client.subscribe_trades(active_products)

        logger.success(f"LONG position opened: {position.position_id}")
        logger.info(f"Entry: ${fill_price:.2f} | Stop: ${stop_loss_price:.2f} | Target: ${take_profit_price:.2f}")

        return {
            "success": True,
            "message": "LONG position opened",
            "position_id": position.position_id,
            "symbol": alert.symbol,
            "side": "LONG",
            "entry_price": fill_price,
            "size": position_size,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "trailing_activation": trailing_activation_price
        }

    except Exception as e:
        logger.error(f"Error opening LONG position: {e}")
        raise


async def handle_short_entry(alert: TradingViewAlert) -> Dict[str, Any]:
    """Handle SHORT entry signal"""
    try:
        # Check position limits
        if len(position_manager.positions) >= Config.MAX_CONCURRENT_POSITIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Max positions reached ({Config.MAX_CONCURRENT_POSITIONS})"
            )

        # Check if already have position in this product
        for pos in position_manager.get_all_positions():
            if pos.product_id == alert.symbol:
                logger.warning(f"Already have position in {alert.symbol}")
                raise HTTPException(status_code=400, detail=f"Already have position in {alert.symbol}")

        # Place market SELL order (short)
        logger.info(f"Placing SHORT order: ${alert.position_size_usd} of {alert.symbol}")

        order = coinbase_client.place_market_order(
            product_id=alert.symbol,
            side="SELL",
            size=str(alert.position_size_usd)
        )

        # Get actual fill price
        fill_price = coinbase_client.get_current_price(alert.symbol)

        # Calculate position size in base currency
        position_size = alert.position_size_usd / fill_price

        # Calculate stop/target prices (inverted for shorts)
        stop_loss_price = fill_price * (1 + alert.stop_loss_pct / 100)
        take_profit_price = fill_price * (1 - alert.take_profit_pct / 100)
        trailing_activation_price = fill_price * (1 - alert.trailing_activation_pct / 100)

        # Create position
        position = Position(
            position_id=str(uuid.uuid4()),
            product_id=alert.symbol,
            side="SHORT",
            size=position_size,
            entry_price=fill_price,
            current_price=fill_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            trailing_activation_price=trailing_activation_price,
            trailing_distance_pct=alert.trailing_distance_pct,
            status=PositionStatus.ACTIVE
        )

        # Add to position manager
        position_manager.add_position(position)

        # Re-subscribe to WebSocket with updated products
        active_products = position_manager.get_active_products()
        await coinbase_client.subscribe_trades(active_products)

        logger.success(f"SHORT position opened: {position.position_id}")
        logger.info(f"Entry: ${fill_price:.2f} | Stop: ${stop_loss_price:.2f} | Target: ${take_profit_price:.2f}")

        return {
            "success": True,
            "message": "SHORT position opened",
            "position_id": position.position_id,
            "symbol": alert.symbol,
            "side": "SHORT",
            "entry_price": fill_price,
            "size": position_size,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "trailing_activation": trailing_activation_price
        }

    except Exception as e:
        logger.error(f"Error opening SHORT position: {e}")
        raise


async def handle_exit(alert: TradingViewAlert, side: str) -> Dict[str, Any]:
    """Handle EXIT signal from TradingView"""
    try:
        # Find position with this symbol and side
        position_to_close = None
        for pos in position_manager.get_all_positions():
            if pos.product_id == alert.symbol and pos.side == side:
                position_to_close = pos
                break

        if not position_to_close:
            logger.warning(f"No {side} position found for {alert.symbol}")
            return {
                "success": False,
                "message": f"No {side} position found for {alert.symbol}"
            }

        # Close the position
        await position_manager.close_position_manual(position_to_close.position_id)

        return {
            "success": True,
            "message": f"{side} position closed",
            "position_id": position_to_close.position_id,
            "symbol": alert.symbol,
            "pnl": position_to_close.pnl,
            "pnl_pct": position_to_close.pnl_pct
        }

    except Exception as e:
        logger.error(f"Error closing position: {e}")
        raise


async def handle_close_all() -> Dict[str, Any]:
    """Close all positions"""
    try:
        positions_closed = []

        for pos in list(position_manager.get_all_positions()):
            await position_manager.close_position_manual(pos.position_id)
            positions_closed.append(pos.position_id)

        return {
            "success": True,
            "message": f"Closed {len(positions_closed)} positions",
            "positions_closed": positions_closed
        }

    except Exception as e:
        logger.error(f"Error closing all positions: {e}")
        raise


@app.post("/close/{position_id}")
async def close_position_endpoint(position_id: str):
    """Manual endpoint to close a specific position"""
    try:
        success = await position_manager.close_position_manual(position_id)

        if success:
            return {"success": True, "message": f"Position {position_id} closed"}
        else:
            raise HTTPException(status_code=404, detail="Position not found")

    except Exception as e:
        logger.error(f"Error closing position: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting server...")
    uvicorn.run(
        "main:app",
        host=Config.HOST,
        port=Config.PORT,
        log_level=Config.LOG_LEVEL.lower(),
        reload=Config.ENVIRONMENT == "development"
    )
