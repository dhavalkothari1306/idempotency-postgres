"""
phase3_correct.py

Correct idempotency: a UNIQUE constraint on idempotency_key enforced by
the database. No check-then-insert. The INSERT itself either succeeds or
raises a unique-violation error, which is caught and used to replay the
stored response. Safe under any concurrency.

Run with:
    uvicorn phase3_correct:app --port 8000
"""

import time
from fastapi import FastAPI
from pydantic import BaseModel
import psycopg2
from psycopg2 import errors as pg_errors

DB = dict(host="localhost", port=5432, dbname="benchdb",
          user="postgres", password="postgres")

app = FastAPI()


def get_conn():
    return psycopg2.connect(**DB)


conn = get_conn()
cur = conn.cursor()
cur.execute("DROP TABLE IF EXISTS orders_safe;")
cur.execute("""
    CREATE TABLE orders_safe (
        id              SERIAL PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,  -- database enforces uniqueness
        client_id       TEXT NOT NULL,
        product         TEXT NOT NULL,
        amount          NUMERIC NOT NULL,
        response        JSONB,                 -- stored response for replay
        created_at      TIMESTAMPTZ DEFAULT now()
    );
""")
conn.commit()
cur.close()
conn.close()
print("orders_safe table created (UNIQUE constraint on idempotency_key).")


class OrderRequest(BaseModel):
    idempotency_key: str
    client_id: str
    product: str
    amount: float


@app.post("/orders")
def create_order(req: OrderRequest):
    conn = get_conn()
    cur = conn.cursor()

    time.sleep(2)  # simulate processing

    try:
        cur.execute(
            "INSERT INTO orders_safe (idempotency_key, client_id, product, amount, response) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (req.idempotency_key, req.client_id, req.product,
             req.amount, '{"status": "created"}')
        )
        order_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {"order_id": order_id, "status": "created"}

    except pg_errors.UniqueViolation:
        # Another request already committed this key — replay stored response
        conn.rollback()
        cur.execute(
            "SELECT id, response FROM orders_safe WHERE idempotency_key = %s",
            (req.idempotency_key,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return {"order_id": row[0], "status": "replayed (idempotent)"}


@app.get("/orders/count")
def count_orders():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*), idempotency_key FROM orders_safe GROUP BY idempotency_key"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"rows": [{"count": r[0], "key": r[1]} for r in rows]}
