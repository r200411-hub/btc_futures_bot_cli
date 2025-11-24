from core.connection import DeltaExchangeWebSocket
from core.strategy import Strategy
from core.trader import TradeManager
from core.logger import MLLogger
from core.bad_tick_filter import BadTickFilter
from core.heartbeat import HeartbeatMonitor
from core.freeze_detector import FreezeDetector
from core.validator import AccuracyValidator
from config.settings import settings

import sys, time, os

sys.stdout.reconfigure(line_buffering=True)


### INIT ###

strategy = Strategy(settings)
trader   = TradeManager(settings)
logger   = MLLogger("data/ml_data.csv")
validator = AccuracyValidator()

tick_filter = BadTickFilter(
    log_callback=lambda reason, price, pct=None: print(f"⚠ BAD TICK: {reason} {price} Δ={pct}")
)


### CALLBACK ###

def on_price(price, raw=None):

    freeze.tick()
    hb.beat()

    if not tick_filter.validate(price):
        return

    strategy.update(price)
    sig = strategy.signal()

    logger.log(price, strategy, trader, sig)

    if sig and trader.can_trade() and not trader.position:
        print(f"\n🟢 SIGNAL: {sig} @ {price}")
        trader.open(sig, price)

    if trader.position:

        pnl = trader.calculate_pnl(price)
        print(f"PnL: {pnl:.2f}", end="\r")

        if pnl > settings["take_profit"] or pnl < settings["stop_loss"]:
            entry = trader.position["entry"]
            side  = trader.position["type"]

            trader.close(price, "SL/TP")
            logger.log(price, strategy, trader, sig)

            validator.evaluate(side, entry, price)
            print(f"📊 ACCURACY = {validator.accuracy()}%")


### WS ###

ws = DeltaExchangeWebSocket(
    settings["api_key"],
    settings["api_secret"],
    on_price
)


### DIAGNOSTICS ###

hb = HeartbeatMonitor(timeout=10, on_dead=lambda: ws.reconnect())
hb.start()

freeze = FreezeDetector(timeout_seconds=30, on_freeze_callback=lambda: ws.reconnect())
freeze.start()



### RUN ###

os.system("")
ws.connect()

print("Websocket started… press CTRL+C to stop")

try:
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("\n👋 Exit requested")
