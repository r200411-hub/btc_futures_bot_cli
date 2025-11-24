settings = {
    "api_key": "29zoxlMmTijgJp0xhWMkeF7mEA4PtQ",
    "api_secret": "5KiQJMTDD9I6x8iM4EmfbtaTDdYs5yNaNY3NMuX8HoXH9AxMgd75J7wMEnrr",
    
    "brick_size": 55,
    "fast_ema": 9,
    "slow_ema": 21,

    "min_trade_gap": 60,      # seconds
    "position_size": 0.001,
    "leverage": 50,

    "take_profit": 100,
    "stop_loss": -50,
    # dynamic EMA tuning (rough)
    "vol_low": 10.0,    # calm regime ~ small |Δprice|
    "vol_high": 60.0,   # very wild regime
    "fast_min": 4,
    "fast_max": 20,
    "slow_min": 10,
    "slow_max": 50,
}
