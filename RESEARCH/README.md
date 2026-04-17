# RoK Research Index

This directory contains the reverse-engineering and protocol-analysis material
that sits behind the main project. Some files are polished notes, others are
lab notebooks kept because they capture a useful dead end or a partial result.

## Where to start

If you only want the shortest route through the research material, start here:

1. `rok_protocol_analysis.md`
        Broad protocol and traffic notes.
2. `../docs/title-injection.md`
        The direct Lua title-assignment path.
3. `../docs/whmp-protocol-solution.md`
        Packet-level notes for the WHMP title path.
4. `frida/README.md`
        Frida runtime notes for the Android-side capture work.

## Useful scripts

- `rok_analyzer.py`
  Interactive helper that groups together several common research tasks.
- `analyze_payload.py`
  Small payload decoder for quick inspection of captured data.
- `setup_research.py`
  One-off setup helper used to bootstrap a local research environment.

## What the research established

- The game uses a custom LGIM-based networking layer in the paths examined.
- Windows cold-attach is substantially less stable than Android spawn mode.
- Some useful title-assignment work was easier to validate by observing the
  resulting network traffic than by relying only on Lua-layer hooks.
- Metadata and runtime state are often easier to inspect from a live process or
  Android environment than from static binaries alone.

## What this folder is not

- It is not a clean step-by-step tutorial.
- It is not a supported SDK.
- It is not guaranteed to stay aligned with the latest game build.

Treat it as research history with runnable helpers.

## Safety note

Using these tools against a live account is likely to violate the game's Terms
of Service. Work on throwaway accounts and isolated emulator instances only.
