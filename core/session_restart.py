import time
import threading
from datetime import datetime, timedelta


class AutoSessionRestarter:

    def __init__(self, restart_hour=5, restart_minute=15, callback=None):
        """
        restart_hour + restart_minute = when restart occurs every day
        callback = function to call when restart triggers
        """
        self.restart_hour = restart_hour
        self.restart_minute = restart_minute
        self.callback = callback
        self.running = False


    def start(self):
        """Start background checker thread"""
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()


    def _loop(self):

        while self.running:

            now = datetime.now()
            target = now.replace(
                hour=self.restart_hour,
                minute=self.restart_minute,
                second=0,
                microsecond=0
            )

            # if we missed restart time today, schedule tomorrow
            if target <= now:
                target += timedelta(days=1)

            wait = (target - now).total_seconds()

            print(f"⏳ Next scheduled restart in {wait/3600:.2f} hours")

            time.sleep(wait)

            if callable(self.callback):
                print("🔄 AUTO SESSION RESTART TRIGGERED")
                self.callback()

