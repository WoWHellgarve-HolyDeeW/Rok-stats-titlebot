"""
Script para testar o endpoint de login directamente.
Uso: python test_login.py <kingdom_number> <password>
"""
import sys
import os
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

def test_login(
    kingdom_number: int,
    password: str,
    api_url: str = "http://localhost:8000",
    host_header: Optional[str] = None,
):
    print(f"")
    print(f"========================================")
    print(f"  Teste de Login via API")
    print(f"========================================")
    print(f"")
    print(f"  API URL: {api_url}")
    print(f"  Kingdom: {kingdom_number}")
    print(f"  Password: {password}")
    print(f"")
    
    try:
        headers = {"Content-Type": "application/json"}
        if host_header:
            headers["Host"] = host_header
        response = requests.post(
            f"{api_url}/auth/login",
            json={"kingdom": kingdom_number, "password": password},
            headers=headers,
            timeout=10
        )
        
        print(f"  Status Code: {response.status_code}")
        print(f"  Response: {response.text}")
        print(f"")
        
        if response.status_code == 200:
            print(f"  [OK] LOGIN BEM SUCEDIDO!")
            data = response.json()
            print(f"  Token: {data.get('access_token', 'N/A')[:50]}...")
        else:
            print(f"  [ERRO] LOGIN FALHOU!")
            
    except requests.exceptions.ConnectionError as e:
        print(f"  [ERRO] Nao foi possivel conectar a {api_url}")
        print(f"  Detalhe: {e}")
    except Exception as e:
        print(f"  [ERRO] {type(e).__name__}: {e}")
    
    print(f"")
    print(f"========================================")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python test_login.py <kingdom_number> <password> [api_url]")
        print("Exemplo: python test_login.py 3167 YD4t12geTy-Q9l2p")
        print("Exemplo: python test_login.py 3167 YD4t12geTy-Q9l2p http://localhost:8000")
        print("Exemplo: python test_login.py 3167 YD4t12geTy-Q9l2p http://127.0.0.1/api rok.wowhellgarve.com")
        sys.exit(1)
    
    kingdom_number = int(sys.argv[1])
    password = sys.argv[2]
    api_url = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:8000"
    host_header = sys.argv[4] if len(sys.argv) > 4 else None
    
    test_login(kingdom_number, password, api_url, host_header)
