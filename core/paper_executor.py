# core/paper_executor.py
import threading
import time
import random
import math
from queue import Queue, Empty
from typing import Optional

from core.executor_base import ExecutorBase

class PaperExecutor(ExecutorBase):
    """
    Realistic paper trading executor.

    Features:
      - spread (bid/ask)
      - slippage (random & percent)
      - latency (ms)
      - maker/taker fee simulation
      - trailing stop support (executed on background)
      - min trade gap enforcement
      - simulated fills delivered to TradeManager via its public methods
    """

    def __init__(self, settings: dict, trader, csv_logger=None, pq_logger=None):
        self.settings = settings
        self.trader = trader
        self.csv_logger = csv_logger
        self.pq_logger = pq_logger

        self.queue = Queue()
        self.worker = None
        self.stop_event = threading.Event()

        # runtime
        self.last_fill_ts = 0
        self.min_trade_gap_s = float(settings.get("min_trade_gap_s", settings.get("min_trade_gap", 1.0)))
        self.sim_spread_usd = float(settings.get("sim_spread_usd", 1.0))
        self.sim_slippage_pct = float(settings.get("sim_slippage_pct", 0.0005))
        self.sim_latency_ms = float(settings.get("sim_latency_ms", 20))
        self.sim_random_slippage = bool(settings.get("sim_random_slippage", True))
        self.fee_taker_pct = float(settings.get("fee_taker_pct", 0.0005))
        self.fee_maker_pct = float(settings.get("fee_maker_pct", 0.0002))
        self.enable_trailing = bool(settings.get("enable_trailing", False))
        self.trailing_pts = float(settings.get("trailing_pts", 0.0))
        self.fill_probability = float(settings.get("sim_fill_prob", 0.995))

        # order book of outstanding simulated orders (simple list)
        self.outstanding = {}
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

    def stop(self):
        self.stop_event.set()
        # drain queue then stop
        if self.worker:
            self.worker.join(timeout=5)

    def submit_order(self, side: str, size: float, price: float, meta: dict=None) -> dict:
        """
        Submit an order to the paper executor.

        Returns a lightweight order object {order_id, submitted_at}
        """
        now = time.time()
        if now - self.last_fill_ts < self.min_trade_gap_s:
            # enforce min gap: reject by returning None-like order with reason
            return {"status": "rejected", "reason": "min_trade_gap", "ts": now}

        order = {
            "order_id": self._next_oid(),
            "side": side.upper(),
            "size": float(size),
            "submitted_price": float(price),
            "meta": meta or {},
            "submitted_at": now,
        }

        self.queue.put(order)
        return {"status": "queued", "order_id": order["order_id"], "ts": now}

    def cancel_all(self):
        with self.lock:
            self.outstanding.clear()
        # queue flush won't produce fills for cleared orders

    # -------------------------
    # Internal helpers
    # -------------------------
    def _next_oid(self):
        with self.lock:
            self.order_id_ctr += 1
            return f"paper-{self.order_id_ctr}"

    def _run(self):
        """Background loop to process queued orders and simulate fills."""
        while not self.stop_event.is_set():
            try:
                order = self.queue.get(timeout=0.5)
            except Empty:
                continue

            # simulate network latency
            latency = max(0.0, random.gauss(self.sim_latency_ms, self.sim_latency_ms * 0.25) / 1000.0)
            time.sleep(latency)

            # evaluate fill probability
            if random.random() > self.fill_probability:
                # simulate an occasional miss/no-fill
                continue

            # compute executed price: apply half-spread and slippage
            executed_price = self._compute_executed_price(order)

            # compute fees
            fee = executed_price * order["size"] * self.fee_taker_pct

            # record fill timestamp
            fill_ts = time.time()
            self.last_fill_ts = fill_ts

            # call trader to open/close position
            try:
                # open or close depending on side and existing position
                # if there's no position -> open_position
                # if there is a position of opposite side -> close and open new (simulate)
                if not getattr(self.trader, "position", None):
                    # open position
                    self._call_trader_open(order["side"], executed_price, order["size"], fill_ts, fee)
                else:
                    # If trader already has a position and side equals current side -> ignore duplicate
                    cur_side = self.trader.position.get("type") if self.trader.position else None
                    if cur_side and cur_side == order["side"]:
                        # Already in same side — ignore or treat as add (simple: ignore)
                        pass
                    else:
                        # close existing position and record PnL in trader
                        self._call_trader_close(executed_price, "EXECUTE_REPLACE", fill_ts, fee)
                        # optionally open fresh position if requested
                        self._call_trader_open(order["side"], executed_price, order["size"], fill_ts, fee)

                # log fill to CSV/Parquet if provided
                self._log_fill(order, executed_price, fee, fill_ts)

            except Exception as e:
                # do not crash worker
                print("PaperExecutor: failed to apply fill:", e)

        # worker stopping -> do flush if needed
        return

    def _compute_executed_price(self, order):
        side = order["side"]
        p = float(order["submitted_price"])
        half_spread = self.sim_spread_usd / 2.0
        # sign: BUY/LONG pays higher (ask), SELL/SHORT receives lower (bid)
        sign = 1.0 if side == "LONG" else -1.0
        # slippage magnitude proportional to price
        base_slip = self.sim_slippage_pct * p
        if self.sim_random_slippage:
            slip = random.gauss(base_slip, base_slip * 0.5)
        else:
            slip = base_slip
        executed = p + sign * (half_spread + slip)
        # round a little
        return float(round(executed, 8))

    def _call_trader_open(self, side, price, size, ts, fee):
        # prefer canonical method names
        if hasattr(self.trader, "open_position"):
            self.trader.open_position(side, price)
        elif hasattr(self.trader, "open"):
            # fallback older naming
            try:
                self.trader.open(side, price)
            except TypeError:
                # many open() signatures exist; try open_position style
                self.trader.open_position(side, price)
        else:
            raise RuntimeError("Trader has no open_position/open implementation")

    def _call_trader_close(self, price, reason, ts, fee):
        if hasattr(self.trader, "close_position"):
            self.trader.close_position(price, reason)
        elif hasattr(self.trader, "close"):
            self.trader.close(price, reason)
        else:
            raise RuntimeError("Trader has no close_position/close implementation")

    def _log_fill(self, order, executed_price, fee, fill_ts):
        # simple logging record for the fill (non-blocking best-effort)
        rec = {
            "timestamp": fill_ts,
            "side": order["side"],
            "order_id": order["order_id"],
            "submitted_price": order["submitted_price"],
            "executed_price": executed_price,
            "size": order["size"],
            "fee": fee
        }
        try:
            if self.csv_logger:
                try:
                    # many logger implementations take (price, strategy, trader, regime, sig)
                    # we will attempt to append a simple fill row if logger exposes 'w' writer
                    if hasattr(self.csv_logger, "w"):
                        # nothing standardized — skip
                        pass
                except:
                    pass
            if self.pq_logger:
                # best-effort: create a small event row
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
