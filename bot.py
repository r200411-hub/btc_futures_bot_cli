from core.connection import DeltaExchangeWebSocket
from core.strategy import Strategy
from core.trader import TradeManager
from core.logger import MLLogger
from core.bad_tick_filter import BadTickFilter
from core.heartbeat import HeartbeatMonitor
from core.freeze_detector import FreezeDetector
from core.validator import AccuracyValidator
from config.settings import settings
from core.hang_guard import SilentHangGuard
from core.slowdown import SlowdownDetector
from core.risk_guard import RiskGuard
from core.regime import MarketRegimeDetector
from core.parquet_logger import ParquetLogger

import websocket,sys, time, os
sys.stdout.reconfigure(line_buffering=True)


### INIT GLOBALS ###

strategy = Strategy(settings)
trader   = TradeManager(settings)
regime = MarketRegimeDetector()
logger   = MLLogger("data/ml_data.csv")
logger_pq  = ParquetLogger("data/tickdata.parquet")
validator = AccuracyValidator()
#print("Writing to:", os.path.abspath("data/ml_data.csv"))

tick_filter = BadTickFilter(log_callback=lambda reason, price, pct=None: print(f"⚠ BAD TICK: {reason} {price} Δ={pct}"))


### CALLBACK ###

def on_price(price, raw=None):
    

    # try:
    #     price = float(price)
    #     print("writing row..", price)
    # except:
    #  return

    slow.mark()
    freeze.tick()
    hb.beat()
    

    if not tick_filter.validate(price):
        return
    
    #print("writing row..", price) -- # for testing code
    # 1) update strategy
    strategy.update(price)
    #print("writing row..1", price) # for testing code

    # 2) update regime detector AFTER strategy
    try:
        current_regime = regime.update(price, strategy)
    except Exception as e:
        print("⚠ regime.update() crashed:", e)
        return

    
     # 3) generate signal
    sig = strategy.signal()
    
    # 4) optional debug:
   # print(f"tick {price:.2f} | regime={current_regime}")
    
    # 5) log ML data including regime
    #logger.log(price, strategy, trader, sig)  # later we can extend logger for regime
    #print("LOG CALLED", price)  # test print to check if log cvs is called
    try:
        
        try:
            logger.log(price, strategy, trader, regime, sig)
        except Exception as e:
            print("LOGGER ERROR:", e)


        logger_pq.log({
            "timestamp": time.time(),
            "price": price,
            "fast_ema": strategy.fast[-1] if strategy.fast else None,
            "slow_ema": strategy.slow[-1] if strategy.slow else None,
            "fast_period": strategy.fast_period,
            "slow_period": strategy.slow_period,
            "ema_spread": (strategy.fast[-1] - strategy.slow[-1]) if strategy.fast and strategy.slow else None,
            "vol_ema": strategy.vol,
            "regime": regime.current_regime,
            "regime_confidence": regime.confidence,
            "brick_dir": strategy.bricks[-1]["dir"] if strategy.bricks else None,
            "brick_count": len(strategy.bricks),
            "signal": sig,
            "pos_side": trader.position["type"] if trader.position else None,
            "pnl": trader.calculate_pnl(price) if trader.position else 0.0
                     })

    except Exception as e:
                print("LOGGER ERROR:", e)
    

    ### REGIME FILTERED EXECUTION ###
    if sig:
        # regime-based blocking
        if sig == "LONG" and not regime.can_trade_long():
            print(f"⛔ LONG blocked by regime: {regime.current_regime}")
        elif sig == "SHORT" and not regime.can_trade_short():
            print(f"⛔ SHORT blocked by regime: {regime.current_regime}")
        elif regime.is_danger():
            print(f"⛔ Trade blocked (danger regime: {regime.current_regime})")
        else:
            print(f"✅ Trade allowed in regime: {regime.current_regime}")
            if sig and not trader.position:
                trader.open(sig, price)
                risk.on_open(sig, price)

     ### MANAGE ACTIVE POSITION ###
    if trader.position:

        pnl = trader.calculate_pnl(price)
        print(f"PnL: {pnl:.2f}", end="\r")

        if pnl > settings["take_profit"] or pnl < settings["stop_loss"]:
            entry = trader.position["entry"]
            side  = trader.position["type"]

            trader.close(price, "SL/TP")
            logger.log(price, strategy, trader,regime, sig)
            risk.reset()

            validator.evaluate(side, entry, price)
            print(f"📊 ACCURACY = {validator.accuracy()}%")


### WS+ GUARDS ###
### INIT ###
os.system("")  # enable ansi flush on windows

ws = DeltaExchangeWebSocket(
        settings["api_key"],
        settings["api_secret"],
        on_price 
    )

### Attach Guards AFTER ws is created

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
    max_exposure_seconds=180,
    max_distance_pct=0.4,
    on_risk=lambda reason: trader.close(strategy.last_price, reason)
)

### START WS
ws.connect()

print("Websocket started… press CTRL+C to stop")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n👋 Exit requested")


