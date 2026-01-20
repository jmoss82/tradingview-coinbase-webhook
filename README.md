# TradingView → Coinbase Webhook Server

Automated trading system that receives TradingView alerts and executes trades on Coinbase Advanced Trade with real-time position monitoring and exit management.

## Features

- **Webhook Endpoint:** Receives TradingView alerts via HTTP POST
- **Automated Trading:** Executes market orders on Coinbase
- **Position Monitoring:** Real-time WebSocket price tracking
- **Exit Management:**
  - Stop Loss (hard stop)
  - Take Profit (target)
  - Trailing Stop (activates at profit threshold)
- **Position Persistence:** Survives server restarts
- **Paper Trading Mode:** Test without real money

## Quick Start

### 1. Deploy to Railway

**Prerequisites:**
- Railway account
- Coinbase API key with View + Trade permissions
- GitHub account

**Steps:**

1. **Push to GitHub:**
   ```bash
   cd webhook_server
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin <your-github-repo-url>
   git push -u origin main
   ```

2. **Deploy on Railway:**
   - Go to https://railway.app
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your repository
   - Railway will auto-detect Python and deploy

3. **Configure Environment Variables:**
   In Railway dashboard, go to Variables and add:
   ```
   COINBASE_API_KEY=d0b8ad11-e181-4283-9e37-e883dd3355ad
   COINBASE_API_SECRET=7xPCaVflrgYxcA/gENb8T+jo9KFjmsVpZ7kVu/pNxOCgXokUH/5yCPElBk0lduTIeIw7XZp4zmNI5F90R9rFnA==
   ENABLE_TRADING=false
   MAX_CONCURRENT_POSITIONS=3
   DEFAULT_POSITION_SIZE_USD=25.0
   ```

4. **Get Your Webhook URL:**
   - Railway provides a public URL like: `https://your-app.railway.app`
   - Your webhook endpoint will be: `https://your-app.railway.app/webhook`

### 2. Test the Deployment

```bash
# Health check
curl https://your-app.railway.app/health

# Check status
curl https://your-app.railway.app/status

# Test webhook (paper trading mode)
curl -X POST https://your-app.railway.app/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "action": "LONG",
    "symbol": "BTC-USD",
    "price": 45000,
    "stop_loss_pct": 1.5,
    "take_profit_pct": 1.5,
    "trailing_activation_pct": 0.8,
    "trailing_distance_pct": 0.75,
    "position_size_usd": 10
  }'
```

### 3. Update TradingView Strategy

**Modify Pine Script Alert Messages:**

```pine
// Entry alert for LONG
LongEntry = '{"action": "LONG", "symbol": "' + syminfo.ticker + '-USD", "price": ' + str.tostring(close) + ', "stop_loss_pct": 1.5, "take_profit_pct": 1.5, "trailing_activation_pct": 0.8, "trailing_distance_pct": 0.75, "position_size_usd": 25}'

// Entry alert for SHORT
ShortEntry = '{"action": "SHORT", "symbol": "' + syminfo.ticker + '-USD", "price": ' + str.tostring(close) + ', "stop_loss_pct": 1.5, "take_profit_pct": 1.5, "trailing_activation_pct": 0.8, "trailing_distance_pct": 0.75, "position_size_usd": 25}'

// Use in strategy
if strategy.position_size > 0 and strategy.position_size[1] == 0
    alert(LongEntry, alert.freq_once_per_bar_close)

if strategy.position_size < 0 and strategy.position_size[1] == 0
    alert(ShortEntry, alert.freq_once_per_bar_close)
```

**Create Alert on TradingView:**
1. Open your chart with the strategy
2. Click "Alerts" → "Create Alert"
3. Condition: Strategy "Bj Bot" → "Order fills only"
4. Webhook URL: `https://your-app.railway.app/webhook`
5. Message: `{{strategy.order.alert_message}}`
6. Save alert

### 4. Go Live

**Enable Real Trading:**

In Railway, update environment variable:
```
ENABLE_TRADING=true
```

Railway will automatically redeploy.

**Start with Small Positions:**
- Use small dollar amounts ($10-25)
- Monitor for 24 hours
- Verify stop loss, take profit, and trailing stop work correctly

## API Endpoints

### `POST /webhook`
Main webhook endpoint for TradingView alerts.

**Request Body:**
```json
{
  "action": "LONG",
  "symbol": "BTC-USD",
  "price": 45000.00,
  "stop_loss_pct": 1.5,
  "take_profit_pct": 1.5,
  "trailing_activation_pct": 0.8,
  "trailing_distance_pct": 0.75,
  "position_size_usd": 100.00,
  "leverage": 1.0
}
```

**Actions:**
- `LONG` - Open long position
- `SHORT` - Open short position
- `EXIT_LONG` - Close long position
- `EXIT_SHORT` - Close short position
- `CLOSE_ALL` - Close all positions

### `GET /health`
Health check endpoint.

### `GET /status`
Returns current positions and system status.

### `POST /close/{position_id}`
Manually close a specific position.

## Configuration

All settings can be configured via environment variables:

### Required
- `COINBASE_API_KEY` - Your Coinbase API key ID
- `COINBASE_API_SECRET` - Your Coinbase API secret

### Trading Settings
- `ENABLE_TRADING` - `true` or `false` (default: `false`)
- `DEFAULT_POSITION_SIZE_USD` - Default position size (default: `100.0`)
- `DEFAULT_STOP_LOSS_PCT` - Default stop loss % (default: `1.5`)
- `DEFAULT_TAKE_PROFIT_PCT` - Default take profit % (default: `1.5`)
- `DEFAULT_TRAILING_ACTIVATION_PCT` - Trailing stop activation % (default: `0.8`)
- `DEFAULT_TRAILING_DISTANCE_PCT` - Trailing stop distance % (default: `0.75`)
- `MAX_LEVERAGE` - Maximum allowed leverage (default: `3.0`)

### Risk Management
- `MAX_CONCURRENT_POSITIONS` - Max open positions (default: `5`)

## Position Monitoring

The server runs a background monitor that:
1. Subscribes to Coinbase WebSocket for real-time prices
2. Updates position P&L continuously
3. Checks exit conditions every 500ms:
   - Stop loss (highest priority)
   - Trailing stop (if activated)
   - Take profit
4. Executes market orders when conditions are met
5. Persists positions to `positions.json`

## Trailing Stop Logic

**Activation:**
- Long: Price reaches entry + activation %
- Short: Price reaches entry - activation %

**Behavior:**
- Long: Stop follows price up by distance %, never moves down
- Short: Stop follows price down by distance %, never moves up

**Example (LONG at $100):**
- Activation: +0.8% = $100.80
- Distance: 0.75%
- Price hits $101 → Stop sets to $100.24
- Price hits $102 → Stop updates to $101.23
- Price drops to $101.23 → Stop triggers, exit at market

## Logs

View logs in Railway dashboard:
- Real-time log streaming
- Filter by ERROR, INFO, DEBUG
- Shows all webhook requests, trades, and exits

## Troubleshooting

**"401 Unauthorized"**
- Check API key and secret are correct
- Verify API key has View + Trade permissions
- Ensure Railway IP is whitelisted in Coinbase (if IP restrictions enabled)

**Webhook not receiving alerts**
- Verify TradingView alert is active
- Check webhook URL is correct
- Look at Railway logs for incoming requests

**Positions not closing**
- Check Railway logs for errors
- Verify WebSocket connection is active (`/status` endpoint)
- Check if `ENABLE_TRADING=true`

**Server crashed**
- Railway auto-restarts
- Positions reload from `positions.json`
- WebSocket reconnects automatically

## Safety Features

- **Paper Trading Mode:** Test without risk (`ENABLE_TRADING=false`)
- **Position Limits:** Prevents over-trading
- **Leverage Cap:** Safety limit on leverage
- **Position Persistence:** Survives crashes
- **Duplicate Prevention:** Won't open multiple positions in same symbol

## Risk Warnings

⚠️ **IMPORTANT:**
- Start with paper trading mode
- Test with small amounts first ($10-25)
- Monitor closely for first 24 hours
- Have backup plan to manually close on Coinbase
- Understand slippage on market orders
- Know the risks of automated trading

## Support

For issues or questions, check:
- Railway logs (application errors)
- Coinbase dashboard (trade verification)
- TradingView alerts (signal timing)

## License

For personal use only.
