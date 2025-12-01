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
        self._thread = None # Store thread reference for clean management

    def beat(self):
        """Called every WS tick (on_message, on_ping, on_pong)"""
        self.last_beat = time.time()


    def start(self):
        """Start background thread"""
        if self.running:
            return
        
        # Reset last_beat to current time when starting a new session
        self.last_beat = time.time()
        self.running = True

        self._thread =threading.Thread(target=self._loop, daemon=True).start()
        print("Heartbeat monitor started.")

    def _loop(self):
        """Detect death. Exits immediately on first detection."""
        while self.running:
            time_since_beat = time.time() - self.last_beat
            
            if time_since_beat > self.timeout:
                print(f"💔 HEARTBEAT LOST — WS dead ({time_since_beat:.1f}s no beat)")
                
                # CRITICAL FIX: Stop the monitor BEFORE calling on_dead
                self.running = False 
                
                if callable(self.on_dead):
                    self.on_dead()
                
                # Do NOT reset self.last_beat here. The loop must exit.
                return # Exit the thread loop immediately
            
            # Use a slightly smarter sleep based on remaining timeout
            sleep_time = max(1, self.timeout - time_since_beat)
            time.sleep(min(sleep_time, 5)) # Don't sleep more than 5 seconds at a time

        print("Heartbeat loop finished.")

    def stop(self):
        """Stop the background thread gracefully."""
        if self.running:
            self.running = False
            # Wait briefly for the thread to exit to ensure a clean state
            if self._thread and self._thread.is_alive():
                 self._thread.join(timeout=1)
            self._thread = None
            print("Heartbeat monitor stopped.") # print("Heartbeat monitor stopped.") # Removed print for cleaner logs

    def on_dead(self):
        if self.ws.health_state == "BAD":
            return
        self.ws.mark_dead()
        self.ws.reconnect()
        