# RoK Stats Hub

A complete statistics dashboard and automation toolkit for Rise of Kingdoms.

## Features

**Dashboard & Statistics**
- Real-time kingdom rankings (Power, Kill Points, Deaths)
- Player profiles with historical stat charts
- Alliance rankings and member statistics
- Inactive player detection

**DKP System (KvK Performance Tracking)**
- Configurable KvK performance formula
- Power-tiered goals (different targets per power bracket)
- Formula: `(T4×2) + (T5×4) + (Dead×6) - (Power × coefficient)`
- Visual ranking with progress indicators

**Title Bot**
- Automated title management via in-game chat
- Queue system for title requests
- Real-time status tracking

**Scanner**
- OCR-based kingdom scanning
- Automatic data upload to dashboard
- Support for BlueStacks emulator

---

## Requirements

| Software | Version | Download |
|----------|---------|----------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 20 LTS+ | [nodejs.org](https://nodejs.org/) |
| Git | Latest | [git-scm.com](https://git-scm.com/download/win) |
| Tesseract OCR | 5.x | [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) |
| BlueStacks | 5.x | [bluestacks.com](https://www.bluestacks.com/) |

### Tesseract OCR Installation

**Windows:**
1. Download installer from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
2. Run the installer
3. Check "Add to PATH" during installation
4. Verify: `tesseract --version`

**Linux:**
```bash
sudo apt install tesseract-ocr tesseract-ocr-eng
```

**macOS:**
```bash
brew install tesseract
```

### ADB (Android Debug Bridge)

Download [platform-tools](https://developer.android.com/tools/releases/platform-tools) and extract to `RokTracker/deps/platform-tools/`

---

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/rok-stats-hub.git
cd rok-stats-hub
```

### 2. Setup Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate      # Windows
source .venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
copy .env.example .env        # Edit with your keys
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. Setup Frontend

```bash
cd frontend-next
npm install
copy .env.example .env.local
npm run dev
```

### 4. Create Admin Account

1. Open `http://localhost:3000/admin`
2. Create admin account
3. Create your kingdom

### 5. Setup Scanner (Optional)

```bash
cd RokTracker
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements_win64.txt
copy api_config.example.json api_config.json   # Edit with your kingdom
```

---

## Project Structure

```
rok-stats-hub/
├── backend/                 # FastAPI backend (Python)
│   ├── app/                 # Application code
│   ├── alembic/             # Database migrations
│   └── .env.example         # Environment template
│
├── frontend-next/           # Next.js dashboard (TypeScript)
│   ├── app/                 # Pages and routes
│   ├── components/          # React components
│   └── .env.example         # Environment template
│
├── RokTracker/              # OCR Scanner (Python)
│   ├── kingdom_scanner_*.py # Kingdom scanner
│   ├── title_bot.py         # Title bot
│   └── roktracker/          # Core scanner logic
│
└── scripts/                 # Deployment scripts
```

---

## Configuration

### Backend (.env)

```env
DATABASE_URL=sqlite:///./rokstats.db
SECRET_KEY=your-secret-key-min-32-characters
INGEST_TOKEN=your-scanner-token
```

Generate keys: `python -c "import secrets; print(secrets.token_hex(32))"`

### Frontend (.env.local)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Scanner (api_config.json)

```json
{
  "api_url": "http://localhost:8000/api",
  "kingdom_numbers": [1234],
  "primary_kingdom": 1234
}
```

---

## Usage

### Kingdom Scanner

```bash
cd RokTracker
.\venv\Scripts\activate
python kingdom_scanner_console.py
```

### Title Bot

```bash
cd RokTracker
.\venv\Scripts\activate
python title_bot.py
```

---

## Troubleshooting

**Tesseract not found** - Ensure it's installed and added to PATH

**ADB not found** - Extract platform-tools to `RokTracker/deps/platform-tools/`

**Cannot connect to BlueStacks** - Enable ADB in BlueStacks settings

**Database locked** - Only run one backend instance at a time

---

## API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Disclaimer

This project is for educational purposes. Use of automated tools in Rise of Kingdoms may violate the game's Terms of Service. Use at your own risk.

---

## License

MIT License - See [LICENSE](LICENSE)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
