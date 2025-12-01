settings = {
    "api_key": "29zoxlMmTijgJp0xhWMkeF7mEA4PtQ",
    "api_secret": "5KiQJMTDD9I6x8iM4EmfbtaTDdYs5yNaNY3NMuX8HoXH9AxMgd75J7wMEnrr",

    # Strategy core
    "brick_size": 10,
    "fast_ema": 9,
    "slow_ema": 21,

    # Trading
    "position_size": 0.01,
    "leverage": 50,

    # Risk
    "take_profit": 4.0,
    "stop_loss": 2.0,
    "max_exposure_seconds": 180,

    # Dynamic EMA
    "vol_low": 10.0,
    "vol_high": 60.0,
    "fast_min": 4,
    "fast_max": 20,
    "slow_min": 10,
    "slow_max": 50,

    # Renko / signal rules
    "min_trade_gap_s": 0.5,

    # Paper trading
    "sim_spread_usd": 1.0,
    "sim_slippage_pct": 0.0005,
    "sim_latency_ms": 20,
    "sim_random_slippage": True,
    "fee_taker_pct": 0.0005,
    "fee_maker_pct": 0.0002,
    "enable_trailing": True,
    "trailing_pts": 150.0,

    # Execution mode
    "simulate_live": True,     # ← ALWAYS True while testing
    "delta_rest_base": "https://api.delta.exchange"
}
