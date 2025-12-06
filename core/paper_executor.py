# core/paper_executor.py
import threading
import time
import random
from queue import Queue, Empty
from typing import Optional, Dict

try:
    from core.executor_base import ExecutorBase
    _BASE = ExecutorBase
except Exception:
    _BASE = object


class PaperExecutor(_BASE):
    """
    Paper executor: queue orders and apply fills to TradeManager.
    Expects TradeManager.open(side, price, size) and TradeManager.close(price, reason).
    """

    def __init__(self, settings: dict, trader, csv_logger=None, pq_logger=None):
        self.settings = settings or {}
        self.trader = trader
        self.csv_logger = csv_logger
        self.pq_logger = pq_logger

        self.queue: "Queue[Dict]" = Queue()
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

        self.last_fill_ts = 0.0
        self.min_trade_gap_s = float(self.settings.get("min_trade_gap_s", self.settings.get("min_trade_gap", 0.5)))
        self.sim_spread_usd = float(self.settings.get("sim_spread_usd", 1.0))
        self.sim_slippage_pct = float(self.settings.get("sim_slippage_pct", 0.0005))
        self.sim_latency_ms = float(self.settings.get("sim_latency_ms", 20))
        self.sim_random_slippage = bool(self.settings.get("sim_random_slippage", True))
        self.fee_taker_pct = float(self.settings.get("fee_taker_pct", 0.0005))
        self.fill_probability = float(self.settings.get("sim_fill_prob", 0.995))

        self.order_id_ctr = 0
        self.lock = threading.Lock()

        # Outstanding orders (required for cancel_all)
        self.outstanding: Dict[str, Dict] = {}

    # ---------------------------------------------------------------------
    # Required abstract method override
    # ---------------------------------------------------------------------
    def cancel_all(self):
        """
        Cancel all outstanding simulated orders (required by ExecutorBase).
        """
        with self.lock:
            n = len(self.outstanding)
            self.outstanding.clear()
        return n

    # ---------------------------------------------------------------------
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

    def _next_oid(self):
        with self.lock:
            self.order_id_ctr += 1
            return f"paper-{self.order_id_ctr}"

    def submit_order(self, side: str, size: float, price: float, meta: dict = None) -> dict:
        now = time.time()
        if side is None:
            return {"status": "rejected", "reason": "invalid_side_none", "ts": now}

        side_norm = str(side).upper()
        if side_norm not in ("LONG", "SHORT"):
            return {"status": "rejected", "reason": f"invalid_side_{side_norm}", "ts": now}

        if now - self.last_fill_ts < self.min_trade_gap_s:
            return {"status": "rejected", "reason": "min_trade_gap", "ts": now}

        order = {
            "order_id": self._next_oid(),
            "side": side_norm,
            "size": float(size),
            "submitted_price": float(price),
            "meta": meta or {},
            "submitted_at": now,
        }

        with self.lock:
            self.outstanding[order["order_id"]] = order

        self.queue.put(order)
        return {"status": "queued", "order_id": order["order_id"], "ts": now}

    # ---------------------------------------------------------------------
    def _compute_executed_price(self, order):
        p = float(order["submitted_price"])
        half_spread = self.sim_spread_usd / 2.0
        sign = 1.0 if order["side"] == "LONG" else -1.0
        base_slip = self.sim_slippage_pct * p
        slip = random.gauss(base_slip, base_slip * 0.5) if self.sim_random_slippage else base_slip
        executed = p + sign * (half_spread + slip)
        return float(round(executed, 8))

    # ---------------------------------------------------------------------
    def _apply_fill_to_trader(self, order, executed_price, fee, fill_ts):
        pos = getattr(self.trader, "position", None) or {}
        cur_side = pos.get("side") or pos.get("type")

        # open new position if none
        if not cur_side:
            try:
                self.trader.open(order["side"], executed_price, order["size"])
            except TypeError:
                self.trader.open(order["side"], executed_price)
            return

        # same side → ignore
        if cur_side.upper() == order["side"].upper():
            return

        # opposite → close then open
        self.trader.close(executed_price, "EXECUTE_REPLACE")
        try:
            self.trader.open(order["side"], executed_price, order["size"])
        except TypeError:
            self.trader.open(order["side"], executed_price)

    # ---------------------------------------------------------------------
    def _log_fill(self, order, executed_price, fee, fill_ts):
        if not self.pq_logger:
            return
        row = {
            "timestamp": datetime_iso(fill_ts),
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

    # ---------------------------------------------------------------------
    def _run(self):
        while not self.stop_event.is_set():
            try:
                order = self.queue.get(timeout=0.5)
            except Empty:
                continue

            # latency
            latency = max(0.0, random.gauss(self.sim_latency_ms, max(1.0, self.sim_latency_ms * 0.25)) / 1000.0)
            time.sleep(latency)

            # random no-fill simulation
            if random.random() > self.fill_probability:
                continue

            executed_price = self._compute_executed_price(order)
            fee = executed_price * order["size"] * self.fee_taker_pct
            fill_ts = time.time()

            with self.lock:
                self.last_fill_ts = fill_ts
                self.outstanding.pop(order["order_id"], None)

            self._apply_fill_to_trader(order, executed_price, fee, fill_ts)
            self._log_fill(order, executed_price, fee, fill_ts)


def datetime_iso(ts=None):
    import datetime
    if ts is None:
        ts = time.time()
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
