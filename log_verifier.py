#!/usr/bin/env python3
"""
log_verifier.py

Scans a log directory, verifies every compressed log file (.log.gz)
and its corresponding anchor (.anchor.json) using HMAC-SHA256.
"""

import os
import json
import gzip
import hmac, hashlib
import sys

def verify_logs(base_dir, hmac_key: bytes, date_str: str):
    """
    Verify integrity of log file and anchor for a given date.
    """
    log_path = os.path.join(base_dir, f"{date_str}.log.gz")
    anchor_path = os.path.join(base_dir, f"{date_str}.anchor.json")

    if not os.path.exists(log_path):
        print(f"[WARN] No log file for {date_str}")
        return False
    if not os.path.exists(anchor_path):
        print(f"[WARN] No anchor file for {date_str}")
        return False

    prev_hash = None
    try:
        with gzip.open(log_path, "rt", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                entry = json.loads(line)

                # recompute canonical form without "h"
                canonical = json.dumps({k: entry[k] for k in entry if k != "h"},
                                       sort_keys=True, separators=(",", ":")).encode()
                recomputed = hashlib.sha256(canonical).hexdigest()

                if recomputed != entry["h"]:
                    print(f"[ERROR] Hash mismatch at line {i} in {date_str}")
                    return False

                # chain check
                if entry["ph"] is None:
                    if prev_hash is not None:
                        print(f"[INFO] Chain reset at line {i} in {date_str}")
                else:
                    if entry["ph"] != prev_hash:
                        print(f"[ERROR] Chain mismatch at line {i} in {date_str}")
                        return False

                prev_hash = entry["h"]
    except Exception as e:
        print(f"[ERROR] Could not read {log_path}: {e}")
        return False

    # verify anchor
    try:
        with open(anchor_path, "r", encoding="utf-8") as f:
            anchor = json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not read anchor {anchor_path}: {e}")
        return False

    sig = anchor.pop("sig", None)
    if sig is None:
        print(f"[ERROR] Missing signature in anchor for {date_str}")
        return False

    # recompute signature exactly like LogWriter
    msg = json.dumps(anchor, sort_keys=True, separators=(",", ":")).encode()
    recomputed_sig = hmac.new(hmac_key, msg, hashlib.sha256).hexdigest()

    if sig != recomputed_sig:
        print(f"[ERROR] Anchor signature mismatch for {date_str}")
        print("---- Diagnostic ----")
        print("Canonical anchor message (signed):")
        print(msg.decode())
        print("Stored sig:", sig)
        print("Recomputed sig:", recomputed_sig)
        print("--------------------")
        return False

    if anchor.get("last_hash") != prev_hash:
        print(f"[ERROR] Anchor last_hash does not match final log entry for {date_str}")
        return False

    print(f"[OK] Verification successful for {date_str}")
    return True


def verify_all(base_dir, hmac_key: bytes):
    """
    Verify all logs in the base_dir.
    """
    dates = [fname.replace(".log.gz", "")
             for fname in os.listdir(base_dir)
             if fname.endswith(".log.gz")]

    if not dates:
        print("[INFO] No log files found.")
        return True

    dates.sort()
    success = True
    for date_str in dates:
        ok = verify_logs(base_dir, hmac_key, date_str)
        if not ok:
            success = False

    if success:
        print("[SUMMARY] All logs verified successfully.")
    else:
        print("[SUMMARY] Some logs failed verification.")

    return success


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python log_verifier.py <log_dir> <hmac_key>")
        sys.exit(1)

    base_dir = sys.argv[1]
    hmac_key = sys.argv[2].encode()

    all_ok = verify_all(base_dir, hmac_key)
    sys.exit(0 if all_ok else 1)