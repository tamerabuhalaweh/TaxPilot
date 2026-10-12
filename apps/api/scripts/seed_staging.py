"""Seed a staging database with synthetic access (OPERATOR USE ONLY).

Creates one synthetic firm, two verified users (owner + accountant, random
passwords), and two synthetic clients. Refuses anything but staging. Refuses
reruns when seeded accounts already exist. Credentials are written ONLY to the
file named by SEED_OUT_FILE (created 0600); NOTHING secret is printed to stdout,
because hosting providers retain process logs.

Usage (staging shell only):
    ENVIRONMENT=staging DATABASE_URL=postgresql+psycopg://... \\
      SEED_OUT_FILE=/run/secrets/staging-seed.txt \\
      python apps/api/scripts/seed_staging.py
"""

import os
import secrets
import stat
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_settings  # noqa: E402
from app.db import create_db_engine  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.store import Store, tables  # noqa: E402

SEED_MARKER_DOMAIN = "example.com"
SEED_EMAILS = ("staging-owner@example.com", "staging-staff@example.com")


def fail(message: str) -> int:
    print(f"REFUSED: {message}", file=sys.stderr)
    return 2


def main() -> int:
    settings = get_settings()
    if settings.environment != "staging":
        return fail("this script runs only with ENVIRONMENT=staging (never production, never development).")
    out_path = os.environ.get("SEED_OUT_FILE", "")
    if not out_path:
        return fail("SEED_OUT_FILE must name the credential handoff file (passwords are never printed).")

    engine = create_db_engine(settings)
    conn = engine.connect()
    store = Store(conn, tables())
    try:
        for email in SEED_EMAILS:
            if store.get_user_by_email(email) is not None:
                return fail(f"seeded account already exists ({email}); reruns refused, rotate instead.")
    finally:
        conn.close()
    # Credential handoff FIRST (0600 file, never stdout): if the database
    # transaction below fails, the file is deleted — no orphaned secrets.
    crew = [
        (SEED_EMAILS[0], f"Staging-{secrets.token_urlsafe(18)}!", "owner"),
        (SEED_EMAILS[1], f"Staging-{secrets.token_urlsafe(18)}!", "accountant"),
    ]
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(out_path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("TaxPilot staging credentials — ROTATE AFTER FIRST LOGIN.\n")
            for email, password, role in crew:
                fh.write(f"{role}: {email} / {password}\n")
    except BaseException:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    try:
        mode = stat.S_IMODE(os.stat(out_path).st_mode)
        if os.name != "nt" and mode != 0o600:
            os.remove(out_path)
            return fail("credential file permissions could not be restricted to 0600.")
        if os.name == "nt":
            print(
                f"WARNING: Windows file modes do not enforce 0600; restrict {out_path} via ACLs manually.",
                file=sys.stderr,
            )
    except OSError as exc:
        return fail(f"could not verify credential file: {exc}")
    conn = engine.connect()
    store = Store(conn, tables())
    try:
        for email in SEED_EMAILS:
            if store.get_user_by_email(email) is not None:
                try:
                    os.remove(out_path)  # no orphaned secrets for accounts we did not create
                except OSError:
                    pass
                return fail(f"seeded account already exists ({email}); reruns refused, rotate instead.")
        tenant = store.create_tenant("Staging Preview Firm")
        for email, password, role in crew:
            user = store.create_user(email, hash_password(password))
            store.mark_verified(str(user["id"]))
            store.add_membership(str(tenant["id"]), str(user["id"]), role)
            store.audit(
                "user.seeded", str(tenant["id"]), str(user["id"]), f"user:{user['id']}", "seed-script"
            )
        for name in ("Staging Client Alpha", "Staging Client Beta"):
            client = store.create_client(str(tenant["id"]), name, sector="Services")
            store.audit("client.seeded", str(tenant["id"]), None, f"client:{client['id']}", "seed-script")
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise
    finally:
        conn.close()
    print("Staging seed complete for Staging Preview Firm.")
    print(f"Credentials written ONLY to {out_path}. Rotate after first login.")
    print("Seeded logins: staging-owner@example.com, staging-staff@example.com (passwords in file only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
