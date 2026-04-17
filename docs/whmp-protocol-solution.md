# ROK Title Injection - WHMP Protocol Notes

## Context

During title-bot work, the direct `SetTitle()` Lua path was not reliable on
every tested build for positive titles such as Duke, Justice, Architect and
Scientist. That pushed the investigation one layer down: instead of watching
the Lua handler alone, we also captured the network traffic produced by a
manual in-game title assignment.

This document records what was observed from that traffic and how the packet
generator in this repository was derived from it.

## Main finding

On the tested build, a successful positive-title assignment produced a small
packet framed with the ASCII magic `WHMP`. The payload looked like a compact,
protobuf-style message containing at least:

- the title type
- the target governor ID
- a short approval/container field that remained stable across captures

The important operational result was simple: a packet built to match the
captured shape could reproduce the same title assignment when sent through the
same authenticated game session.

## Packet shape observed

```
Header (16 bytes):
  Bytes 0-3:   "WHMP" magic (0x57 0x48 0x4d 0x50)
  Byte 4:      0x30
  Bytes 5-14:  10 zero bytes
  Byte 15:     payload length

Payload sample (13 bytes):
  0x08 0x06                          -> field 1, title type = 6 (Duke)
  0x3a 0x05 0x10 0xcb 0xfc 0xef 0x46 -> nested field containing governor ID 148635211
  0x12 0x02 0x08 0x17                -> short approval/container block

Full sample:
  57484d5030000000000000000000000d08063a0510cbfcef4612020817
```

## Interpretation used in the tooling

- The `WHMP` header is treated as a fixed frame prefix.
- The first payload field is treated as the positive-title type.
- The governor ID is encoded as a protobuf-style varint inside a nested field.
- The session appears to determine who is issuing the title; that information
  was not seen as an explicit receiver field in the captured packet.
- Across the title captures analysed for this path, the title type byte changed
  in the expected way for Justice, Duke, Architect and Scientist.

## Validation

The packet generator was validated against a manual Duke assignment captured on
the same build. Replaying the generated packet through the authenticated
session produced the expected result in-game.

That is strong enough to treat this as a working research path, but not strong
enough to treat the protocol as frozen. If the game updates, capture again and
re-verify before assuming offsets or field meanings are still correct.

## Files that implement this path

- `RESEARCH/frida/whmp_injector.py`
  Builds WHMP title packets from `title_type` and `governor_id`.
- `backend/title_service.py`
  Wraps packet selection and the backend-facing title assignment flow.
- `backend/title_injector.py`
  Small CLI entry point for listing titles, generating packets and testing the
  injection path.

## Title IDs used here

| ID | Title      |
|----|------------|
| 5  | Justice    |
| 6  | Duke       |
| 7  | Architect  |
| 8  | Scientist  |
| 9  | Traitor    |
| 10 | Beggar     |
| 11 | Exile      |
| 12 | Slave      |
| 13 | Sluggard   |

## Practical notes

- This path depends on a live authenticated game session.
- Title assignment traffic was observed in plaintext WHMP form on the tested
  socket, but that should be treated as an observation for one runtime path,
  not a blanket statement about all game networking.
- Rapid replay is a bad idea. Keep spacing between assignments conservative.
- The safer production path is still the one documented in the daemon/runtime
  docs. This packet work is here because it helped explain failures and gave us
  another verified injection route.

## Limitations

- Field names are inferred from captures and behaviour, not from official
  protocol definitions.
- The documented packet shape is tied to the tested game build.
- Manual validation covered a limited set of positive titles, not every title
  class exposed by the game.

## Minimal commands

```bash
python backend/title_injector.py list
python backend/title_injector.py packet duke
python RESEARCH/frida/whmp_injector.py
```
