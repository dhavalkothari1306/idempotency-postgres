"""
phase2_naive_check.py

"Idempotency" implemented as an application-level check-then-insert.
Sequential retries look fine. Concurrent retries still create duplicates
because the check and insert are two separate operations with no lock between them.

Run with:
    uvicorn phase2_naive_check:app --port 8000
"""

import time
from fastapi import FastAPI
from pydantic import BaseModel
import psycopg2

DB = dict(host="localhost", port=5432, dbname="benchdb",
          user="postgres", password="postgres")

app = FastAPI()


def get_conn():
    return psycopg2.connect(**DB)


conn = get_conn()
cur = conn.cursor()
cur.execute("DROP TABLE IF EXISTS orders_naive;")
cur.execute("""
    CREATE TABLE orders_naive (
        id              SERIAL PRIMARY KEY,
        idempotency_key TEXT NOT NULL,
        client_id       TEXT NOT NULL,
        product         TEXT NOT NULL,
        amount          NUMERIC NOT NULL,
        created_at      TIMESTAMPTZ DEFAULT now()
    );
""")
conn.commit()
cur.close()
conn.close()
print("orders_naive table created (check-then-insert, no unique constraint).")


class OrderRequest(BaseModel):
    idempotency_key: str
    client_id: str
    product: str
    amount: float


@app.post("/orders")
def create_order(req: OrderRequest):
    conn = get_conn()
    cur = conn.cursor()

    # Application-level check — LOOKS safe, but is not under concurrency.
    # Two requests with the same key can both pass this check before either
    # has committed the insert.
    cur.execute(
        "SELECT id FROM orders_naive WHERE idempotency_key = %s",
        (req.idempotency_key,)
    )
    existing = cur.fetchone()

    if existing:
        cur.close()
        conn.close()
        return {"order_id": existing[0], "status": "replayed"}

    # Simulate processing delay — gives concurrent retries time to
    # both pass the check above before either inserts
    time.sleep(2)

    cur.execute(
        "INSERT INTO orders_naive (idempotency_key, client_id, product, amount) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (req.idempotency_key, req.client_id, req.product, req.amount)
    )
    order_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"order_id": order_id, "status": "created"}


@app.get("/orders/count")
def count_orders():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), idempotency_key FROM orders_naive GROUP BY idempotency_key"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"rows": [{"count": r[0], "key": r[1]} for r in rows]}
