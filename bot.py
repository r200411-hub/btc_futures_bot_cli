# bot.py  -- Full realistic paper trading integration (Option 1)
import os
import sys
import time
import signal
import threading
from datetime import datetime, timezone

# Core modules (assumed present in your project)
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
from core.paper_executor import PaperExecutor
from config.settings import settings

# make prints line-buffered on Windows
sys.stdout.reconfigure(line_buffering=True)
os.system("")  # enable ANSI (Windows) — harmless elsewhere

# ---------------------------
# Initialize components
# ---------------------------
strategy = Strategy(settings)
trader = TradeManager(settings)
regime = MarketRegimeDetector()
logger_csv = MLLogger("data/ml_data.csv")
logger_pq = ParquetLogger("data/tickdata.parquet")
validator = AccuracyValidator()

# Paper executor: realistic fills / latency / spread / slippage / fees
executor = PaperExecutor(settings, trader, csv_logger=logger_csv, pq_logger=logger_pq)
executor.start()

# Tick filter and guards will be attached once ws is available
tick_filter = BadTickFilter(log_callback=lambda reason, price, pct=None: print(f"⚠ BAD TICK: {reason} {price} Δ={pct}"))

# ---------------------------
# Helpers: place_order -> executor
# ---------------------------
def place_order(side: str, price: float, size: float = None):
    """Submit an order to paper executor and print/return the outcome."""
    size = size or settings.get("position_size", 0.01)
    res = executor.submit_order(side, size, price, meta={"source": "bot"})
    if res.get("status") in ("queued",):
        print(f"🟡 Order queued: {side} @ {price:.2f} size={size} (order_id={res.get('order_id')})")
    else:
        # rejected or immediate response
        print(f"🔴 Order status: {res}")
    return res

def close_position_by_executor(price: float):
    """
    Close existing position by submitting opposite-side order.
    PaperExecutor's worker will handle close logic (it closes if existing side differs).
    """
    if not getattr(trader, "position", None):
        print("⚪ No open position to close.")
        return
    # Correct: read actual side
    cur_side = trader.position.get("side") or trader.position.get("type")
    if not cur_side:
        print("⚠ trader.position has no side/type key!")
        return
    opposite = "SHORT" if cur_side == "LONG" else "LONG"
    place_order(opposite, price, size=trader.position.get("size", settings.get("position_size")))


# ---------------------------
# periodic auto-flush for parquet logger
# ---------------------------
_auto_flush_timer = None
def _auto_flush_worker():
    try:
        logger_pq.flush()
    except Exception as e:
        print("Auto-flush failed:", e)
    # schedule again
    global _auto_flush_timer
    _auto_flush_timer = threading.Timer(30.0, _auto_flush_worker)
    _auto_flush_timer.daemon = True
    _auto_flush_timer.start()

# ---------------------------
# graceful shutdown
# ---------------------------
def shutdown(signum=None, frame=None):
    print("\n🛑 SHUTDOWN requested — flushing & stopping background workers...")
    try:
        # stop recurring flush
        global _auto_flush_timer
        if _auto_flush_timer:
            _auto_flush_timer.cancel()
    except:
        pass

    try:
        logger_pq.flush()
    except Exception as e:
        print("Error flushing parquet:", e)

    try:
        logger_pq.close()
    except:
        pass

    try:
        logger_csv and getattr(logger_csv, "close", lambda: None)()
    except:
        pass

    try:
        executor.stop()
    except Exception as e:
        print("Error stopping executor:", e)

    try:
        # let connection thread shut down gracefully if present
        if 'ws' in globals() and getattr(ws, "ws", None):
            try:
                ws.ws.keep_running = False
            except:
                pass
    except:
        pass

    # small sleep to let final flushes happen
    time.sleep(0.25)
    print("Goodbye.")
    # use os._exit here to avoid blocking if threads remain (clean)
    os._exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ---------------------------
# Core callback (per tick)
# ---------------------------
def on_price(price, raw=None):
    """
    Main tick callback.
    - validate tick
    - update strategy
    - update regime
    - log ML row
    - decide signals
    - submit orders to PaperExecutor (executor handles fills)
    """
    try:
        price = float(price)
    except Exception:
        return

    # mark diagnostics (these are safe no-ops if not set)
    try:
        slow.mark()
    except Exception:
        pass
    try:
        freeze.tick()
    except Exception:
        pass
    try:
        hb.beat()
    except Exception:
        pass

    # basic bad tick filtering
    if not tick_filter.validate(price):
        return

    # update strategy first
    strategy.update(price)

    # regime detector uses strategy info (EMA + bricks)
    try:
        current_regime = regime.update(price, strategy)
    except Exception as e:
        print("⚠ regime.update() crashed:", e)
        current_regime = getattr(regime, "current_regime", "UNKNOWN")

    # generate signal (renko + ema crossover)
    sig = strategy.signal()

    # debug print
    print(f"tick {price:.2f} | regime={current_regime} | signal={sig}")

    # Log ML row (CSV + Parquet)
    try:
        logger_csv.log(price, strategy, trader, regime, sig)
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
            "ema_spread": (strategy.fast[-1] - strategy.slow[-1]) if (strategy.fast and strategy.slow) else None,
            "vol_ema": getattr(strategy, "vol", None),
            "regime": regime.current_regime,
            "regime_confidence": getattr(regime, "confidence", getattr(regime, "last_spread", 0.0)),
            "brick_dir": strategy.bricks[-1]["dir"] if strategy.bricks else None,
            "brick_count": len(strategy.bricks),
            "signal": sig,
            "pos_side": trader.position.get("side") if trader.position else None,
            "pnl": trader.calculate_pnl(price) if getattr(trader, "position", None) else 0.0
        })
    except Exception as e:
        print("LOGGER ERROR for Parquet:", e)

    # Regime-aware execution: submit to executor (paper)
    if sig:
        # block if regime says no
        if sig == "LONG" and not regime.can_trade_long():
            print(f"⛔ LONG blocked by regime: {regime.current_regime}")
        elif sig == "SHORT" and not regime.can_trade_short():
            print(f"⛔ SHORT blocked by regime: {regime.current_regime}")
        elif regime.is_danger():
            print(f"⛔ Trade blocked (danger regime: {regime.current_regime})")
        else:
            # place order via executor (submission only)
            place_order(sig, price)

    # Manage active position: check SL/TP via PnL and close by submitting opposite-side order
    if getattr(trader, "position", None):
        pnl = trader.calculate_pnl(price)
        # print PnL inline
        print(f"PnL: {pnl:.2f}", end="\r")

        # check stoploss/takeprofit from settings
        if pnl >= settings.get("take_profit") or pnl <= -abs(settings.get("stop_loss")):
            print("\n🏁 SL/TP triggered — closing position via executor")
            # close by submitting opposite-side (executor will close existing position)
            close_position_by_executor(price)
            # small delay to let executor apply fill
            time.sleep(0.05)
            # log after close
            try:
                logger_csv.log(price, strategy, trader, regime, None)
            except:
                pass

# ---------------------------
# Create WS and attach guards
# ---------------------------

# make WS object
ws = DeltaExchangeWebSocket(settings["api_key"], settings["api_secret"], on_price)

# Guards: hang, heartbeat, freeze, slowdown
hang = SilentHangGuard(timeout=10, on_hang=lambda: ws.reconnect())
hang.start()
ws.hang = hang

hb = HeartbeatMonitor(timeout=10, on_dead=lambda: ws.reconnect())
hb.start()

freeze = FreezeDetector(timeout_seconds=30, on_freeze_callback=lambda: ws.reconnect())
freeze.start()

slow = SlowdownDetector(
    window=40,
    threshold_factor=3.0,
    on_slow=lambda: ws.reconnect()
)
slow.start()

risk = RiskGuard(
    max_exposure_seconds=settings.get("max_exposure_seconds", 180),
    max_distance_pct=settings.get("max_distance_pct", 0.4),
    on_risk=lambda reason: close_position_by_executor(strategy.last_price if hasattr(strategy, "last_price") else None)
)

# start auto-flush
_auto_flush_worker()

# ---------------------------
# Start connection
# ---------------------------
ws.connect()
print("Websocket started… press CTRL+C to stop")

# ---------------------------
# Main loop (keeps process alive)
# ---------------------------
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    shutdown()
