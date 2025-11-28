# core/executor_live.py
"""
Delta Exchange live executor (skeleton).

Notes:
 - This module uses REST endpoints for placing orders and managing positions.
 - You must fill/verify endpoints and request body according to Delta's real API docs.
 - This code demonstrates authenticated signing pattern and common operations.
 - It uses `requests`. Install: pip install requests
 - Use with caution on real funds. Test on a sandbox/testnet if available.

Interface:
  - open_position(side, price, size)
  - close_position(position_id_or_side, price, reason)
  - get_open_positions()
  - cancel_all()
"""

import time
import hmac
import hashlib
import json
import requests

class LiveExecutor:
    def __init__(self, settings):
        self.settings = settings
        self.api_key = settings.get("api_key")
        self.api_secret = settings.get("api_secret")
        self.base = settings.get("delta_rest_base", "https://api.delta.exchange")  # change to testnet if available
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "User-Agent": "btc-bot/1.0"})
        # NOTE: Do not enable live trading until you are 100% ready and using correct credentials/permissions.
        self.simulate = settings.get("simulate_live", True)  # safe default: simulate orders

    # ---- helper: signed request ----
    def _sign(self, method, path, body=""):
        """
        Delta typical signature: HMAC_SHA256(api_secret, method + timestamp + pathname + body)
        (adjust format per Delta docs if different)
        """
        ts = str(int(time.time() * 1000))
        payload = method.upper() + ts + path + (body or "")
        sig = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {
            "api-key": self.api_key,
            "timestamp": ts,
            "signature": sig
        }
        return headers

    # ---- rest helpers ----
    def _post(self, path, body):
        url = self.base + path
        body_s = json.dumps(body) if body is not None else ""
        headers = self._sign("POST", path, body_s)
        try:
            r = self.session.post(url, data=body_s, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print("❌ REST POST error:", e)
            return None

    def _get(self, path):
        url = self.base + path
        headers = self._sign("GET", path, "")
        try:
            r = self.session.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print("❌ REST GET error:", e)
            return None

    # ---- public actions (skeleton) ----
    def open_position(self, side, price, size=None, product_id=None):
        """Place a market/limit order. side: 'LONG' or 'SHORT' (map to buy/sell accordingly)"""
        size = size or self.settings.get("position_size", 0.01)
        # mapping to exchange: LONG -> buy, SHORT -> sell (confirm with Delta docs)
        side_map = {"LONG": "buy", "SHORT": "sell"}
        side_payload = side_map.get(side, side.lower())

        # For safety, if simulate==True we just print and return a simulated order
        if self.simulate:
            order = {
                "id": f"sim-{int(time.time()*1000)}",
                "side": side,
                "price": float(price),
                "size": float(size),
                "status": "OPEN",
                "simulated": True,
                "timestamp": time.time()
            }
            print(f"📈 [LIVE-SIM] OPEN {side} @ {price:.2f} size={size}")
            return order

        # Real request example (adjust endpoint/body per Delta API)
        # Example endpoint (PLACEHOLDER): /v3/orders
        body = {
            "symbol": "BTCUSD",          # adjust or pass product_id
            "side": side_payload,
            "type": "market",           # or "limit"
            "size": size,
            "price": price if price else None,
            "leverage": self.settings.get("leverage", 10)
        }

        resp = self._post("/v3/orders", body)
        if resp:
            print(f"📈 [LIVE] Order placed: {resp}")
        return resp

    def close_position(self, identifier=None, price=None, reason="MANUAL"):
        """
        Close a position. Implementation depends on how the exchange exposes positions.
        This is a skeleton: you may want to place a counter order or call a close-by-id endpoint.
        """
        if self.simulate:
            print(f"📉 [LIVE-SIM] CLOSE {identifier} @ {price:.2f} ({reason})")
            return {"simulated": True, "id": f"close-sim-{int(time.time()*1000)}"}

        # In real: either call cancel or place opposing order to flatten
        # Example (placeholder):
        resp = self._post("/v3/close_position", {"id": identifier, "price": price})
        return resp

    def get_open_positions(self):
        if self.simulate:
            return []
        return self._get("/v3/positions")

    def cancel_all(self):
        if self.simulate:
            print("⚠ [LIVE-SIM] cancel_all called")
            return True
        return self._post("/v3/cancel_all", {})

