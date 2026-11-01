from pathlib import Path
root = Path(__file__).resolve().parent
src = root / "dist" / "FFXIVTextureBatchConverter.exe"
dst = root / "dist" / "FF14 Tex Converter.exe"
if not src.is_file():
    print("Missing:", src)
    raise SystemExit(1)
if dst.exists():
    dst.unlink()
src.replace(dst)
print("Final EXE:", dst)
