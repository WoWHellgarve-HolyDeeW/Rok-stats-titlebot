"""
Quick Test Suite — Verify all major endpoints are responding.
Run from backend dir with venv active:
    python quick_test.py <kingdom> <password> [api_url]

Or set:
    ROK_TEST_KINGDOM
    ROK_TEST_PASSWORD
    ROK_TEST_API_URL
    ROK_TEST_INTERNAL_API_KEY
"""
import os
import sys
import requests

PASS = 0
FAIL = 0


def load_settings():
    api = os.getenv("ROK_TEST_API_URL", "http://localhost:8000")
    kingdom = os.getenv("ROK_TEST_KINGDOM")
    password = os.getenv("ROK_TEST_PASSWORD")

    if len(sys.argv) >= 3:
        kingdom = sys.argv[1]
        password = sys.argv[2]
    if len(sys.argv) >= 4:
        api = sys.argv[3]

    if not kingdom or not password:
        print("Usage: python quick_test.py <kingdom> <password> [api_url]")
        print("Or set ROK_TEST_KINGDOM and ROK_TEST_PASSWORD in the environment.")
        sys.exit(1)

    internal_api_key = (
        os.getenv("ROK_TEST_INTERNAL_API_KEY")
        or os.getenv("INTERNAL_API_KEY")
        or ""
    )
    return api, int(kingdom), password, internal_api_key


def test(name, method, url, expected_status=200, json_body=None, token=None):
    global PASS, FAIL
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=10)
        else:
            r = requests.post(url, json=json_body, headers=headers, timeout=10)
        ok = r.status_code == expected_status
        if ok:
            PASS += 1
            print(f"  [OK]   {name}  ({r.status_code})")
        else:
            FAIL += 1
            detail = r.text[:100] if r.text else ""
            print(f"  [FAIL] {name}  (got {r.status_code}, expected {expected_status})  {detail}")
        return r.json() if r.status_code < 500 and r.text else {}
    except requests.exceptions.ConnectionError:
        FAIL += 1
        print(f"  [FAIL] {name}  (connection refused)")
        return {}
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {name}  ({e})")
        return {}


print()
print("=" * 60)
print("  RoK Stats — Quick Test Suite")
print("=" * 60)
print()

API, KD, PASSWORD, INTERNAL_API_KEY = load_settings()

# 1. Health check
print("--- Auth & Health ---")
test("Root (404 expected)", "GET", f"{API}/", 404)
data = test("Login", "POST", f"{API}/auth/login", 200, {"kingdom": KD, "password": PASSWORD})
token = data.get("access_token", "")
if not token:
    print("  [FATAL] No token — aborting remaining tests")
    sys.exit(1)

# 2. Kingdom endpoints
print()
print("--- Kingdom Data ---")
test("Kingdom summary", "GET", f"{API}/kingdoms/{KD}/summary", token=token)
test("Alliances", "GET", f"{API}/kingdoms/{KD}/alliances", token=token)
test("Governors", "GET", f"{API}/kingdoms/{KD}/governors", token=token)
test("Scans", "GET", f"{API}/kingdoms/{KD}/scans", token=token)

# 3. Live data endpoints (NEW)
print()
print("--- Live Data (Frida) ---")
act = test("Live Activity", "GET", f"{API}/kingdoms/{KD}/live/activity?minutes=60", token=token)
test("Live Chat Stats", "GET", f"{API}/kingdoms/{KD}/live/chat-stats?hours=24", token=token)
test("Live Sessions", "GET", f"{API}/kingdoms/{KD}/live/sessions", token=token)

if act:
    chats = len(act.get("chat_feed", []))
    session = act.get("active_session")
    stats = act.get("stats", {})
    print(f"  -> Chats: {chats}, Session: {'ACTIVE' if session else 'none'}, Players: {stats.get('unique_players', 0)}")

# 4. Title system
print()
print("--- Title System ---")
test("Title Queue", "GET", f"{API}/kingdoms/{KD}/titles/queue", token=token)
test("Title Stats", "GET", f"{API}/kingdoms/{KD}/titles/stats", token=token)
test("Title Settings", "GET", f"{API}/kingdoms/{KD}/titles/settings", token=token)

# 5. Ingest endpoint
print()
print("--- Ingest ---")
# NOTE: No INGEST_TOKEN set in dev → ingest is open (200)
test("Frida Ingest (open dev)", "POST", f"{API}/ingest/frida", 200,
     {"session_id": "test", "kingdom": KD, "chats": [], "players": [], "coords": []})
if INTERNAL_API_KEY:
    test("Frida Ingest (with token)", "POST", f"{API}/ingest/frida", 200,
        {"session_id": "test-suite", "kingdom": KD, "chats": [], "players": [], "coords": []},
        INTERNAL_API_KEY)
else:
    print("  [SKIP] Frida Ingest (with token)  no internal API key configured")

# Summary
print()
print("=" * 60)
print(f"  Results:  {PASS} passed, {FAIL} failed, {PASS+FAIL} total")
print("=" * 60)
print()

sys.exit(0 if FAIL == 0 else 1)
