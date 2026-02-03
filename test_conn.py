import psycopg2
import sys

try:
    print("Connecting to database at localhost:5433...", flush=True)
    conn = psycopg2.connect(
        host="localhost",
        port="5433",
        user="postgres",
        password="045050",
        dbname="postgres"
    )
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()
    print(f"? Connection successful!", flush=True)
    print(f"?? Database Version: {version[0]}", flush=True)
    cur.close()
    conn.close()
except Exception as e:
    print(f"? Connection failed: {e}", file=sys.stderr, flush=True)

