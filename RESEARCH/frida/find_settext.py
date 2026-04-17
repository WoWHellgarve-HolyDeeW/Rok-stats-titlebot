"""Find the class names for each set_text(string) method in dump.cs"""
import re

with open("RESEARCH/Il2CppDumper/dump.cs", "r", encoding="utf-8") as f:
    lines = f.readlines()

current_class = ""
results = []

for i, line in enumerate(lines):
    # Track current class
    cm = re.search(r'(?:public|private|internal|protected)\s+(?:sealed\s+|static\s+|abstract\s+)*(?:class|struct)\s+(\S+)', line)
    if cm:
        current_class = cm.group(1)
    
    # Find set_text(string ...) methods
    if 'set_text(string' in line or 'set_Text(string' in line:
        # Get the RVA comment from previous lines
        rva = ""
        for j in range(max(0,i-3), i):
            rm = re.search(r'RVA:\s*(0x[\dA-Fa-f]+)', lines[j])
            if rm:
                rva = rm.group(1)
        results.append((current_class, rva, line.strip()))

print(f"Found {len(results)} set_text/set_Text methods:\n")
for cls, rva, decl in results:
    print(f"  Class: {cls:40s} RVA: {rva:12s} | {decl[:80]}")

# Also find Lua_UnityEngine_UI_Text class methods
print("\n\n=== Lua_UnityEngine_UI_Text methods ===")
in_lua_text = False
for i, line in enumerate(lines):
    if 'class Lua_UnityEngine_UI_Text' in line:
        in_lua_text = True
        print(f"  [line {i+1}] {line.rstrip()}")
        continue
    if in_lua_text:
        if line.strip().startswith('}') and not line.strip().startswith('{ }'):
            break
        if 'RVA:' in line or 'static' in line or 'void' in line or 'int' in line:
            print(f"  [line {i+1}] {line.rstrip()}")
