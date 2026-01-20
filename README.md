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

### Software Requirements

| Software | Version | Download | Notes |
|----------|---------|----------|-------|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) | Check "Add to PATH" during install |
| Node.js | 20 LTS+ | [nodejs.org](https://nodejs.org/) | LTS version recommended |
| Git | Latest | [git-scm.com](https://git-scm.com/download/win) | |
| Tesseract OCR | 5.x | [See below](#tesseract-ocr-installation) | Required for scanner |
| BlueStacks | 5.x | [bluestacks.com](https://www.bluestacks.com/) | Required for scanner |

### Tesseract OCR Installation

The scanner requires Tesseract OCR to read text from the game.

**Windows:**

1. Download installer from: https://github.com/UB-Mannheim/tesseract/wiki
   - Direct link: [tesseract-ocr-w64-setup-5.3.3.exe](https://github.com/UB-Mannheim/tesseract/releases)
2. Run the installer
3. **IMPORTANT**: Check "Add to PATH" during installation
4. Default install path: `C:\Program Files\Tesseract-OCR`
5. Verify installation:
   ```powershell
   tesseract --version
   ```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-eng
```

**macOS:**
```bash
brew install tesseract
```

### ADB Setup (For Scanner)

The scanner needs ADB to communicate with BlueStacks.

1. Download [Platform Tools](https://developer.android.com/tools/releases/platform-tools)
2. Extract the ZIP file
3. Copy `platform-tools` folder to: `RokTracker/deps/platform-tools/`
4. Enable ADB in BlueStacks: Settings > Advanced > Android Debug Bridge

**Verify ADB works:**
```powershell
cd RokTracker\deps\platform-tools
.\adb.exe devices
```

---

## Installation

### Step 1: Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/rok-stats-hub.git
cd rok-stats-hub
```

### Step 2: Backend Setup

```powershell
cd backend

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.\.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create config file
copy .env.example .env
```

**Edit `backend/.env`:**
```env
DATABASE_URL=sqlite:///./rokstats.db
SECRET_KEY=generate-a-random-32-char-string-here
INGEST_TOKEN=generate-another-random-string-here
```

Generate random keys:
```python
python -c "import secrets; print(secrets.token_hex(32))"
```

**Initialize database and start:**
```powershell
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Backend runs at: http://localhost:8000

### Step 3: Frontend Setup

Open a new terminal:

```powershell
cd frontend-next

# Install dependencies
npm install

# Create config file
copy .env.example .env.local

# Start development server
npm run dev
```

Frontend runs at: http://localhost:3000

### Step 4: Create Admin Account

1. Open http://localhost:3000/admin
2. Create an admin account
3. Go to Admin Dashboard
4. Create your kingdom (enter kingdom number)

### Step 5: Scanner Setup (Optional)

```powershell
cd RokTracker

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements_win64.txt

# Create config files
copy api_config.example.json api_config.json
copy bot_config.example.json bot_config.json
```

**Edit `RokTracker/api_config.json`:**
```json
{
  "api_url": "http://localhost:8000/api",
  "kingdom_numbers": [YOUR_KINGDOM_NUMBER],
  "primary_kingdom": YOUR_KINGDOM_NUMBER,
  "auto_upload": true
}
```

**Setup external dependencies:**
- See `RokTracker/deps/README.md` for ADB and Tesseract data setup

---

## Project Structure

```
rok-stats-hub/
├── backend/                 # FastAPI backend (Python)
│   ├── app/                 # Application code
│   │   ├── main.py          # API routes
│   │   ├── models.py        # Database models
│   │   ├── schemas.py       # Data validation
│   │   └── auth.py          # Authentication
│   ├── alembic/             # Database migrations
│   ├── .env.example         # Config template
│   └── requirements.txt     # Python dependencies
│
├── frontend-next/           # Next.js dashboard
│   ├── app/                 # Pages (App Router)
│   ├── components/          # React components
│   ├── lib/                 # Utilities
│   └── .env.example         # Config template
│
├── RokTracker/              # Scanner & Title Bot
│   ├── kingdom_scanner_*.py # Kingdom scanners
│   ├── title_bot.py         # Title bot
│   ├── roktracker/          # Core scanner module
│   ├── deps/                # External dependencies
│   │   ├── platform-tools/  # ADB (download required)
│   │   └── tessdata/        # OCR data (optional)
│   ├── api_config.example.json
│   └── requirements_win64.txt
│
├── scripts/                 # Deployment scripts
├── SETUP.bat                # Windows auto-setup
└── START-DEV.bat            # Start all services
```

---

## Configuration Reference

### Backend Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| DATABASE_URL | Database connection | `sqlite:///./rokstats.db` |
| SECRET_KEY | JWT signing key (32+ chars) | `your-random-secret` |
| INGEST_TOKEN | Scanner auth token | `your-ingest-token` |
| HOST | Server host | `0.0.0.0` |
| PORT | Server port | `8000` |

### Frontend Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| NEXT_PUBLIC_API_URL | Backend API URL | `http://localhost:8000` |

### Scanner Configuration (api_config.json)

| Field | Description |
|-------|-------------|
| api_url | Backend API endpoint |
| kingdom_numbers | List of kingdom numbers to track |
| primary_kingdom | Main kingdom for reports |
| auto_upload | Auto-upload scans to API |

---

## Usage

### Running the Dashboard

**Quick start (Windows):**
```powershell
.\START-DEV.bat
```

**Manual start:**
```powershell
# Terminal 1 - Backend
cd backend
.\.venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 - Frontend
cd frontend-next
npm run dev
```

### Running the Scanner

1. Open BlueStacks with Rise of Kingdoms
2. Navigate to kingdom rankings screen
3. Run scanner:
   ```powershell
   cd RokTracker
   .\venv\Scripts\activate
   python kingdom_scanner_console.py
   ```
4. Follow on-screen instructions

### Running the Title Bot

1. Open BlueStacks with Rise of Kingdoms
2. Ensure your account has title permissions
3. Run bot:
   ```powershell
   cd RokTracker
   .\venv\Scripts\activate
   python title_bot.py
   ```
4. Players request titles via alliance chat

---

## API Documentation

When backend is running:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /kingdoms | List all kingdoms |
| GET | /kingdoms/{id}/summary | Kingdom overview |
| GET | /kingdoms/{id}/top-power | Power rankings |
| GET | /kingdoms/{id}/dkp | DKP rankings |
| GET | /governors/{id} | Governor profile |
| POST | /ingest/roktracker | Upload scan data |

---

## Troubleshooting

### Tesseract not found

- Ensure Tesseract is installed
- Check it's in PATH: `tesseract --version`
- Restart terminal after installation

### ADB not found / Cannot connect to BlueStacks

1. Download platform-tools and extract to `RokTracker/deps/platform-tools/`
2. Enable ADB in BlueStacks (Settings > Advanced)
3. Connect manually: `.\deps\platform-tools\adb.exe connect localhost:5555`

### Scanner not detecting game window

- Ensure BlueStacks window is visible (not minimized)
- Try running as Administrator
- Check correct BlueStacks instance name in config

### Database locked error

- Only run one backend instance at a time
- For production, use PostgreSQL instead of SQLite

### Module not found errors

- Ensure virtual environment is activated
- Run `pip install -r requirements.txt` again

---

## Production Deployment

See [DEPLOY-GUIDE.md](DEPLOY-GUIDE.md) for production deployment instructions.

**Quick Docker deployment:**
```bash
docker-compose up -d
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

---

## Disclaimer

This project is for educational purposes. Use of automated tools in Rise of Kingdoms may violate the game's Terms of Service. Use at your own risk. The authors are not responsible for any consequences including account bans.

---

## License

MIT License - See [LICENSE](LICENSE)
