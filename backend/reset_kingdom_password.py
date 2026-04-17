"""
Script para resetar a password de um kingdom.
Uso: python reset_kingdom_password.py <kingdom_number> [new_password]
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import Kingdom
from app.auth import generate_password, hash_password

def reset_password(kingdom_number: int, new_password: str | None = None):
    db = SessionLocal()
    try:
        kingdom = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
        if not kingdom:
            print(f"[ERRO] Kingdom {kingdom_number} não encontrado!")
            return
        
        password_to_set = new_password or generate_password()
        kingdom.password_hash = hash_password(password_to_set)
        db.commit()
        
        print(f"")
        print(f"========================================")
        print(f"  Kingdom {kingdom_number} - Nova Password")
        print(f"========================================")
        print(f"")
        print(f"  Password: {password_to_set}")
        print(f"")
        print(f"  GUARDA ESTA PASSWORD!")
        print(f"========================================")
        print(f"")
        
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python reset_kingdom_password.py <kingdom_number> [new_password]")
        print("Exemplo: python reset_kingdom_password.py 0000")
        print("Exemplo: python reset_kingdom_password.py 0000 <new_password>")
        sys.exit(1)
    
    try:
        kingdom_number = int(sys.argv[1])
        password_arg = sys.argv[2] if len(sys.argv) >= 3 else None
        reset_password(kingdom_number, password_arg)
    except ValueError:
        print("[ERRO] kingdom_number deve ser um número!")
        sys.exit(1)
