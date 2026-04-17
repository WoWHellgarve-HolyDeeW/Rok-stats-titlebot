# Disclaimer

This project is published for **research, security study and educational
purposes** only.

## What this project does

- Performs runtime instrumentation of the Rise of Kingdoms game process via
  Frida (`libEngineDll.so` hooks, Lua VM probing, memory scanning).
- Decodes the game's custom WHMP network protocol.
- Extracts governor, alliance and chat data in real time.
- Drives title assignment through the game's own scripting entry points.

## Risks to you

- Running the Frida runtime against a live account is likely to violate the
  **Rise of Kingdoms Terms of Service** and may result in **account
  suspension, loss of progress, or permanent ban**.
- Some hooks bypass anti-cheat initialization (SIGILL handling, null-page
  mmap, CrashUtils neutralization). These are documented for research;
  using them on an account you care about is a bad idea.
- The `_il2cpp_dump/` directory contains extracted binaries and metadata
  owned by third parties. Redistributing them further may not be permitted
  in your jurisdiction.

## Recommendations

- **Only use throwaway accounts.**
- **Only use a dedicated emulator instance**, ideally in a VM.
- **Treat this repository as a white paper with runnable code**, not as a
  turn-key cheat.

## Legal position

- The authors make **no warranty** of fitness for any purpose.
- The authors are **not affiliated** with Lilith Games, Farlight, or any
  publisher of Rise of Kingdoms.
- By cloning, running or modifying this project you accept full
  responsibility for any consequences to your accounts, devices or network.

If you are a rights holder and want any asset removed, open an issue and it
will be removed in good faith.
