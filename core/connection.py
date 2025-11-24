import websocket
import json
import hmac, hashlib, time, threading
from core.hang_guard import SilentHangGuard


class DeltaExchangeWebSocket:

    def __init__(self, key, secret, callback):
        self.key = key
        self.secret = secret
        self.cb = callback
        self.ws = None
        self.active = False
        self.hang = None


    def connect(self):

        if self.active:
            print("⚠️ WS already running, skipping connect")
            return

        print("⏳ Connecting to Delta WebSocket…")

        self.active = True

        self.ws = websocket.WebSocketApp(
            "wss://socket.india.delta.exchange",
            on_message=self._on_message,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error
        )
        

        # run in thread
        threading.Thread(
            target=lambda: self.ws.run_forever(ping_interval=10, ping_timeout=5),
            daemon=True
        ).start()


    def _on_open(self, ws):
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

    def _on_error(self, ws, err):
        print("❌ WS ERROR:", err)
        self.active = False


    def reconnect(self):
        print("🔄 RECONNECTING WS…")

        try:
            if self.ws:
                self.ws.close()
        except:
            pass

        self.active = False

        time.sleep(1)
        self.connect()
