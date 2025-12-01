# core/connection.py
import websocket
import json
import hmac
import hashlib
import time
import threading
from core.adaptive_reconnect import AdaptiveReconnect

class DeltaExchangeWebSocket:
    def __init__(self, key, secret, callback):
        self.key = key
        self.secret = secret
        self.cb = callback
        self.ws = None
        self.thread = None

        self.active = False
        self._authed = False

        self.hang = None
        self.reconnect_lock = threading.Lock()

        self.last_reconnect = 0
        self.reconnect_attempts = 0
        # optional list for debugging/tracking scheduled timers
        self.timers = []
        self.reconnector = AdaptiveReconnect() if hasattr(__import__('core'), 'adaptive_reconnect') else None

        self.health_state = "OK"   # "OK" | "BAD"

        self._stop_event = threading.Event()

        # Reconnect scheduling helpers
        self._reconnect_token = 0
        self._reconnect_timer = None

    def mark_dead(self):
        """Called by guards to indicate unhealthy connection."""
        self.health_state = "BAD"
        self.active = False

    def is_running(self):
        return self.active and (self.thread is not None and self.thread.is_alive())

    def _run_ws(self):
        try:
            # run_forever blocks until connection closes or keep_running = False
            self.ws.run_forever(ping_interval=10, ping_timeout=3)
        except Exception as e:
            print("WS thread crash:", e)
        finally:
            self.active = False

    def connect(self):
        """Start websocket in a background thread if not already active."""
        # IMPORTANT: if active True, don't start another connect
        if self.active:
            print("⚠️ WS already running, skipping connect")
            # also cancel any stale reconnect timers/tokens (defensive)
            self._cancel_pending_reconnect()
            return

        print("⏳ Connecting to Delta WebSocket…")
        self._stop_event.clear()
        self.active = True
        self._authed = False
        self.health_state = "OK"

        # cancel any scheduled reconnect because we're actively connecting now
        self._cancel_pending_reconnect()

        self.ws = websocket.WebSocketApp(
            "wss://socket.india.delta.exchange",
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_ping=self._on_ping,
            on_pong=self._on_pong
        )

        self.thread = threading.Thread(target=self._run_ws, daemon=True)
        self.thread.start()

    def close(self, join_timeout=5):
        """Gracefully stop the websocket thread and close resources."""
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

            self.active = False
            self._authed = False
            self.health_state = "BAD"

            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=join_timeout)
        except Exception as e:
            print("Exception during close():", e)
        finally:
            self.ws = None
            self.thread = None

    # ---------- websocket handlers ----------
    def _on_open(self, ws):
        # reset reconnect attempts and cancel pending timers — connection is live
        try:
            if self.reconnector:
                self.reconnector.on_connect()
        except Exception:
            pass

        # if a reconnect timer was pending, cancel/advance token so it won't fire later
        self._cancel_pending_reconnect()

        self.reconnect_attempts = 0
        self.health_state = "OK"
        self._authed = False

        print("🟢 WebSocket OPENED")
        try:
            ts = str(int(time.time()))
            msg = "GET" + ts + "/live"
            sig = hmac.new(self.secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

            try:
                # defensive send: wrap each send
                ws.send(json.dumps({
                    "type": "auth",
                    "payload": {
                        "api-key": self.key,
                        "signature": sig,
                        "timestamp": ts
                    }
                }))
            except Exception as e:
                print("⚠ socket not ready for send in _on_open():", e)

            try:
                ws.send(json.dumps({
                    "type": "subscribe",
                    "payload": {
                        "channels": [{"name": "v2/ticker", "symbols": ["BTCUSD"]}]
                    }
                }))
            except Exception as e:
                print("⚠ subscribe send failed in _on_open():", e)

        except Exception as e:
            print("⚠ _on_open send failed:", e)

    def _on_message(self, ws, message):
        try:
            if self.hang:
                try:
                    self.hang.mark()
                except Exception as e:
                    print("⚠ hang.mark() failed:", e)
        except Exception:
            pass

        try:
            data = json.loads(message)
        except Exception:
            return

        try:
            if (data.get("type") == "success") or (data.get("message") == "Authenticated"):
                if not getattr(self, "_authed", False):
                    print("AUTH SUCCESS")
                    self._authed = True

            if data.get("type") == "subscriptions":
                print("MARKET DATA CHANNELS ACTIVE")

            if "mark_price" in data:
                try:
                    price = float(data["mark_price"])
                except Exception:
                    return
                try:
                    self.cb(price, data)
                except Exception as e:
                    print("⚠ callback raised:", e)
        except Exception as e:
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
        print("❌ WS ERROR:", err)
        self.active = False

    def _on_ping(self, ws, message):
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

    # ---------- reconnect scheduling ----------
    def _cancel_pending_reconnect(self):
        """Cancel pending reconnect timer and bump token to invalidate scheduled tasks."""
        try:
            # increment token so any scheduled timer will be ignored
            self._reconnect_token += 1
            if self._reconnect_timer:
                try:
                    self._reconnect_timer.cancel()
                except Exception:
                    pass
                self._reconnect_timer = None

         # cancel older timers (bookkeeping)
            try:
                    for tt in list(self.timers):
                        try:
                            tt.cancel()
                        except:
                            pass
                    self.timers.clear()           
            except Exception:
                pass
        except Exception:
            pass

    def reconnect(self):
        """Schedule a reconnect with adaptive backoff. Non-blocking & cancellable."""
        with self.reconnect_lock:
            # If we already think the WS is active, ignore reconnect requests
            if self.active:
                # there may be races where thread exists but not fully usable; this is an optimization
                print("⚠ reconnect requested but connection already active — ignoring")
                return

            now = time.time()
            if now - self.last_reconnect < 3:
                print("⚠ reconnect suppressed (recent)")
                return
            self.last_reconnect = now
            self.reconnect_attempts += 1

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
            print(f"🔄 RECONNECTING WS… scheduling in {delay}s (attempt={self.reconnect_attempts}, quality={q})")

            # cancel previous scheduled reconnect (if any) and bump token
            self._reconnect_token += 1
            token = self._reconnect_token
            if self._reconnect_timer:
                try:
                    self._reconnect_timer.cancel()
                except Exception:
                    pass
                self._reconnect_timer = None

            # schedule a timer that will call _do_reconnect(token)
            t = threading.Timer(delay, lambda: self._do_reconnect(token))
            t.daemon = True
            self._reconnect_timer = t
            # bookkeeping
            try:
                self.timers.append(t)
            except Exception:
                pass
            t.start()

    def _do_reconnect(self, token):
        """Executed by Timer; will only run if token still current."""
        with self.reconnect_lock:
            if token != self._reconnect_token:
                # stale scheduled reconnect — ignore
                return

            # If active (some other code connected meanwhile) skip
            if self.active:
                # cancel pending and return
                self._cancel_pending_reconnect()
                print("🔁 Scheduled reconnect aborted — connection already active")
                return

            print("🔁 Performing scheduled reconnect now (token=%s)..." % token)

            # graceful close of previous ws if any
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

            # clear handles
            self.ws = None
            self.thread = None
            self.active = False
            self._authed = False

            # attempt to connect (will cancel stale timers inside connect())
            try:
                self.connect()
            except Exception as e:
                print("⚠ reconnect connect() failed:", e)
                # schedule another attempt with backoff
                self.reconnect()
