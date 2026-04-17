"""Quick test: verify find-player endpoints are registered."""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

out_file = r"c:\Users\nelso\Desktop\rok_stats_iara\_endpoint_check.txt"

with open(out_file, "w") as f:
    f.write("START\n")
    try:
        from app.main import app
        f.write("IMPORTED OK\n")
        routes = [(r.path, r.methods) for r in app.routes if hasattr(r, "path") and "find" in r.path]
        for path, methods in routes:
            f.write(f"  {methods} {path}\n")
        f.write(f"\nTotal find-player routes: {len(routes)}\n")
    except Exception as e:
        f.write(f"ERROR: {e}\n")
        traceback.print_exc(file=f)
