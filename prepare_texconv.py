# -*- coding: utf-8 -*-
# FF14 Tex Converter — Copyright (C) 2026 MaellaKnows
# Licensed under the GNU General Public License v3.0; see LICENSE.
# Additional terms under GPLv3 §7 apply: see ADDITIONAL-TERMS.md
"""Download the official Microsoft DirectXTex texconv binary for packaging.

Sources, in order:
  1. GitHub Release (may2026 tag, the version this build was tested with)
  2. GitHub "latest" release
  3. NuGet package Microsoft.DirectXTex.Texconv (unzipped)
"""
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "tools" / "texconv.exe"

VERSION = "2026.5.8"
URLS = [
    "https://github.com/Microsoft/DirectXTex/releases/download/may2026/texconv.exe",
    "https://github.com/Microsoft/DirectXTex/releases/latest/download/texconv.exe",
    "https://www.nuget.org/api/v2/package/Microsoft.DirectXTex.Texconv/" + VERSION,
]


def download(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Miili-FFXIV-TEX-Converter-build"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    if OUT.exists() and OUT.stat().st_size > 100_000:
        print("[OK] texconv.exe already exists.")
        return 0

    print(f"[INFO] Downloading official Microsoft DirectXTex Texconv {VERSION}...")

    data = None
    last_error = None
    for url in URLS:
        try:
            print(f"[INFO] URL: {url}")
            data = download(url)
            if len(data) > 100_000:
                break
            last_error = "file too small"
            data = None
        except Exception as exc:
            last_error = exc
            print(f"[WARN] Download failed: {exc}")

    if data is None:
        print("[ERROR] Could not download texconv.exe.", file=sys.stderr)
        print("[ERROR] Please check your Internet connection and try again.", file=sys.stderr)
        if last_error:
            print(f"[ERROR] {last_error}", file=sys.stderr)
        return 2

    if data[:2] != b"MZ":
        # NuGet packages are zips; pull texconv.exe out of them.
        tmp = OUT.with_suffix(".nupkg")
        tmp.write_bytes(data)
        try:
            with zipfile.ZipFile(tmp) as z:
                names = [n for n in z.namelist() if n.lower().endswith("texconv.exe")]
                if not names:
                    print("[ERROR] No texconv.exe inside the downloaded package.", file=sys.stderr)
                    return 3
                names.sort(key=lambda n: (0 if "win-x64" in n.lower() else 1, len(n)))
                with z.open(names[0]) as src, open(OUT, "wb") as dst:
                    dst.write(src.read())
        finally:
            tmp.unlink(missing_ok=True)
    else:
        # 官方 Release 直接给裸 EXE，写盘后下面统一校验。
        OUT.write_bytes(data)

    if not OUT.is_file() or OUT.stat().st_size <= 100_000 or OUT.read_bytes()[:2] != b"MZ":
        print("[ERROR] Downloaded file is not a valid texconv.exe.", file=sys.stderr)
        return 3

    print(f"[OK] texconv.exe prepared: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
