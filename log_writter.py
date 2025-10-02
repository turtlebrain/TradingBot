import os
import json
import hmac, hashlib
import uuid
import gzip
import datetime

class AuditWriter:
    def __init__(self, base_dir, hmac_key: bytes, app_env: str):
        self.base_dir = base_dir                # base directory to store audit files
        self.hmac_key = hmac_key                # HMAC key for signing anchors
        self.app_env = app_env                  # application environment (e.g., 'practice', 'live')
        self.sid = None                         # session ID
        self.prev_hash = None                   # previous hash for chaining
        self.fp = None                          # file pointer to current log file
        self.current_date = None                # current date for daily file management
        os.makedirs(base_dir, exist_ok=True)

    def _file_path(self, date_str):
        """
        Generate filename for a given date's log file.
        """
        return os.path.join(self.base_dir, f"{date_str}.log.gz")
    
    def _manifest_path(self, date_str):
        """
        Generate  filename for a given date's anchor file (signed summary)
        """
        return os.path.join(self.base_dir, f"{date_str}.anchor.json")
    
    def _now(self):
        """
        Get current UTC time.
        """
        return datetime.datetime.now(datetime.timezone.utc)
    
    def _date_str(self):
        """
        Get current date string in YYYY-MM-DD iso format.
        """
        return self._now().isoformat()
    
    def _open_today(self):
        """
        Open today's log file, creating a new one and resetting the hash chain if the date has changed 
        """
        date_str = self._date_str()
        if self.current_date == date_str and self.fp:
            return  # already opened for today
        self._close_with_anchor()  # close previous day's file with anchor
        path = self._file_path(date_str)
        self.fp = gzip.open(path, "ab")
        self.current_date = date_str
        self.prev_hash = None  # reset hash chain for new day
        
    def _close_with_anchor(self):
        """
        Close current log file and write an anchor file with summary and signature.
        """
        if not self.fp or not self.current_date:
            return  # nothing to close
        self.fp.flush()
        self.fp.close()
        self.fp = None
        # Create anchor file with summary
        anchor = {
            "date": self.current_date,
            "sid": self.sid,
            "last_hash": self.prev_hash,
            "env": self.app_env,
            "ts": self._now().isoformat()
        }
        msg = json.dumps(anchor, sort_keys = True, seperators=(",", ":")).encode()
        # signs the anchor with HMAC-SHA256 to prove file wasn't tampered
        sig = hmac.new(self.hmac_key, msg, hashlib.sha256).hexdigest()  
        anchor["sig"] = sig
        with open(self._manifest_path(self.current_date), "w", encoding = "utf-8") as mf:
            json.dump(anchor, mf, seperators=(",", ":" ))
        self.current_date = None
        
    def start_session(self):
        self.sid = str(uuid.uuid4())
        self._open_today()
        # Log "session.start" event
        self._write("session.start", {"env": self.app_env})
        
    def end_session(self):
        self._write("session.end", {})
        self._close_with_anchor()
            
    def _canonical(self, entry):
        """
        Creates a deterministic JSON string (keys sorted, no spaces) needed for consistent hashing
        """
        return json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    
    def _write(self, event_type, payload, cid=None):
        """
        Write a log entry with event type, payload, timestamp, session ID, and optional correlation ID.
        Each entry is chained with a SHA256 hash of the previous entry for integrity.
        """
        self._open_today()
        entry = {
            "ts": self._now().isoformat(),
            "e" : event_type,
            "sid": self.sid,
            "cid": cid,
            "p": payload if payload else None,
            "ph": self.prev_hash
        }
        canonical = self._canonical(entry)
        curr_hash = hashlib.sha256(canonical).hexdigest()
        entry["h"] = curr_hash
        self.prev_hash = curr_hash
        line = self._canonical(entry) + b"\n"
        self.fp.write(line)