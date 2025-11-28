# core/live_executor.py
class LiveRESTExecutor:
    """
    Placeholder for the live REST executor. Implement this when you connect to
    Delta REST endpoints (testnet/live). For now it raises NotImplementedError.
    """
    def __init__(self, settings, trader, logger=None):
        self.settings = settings
        self.trader = trader
        self.logger = logger

    def start(self):
        raise NotImplementedError("LiveRESTExecutor not implemented yet")

    def stop(self):
        raise NotImplementedError("LiveRESTExecutor not implemented yet")

    def submit_order(self, side, size, price, meta=None):
        raise NotImplementedError("LiveRESTExecutor not implemented yet")

    def cancel_all(self):
        raise NotImplementedError("LiveRESTExecutor not implemented yet")
