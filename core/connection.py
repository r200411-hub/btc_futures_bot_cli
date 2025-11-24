import websocket
import json
import hmac, hashlib, time, threading
from core.hang_guard import SilentHangGuard
from core.adaptive_reconnect import AdaptiveReconnect

class DeltaExchangeWebSocket:

    def __init__(self, key, secret, callback):
        self.key = key
        self.secret = secret
        self.cb = callback
        self.ws = None

        self.active = False
        self.hang = None  # SilentHangGuard (injected later)
        self.reconnect_lock = threading.Lock() 

        self.last_reconnect = 0
        self.reconnect_attempts = 0
        self.reconnector = AdaptiveReconnect()  # uptime tracker module (optional)

    def connect(self):

        if self.active:
            print("⚠️ WS already running, skipping connect")
            return

        print("⏳ Connecting to Delta WebSocket…")

        self.active = True
        self._authed = False

        self.ws = websocket.WebSocketApp(
            "wss://socket.india.delta.exchange",
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error
        )
        

        # run in thread
        threading.Thread(
            target=lambda: self.ws.run_forever(ping_interval=10, ping_timeout=3),
            daemon=True
        ).start()


    def _on_open(self, ws):
        self.reconnector.on_connect()
        self.reconnect_attempts = 0
        print("🟢 WebSocket OPENED")

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
            "type":"subscribe",
            "payload":{
                "channels":[{"name":"v2/ticker","symbols":["BTCUSD"]}]
            }
        }))


    def _on_message(self, ws, message):
        if self.hang:
           self.hang.mark()


        try:
            data = json.loads(message)
            if (data.get("type") == "success") or (data.get("message") == "Authenticated"):
                if not getattr(self, "_authed", False):
                    print("AUTH SUCCESS")
                    self._authed = True

            # if data.get("type") == "success":
            #     print("AUTH SUCCESS")

            # elif data.get("message") == "Authenticated":
            #     print("AUTH SUCCESS")


            elif data.get("type") == "subscriptions":
                print("MARKET DATA CHANNELS ACTIVE")

            elif "mark_price" in data:
                price = float(data["mark_price"])
                self.cb(price, data)

        except:
            pass


    def _on_close(self, ws, *args):
        print("🔴 WS CLOSED")
        self.active = False
        avg_up = self.reconnector.on_disconnect()
        print(f"🔻 Avg uptime: {avg_up:.1f}s (quality={self.reconnector.get_quality_score()})")

    def _on_error(self, ws, err):
        print("❌ WS ERROR:", err)
        self.active = False


    def reconnect(self):

        with self.reconnect_lock:

            now = time.time()
            if now - self.last_reconnect < 3:
                print("⚠ reconnect suppressed")
                return
            
            self.last_reconnect = now
            self.reconnect_attempts += 1


            # 1) base adaptive delay
            q = self.reconnector.get_quality_score()
            if q == "excellent":
                delay = 2
            elif q == "good":
                delay = 5
            elif q == "poor":
                delay = 12
            else:
                delay = 30

            # 2) exponential backoff penalty
            penalty = min(2 ** self.reconnect_attempts, 30)

            delay += penalty

            print(f"🔄 RECONNECTING WS… delay {delay}s (attempt={self.reconnect_attempts}, quality={q})")


            try:
                if self.ws:
                    self.ws.close()
            except:
                pass

            self.active = False

            time.sleep(delay)
            self.connect()



