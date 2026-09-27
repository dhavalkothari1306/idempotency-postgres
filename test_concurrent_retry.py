"""
test_concurrent_retry.py

Fires N concurrent POST requests with the SAME idempotency key to simulate
a client timeout + simultaneous retry burst. Run this against each phase
to observe the difference in row counts.

Usage:
    # Against phase 1 (no protection):
    python test_concurrent_retry.py --concurrency 5

    # Against phase 2 (naive check) — should still show duplicates:
    python test_concurrent_retry.py --concurrency 5

    # Against phase 3 (correct fix) — should show exactly 1 row:
    python test_concurrent_retry.py --concurrency 5

After each run, check row count:
    curl http://localhost:8000/orders/count
"""

import argparse
import json
import urllib.request
import threading
import time

URL    = "http://localhost:8000/orders"
COUNT_URL = "http://localhost:8000/orders/count"

# All requests use the same idempotency key — simulating a retry burst
PAYLOAD = {
    "idempotency_key": "order-test-001",
    "client_id":       "user-42",
    "product":         "Pro Plan",
    "amount":          29.00
}

parser = argparse.ArgumentParser()
parser.add_argument("--concurrency", type=int, default=5,
                    help="Number of simultaneous requests (default: 5)")
args = parser.parse_args()

results = []
lock    = threading.Lock()


def send_request():
    data    = json.dumps(PAYLOAD).encode()
    req     = urllib.request.Request(
        URL, data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
            with lock:
                results.append({"status": "ok", "body": body})
    except Exception as e:
        with lock:
            results.append({"status": "error", "error": str(e)})


print(f"Firing {args.concurrency} concurrent requests with the same idempotency key...")
threads = [threading.Thread(target=send_request) for _ in range(args.concurrency)]

# Start all threads as close together as possible
for t in threads:
    t.start()
for t in threads:
    t.join()

print("\nResponses:")
for i, r in enumerate(results, 1):
    print(f"  Request {i}: {r}")

# Check row count
print("\nRow count after concurrent requests:")
try:
    with urllib.request.urlopen(COUNT_URL, timeout=10) as resp:
        count_data = json.loads(resp.read())
        print(f"  {json.dumps(count_data, indent=2)}")
        total = sum(r["count"] for r in count_data.get("rows", []))
        print(f"\nTotal rows for this key: {total}")
        if total == 1:
            print("CORRECT: exactly 1 row created despite concurrent retries.")
        else:
            print(f"BUG: {total} rows created — duplicate orders exist.")
except Exception as e:
    print(f"  Could not fetch count: {e}")
