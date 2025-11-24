class AccuracyValidator:

    def __init__(self):
        self.trades = []
        self.correct = 0
        self.total = 0


    def evaluate(self, signal, entry_price, exit_price):

        if signal is None:
            return

        direction = 1 if signal == "LONG" else -1

        profit = (exit_price - entry_price) * direction

        good = profit > 0

        self.total += 1
        if good:
            self.correct += 1

        self.trades.append({
            "signal": signal,
            "entry": entry_price,
            "exit": exit_price,
            "profit": profit,
            "correct": good,
            "accuracy": self.accuracy()
        })


    def accuracy(self):
        if self.total == 0:
            return 0
        return round(self.correct / self.total * 100, 2)
