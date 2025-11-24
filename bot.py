from core.connection import DeltaExchangeWebSocket
from core.strategy import Strategy
from core.trader import TradeManager
from core.logger import MLLogger
from config.settings import settings
import time

logger = MLLogger("data/ml_data.csv")

strategy = Strategy(settings)
trader = TradeManager(settings)

def on_price(price,raw=None):
    
    strategy.update(price)
    sig = strategy.signal()
    logger.log(price, strategy, trader,sig)
    # print("fast:", len(strategy.fast), "slow:", len(strategy.slow), "bricks:", len(strategy.bricks), end="\r")
    
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

    # print("tick", price)
        


ws = DeltaExchangeWebSocket(
    settings["api_key"],
    settings["api_secret"],
    on_price
    
)

ws.connect()
