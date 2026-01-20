"""
Coinbase Advanced Trade API client
Handles REST API calls and WebSocket connections
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Callable, List
from coinbase.rest import RESTClient
from coinbase.websocket import WSClient
from loguru import logger

from models import Trade, Position, Balance, Side


class CoinbaseClient:
    """
    Client for Coinbase Advanced Trade API
    """

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

        # Initialize REST client
        self.rest_client = RESTClient(
            api_key=api_key,
            api_secret=api_secret
        )

        self.ws_client = None
        self._trade_callbacks: List[Callable[[Trade], None]] = []
        self._ws_running = False

    # ==================== REST API ====================

    def get_product(self, product_id: str) -> dict:
        """Get product details"""
        try:
            response = self.rest_client.get_product(product_id=product_id)
            return response
        except Exception as e:
            logger.error(f"Error getting product {product_id}: {e}")
            raise

    def get_positions(self) -> List[Position]:
        """Get all open positions"""
        try:
            # For perpetuals
            response = self.rest_client.list_futures_positions()
            positions = []

            if hasattr(response, 'positions') and response.positions:
                for pos in response.positions:
                    positions.append(Position(
                        position_id=pos.product_id,
                        product_id=pos.product_id,
                        side=pos.side,
                        size=float(pos.number_of_contracts),
                        entry_price=float(pos.entry_vwap),
                        current_price=float(pos.mark_price) if hasattr(pos, 'mark_price') else 0.0,
                        unrealized_pnl=float(pos.unrealized_pnl) if hasattr(pos, 'unrealized_pnl') else 0.0,
                    ))

            return positions
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def get_balances(self) -> List[Balance]:
        """Get account balances"""
        try:
            response = self.rest_client.get_accounts()
            balances = []

            if hasattr(response, 'accounts'):
                for account in response.accounts:
                    if hasattr(account, 'available_balance'):
                        balances.append(Balance(
                            currency=account.currency,
                            available=float(account.available_balance.value),
                            hold=float(account.hold.value) if hasattr(account, 'hold') else 0.0,
                            total=float(account.available_balance.value)
                        ))

            return balances
        except Exception as e:
            logger.error(f"Error getting balances: {e}")
            return []

    def place_market_order(self, product_id: str, side: str, size: str) -> dict:
        """
        Place market order

        Args:
            product_id: e.g. "BTC-USD"
            side: "BUY" or "SELL"
            size: Quote size in USD (e.g., "100" for $100)

        Returns:
            Order response dict
        """
        try:
            logger.info(f"Placing market order: {side} ${size} of {product_id}")

            # Use market order with quote size (USD amount)
            order = self.rest_client.market_order(
                client_order_id=f"webhook_{datetime.utcnow().timestamp()}",
                product_id=product_id,
                side=side.upper(),
                quote_size=size
            )

            logger.success(f"Order placed: {order}")
            return order
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            raise

    def close_position(self, product_id: str, side: str, size: float) -> dict:
        """
        Close position by placing opposite order

        Args:
            product_id: Product to close
            side: Original position side ("LONG" or "SHORT")
            size: Size to close
        """
        try:
            # Determine opposite side
            close_side = "SELL" if side == "LONG" else "BUY"

            logger.info(f"Closing position: {product_id} {side} with {close_side} {size}")

            # Place market order to close
            order = self.rest_client.market_order(
                client_order_id=f"close_{datetime.utcnow().timestamp()}",
                product_id=product_id,
                side=close_side,
                base_size=str(size)  # Use base size for closing
            )

            logger.success(f"Position closed: {order}")
            return order
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            raise

    def get_current_price(self, product_id: str) -> float:
        """Get current market price for a product"""
        try:
            product = self.get_product(product_id)
            if hasattr(product, 'price'):
                return float(product.price)
            elif isinstance(product, dict) and 'price' in product:
                return float(product['price'])
            else:
                logger.warning(f"Could not get price for {product_id}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting current price: {e}")
            return 0.0

    # ==================== WebSocket ====================

    def on_trade(self, callback: Callable[[Trade], None]):
        """Register callback for trade events"""
        self._trade_callbacks.append(callback)

    async def subscribe_trades(self, product_ids: List[str]):
        """Subscribe to real-time trades via WebSocket"""
        try:
            logger.info(f"Connecting to Coinbase WebSocket for {product_ids}...")

            def on_message(msg):
                try:
                    if msg.get('channel') == 'market_trades':
                        for event in msg.get('events', []):
                            for trade_data in event.get('trades', []):
                                # Parse trade
                                trade = Trade(
                                    symbol=trade_data.get('product_id'),
                                    price=float(trade_data.get('price')),
                                    size=float(trade_data.get('size')),
                                    side=Side.BUY if trade_data.get('side') == 'BUY' else Side.SELL,
                                    timestamp=datetime.fromisoformat(trade_data.get('time').replace('Z', '+00:00')),
                                    trade_id=trade_data.get('trade_id', '')
                                )

                                # Call all registered callbacks
                                for callback in self._trade_callbacks:
                                    callback(trade)
                except Exception as e:
                    logger.error(f"Error processing trade message: {e}")

            # Initialize WebSocket client
            self.ws_client = WSClient(
                api_key=self.api_key,
                api_secret=self.api_secret,
                on_message=on_message
            )

            # Open connection
            self.ws_client.open()

            # Subscribe to market trades
            self.ws_client.subscribe(
                product_ids=product_ids,
                channels=["market_trades"]
            )

            logger.success(f"Subscribed to market trades for: {', '.join(product_ids)}")
            self._ws_running = True

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            raise

    async def run_ws_loop(self):
        """Keep WebSocket connection alive"""
        try:
            while self._ws_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("WebSocket loop interrupted")
            await self.disconnect_ws()

    async def disconnect_ws(self):
        """Disconnect WebSocket"""
        if self.ws_client:
            try:
                self.ws_client.close()
                logger.info("WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting WebSocket: {e}")
        self._ws_running = False
