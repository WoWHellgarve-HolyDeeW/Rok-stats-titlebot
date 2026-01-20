import pandas as pd
import requests
import re

csv_path = r'C:\Users\nelso\Desktop\rok_stats_iara\RokTracker\scans_kingdom\TOP300-2026-01-14-3167-[7912fy96].csv'

# Token from start_hub.bat - deixar None se backend foi iniciado sem token
INGEST_TOKEN = ""  # Tentar com string vazia

# Extract kingdom from filename
match = re.search(r'-(\d{4})-\[', csv_path)
kingdom = int(match.group(1)) if match else 3167
print(f'Kingdom: {kingdom}')

df = pd.read_csv(csv_path)
print(f'Records: {len(df)}')

def safe_int(val):
    if val in ['Skipped', 'Unknown', '', None] or pd.isna(val):
        return 0
    try:
        return int(str(val).replace(',', '').strip())
    except:
        return 0

records = []
for _, row in df.iterrows():
    records.append({
        'governor_id': safe_int(row.get('ID')),
        'governor_name': row.get('Name', 'Unknown'),
        'kingdom': kingdom,
        'power': safe_int(row.get('Power')),
        'kill_points': safe_int(row.get('Killpoints')),
        'alliance_name': row.get('Alliance'),
        't1_kills': safe_int(row.get('T1 Kills')),
        't2_kills': safe_int(row.get('T2 Kills')),
        't3_kills': safe_int(row.get('T3 Kills')),
        't4_kills': safe_int(row.get('T4 Kills')),
        't5_kills': safe_int(row.get('T5 Kills')),
        'dead': safe_int(row.get('Deads')),
        'rss_gathered': safe_int(row.get('Rss Gathered', 0)),
        'rss_assistance': safe_int(row.get('Rss Assistance', 0)),
        'helps': safe_int(row.get('Helps', 0)),
    })

print(f'First record: {records[0]}')

payload = {
    'scan_type': 'kingdom',
    'source_file': 'TOP300-2026-01-14-3167-[7912fy96].csv',
    'records': records
}

headers = {'x-api-key': INGEST_TOKEN} if INGEST_TOKEN else {}

print('Uploading...')
resp = requests.post('http://localhost:8000/ingest/roktracker', json=payload, headers=headers, timeout=60)
print(f'Response: {resp.status_code}')
print(resp.text[:500] if resp.text else 'No response body')
