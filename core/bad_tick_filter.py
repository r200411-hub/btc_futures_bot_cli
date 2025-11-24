import time

class BadTickFilter:

    def __init__(self, log_callback=None):
        self.last_price = None
        self.max_jump_pct = 0.40      
        self.min_price = 1000         
        self.max_price = 200000       
        self.log_callback = log_callback


    def validate(self, price):

        try:
            price = float(price)
        except:
            return False

        # reject nonsense
        if price < self.min_price or price > self.max_price:
            self._log("out_of_range", price)
            return False

        # reject % spike
        if self.last_price is not None:
            pct = abs((price - self.last_price) / self.last_price) * 100

            if pct > self.max_jump_pct:
                self._log("sudden_spike", price, pct)
                return False

        self.last_price = price
        return True


    def _log(self, reason, price, pct=None):
        if self.log_callback:
            self.log_callback(reason, price, pct)
