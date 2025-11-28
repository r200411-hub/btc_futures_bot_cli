# tests/paper_test.py
from core.paper_executor import PaperTradeExecutor
import time

settings = {
    "sim_spread_usd": 1.0,
    "sim_slippage_pct": 0.0005,
    "sim_latency_ms": 10,
    "fee_taker_pct": 0.0005,
    "position_size": 0.01,
    "take_profit": 2.0,
    "stop_loss": 1.0,
    "enable_trailing": True,
    "trailing_pts": 50.0
}

t = PaperTradeExecutor(settings)

print("Request open LONG at 100")
t.open_position("LONG", 100.0)
time.sleep(0.05)
for p in [100.2, 100.6, 101.0, 101.5, 101.0, 100.0, 99.0]:
    t.on_tick(p)
    print("tick", p, "pnl", t.calculate_pnl(p))
    time.sleep(0.02)



time.sleep(0.1)
print("Closing...")
t.close_position(101.5, reason="TEST_CLOSE")
time.sleep(0.1)
print("Trades:", t.trades)
print("Total PnL:", t.total_pnl)
