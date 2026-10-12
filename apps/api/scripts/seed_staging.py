"""Seed a staging database with synthetic access (OPERATOR USE ONLY).

Creates one synthetic firm, two verified users (owner + accountant, random
passwords printed ONCE to stdout — rotate after first login), and two synthetic
clients. Refuses production unconditionally. Never commit output. Never use real
names, customer data, or reusable passwords.

Usage (staging shell only):
    DATABASE_URL=postgresql+psycopg://... python apps/api/scripts/seed_staging.py
"""

import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_settings  # noqa: E402
from app.db import create_db_engine  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.store import Store, tables  # noqa: E402

settings = get_settings()
if settings.environment == "production":
    print("REFUSED: never seed production.", file=sys.stderr)
    sys.exit(2)

engine = create_db_engine(settings)
conn = engine.connect()
store = Store(conn, tables())
try:
    tenant = store.create_tenant("Staging Preview Firm")
    crew = []
    for role, label in (("owner", "owner"), ("accountant", "staff")):
        password = f"Staging-{secrets.token_urlsafe(18)}!"
        email = f"staging-{label}@example.com"
        user = store.create_user(email, hash_password(password))
        store.mark_verified(str(user["id"]))
        store.add_membership(str(tenant["id"]), str(user["id"]), role)
        store.audit("user.seeded", str(tenant["id"]), str(user["id"]), f"user:{user['id']}", "seed-script")
        crew.append((email, password, role))
    for name in ("Staging Client Alpha", "Staging Client Beta"):
        client = store.create_client(str(tenant["id"]), name, sector="Services")
        store.audit("client.seeded", str(tenant["id"]), None, f"client:{client['id']}", "seed-script")
    conn.commit()
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()

print("Staging seed complete. ROTATE THESE CREDENTIALS AFTER FIRST LOGIN:")
for email, password, role in crew:
    print(f"  {role}: {email} / {password}")
