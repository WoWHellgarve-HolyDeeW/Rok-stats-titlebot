"""
Script para diagnosticar problemas de password.
Uso: python check_password.py <kingdom_number> <password>
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, DATABASE_URL
from app.models import Kingdom
from app.auth import hash_password, SECRET_KEY

def check_password(kingdom_number: int, password: str):
    print(f"")
    print(f"========================================")
    print(f"  Diagnostico de Password")
    print(f"========================================")
    print(f"")
    print(f"  DATABASE_URL: {DATABASE_URL}")
    print(f"  SECRET_KEY: {SECRET_KEY[:20]}...")
    print(f"  Working Dir: {os.getcwd()}")
    print(f"")
    
    db = SessionLocal()
    try:
        kingdom = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
        if not kingdom:
            print(f"  [ERRO] Kingdom {kingdom_number} NAO EXISTE na base de dados!")
            print(f"")
            print(f"  Kingdoms existentes:")
            all_kd = db.query(Kingdom).all()
            for k in all_kd:
                print(f"    - Kingdom {k.number}: {k.name}")
            return
        
        print(f"  Kingdom encontrado: {kingdom.name}")
        print(f"")
        print(f"  Hash guardado: {kingdom.password_hash}")
        
        # Calcular hash da password fornecida
        computed_hash = hash_password(password)
        print(f"  Hash calculado: {computed_hash}")
        print(f"")
        
        if kingdom.password_hash == computed_hash:
            print(f"  [OK] PASSWORD CORRECTA!")
        else:
            print(f"  [ERRO] PASSWORD INCORRECTA!")
            print(f"")
            print(f"  Os hashes nao correspondem.")
            print(f"  Possivel causa: AUTH_SECRET_KEY diferente entre reset e servidor")
        
        print(f"")
        print(f"========================================")
        
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python check_password.py <kingdom_number> <password>")
        print("Exemplo: python check_password.py 3167 YD4t12geTy-Q9l2p")
        sys.exit(1)
    
    try:
        kingdom_number = int(sys.argv[1])
        password = sys.argv[2]
        check_password(kingdom_number, password)
    except ValueError:
        print("[ERRO] kingdom_number deve ser um numero!")
        sys.exit(1)
