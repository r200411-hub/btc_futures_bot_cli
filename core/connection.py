# core/connection.py
import websocket
import json
import hmac
import hashlib
import time
import threading
from core.adaptive_reconnect import AdaptiveReconnect

# NOTE:
# - Guards (SilentHangGuard / FreezeDetector etc.) should *not* call .connect() or .close()
#   directly. They should set a health flag or call ws.mark_dead() and the main loop should
#   perform the actual reconnect by calling ws.reconnect().
#
# - Inject hang guard via: ws.hang = hang_instance  BEFORE calling ws.connect()


class DeltaExchangeWebSocket:
    def __init__(self, key, secret, callback):
        self.key = key
        self.secret = secret
        self.cb = callback          # user callback: cb(price, raw)
        self.ws = None
        self.thread = None

        self.active = False        # means "we think it's running"
        self._authed = False

        self.hang = None           # injected SilentHangGuard
        self.reconnect_lock = threading.Lock()

        self.last_reconnect = 0
        self.reconnect_attempts = 0
        # optional uptime tracker
        self.reconnector = AdaptiveReconnect() if hasattr(__import__('core'), 'adaptive_reconnect') else None

        # health flag set by guards to request reconnect by main loop
        self.health_state = "OK"   # "OK" | "BAD"

        # internal stop event for thread
        self._stop_event = threading.Event()

    # External helpers -----------------------------------------------------
    def mark_dead(self):
        """Quickly mark connection inactive (guards can call this)."""
        self.health_state = "BAD"
        self.active = False

    def is_running(self):
        return self.active and (self.thread is not None and self.thread.is_alive())

    # Run wrapper ----------------------------------------------------------
    def _run_ws(self):
        # keep_running is set by WebSocketApp; run_forever blocks until closed
        try:
            # run_forever will return when keep_running becomes False or an exception occurs
            self.ws.run_forever(ping_interval=10, ping_timeout=3)
        except Exception as e:
            print("WS thread crash:", e)
        finally:
            # ensure active state reflects reality
            self.active = False

    # Public API -----------------------------------------------------------
    def connect(self):
        """Start websocket in a background thread if not already active."""
        if self.active:
            print("⚠️ WS already running, skipping connect")
            return

        print("⏳ Connecting to Delta WebSocket…")
        self._stop_event.clear()
        self.active = True
        self._authed = False

        # build WebSocketApp with handlers
        self.ws = websocket.WebSocketApp(
            "wss://socket.india.delta.exchange",
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_ping=self._on_ping,
            on_pong=self._on_pong
        )

        # run in thread
        self.thread = threading.Thread(target=self._run_ws, daemon=True)
        self.thread.start()

    def close(self, join_timeout=5):
        """Gracefully stop the websocket thread and close resources."""
        try:
            # prefer to stop run_forever loop
            if self.ws:
                # this tells run_forever to exit
                try:
                    self.ws.keep_running = False
                except Exception:
                    pass

                # attempt to close socket if exists
                try:
                    if getattr(self.ws, "sock", None):
                        try:
                            self.ws.sock.shutdown(2)
                        except Exception:
                            pass
                        try:
                            self.ws.sock.close()
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    self.ws.close()
                except Exception:
                    pass

            # mark inactive
            self.active = False
            self._authed = False
            self.health_state = "BAD"

            # join thread if possible
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=join_timeout)
        except Exception as e:
            print("Exception during close():", e)
        finally:
            self.ws = None
            self.thread = None

    # WebSocket Handlers --------------------------------------------------
    def _on_open(self, ws):
        try:
            if self.reconnector:
                self.reconnector.on_connect()
            self.reconnect_attempts = 0
        except Exception:
            pass

        print("🟢 WebSocket OPENED")
        try:
            ts = str(int(time.time()))
            msg = "GET" + ts + "/live"
            sig = hmac.new(self.secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

            ws.send(json.dumps({
                "type": "auth",
                "payload": {
                    "api-key": self.key,
                    "signature": sig,
                    "timestamp": ts
                }
            }))

            ws.send(json.dumps({
                "type": "subscribe",
                "payload": {
                    "channels": [{"name": "v2/ticker", "symbols": ["BTCUSD"]}]
                }
            }))
        except Exception as e:
            print("⚠ _on_open send failed:", e)

    def _on_message(self, ws, message):
        # mark hang guard if present
        try:
            if self.hang:
                try:
                    self.hang.mark()
                except Exception as e:
                    # don't let hang guard errors bubble here
                    print("⚠ hang.mark() failed:", e)
        except Exception:
            pass

        # parse and dispatch safely
        try:
            data = json.loads(message)
        except Exception:
            return

        try:
            # Authentication events
            if (data.get("type") == "success") or (data.get("message") == "Authenticated"):
                if not getattr(self, "_authed", False):
                    print("AUTH SUCCESS")
                    self._authed = True
                # we keep processing in case data also contains mark_price

            # Subscription confirmed
            if data.get("type") == "subscriptions":
                print("MARKET DATA CHANNELS ACTIVE")

            # Ticker/mark price
            if "mark_price" in data:
                try:
                    price = float(data["mark_price"])
                except Exception:
                    return
                # protect callback from raising
                try:
                    self.cb(price, data)
                except Exception as e:
                    # user callback exceptions should not kill WS thread
                    print("⚠ callback raised:", e)
        except Exception as e:
            # catch-all for any unexpected structure
            print("⚠ _on_message processing error:", e)

    def _on_close(self, ws, *args):
        print("🔴 WS CLOSED")
        self.active = False
        try:
            if self.reconnector:
                avg_up = self.reconnector.on_disconnect()
                print(f"🔻 Avg uptime: {avg_up:.1f}s (quality={self.reconnector.get_quality_score()})")
        except Exception:
            pass

    def _on_error(self, ws, err):
        # websocket-client sometimes returns exception strings or Exception objects
        print("❌ WS ERROR:", err)
        self.active = False

    def _on_ping(self, ws, message):
        # optional hook for diagnostics
        # mark hang guard so ping/pong traffic is considered activity
        try:
            if self.hang:
                self.hang.mark()
        except Exception:
            pass

    def _on_pong(self, ws, message):
        try:
            if self.hang:
                self.hang.mark()
        except Exception:
            pass

    # Reconnect control ---------------------------------------------------
    def reconnect(self):
        """Close and re-connect with adaptive backoff. Thread-safe."""
        with self.reconnect_lock:
            now = time.time()
            if now - self.last_reconnect < 3:
                print("⚠ reconnect suppressed (recent)")
                return
            self.last_reconnect = now
            self.reconnect_attempts += 1

            # adapt base delay by quality (if reconnector present)
            try:
                q = self.reconnector.get_quality_score() if self.reconnector else "very_bad"
            except Exception:
                q = "very_bad"

            if q == "excellent":
                base = 2
            elif q == "good":
                base = 5
            elif q == "poor":
                base = 12
            else:
                base = 30

            penalty = min(2 ** self.reconnect_attempts, 30)
            delay = base + penalty
            print(f"🔄 RECONNECTING WS… delay {delay}s (attempt={self.reconnect_attempts}, quality={q})")

            # attempt graceful close
            try:
                if self.ws:
                    try:
                        self.ws.keep_running = False
                    except Exception:
                        pass
                    try:
                        if getattr(self.ws, "sock", None):
                            try:
                                self.ws.sock.shutdown(2)
                            except Exception:
                                pass
                            try:
                                self.ws.sock.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        self.ws.close()
                    except Exception:
                        pass
            except Exception:
                pass

            # clear internal handles
            self.ws = None
            self.thread = None
            self.active = False
            self._authed = False

            # wait and reconnect
            time.sleep(delay)
            # reset suppression guard when we actually start new connect
            try:
                self.connect()
            except Exception as e:
                print("⚠ reconnect connect() failed:", e)

