# Dependencies Setup

This folder should contain external dependencies that cannot be installed via pip.

## Required Dependencies

### 1. Tesseract OCR Data Files (tessdata)

Download trained data files for OCR:

1. Go to: https://github.com/tesseract-ocr/tessdata
2. Download `eng.traineddata` (English)
3. Create folder: `deps/tessdata/`
4. Place the file inside: `deps/tessdata/eng.traineddata`

**Or copy from Tesseract installation:**
```
C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata
```

### 2. ADB (Android Debug Bridge)

Required for scanner to communicate with BlueStacks:

1. Download from: https://developer.android.com/tools/releases/platform-tools
2. Extract the ZIP file
3. Copy the `platform-tools` folder here: `deps/platform-tools/`

**Final structure:**
```
deps/
├── platform-tools/
│   ├── adb.exe
│   ├── fastboot.exe
│   └── ...
└── tessdata/
    └── eng.traineddata
```

### 3. Verify ADB Connection

After setup, test ADB:

```powershell
.\deps\platform-tools\adb.exe devices
```

If BlueStacks is running with ADB enabled, you should see it listed.

## BlueStacks ADB Setup

1. Open BlueStacks
2. Go to Settings > Advanced
3. Enable "Android Debug Bridge (ADB)"
4. Note the port number (default: 5555)

## Troubleshooting

**ADB not connecting:**
```powershell
.\deps\platform-tools\adb.exe connect localhost:5555
```

**Multiple emulators:**
Check which port your BlueStacks uses in Settings > Advanced
