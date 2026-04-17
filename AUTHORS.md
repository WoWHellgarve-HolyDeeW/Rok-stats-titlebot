# Authors

This project is authored and maintained by **WoWHellgarve-HolyDeeW**.

- Project repository: https://github.com/WoWHellgarve-HolyDeeW/Rok-stats-titlebot
- Original work: 2025-2026
- Licensed under the GNU Affero General Public License v3.0 or later.

## Credits

Original author:

- **WoWHellgarve-HolyDeeW** - Reverse engineering, Frida runtime stack,
  chat relay, title injection via Lua, backend architecture, Next.js
  dashboard, research documentation.

Third-party components this project builds on:

- [Frida](https://frida.re/) - dynamic instrumentation toolkit.
- [Il2CppDumper](https://github.com/Perfare/Il2CppDumper) - inspiration
  for the `_il2cpp_dump/` pipeline.
- [RoKTracker](https://github.com/Cyrexxis/RoKTracker) - OCR scanner
  preserved under `RokTracker/` for reference.
- [FastAPI](https://fastapi.tiangolo.com/) and
  [Next.js](https://nextjs.org/) for the web stack.

## If you fork this project

You are encouraged to. The AGPL-3.0 license requires that you keep the
attribution in `backend/app/_attribution.py`, in this file, and in the
`LICENSE` header. Add your own name to the list above rather than
removing the existing one.
