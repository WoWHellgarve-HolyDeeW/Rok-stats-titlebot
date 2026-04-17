# RoK Research - Quick Guide

## Current snapshot

**Last reviewed:** 21 Janeiro 2026

Working:

- memory scanner in `rok_service/quick_scan.py`
- full IL2CPP dump
- mapped function addresses for the Windows client

Still weak or blocked:

- stable Frida instrumentation on Windows
- direct packet capture on Windows

## Useful paths

```text
RESEARCH/
├── docs/
│   ├── TECHNICAL_ANALYSIS.md
│   └── QUICK_GUIDE.md
├── Il2CppDumper/
│   └── dump.cs
├── rok_service/
│   ├── quick_scan.py
│   ├── premium_analytics.py
│   ├── real_addresses.txt
│   └── *.js
└── tools/
```

## Useful commands

### Memory scan

```powershell
cd C:\Users\Administrador\Desktop\rok_stats_iara\RESEARCH\rok_service
python quick_scan.py
```

### Locate key classes in the dump

```powershell
Select-String -Path "Il2CppDumper\dump.cs" -Pattern "class.*LGIM|class.*EzLgim" | Select-Object -First 20
```

## Read first

- [TECHNICAL_ANALYSIS.md](./TECHNICAL_ANALYSIS.md)
- [real_addresses.txt](../rok_service/real_addresses.txt)
- [dump.cs](../Il2CppDumper/dump.cs)

## Best next step

If this line of research continues, the cleanest next environment is a rooted
Android emulator with Frida and a MITM setup. Windows remains useful for dump
analysis and breakpoint work, but it has not been the reliable path for live
instrumentation.
