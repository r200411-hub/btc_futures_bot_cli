from core.connection import DeltaExchangeWebSocket
from core.strategy import Strategy
from core.trader import TradeManager
from core.logger import MLLogger
from core.bad_tick_filter import BadTickFilter
from core.heartbeat import HeartbeatMonitor 
from config.settings import settings
from core.validator import AccuracyValidator
from core.freeze_detector import FreezeDetector
from core.session_restart import AutoSessionRestarter 

import time

import sys ,os
sys.stdout.reconfigure(line_buffering=True)


tick_filter = BadTickFilter(
    log_callback=lambda reason, price, pct=None: print(f"⚠ BAD TICK: {reason} {price} Δ={pct}")
)

validator = AccuracyValidator()


tick_filter = BadTickFilter()
logger = MLLogger("data/ml_data.csv")

hb = HeartbeatMonitor(timeout=10, on_dead=lambda: ws.reconnect())
hb.start()

strategy = Strategy(settings)
trader = TradeManager(settings)

def on_price(price,raw=None):

    freeze.tick()  # <--- IMPORTANT
    hb.beat()

    strategy.update(price)
    sig = strategy.signal()
    logger.log(price, strategy, trader,sig)
    # print("fast:", len(strategy.fast), "slow:", len(strategy.slow), "bricks:", len(strategy.bricks), end="\r")
   
   

    if not tick_filter.validate(price):
        print("bad tick ignored:", price)
        return
    
    if sig:
        print(f"\n🟢 SIGNAL: {sig} price={price}")
   
    if sig and trader.can_trade() and not trader.position:
        trader.open(sig, price)

    # if trader.position:
    #     pnl = (price - trader.position["entry"]) if trader.position["side"]=="LONG" else (trader.position["entry"]-price)
    #     print(f"Pnl: {pnl:.2f}", end="\r")
    if trader.position:
        pnl = trader.calculate_pnl(price)
        print(f"Pnl: {pnl:.2f}", end="\r")

        if pnl>settings["take_profit"] or pnl<settings["stop_loss"]:
            trader.close(price,"SL/TP")
            logger.log(price, strategy, trader, sig)

        if trader.position:
            pnl = trader.calculate_pnl(price)

    if pnl>settings["take_profit"] or pnl<settings["stop_loss"]:
        
        entry = trader.position["entry"]
        side  = trader.position["type"]

        trader.close(price,"SL/TP")

        validator.evaluate(side, entry, price)

        print(f"📊 LIVE ACCURACY = {validator.accuracy()}%")

    print("tick", price)
        




ws = DeltaExchangeWebSocket(
    settings["api_key"],
    settings["api_secret"],
    on_price
    
)

freeze = FreezeDetector(
    timeout_seconds=30,
    on_freeze_callback=lambda: ws.reconnect()
)

freeze.start()


ws.connect()
sys.stdout.flush()
os.system("")  # enables ANSI + flush behaviour in Windows terminal
# prevent program exit
print("Websocket started… press CTRL+C to stop")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n👋 Exiting bot…")

while True:
    if hb.is_dead():
        print("💔 Heartbeat lost — reconnecting…")
        ws.reconnect()
    time.sleep(2)