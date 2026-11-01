# FF14 Tex Converter — Copyright (C) 2026 MaellaKnows
# Licensed under the GNU General Public License v3.0; see LICENSE.
# Additional terms under GPLv3 §7 apply: see ADDITIONAL-TERMS.md
from pathlib import Path
root = Path(__file__).resolve().parent
src = root / "dist" / "FFXIVTextureBatchConverter.exe"
# 名字要和 GitHub Release 里的资源名一致，releases/latest/download/ 直链才不会断。
# 不用空格：GitHub 会把空格替换成点，直接用点更稳。
dst = root / "dist" / "FF14.Tex.Converter.exe"
if not src.is_file():
    print("Missing:", src)
    raise SystemExit(1)
if dst.exists():
    dst.unlink()
src.replace(dst)
print("Final EXE:", dst)
