import time

class AdaptiveReconnect:

    def __init__(self):
        self.last_connect = None
        self.last_disconnect = None
        self.avg_uptime = 0
        self.samples = 0

    def on_connect(self):
        self.last_connect = time.time()

    def on_disconnect(self):
        if not self.last_connect:
            return self.avg_uptime or 0

        uptime = time.time() - self.last_connect
        self.samples += 1

        if self.avg_uptime is None:
            self.avg_uptime = uptime
        else:
            # gradual smoothing, faster early
            alpha = min(0.25, 1 / self.samples)
            self.avg_uptime = (alpha * uptime) + ((1 - alpha) * self.avg_uptime)

        return self.avg_uptime

    def get_quality_score(self):

        # in seconds
        u = self.avg_uptime or 0

        if u > 120: return "excellent"
        if u > 60: return "good"
        if u > 20: return "poor"
        return "very_bad"
