import time
import uuid
import requests
from urllib.parse import urlparse

class LoggedSession(requests.Session):
    def __init__(self, log, env: str, actor_id: str):
        super().__init__()
        self.log = log              # LogWriter instance
        self.env = env              # application environment (e.g., 'practice', 'live')
        self.actor_id = actor_id    # identifier for the actor (e.g., user or system component)
        
    def request(self, method, url, **kwargs):
        cid = str(uuid.uuid4())  # unique correlation ID for this request
        parsed = urlparse(url)
        path = parsed.path
        host = parsed.netloc
        headers = kwargs.get("headers", {})
        body = kwargs.get("json") or kwargs.get("data")
        
        start = time.time()
        self.log.log_req(
            method = method,
            url_path = path,
            host = host,
            headers = headers,
            body = body,
            cid = cid,
            env = self.env,
        )
        
        try:
            resp = super().request(method, url, **kwargs)
        except Exception as ex:
            ms = int((time.time() - start) * 1000)
            # Minimal connectivity/error logging
            self.log._write("conn.error", {"msg":str(ex)[:200], "ms": ms}, cid = cid)
            raise
        
        ms = int((time.time() - start) * 1000)
        klass = "success" if resp.ok else ("retryable" if resp.status_code >= 500 else "validation")
        self.log.log_resp(status=resp.status_code, ms = ms, cid = cid, klass = klass)
        return resp