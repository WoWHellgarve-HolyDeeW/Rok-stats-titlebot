#!/usr/bin/env python
"""
Import scans from the server filesystem.
This script calls the internal endpoint that doesn't require admin token.
Run this on the server after git pull to import new scans.
"""

import requests
import sys
import os

def main():
    # Default to localhost, but allow override via env var
    api_url = os.getenv("ROK_API_URL", "http://localhost:8000")
    internal_key = os.getenv("INTERNAL_API_KEY", "")
    
    print("=" * 50)
    print("  RoK Stats - Import Scans do Servidor")
    print("=" * 50)
    print()
    print(f"API: {api_url}")
    print()
    
    try:
        headers = {"Content-Type": "application/json"}
        if internal_key:
            headers["X-Internal-Key"] = internal_key
        
        resp = requests.post(
            f"{api_url}/internal/import-scans",
            headers=headers,
            timeout=120
        )
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✓ Pasta: {data.get('folder', 'N/A')}")
            print(f"✓ Total ficheiros: {data.get('total_files', 0)}")
            print(f"✓ Novos imports: {data.get('new_imports', 0)}")
            print(f"✓ Ignorados (já existem): {data.get('skipped', 0)}")
            print(f"✓ Erros: {data.get('errors', 0)}")
            print()
            
            if data.get('results'):
                print("Detalhes:")
                for r in data['results']:
                    status = r.get('status', 'unknown')
                    file = r.get('file', 'unknown')
                    if status == 'ok':
                        print(f"  ✓ {file} - {r.get('imported', 0)} records (kingdom {r.get('kingdom', '?')})")
                    elif status == 'skipped':
                        print(f"  - {file} - já importado")
                    else:
                        print(f"  ✗ {file} - {r.get('message', 'erro')}")
            
            return 0
        else:
            print(f"✗ Erro: {resp.status_code}")
            print(resp.text)
            return 1
            
    except requests.exceptions.ConnectionError:
        print("✗ Erro: Não foi possível conectar à API")
        print(f"  Verifica se o servidor está a correr em {api_url}")
        return 1
    except Exception as e:
        print(f"✗ Erro: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
