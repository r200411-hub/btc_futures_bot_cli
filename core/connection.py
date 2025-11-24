import websocket
import json
import hmac, hashlib, time

class DeltaExchangeWebSocket:

    def __init__(self, key, secret, callback):
        self.key = key
        self.secret = secret
        self.cb = callback
        self.ws = None

    def connect(self):
        print("⏳ Connecting to Delta WebSocket…")
        self.ws = websocket.WebSocketApp(
            "wss://socket.india.delta.exchange",
            on_message=self._on_message,
            on_open=self._on_open
        )

        self.ws.run_forever()

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
        try:
            data = json.loads(message)
           # print("RAW:", message)
            if data.get("type") == "success":
               print("AUTH SUCCESS")
            if data.get("type") == "subscriptions":
               print("MARKET DATA CHANNELS ACTIVE")


            if "mark_price" in data:
                self.cb(float(data["mark_price"]),data)
        except:
            pass
