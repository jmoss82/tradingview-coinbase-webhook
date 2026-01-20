"""
Position Manager - Monitors positions and executes exits
Handles stop loss, take profit, and trailing stop logic
"""
import asyncio
import json
from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger

from models import Position, Trade, ExitReason, PositionStatus
from coinbase_client import CoinbaseClient
from config import Config


class PositionManager:
    """Manages active positions and exit logic"""

    def __init__(self, coinbase_client: CoinbaseClient):
        self.client = coinbase_client
        self.positions: Dict[str, Position] = {}
        self.monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None

        # Load persisted positions
        self._load_positions()

        # Register price update callback
        self.client.on_trade(self._on_price_update)

    def add_position(self, position: Position):
        """Add a new position to monitor"""
        self.positions[position.position_id] = position
        logger.info(f"Added position {position.position_id} to monitoring: {position.side} {position.size} {position.product_id} @ {position.entry_price}")
        self._save_positions()

    def remove_position(self, position_id: str) -> Optional[Position]:
        """Remove position from monitoring"""
        position = self.positions.pop(position_id, None)
        if position:
            logger.info(f"Removed position {position_id} from monitoring")
            self._save_positions()
        return position

    def get_position(self, position_id: str) -> Optional[Position]:
        """Get position by ID"""
        return self.positions.get(position_id)

    def get_all_positions(self) -> List[Position]:
        """Get all active positions"""
        return list(self.positions.values())

    def get_active_products(self) -> List[str]:
        """Get list of unique product IDs being monitored"""
        return list(set(pos.product_id for pos in self.positions.values()))

    async def start_monitoring(self):
        """Start background monitoring task"""
        if self.monitoring:
            logger.warning("Monitoring already running")
            return

        logger.info("Starting position monitoring...")
        self.monitoring = True

        # Subscribe to WebSocket for active products
        active_products = self.get_active_products()
        if active_products:
            try:
                await self.client.subscribe_trades(active_products)
            except Exception as e:
                logger.error(f"Failed to subscribe to WebSocket: {e}")

        # Start monitoring loop
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.success("Position monitoring started")

    async def stop_monitoring(self):
        """Stop background monitoring"""
        logger.info("Stopping position monitoring...")
        self.monitoring = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        await self.client.disconnect_ws()
        logger.info("Position monitoring stopped")

    async def _monitor_loop(self):
        """Main monitoring loop - checks positions periodically"""
        logger.info("Monitor loop started")

        while self.monitoring:
            try:
                for position_id, position in list(self.positions.items()):
                    await self._check_position(position)

                # Check every 500ms
                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                logger.info("Monitor loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(1)

    async def _check_position(self, position: Position):
        """Check if position should be exited"""
        try:
            # Update P&L
            position.update_pnl()

            # Check trailing stop activation
            if not position.trailing_active and position.should_activate_trailing():
                position.trailing_active = True
                position.status = PositionStatus.TRAILING

                # Initialize trailing stop price
                if position.side == "LONG":
                    position.trailing_stop_price = position.current_price * (1 - position.trailing_distance_pct / 100)
                else:
                    position.trailing_stop_price = position.current_price * (1 + position.trailing_distance_pct / 100)

                logger.info(f"Position {position.position_id} - Trailing stop ACTIVATED at {position.current_price:.2f} (stop: {position.trailing_stop_price:.2f})")
                self._save_positions()

            # Update trailing stop if active
            if position.trailing_active:
                old_stop = position.trailing_stop_price
                position.update_trailing_stop()
                if position.trailing_stop_price != old_stop:
                    logger.debug(f"Position {position.position_id} - Trailing stop updated: {old_stop:.2f} → {position.trailing_stop_price:.2f}")
                    self._save_positions()

            # Check exit conditions (in priority order)
            exit_reason = None

            # 1. Stop loss (highest priority)
            if position.should_stop_loss():
                exit_reason = ExitReason.STOP_LOSS
                logger.warning(f"Position {position.position_id} - STOP LOSS triggered at {position.current_price:.2f}")

            # 2. Trailing stop
            elif position.should_trailing_stop():
                exit_reason = ExitReason.TRAILING_STOP
                logger.info(f"Position {position.position_id} - TRAILING STOP triggered at {position.current_price:.2f}")

            # 3. Take profit
            elif position.should_take_profit():
                exit_reason = ExitReason.TAKE_PROFIT
                logger.success(f"Position {position.position_id} - TAKE PROFIT triggered at {position.current_price:.2f}")

            # Execute exit if needed
            if exit_reason:
                await self._close_position(position, exit_reason)

        except Exception as e:
            logger.error(f"Error checking position {position.position_id}: {e}")

    async def _close_position(self, position: Position, reason: ExitReason):
        """Close a position on Coinbase"""
        try:
            if not Config.ENABLE_TRADING:
                logger.warning(f"[PAPER TRADE] Would close position {position.position_id} - Reason: {reason.value}")
                logger.info(f"[PAPER TRADE] Final P&L: ${position.pnl:.2f} ({position.pnl_pct:+.2f}%)")

                # Still mark as closed in paper mode
                position.status = PositionStatus.CLOSED
                position.exit_reason = reason
                position.closed_at = datetime.utcnow()
                self.remove_position(position.position_id)
                return

            # LIVE TRADING - Execute close order
            logger.info(f"Closing position {position.position_id} - Reason: {reason.value}")

            order = self.client.close_position(
                product_id=position.product_id,
                side=position.side,
                size=position.size
            )

            # Mark position as closed
            position.status = PositionStatus.CLOSED
            position.exit_reason = reason
            position.closed_at = datetime.utcnow()

            # Log results
            logger.success(f"Position closed: {position.position_id}")
            logger.info(f"Final P&L: ${position.pnl:.2f} ({position.pnl_pct:+.2f}%)")
            logger.info(f"Entry: {position.entry_price:.2f} | Exit: {position.current_price:.2f}")

            # Remove from monitoring
            self.remove_position(position.position_id)

        except Exception as e:
            logger.error(f"Failed to close position {position.position_id}: {e}")
            # Don't remove from monitoring if close failed
            raise

    async def close_position_manual(self, position_id: str) -> bool:
        """Manually close a position"""
        position = self.get_position(position_id)
        if not position:
            logger.warning(f"Position {position_id} not found")
            return False

        await self._close_position(position, ExitReason.MANUAL)
        return True

    async def close_all_positions(self):
        """Emergency close all positions"""
        logger.warning("CLOSING ALL POSITIONS")
        for position_id in list(self.positions.keys()):
            await self.close_position_manual(position_id)

    def _on_price_update(self, trade: Trade):
        """Callback for WebSocket price updates"""
        # Update current price for all positions of this product
        for position in self.positions.values():
            if position.product_id == trade.symbol:
                position.current_price = trade.price

    def _save_positions(self):
        """Persist positions to file"""
        try:
            data = {
                position_id: {
                    "position_id": pos.position_id,
                    "product_id": pos.product_id,
                    "side": pos.side,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "stop_loss_price": pos.stop_loss_price,
                    "take_profit_price": pos.take_profit_price,
                    "trailing_activation_price": pos.trailing_activation_price,
                    "trailing_distance_pct": pos.trailing_distance_pct,
                    "status": pos.status.value,
                    "trailing_active": pos.trailing_active,
                    "trailing_stop_price": pos.trailing_stop_price,
                    "opened_at": pos.opened_at.isoformat(),
                    "pnl": pos.pnl,
                    "pnl_pct": pos.pnl_pct
                }
                for position_id, pos in self.positions.items()
            }

            with open(Config.POSITIONS_FILE, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save positions: {e}")

    def _load_positions(self):
        """Load positions from file"""
        try:
            with open(Config.POSITIONS_FILE, 'r') as f:
                data = json.load(f)

            for position_id, pos_data in data.items():
                position = Position(
                    position_id=pos_data["position_id"],
                    product_id=pos_data["product_id"],
                    side=pos_data["side"],
                    size=pos_data["size"],
                    entry_price=pos_data["entry_price"],
                    current_price=pos_data["current_price"],
                    stop_loss_price=pos_data["stop_loss_price"],
                    take_profit_price=pos_data["take_profit_price"],
                    trailing_activation_price=pos_data["trailing_activation_price"],
                    trailing_distance_pct=pos_data["trailing_distance_pct"],
                    status=PositionStatus(pos_data["status"]),
                    trailing_active=pos_data["trailing_active"],
                    trailing_stop_price=pos_data["trailing_stop_price"],
                    opened_at=datetime.fromisoformat(pos_data["opened_at"]),
                    pnl=pos_data["pnl"],
                    pnl_pct=pos_data["pnl_pct"]
                )
                self.positions[position_id] = position

            if self.positions:
                logger.info(f"Loaded {len(self.positions)} positions from {Config.POSITIONS_FILE}")

        except FileNotFoundError:
            logger.info(f"No positions file found ({Config.POSITIONS_FILE}), starting fresh")
        except Exception as e:
            logger.error(f"Failed to load positions: {e}")
