import websocket
import json
import threading
import requests
from urllib.parse import urlparse
import datetime
import queue

class QuestradeStreamer:
    def __init__(self, access_token: str, api_server: str, tick_queue: queue.Queue):
        self.access_token = access_token
        self.api_server = api_server
        self.symbol_id = None
        self.ws = None
        self.thread = None
        self.connected = False
        self.tick_queue = tick_queue    # shared queue
        
    def _on_open(self, ws):
        print("WebSocket connection opened.")
        ws.send(self.access_token)
        self.connected = True
        
        
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if "quotes" in data:
                for q in data["quotes"]:
                    ts = datetime.datetime.fromisoformat(q["lastTradeTime"].replace("Z", "+00:00"))
                    ts = ts.astimezone(datetime.timezone.utc)  # normalize to UTC
                    tick = {
                        "price": q["lastTradePrice"],
                        "volume": q.get("lastTradeSize", 0),
                        "timestamp": ts
                    }
                    self.tick_queue.put(tick)
        except Exception as e:
            print("Error processing message:", e)

    def _on_error(self, ws, error):
        print("WebSocket error:", error)
    
    def _on_close(self, ws, close_status_code, close_msg):
        print("WebSocket connection closed:", close_status_code, close_msg)
        self.connected = False
    
    def get_stream_url(self, symbol_id) -> str:
        """
        Ask Questrade REST API for a streaming URL for given symbol.
        Returns a wss:// URL you can use with WebSocketApp.
        """
        self.symbol_id = symbol_id
        url = f"{self.api_server}v1/markets/quotes"
        
        params = {
            "ids": symbol_id,
            "stream": "true",
            "mode": "WebSocket"
        }
        headers = {"Authorization": f"Bearer {self.access_token}"}

        resp = requests.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        port = data.get("streamPort", [])
        if not port:
            raise RuntimeError("No streaming servers returned")
        parsed = urlparse(self.api_server)
        stream_server = parsed.netloc
        stream_url = f"wss://{stream_server}:{port}"
        return stream_url
 
    
    def start_stream(self, symbol_id):
        if self.connected and self.symbol_id == symbol_id:
            print("WebSocket is already connected.")
            return
            
        stream_url = self.get_stream_url(symbol_id)
        self.ws = websocket.WebSocketApp(
            stream_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()
    
    def reconnect(self):
        """Reconnect using current symbol_id and new token"""
        if not self.symbol_id:
            return
        self.stop_stream()
        self.start_stream(self.symbol_id)
    
    def stop_stream(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                print("Error closing websocket:", e)
            self.ws = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None
        self.connected = False   
        print("WebSocket stream stopped.")
        