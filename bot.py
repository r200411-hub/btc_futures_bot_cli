# bot.py  (combined example using PaperExecutor)
import os
import sys
import time
import signal
import threading
from datetime import datetime, timezone

from core.connection import DeltaExchangeWebSocket
from core.strategy import Strategy
from core.trader import TradeManager
from core.logger import MLLogger
from core.parquet_logger import ParquetLogger
from core.bad_tick_filter import BadTickFilter
from core.heartbeat import HeartbeatMonitor
from core.freeze_detector import FreezeDetector
from core.validator import AccuracyValidator
from core.hang_guard import SilentHangGuard
from core.slowdown import SlowdownDetector
from core.risk_guard import RiskGuard
from core.regime import MarketRegimeDetector

# Executor imports
from core.paper_executor import PaperExecutor
from core.live_executor import LiveRESTExecutor  # placeholder

from config.settings import settings

sys.stdout.reconfigure(line_buffering=True)
os.system("")  # enable ANSI in windows terminals

### Setup primary objects ###
strategy = Strategy(settings)
trader = TradeManager(settings)
regime = MarketRegimeDetector()
logger = MLLogger("data/ml_data.csv")
logger_pq = ParquetLogger("data/tickdata.parquet")
validator = AccuracyValidator()

tick_filter = BadTickFilter(log_callback=lambda reason, price, pct=None: print(f"⚠ BAD TICK: {reason} {price} Δ={pct}"))

# Choose executor based on simulate_live flag
if settings.get("simulate_live", True):
    executor = PaperExecutor(settings, trader, csv_logger=logger, pq_logger=logger_pq)
else:
    executor = LiveRESTExecutor(settings, trader, logger=logger)

executor.start()

# Guards + diagnostics
hb = HeartbeatMonitor(timeout=10, on_dead=lambda: ws.reconnect() if 'ws' in globals() else None)
freeze = FreezeDetector(timeout_seconds=30, on_freeze_callback=lambda: ws.reconnect() if 'ws' in globals() else None)
hang = SilentHangGuard(timeout=12, on_hang=lambda: ws.mark_dead() if 'ws' in globals() else None)
slow = SlowdownDetector(window=40, threshold_factor=3.0, on_slow=lambda: ws.reconnect() if 'ws' in globals() else None)

# Start guards later after ws is created

risk = RiskGuard(
    max_exposure_seconds=settings.get("max_exposure_seconds", 180),
    max_distance_pct=settings.get("max_distance_pct", 0.4),
    on_risk=lambda reason: trader.close_position(strategy.last_price, reason) if hasattr(trader, "close_position") else None
)

# Graceful shutdown handler
def _shutdown(signum=None, frame=None):
    print("\n🛑 Shutdown requested — stopping executor & flushing logs")
    try:
        executor.stop()
    except Exception:
        pass
    try:
        logger_pq.flush()
    except Exception:
        pass
    try:
        logger.close()
    except Exception:
        pass
    try:
        if 'ws' in globals() and ws:
            # request mark dead so reconnect loop doesn't spin
            try:
                ws.mark_dead()
            except:
                pass
    except:
        pass
    # few seconds to let background jobs finish
    time.sleep(0.5)
    print("Goodbye.")
    os._exit(0)

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# Safe wrapper for calling executor/trader open/close
def _submit_trade(side, price):
    size = settings.get("position_size", 0.01)
    res = executor.submit_order(side, size, price, meta={"origin":"strategy"})
    if res.get("status") == "rejected":
        print("Order rejected:", res.get("reason"))
    else:
        print("Order queued:", res)

# ------------ Websocket callback -------------
def on_price(price, raw=None):
    # diagnostics
    try:
        slow.mark()
    except:
        pass
    try:
        freeze.tick()
    except:
        pass
    try:
        hb.beat()
    except:
        pass

    # bad-tick filter
    if not tick_filter.validate(price):
        return

    # update strategy
    strategy.update(price)

    # update regime AFTER strategy
    try:
        current_regime = regime.update(price, strategy)
    except Exception as e:
        print("Regime update failed:", e)
        return

    sig = strategy.signal()

    # logging (csv + parquet)
    try:
        logger.log(price, strategy, trader, regime, sig)
    except Exception as e:
        print("LOGGER ERROR for CSV:", e)

    try:
        logger_pq.log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": price,
            "fast_ema": strategy.fast[-1] if strategy.fast else None,
            "slow_ema": strategy.slow[-1] if strategy.slow else None,
            "fast_period": getattr(strategy, "fast_period", None),
            "slow_period": getattr(strategy, "slow_period", None),
            "ema_spread": (strategy.fast[-1] - strategy.slow[-1]) if strategy.fast and strategy.slow else None,
            "vol_ema": getattr(strategy, "vol", None),
            "regime": regime.current_regime,
            "regime_confidence": getattr(regime, "confidence", 0.0),
            "brick_dir": strategy.bricks[-1]["dir"] if strategy.bricks else None,
            "brick_count": len(strategy.bricks),
            "signal": sig,
            "pos_side": trader.position["type"] if trader.position else None,
            "pnl": trader.calculate_pnl(price) if trader.position else 0.0
        })
    except Exception as e:
        print("LOGGER ERROR for Parquet:", e)

    # regime filtering and submission to executor
    if sig:
        if sig == "LONG" and not regime.can_trade_long():
            print(f"⛔ LONG blocked by regime: {regime.current_regime}")
        elif sig == "SHORT" and not regime.can_trade_short():
            print(f"⛔ SHORT blocked by regime: {regime.current_regime}")
        elif regime.is_danger():
            print(f"⛔ Trade blocked (danger regime: {regime.current_regime})")
        else:
            # submit to executor (non-blocking)
            _submit_trade(sig, price)

    # active position management (this remains handled by trader + executor fills)
    if trader.position:
        pnl = trader.calculate_pnl(price)
        print(f"PnL: {pnl:.2f}", end="\r")
        # SL/TP enforcement - prefer letting executor trigger close via separate logic, but quick close here:
        if pnl > settings.get("take_profit", 999999) or pnl < -abs(settings.get("stop_loss", 999999)):
            print("\nAuto-closing due to SL/TP")
            # close via executor by submitting opposite order
            opp = "SHORT" if trader.position["type"] == "LONG" else "LONG"
            _submit_trade(opp, price)

# ------------ Build WS and start -------------
ws = DeltaExchangeWebSocket(
    settings["api_key"],
    settings["api_secret"],
    on_price
)

# attach guard dependencies (ws is defined now)
hang = SilentHangGuard(timeout=12, on_hang=lambda: ws.mark_dead())
hang.start()
ws.hang = hang

hb = HeartbeatMonitor(timeout=10, on_dead=lambda: ws.mark_dead())
hb.start()

freeze = FreezeDetector(timeout_seconds=30, on_freeze_callback=lambda: ws.mark_dead())
freeze.start()

slow = SlowdownDetector(window=40, threshold_factor=3.0, on_slow=lambda: ws.mark_dead())
slow.start()

# start WS
ws.connect()

print("Websocket started… press CTRL+C to stop")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    _shutdown()
