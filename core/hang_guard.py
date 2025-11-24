import time, threading

class SilentHangGuard:

    def __init__(self, timeout=20, on_hang=None):
        self.timeout = timeout
        self.on_hang = on_hang
        self.last_msg = time.time()
        self.running = False

    def mark(self):
        """call this INSIDE on_message()"""
        self.last_msg = time.time()

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            delta = time.time() - self.last_msg

            if delta > self.timeout:
                print(f"\n🛑 WS SILENT HANG detected ({delta:.1f}s no message)")

                if self.on_hang:
                    self.on_hang()

                self.last_msg = time.time()

            time.sleep(3)
