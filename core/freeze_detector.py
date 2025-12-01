import time, threading


class FreezeDetector:

    def __init__(self, timeout_seconds=30, on_freeze_callback=None):
        """
        timeout_seconds  = max allowed time without ticks
        callback         = function called when freeze happens
        """
        self.timeout = timeout_seconds
        self.last_tick = time.time()
        self.running = False
        self.on_freeze_callback = on_freeze_callback


    def tick(self):
        """call this on every incoming tick"""
        self.last_tick = time.time()


    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()


    def _loop(self):
        while self.running:

            delta = time.time() - self.last_tick

            if delta > self.timeout:
                print(f"\n❌ FREEZE DETECTED — No ticks for {delta:.1f}s")

                if self.on_freeze_callback:
                    self.on_freeze_callback()

                self.last_tick = time.time()

            time.sleep(3)
    
    def on_freeze(self):
        if self.ws.health_state == "BAD":
            return
        self.ws.mark_dead()
        self.ws.reconnect()

