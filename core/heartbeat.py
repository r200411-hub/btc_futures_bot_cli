import time
import threading

class HeartbeatMonitor:

    def __init__(self, timeout=10, on_dead=None):
        """
        timeout = seconds without data before declaring connection dead
        on_dead = callback function to execute on death
        """
        self.timeout = timeout
        self.on_dead = on_dead
        self.last_beat = time.time()
        self.running = False


    def beat(self):
        """Called every WS tick"""
        self.last_beat = time.time()


    def start(self):
        """Start background thread"""
        if self.running:
            return

        self.running = True

        threading.Thread(target=self._loop, daemon=True).start()


    def _loop(self):
        """Detect death"""
        while self.running:
            if time.time() - self.last_beat > self.timeout:
                print("💔 HEARTBEAT LOST — WS dead")

                if callable(self.on_dead):
                    self.on_dead()

                self.last_beat = time.time()

            time.sleep(1)

