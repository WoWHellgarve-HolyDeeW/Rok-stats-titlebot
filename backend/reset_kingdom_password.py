"""
Script para resetar a password de um kingdom.
Uso: python reset_kingdom_password.py <kingdom_number>
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import Kingdom
from app.auth import generate_password, hash_password

def reset_password(kingdom_number: int):
    db = SessionLocal()
    try:
        kingdom = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
        if not kingdom:
            print(f"[ERRO] Kingdom {kingdom_number} não encontrado!")
            return
        
        # Gerar nova password
        new_password = generate_password()
        kingdom.password_hash = hash_password(new_password)
        db.commit()
        
        print(f"")
        print(f"========================================")
        print(f"  Kingdom {kingdom_number} - Nova Password")
        print(f"========================================")
        print(f"")
        print(f"  Password: {new_password}")
        print(f"")
        print(f"  GUARDA ESTA PASSWORD!")
        print(f"========================================")
        print(f"")
        
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python reset_kingdom_password.py <kingdom_number>")
        print("Exemplo: python reset_kingdom_password.py 3167")
        sys.exit(1)
    
    try:
        kingdom_number = int(sys.argv[1])
        reset_password(kingdom_number)
    except ValueError:
        print("[ERRO] kingdom_number deve ser um número!")
        sys.exit(1)
