import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

database_url = os.getenv("DATABASE_URL")
db_url = database_url.replace("postgresql+psycopg2://", "postgresql://")

print("Reading SQL file...")
with open("sql/init.sql", "r") as file:
    sql = file.read()

print("Connecting to database...")
try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    print("✅ SQL script executed successfully!")
    cur.close()
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")