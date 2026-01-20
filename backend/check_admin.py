from app.database import SessionLocal
from app.models import AdminUser
from app.auth import hash_password

db = SessionLocal()
admin = db.query(AdminUser).filter_by(username="holy").first()

print(f"Admin exists: {admin is not None}")
if admin:
    print(f"Stored hash: {admin.password_hash}")
    expected = hash_password("holyhola")
    print(f"Expected hash: {expected}")
    print(f"Match: {admin.password_hash == expected}")
    
    # If not matching, let's fix it
    if admin.password_hash != expected:
        print("\n⚠️ Hashes don't match! Updating...")
        admin.password_hash = expected
        db.commit()
        print("✅ Password updated!")
else:
    print("Creating admin...")
    admin = AdminUser(
        username="holy",
        password_hash=hash_password("holyhola"),
        is_super=True
    )
    db.add(admin)
    db.commit()
    print("✅ Admin created!")

db.close()
