# RoK Stats - Next Research Steps

## Short version

The missing pieces in this project are still the same ones identified in the
larger research notes:

1. Windows anti-cheat blocks reliable Frida attach and long-lived runtime hooks.
2. The main game channel is a custom binary protocol that is not yet decoded
	 end to end.

That means the current stack is not "broken". It is already doing the part that
can be kept working with less churn: backend, queueing, OCR-assisted flows and
the dedicated title runtime.

## What commercial tools probably do

This section is inference, not confirmation.

- Use rooted Android devices or rooted emulators, where Frida and memory reads
	are easier to keep alive than on the Windows client.
- Maintain a more mature protocol decoder, or a private client path built on
	top of earlier reverse-engineering work.
- Correlate runtime state with their own backend instead of depending on OCR.

There is at least one useful observation behind that assumption: in testing and
community reports, title-related actions sometimes reveal data paths that are
hard to access from the normal OCR workflow.

## Practical priority

If more research time goes into this area, the next serious path should be
Android rather than another round of Windows cold-attach attempts.

Why:

- The repository already contains Android-side scripts worth testing.
- Windows has been the least stable environment for instrumentation.
- A rooted emulator gives a cleaner place to test SSL bypass, IL2CPP hooks and
	memory reads.

## Reasonable next tasks

1. Validate `frida_scripts/android_position_hook.js` on a rooted emulator.
2. Re-test HTTPS capture with SSL bypass and save a fresh packet set.
3. Compare Android captures with the existing WHMP notes and entity data.
4. Only revisit Windows when there is a specific function or packet path worth
	 reproducing there.

## Files most relevant to that work

- `RESEARCH/ANALYSIS_REPORT.md`
- `RESEARCH/QUICK_START.md`
- `RESEARCH/rok_protocol_analysis.md`
- `RESEARCH/docs/TECHNICAL_ANALYSIS.md`
- `frida_scripts/android_position_hook.js`
- `frida_scripts/android_discovery.js`
- `frida_scripts/rok_il2cpp_bridge.js`

## Cleanup already done

- Duplicate one-off scripts were reduced earlier in this branch.
- The public docs were rewritten to keep the open-source export more factual.
- The export pipeline already strips private deployment values and generated
	artifacts.

## Bottom line

The next credible jump in capability is more likely to come from rooted Android
instrumentation than from another round of Windows attach experiments.
