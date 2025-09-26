import websocket
import json
import threading
import requests
from urllib.parse import urlparse

class QuestradeStreamer:
    def __init__(self, access_token, api_server):
        self.access_token = access_token
        self.api_server = api_server
        self.ws = None
        self.thread = None
        self.connected = False
        
    def _on_open(self, ws):
        print("WebSocket connection opened.")
        # Send access token
        ws.send(self.access_token)
        
    def _on_message(self, ws, message):
        print("Received message:", message)
    
    def _on_error(self, ws, error):
        print("WebSocket error:", error)
    
    def _on_close(self, ws, close_status_code, close_msg):
        print("WebSocket connection closed:", close_status_code, close_msg)
    
    def get_stream_url(self, symbol_id) -> str:
        """
        Ask Questrade REST API for a streaming URL for given symbol.
        Returns a wss:// URL you can use with WebSocketApp.
        """
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
        if self.connected:
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
        self.connected = True
    
    def stop_stream(self):
        if self.ws:
            self.ws.close()
            self.ws = None
        self.connected = False
        print("WebSocket stream stopped.")
        