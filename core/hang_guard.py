# core/silenthang.py (or wherever SilentHangGuard is defined)
import time
import threading

class SilentHangGuard:

    def __init__(self, timeout=20, on_hang=None):
        self.timeout = timeout
        self.on_hang = on_hang
        self.last_msg = time.time()
        self.running = False
        self._thread = None # Store thread reference

    def mark(self):
        """call this INSIDE on_message()"""
        self.last_msg = time.time()

    def start(self):
        """Start background thread."""
        if self.running:
            return
        
        self.last_msg = time.time() # Reset timer on start
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # print("Silent Hang Guard started.")

    def stop(self):
        """CRITICAL: Stop the background thread gracefully."""
        if self.running:
            self.running = False
            # Wait briefly for the thread to exit
            if self._thread and self._thread.is_alive():
                 self._thread.join(timeout=1)
            self._thread = None
            # print("Silent Hang Guard stopped.")

    def _loop(self):
        """Detect hang. Exits immediately on first detection."""
        while self.running:
            delta = time.time() - self.last_msg

            if delta > self.timeout:
                print(f"\n🛑 WS SILENT HANG detected ({delta:.1f}s no message)")
                
                # CRITICAL FIX: Stop the monitor's loop immediately
                self.running = False 
                
                if self.on_hang:
                    self.on_hang()
                
                # Exit the thread loop immediately
                return 

            time.sleep(min(3, self.timeout - delta)) # Use a smarter sleep

    def on_hang(self):
        if self.ws.health_state == "BAD":
            return
        self.ws.mark_dead()
        self.ws.reconnect()
       