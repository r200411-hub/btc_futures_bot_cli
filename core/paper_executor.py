# core/paper_executor.py
import threading
import time
import random
from queue import Queue, Empty
from typing import Optional, Dict

# If you have an ExecutorBase, keep it - otherwise remove the import and
# change the class signature to `class PaperExecutor:`
try:
    from core.executor_base import ExecutorBase
    _BASE = ExecutorBase
except Exception:
    _BASE = object  # fallback if ExecutorBase not present


class PaperExecutor(_BASE):
    """
    Realistic paper trading executor (background worker).
    - submit_order(side, size, price) -> queued fill simulation
    - start()/stop() to run worker thread
    """

    def __init__(self, settings: dict, trader, csv_logger=None, pq_logger=None):
        self.settings = settings or {}
        self.trader = trader
        self.csv_logger = csv_logger
        self.pq_logger = pq_logger

        self.queue: "Queue[Dict]" = Queue()
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

        # runtime params
        self.last_fill_ts = 0.0
        self.min_trade_gap_s = float(settings.get("min_trade_gap_s",
                                                 settings.get("min_trade_gap", 1.0)))
        self.sim_spread_usd = float(settings.get("sim_spread_usd", 1.0))
        self.sim_slippage_pct = float(settings.get("sim_slippage_pct", 0.0005))
        self.sim_latency_ms = float(settings.get("sim_latency_ms", 20))
        self.sim_random_slippage = bool(settings.get("sim_random_slippage", True))
        self.fee_taker_pct = float(settings.get("fee_taker_pct", 0.0005))
        self.fee_maker_pct = float(settings.get("fee_maker_pct", 0.0002))
        self.enable_trailing = bool(settings.get("enable_trailing", False))
        self.trailing_pts = float(settings.get("trailing_pts", 0.0))
        self.fill_probability = float(settings.get("sim_fill_prob", 0.995))

        # outstanding simulated orders
        self.outstanding: Dict[str, Dict] = {}
        self.order_id_ctr = 0
        self.lock = threading.Lock()

    # -------------------------
    # Public API
    # -------------------------
    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def stop(self, timeout: float = 5.0):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=timeout)

    def submit_order(self, side: str, size: float, price: float, meta: dict = None) -> dict:
        """
        Submit an order to the paper executor.

        Returns a lightweight result dict. If queued, status='queued'.
        If rejected because of min_gap, returns status='rejected'.
        """
        now = time.time()
        # Enforce min trade gap (between fills)
        if now - self.last_fill_ts < self.min_trade_gap_s:
            return {"status": "rejected", "reason": "min_trade_gap", "ts": now}

        order = {
            "order_id": self._next_oid(),
            "side": str(side).upper(),
            "size": float(size),
            "submitted_price": float(price),
            "meta": meta or {},
            "submitted_at": now,
        }

        self.queue.put(order)
        return {"status": "queued", "order_id": order["order_id"], "ts": now}

    def cancel_all(self):
        with self.lock:
            n = len(self.outstanding)
            self.outstanding.clear()
        return n

    # -------------------------
    # Internal helpers
    # -------------------------
    def _next_oid(self) -> str:
        with self.lock:
            self.order_id_ctr += 1
            return f"paper-{self.order_id_ctr}"

    def _run(self):
        """
        Worker loop: takes queued orders, simulates latency, fill probability,
        computes executed price (spread+slippage), then calls the trader to open/close
        and logs the fill (best-effort).
        """
        while not self.stop_event.is_set():
            try:
                order = self.queue.get(timeout=0.5)
            except Empty:
                continue

            # simulate latency
            latency = max(0.0, random.gauss(self.sim_latency_ms, max(1.0, self.sim_latency_ms * 0.25)) / 1000.0)
            time.sleep(latency)

            # occasionally simulate no-fill
            if random.random() > self.fill_probability:
                continue

            executed_price = self._compute_executed_price(order)
            fee = executed_price * order["size"] * self.fee_taker_pct
            fill_ts = time.time()

            # update last_fill_ts atomically
            with self.lock:
                self.last_fill_ts = fill_ts

            # apply to trader
            try:
                self._apply_fill_to_trader(order, executed_price, fee, fill_ts)
            except Exception as e:
                print("PaperExecutor: failed to apply fill:", e)

            # log fill best-effort
            try:
                self._log_fill(order, executed_price, fee, fill_ts)
            except Exception:
                pass

        # worker stopping -> exit
        return

    def _compute_executed_price(self, order: dict) -> float:
        side = order["side"]
        p = float(order["submitted_price"])
        half_spread = self.sim_spread_usd / 2.0
        sign = 1.0 if side == "LONG" else -1.0
        base_slip = self.sim_slippage_pct * p
        if self.sim_random_slippage:
            slip = random.gauss(base_slip, base_slip * 0.5)
        else:
            slip = base_slip
        executed = p + sign * (half_spread + slip)
        return float(round(executed, 8))

    def _apply_fill_to_trader(self, order: dict, executed_price: float, fee: float, fill_ts: float):
        """
        Applies the simulated fill to the trader:
         - if no open position -> open
         - if open same side -> ignore (or could add)
         - if open opposite side -> close existing then open new
        Assumes the trader exposes either .open(side, price) and .close(price, reason)
        (older API) or .open_position/.close_position variants — fallback used.
        """
        side = order["side"]
        # current side: try common keys 'type' or 'side'
        cur_side = None
        if getattr(self.trader, "position", None):
            cur_side = (self.trader.position.get("type")
                        or self.trader.position.get("side")
                        or self.trader.position.get("position_side"))

        # no position -> open
        if not cur_side:
            self._call_trader_open(side, executed_price, order["size"], fill_ts, fee)
            return

        # same side -> ignore (simple behavior)
        if cur_side and cur_side.upper() == side.upper():
            # Already in same side; not increasing or scaling in current simple model
            return

        # opposite side -> close then open
        self._call_trader_close(executed_price, "EXECUTE_REPLACE", fill_ts, fee)
        # small delay possible (but not required)
        self._call_trader_open(side, executed_price, order["size"], fill_ts, fee)

    # def _call_trader_open(self, side, price, size, ts, fee):
    #     """Call trader open with fallback names."""
    #     called = False
    #     try:
    #         if hasattr(self.trader, "open_position"):
    #             self.trader.open_position(side, price)
    #             called = True
    #         elif hasattr(self.trader, "open"):
    #             # many open() signatures exist; try basic safe call
    #             try:
    #                 self.trader.open(side, price)
    #                 called = True
    #             except TypeError:
    #                 # fallback to alternate signature
    #                 try:
    #                     self.trader.open_position(side, price)
    #                     called = True
    #                 except Exception:
    #                     pass
    #     except Exception as e:
    #         print("PaperExec OPEN error:", e)
    #     if not called:
    #         raise RuntimeError("Trader has no suitable open/open_position method")

    # def _call_trader_close(self, price, reason, ts, fee):
    #     """Call trader close with fallback names."""
    #     called = False
    #     try:
    #         if hasattr(self.trader, "close_position"):
    #             self.trader.close_position(price, reason)
    #             called = True
    #         elif hasattr(self.trader, "close"):
    #             try:
    #                 self.trader.close(price, reason)
    #                 called = True
    #             except TypeError:
    #                 # fallback to older close_position signature attempt
    #                 try:
    #                     self.trader.close_position(price, reason)
    #                     called = True
    #                 except Exception:
    #                     pass
    #     except Exception as e:
    #         print("PaperExec CLOSE error:", e)
    #     if not called:
    #         raise RuntimeError("Trader has no suitable close/close_position method")

    def _call_trader_open(self, side, price, size, ts, fee):
        """Call TradeManager.open(side, price) cleanly."""
        try:
            self.trader.open(side, price,size)
        except Exception as e:
            print("PaperExec OPEN error:", e)
            raise

    def _call_trader_close(self, price, reason, ts, fee):
        """Call TradeManager.close(price, reason) cleanly."""
        try:
            self.trader.close(price, reason)
        except Exception as e:
            print("PaperExec CLOSE error:", e)
            raise


    def _log_fill(self, order: dict, executed_price: float, fee: float, fill_ts: float):
        rec = {
            "timestamp": fill_ts,
            "side": order["side"],
            "order_id": order["order_id"],
            "submitted_price": order["submitted_price"],
            "executed_price": executed_price,
            "size": order["size"],
            "fee": fee
        }
        # attempt csv logger (best-effort)
        try:
            if self.csv_logger and hasattr(self.csv_logger, "w"):
                # if csv_logger has a writer, you can implement a small fill row writer here
                pass
        except Exception:
            pass

        # attempt parquet logger with a small fill event
        try:
            if self.pq_logger and hasattr(self.pq_logger, "log"):
                row = {
                    "timestamp": fill_ts,
                    "price": executed_price,
                    "fast_ema": None,
                    "slow_ema": None,
                    "fast_period": None,
                    "slow_period": None,
                    "ema_spread": None,
                    "vol_ema": None,
                    "regime": "FILL",
                    "regime_confidence": 0.0,
                    "brick_dir": None,
                    "brick_count": 0,
                    "signal": None,
                    "pos_side": order["side"],
                    "pnl": 0.0
                }
                try:
                    self.pq_logger.log(row)
                except Exception:
                    pass
        except Exception:
            pass
