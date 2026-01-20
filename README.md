# TradingView → Coinbase Webhook Trading System

Automated trading system that receives TradingView "Bj Bot" strategy alerts and executes trades on Coinbase Advanced Trade with real-time position monitoring.

## Status

**Current Configuration:**
- 🟢 **Live:** https://web-production-ef7a1.up.railway.app
- 🟡 **Mode:** Paper Trading (ENABLE_TRADING=false)
- 🟢 **Monitoring:** Active
- ✅ **TradingView Alert:** Configured

## How It Works

1. **TradingView** detects MA crossover signal
2. **Alert fires** → sends JSON webhook to Railway
3. **Railway server** receives alert → places order on Coinbase (if enabled)
4. **Position Monitor** tracks position via WebSocket 24/7
5. **Auto-exits** via stop loss, take profit, or trailing stop

## Quick Links

**Health Check:**
```
https://web-production-ef7a1.up.railway.app/health
```

**Current Positions:**
```
https://web-production-ef7a1.up.railway.app/status
```

**Railway Dashboard:**
```
https://railway.app/dashboard
```

## Current Settings

**Trading:**
- Position Size: $25 per trade (configurable in TradingView)
- Leverage: 1x (configurable in TradingView, test at 1x first!)
- Stop Loss: 1.5%
- Take Profit: 1.5%
- Trailing Stop: Activates at +0.8%, trails by 0.75%
- Max Positions: 3

**Supported Symbols (Coinbase Nano Perpetual Futures):**
- BIP-20DEC30-CDE (Bitcoin)
- ETP-20DEC30-CDE (Ethereum)
- SLP-20DEC30-CDE (Solana)
- XPP-20DEC30-CDE (XRP)

**Note:** Product IDs will change when contracts roll (currently Dec 30, 2030). Symbol mapping will need updating at rollover.

## Enabling Live Trading

**When ready to go live:**

1. Go to Railway dashboard
2. Navigate to environment variables
3. Change: `ENABLE_TRADING=true`
4. Railway auto-redeploys (takes 1-2 minutes)

**Start small:** Use $10-25 positions for first few trades.

## Monitoring

**View Logs:**
- Railway Dashboard → Deployments → Logs
- Watch for: "Webhook received", "Position opened", "Position closed"

**Check Positions:**
- Visit: https://web-production-ef7a1.up.railway.app/status
- Shows active positions, P&L, trailing stop status

**Paper Trading Mode:**
- Logs show: "[PAPER TRADE MODE] Trade not executed"
- No real orders placed
- Position tracking still works (simulated)

## Emergency Controls

**Close Single Position:**
```bash
curl -X POST https://web-production-ef7a1.up.railway.app/close/POSITION_ID
```

**Disable Trading:**
- Railway → Variables → Set `ENABLE_TRADING=false`

**Manual Close on Coinbase:**
- Log into Coinbase Advanced Trade
- Close position manually if needed

## Troubleshooting

**Webhook not receiving alerts:**
- Check TradingView alert is active (green dot)
- Verify webhook URL is correct
- Check Railway logs for incoming requests

**Position not closing:**
- Check Railway logs for errors
- Verify WebSocket connection is active (check /status)
- Ensure ENABLE_TRADING=true if live

**Server not responding:**
- Railway auto-restarts on crashes
- Check deployments tab for status
- Positions reload from positions.json on restart

## Files

- `main.py` - FastAPI webhook server
- `position_manager.py` - Position monitoring & exits
- `coinbase_client.py` - Coinbase API wrapper
- `positions.json` - Persisted position state (auto-created)

## Risk Warnings

⚠️ **Before enabling live trading:**
- Test in paper mode first
- **START WITH 1x LEVERAGE** - Prove strategy works before increasing
- Start with small position sizes ($10-25)
- Monitor closely for first 24 hours
- Understand market orders have slippage
- Know how to manually close on Coinbase
- **Leverage amplifies both gains AND losses** - 5x leverage = 5x risk
- Never risk more than you can afford to lose

⚠️ **Leverage Notes:**
- 1x leverage = No leverage (safer, recommended for testing)
- 5x leverage = $25 position controls $125 of exposure
- Higher leverage increases liquidation risk
- Test extensively at 1x before increasing to 5x

## Support

**Check in order:**
1. Railway logs (deployment errors)
2. /status endpoint (position state)
3. Coinbase dashboard (verify trades)
4. TradingView alerts (signal timing)
