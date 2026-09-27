"""
phase1_no_protection.py

A naive "create order" endpoint with no idempotency protection.
A client timeout + retry creates duplicate rows.

Run with:
    uvicorn phase1_no_protection:app --port 8000
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


# Create orders table on startup
conn = get_conn()
cur = conn.cursor()
cur.execute("DROP TABLE IF EXISTS orders;")
cur.execute("""
    CREATE TABLE orders (
        id           SERIAL PRIMARY KEY,
        client_id    TEXT NOT NULL,
        product      TEXT NOT NULL,
        amount       NUMERIC NOT NULL,
        created_at   TIMESTAMPTZ DEFAULT now()
    );
""")
conn.commit()
cur.close()
conn.close()
print("orders table created (no protection).")


class OrderRequest(BaseModel):
    client_id: str
    product: str
    amount: float


@app.post("/orders")
def create_order(req: OrderRequest):
    # Simulate server-side processing delay (e.g. payment gateway call)
    # This is what causes the client to time out and retry
    time.sleep(2)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO orders (client_id, product, amount) VALUES (%s, %s, %s) RETURNING id",
        (req.client_id, req.product, req.amount)
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
    cur.execute("SELECT COUNT(*), client_id, product FROM orders GROUP BY client_id, product")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"rows": [{"count": r[0], "client_id": r[1], "product": r[2]} for r in rows]}
