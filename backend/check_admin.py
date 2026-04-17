"""
Inspect or update an admin user.

Usage:
  python check_admin.py <username> [password] [--apply]
"""
import sys

from app.auth import hash_password
from app.database import SessionLocal
from app.models import AdminUser


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python check_admin.py <username> [password] [--apply]")
        return 1

    apply_changes = "--apply" in sys.argv[1:]
    args = [arg for arg in sys.argv[1:] if arg != "--apply"]
    username = args[0]
    password = args[1] if len(args) > 1 else None

    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter_by(username=username).first()
        print(f"Admin exists: {admin is not None}")
        if admin:
            print(f"Username: {admin.username}")
            print(f"Super admin: {bool(admin.is_super)}")
            print(f"Stored hash: {admin.password_hash}")

            if password:
                expected = hash_password(password)
                print(f"Password matches: {admin.password_hash == expected}")
                if apply_changes and admin.password_hash != expected:
                    admin.password_hash = expected
                    db.commit()
                    print("Password updated.")
            elif apply_changes:
                print("--apply requires a password.")
                return 1
            return 0

        if not password:
            print("Admin not found. Provide a password and --apply to create it.")
            return 1

        if not apply_changes:
            print("Admin not found. Re-run with --apply to create it.")
            return 1

        admin = AdminUser(
            username=username,
            password_hash=hash_password(password),
            is_super=True,
        )
        db.add(admin)
        db.commit()
        print("Admin created.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
