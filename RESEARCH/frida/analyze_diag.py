"""Analyze diag_chat_text.json to find message text field."""
import json

f = r'C:\Users\Administrador\Desktop\rok_stats_iara\RESEARCH\frida\captures\diag_chat_text.json'
d = json.load(open(f, 'r', encoding='utf-8'))

print("=== DIAGNOSTIC ANALYSIS ===")
print(f"chat_jsons: {len(d.get('chat_jsons', []))}")
print(f"contexts: {len(d.get('contexts', []))}")
print(f"setfields: {len(d.get('setfields', []))}")
print(f"getfields: {len(d.get('getfields', []))}")

# Show ALL keys from chat JSON
for i, cj in enumerate(d.get('chat_jsons', [])[:3]):
    s = cj.get('s', '')
    print(f"\n--- Chat JSON #{i} (len={len(s)}) ---")
    import re
    for m in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s):
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict) and 'chat_ext_user_nickname' in obj:
                print(f"ALL KEYS: {sorted(obj.keys())}")
                for k, v in sorted(obj.items()):
                    print(f"  {k}: {repr(v)[:120]}")
        except:
            pass

# Show context strings near chat
print("\n=== CONTEXT STRINGS NEAR CHAT ===")
for i, ctx in enumerate(d.get('contexts', [])[:5]):
    strs = ctx.get('strings', [])
    print(f"\n--- Context #{i}: {len(strs)} strings ---")
    for s in strs:
        text = s.get('s', '')
        src = s.get('src', '?')
        delta = ctx.get('ms', 0) - s.get('ms', 0)
        # Skip long JSONs and URLs
        if '{' in text and len(text) > 100:
            continue
        if 'http' in text:
            continue
        if len(text) > 200:
            continue
        print(f"  [{src}] -{delta}ms: {text[:150]}")

# Show setfield/getfield
print("\n=== SETFIELD near chat ===")
for sf in d.get('setfields', []):
    print(f"  {sf.get('field')} at ms={sf.get('ms')}")

print("\n=== GETFIELD near chat ===")
for gf in d.get('getfields', []):
    print(f"  {gf.get('field')} at ms={gf.get('ms')}")

# Show interesting fields
print(f"\n=== INTERESTING FIELDS: {len(d.get('interesting_fields', []))} ===")
for x in d.get('interesting_fields', []):
    print(f"  {x}")
