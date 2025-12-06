# bot.py  -- Full realistic paper trading integration (Option C+ with Renko SL/TP + parquet fill & cooldown)
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
# SL/TP policy: Renko-based defaults + override
# ---------------------------
_BRICK = float(settings.get("brick_size", 10.0))
default_stop_loss = _BRICK * 1.0      # 1 brick
default_take_profit = _BRICK * 2.0    # 2 bricks

_user_sl = settings.get("stop_loss", None)
_user_tp = settings.get("take_profit", None)

if _user_sl is None or float(_user_sl) <= 0:
    EFFECTIVE_SL = float(default_stop_loss)
else:
    EFFECTIVE_SL = float(_user_sl)

if _user_tp is None or float(_user_tp) <= 0:
    EFFECTIVE_TP = float(default_take_profit)
else:
    EFFECTIVE_TP = float(_user_tp)

# cooldown after SL/TP close (seconds)
SL_COOLDOWN = float(settings.get("sl_cooldown_s", 10.0))

print(f"Using SL={EFFECTIVE_SL} TP={EFFECTIVE_TP} (brick={_BRICK}) cooldown={SL_COOLDOWN}s")

# ---------------------------
# Helpers, state for anti-reentry logic
# ---------------------------
# closed_due_to_sl stores timestamp of SL/TP close (None if none)
closed_due_to_sl_ts = None
closed_signal = None  # e.g. "LONG" or "SHORT"

# convenience wrappers for safe logging
def safe_log_csv(*args, **kwargs):
    try:
        logger_csv.log(*args, **kwargs)
    except Exception as e:
        print("LOGGER ERROR for CSV:", e)

def safe_log_pq(row):
    try:
        logger_pq.log(row)
    except Exception as e:
        print("LOGGER ERROR for Parquet:", e)

# ---------------------------
# Order helpers
# ---------------------------
def place_order(side: str, price: float, size: float = None):
    """Submit an order to paper executor and print/return the outcome."""
    global closed_due_to_sl_ts, closed_signal
    size = size or settings.get("position_size", 0.01)

    # defensive normalization + validation
    if side is None:
        print(f"⚠ Refusing to place order: side is None for price={price}")
        return {"status": "rejected", "reason": "invalid_side", "ts": time.time()}

    side_norm = str(side).upper()
    if side_norm not in ("LONG", "SHORT"):
        print(f"⚠ Refusing to place order: invalid side='{side}' (normalized='{side_norm}') for price={price}")
        return {"status": "rejected", "reason": "invalid_side", "ts": time.time()}

    # Block re-entry if we closed recently due to SL/TP and cooldown hasn't expired
    if closed_due_to_sl_ts is not None:
        elapsed = time.time() - closed_due_to_sl_ts
        if elapsed < SL_COOLDOWN and closed_signal == side_norm:
            print(f"⚠ Blocking re-entry: recently closed on {closed_signal}, cooldown {SL_COOLDOWN:.1f}s not expired ({elapsed:.1f}s elapsed)")
            return {"status": "rejected", "reason": "blocked_recent_sl_close_cooldown", "ts": time.time()}
        # also block if same signal persists until a fresh crossover; that logic is handled elsewhere (signal change detection)

    # If closed_due_to_sl_ts exists but cooldown passed, still respect the "fresh crossover" requirement:
    # we only prevent immediate re-entry when the signal is identical and we haven't seen a new crossover.
    # That is handled by the closed_signal variable cleared in on_price when signal changes.

    res = executor.submit_order(side_norm, size, price, meta={"source": "bot"})
    if res.get("status") == "queued":
        print(f"🟡 Order queued: {side_norm} @ {price:.2f} size={size} (order_id={res.get('order_id')})")
        # acting on a new order -> clear the SL-close block so we can trade again after this order resolves
        closed_due_to_sl_ts = None
        closed_signal = None
    else:
        print(f"🔴 Order status: {res}")
    return res

def _write_parquet_fill_row(price, side, pnl=0.0):
    """Write a minimal parquet fill event for analysis."""
    try:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": price,
            "fast_ema": strategy.fast[-1] if strategy.fast else None,
            "slow_ema": strategy.slow[-1] if strategy.slow else None,
            "fast_period": getattr(strategy, "fast_period", None),
            "slow_period": getattr(strategy, "slow_period", None),
            "ema_spread": (strategy.fast[-1] - strategy.slow[-1]) if (strategy.fast and strategy.slow) else None,
            "vol_ema": getattr(strategy, "vol", None),
            "regime": "FILL",
            "regime_confidence": 0.0,
            "brick_dir": strategy.bricks[-1]["dir"] if strategy.bricks else None,
            "brick_count": len(strategy.bricks),
            "signal": None,
            "pos_side": side,
            "pnl": float(pnl)
        }
        safe_log_pq(row)
    except Exception as e:
        print("⚠ parquet fill logging failed:", e)

def close_only_position(price: float, reason: str = "MANUAL_CLOSE"):
    """
    Close current position immediately via TradeManager.close (do not open opposite).
    Also write a parquet fill row and set SL-close cooldown and block-signal.
    """
    global closed_due_to_sl_ts, closed_signal
    if not getattr(trader, "position", None):
        print("⚪ No open position to close.")
        return
    pos = trader.position or {}
    side = pos.get("side") or pos.get("type") or None

    # attempt to compute PnL for logging (best-effort)
    try:
        pnl = trader.calculate_pnl(price) if getattr(trader, "position", None) else 0.0
    except Exception:
        pnl = 0.0

    try:
        trader.close(price, reason)
        print(f"📉 CLOSE {side} @ {price} PnL={pnl:.2f} TOTAL={getattr(trader, 'total', 0.0):.2f} ({reason})")
    except Exception as e:
        print("⚠ direct close failed:", e)
        # fallback: attempt executor-based close (but that may re-open; we avoid that)
    # write a parquet fill row marking the close
    _write_parquet_fill_row(price, side, pnl=pnl)

    # mark closed_by_sl timestamp and side (block re-entry for cooldown)
    closed_due_to_sl_ts = time.time()
    closed_signal = side

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
    os._exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ---------------------------
# Core callback (per tick)
# ---------------------------
def on_price(price, raw=None):
    """
    Main tick callback.
    """
    global closed_due_to_sl_ts, closed_signal

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
    brick_dir = strategy.bricks[-1]["dir"] if strategy.bricks else None

    # debug print
    print(f"tick {price:.2f} | signal={sig} | brick_dir={brick_dir}")

    # Log everything safely
    safe_log_csv(price, strategy, trader, regime, sig)
    safe_log_pq({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "price": price,
        "fast_ema": strategy.fast[-1] if strategy.fast else None,
        "slow_ema": strategy.slow[-1] if strategy.slow else None,
        "fast_period": strategy.fast_period,
        "slow_period": strategy.slow_period,
        "ema_spread": (strategy.fast[-1] - strategy.slow[-1]) if (strategy.fast and strategy.slow) else None,
        "vol_ema": strategy.vol,
        "regime": regime.current_regime,
        "regime_confidence": getattr(regime, "confidence", getattr(regime,"last_spread",0.0)),
        "brick_dir": brick_dir,
        "brick_count": len(strategy.bricks),
        "signal": sig,
        "pos_side": trader.position.get("side") if trader.position else None,
        "pnl": trader.calculate_pnl(price) if getattr(trader, "position", None) else 0.0
    })

    # ---- FILTERED PURE TRADING (Option C+) ----
    if sig == "LONG" and brick_dir == "up":
        place_order("LONG", price)
    elif sig == "SHORT" and brick_dir == "down":
        place_order("SHORT", price)

    # Manage active position: check SL/TP via PnL and close (close-only: DO NOT reverse)
    if getattr(trader, "position", None):
        pnl = trader.calculate_pnl(price)
        print(f"PnL: {pnl:.2f}", end="\r")

        if pnl >= EFFECTIVE_TP or pnl <= -abs(EFFECTIVE_SL):
            print("\n🏁 SL/TP triggered — closing position (close-only, no reversal)")
            close_only_position(price, reason="SL/TP")
            time.sleep(0.05)
            try:
                logger_csv.log(price, strategy, trader, regime, None)
            except Exception:
                pass

    # Clear closed_due_to_sl if signal changed (we allow re-entry only after a fresh crossover)
    if closed_due_to_sl_ts is not None:
        # if cooldown expired, also allow re-entry (but still require signal change check below)
        cooldown_passed = (time.time() - closed_due_to_sl_ts) >= SL_COOLDOWN
        if sig is None or (closed_signal is not None and sig != closed_signal) or cooldown_passed:
            print("🔓 SL-close condition cleared (either signal changed or cooldown expired) — re-entry allowed now.")
            closed_due_to_sl_ts = None
            closed_signal = None

# ---------------------------
# Create WS and attach guards
# ---------------------------
ws = DeltaExchangeWebSocket(settings["api_key"], settings["api_secret"], on_price)

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
    on_risk=lambda reason: close_only_position(strategy.last_price if hasattr(strategy, "last_price") else None)
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
