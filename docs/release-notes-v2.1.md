# FF14 Tex Converter v2.1 — 中英双语首发

**Batch PNG → TEX and TEX → TEX conversion for FINAL FANTASY XIV. One window, no plugin loader, no game injection.**

First public release. Drop your textures in, pick a format, done.

<!-- Optional banner — replace OWNER/REPO with your repository, then uncomment:
![FF14 Tex Converter](https://raw.githubusercontent.com/OWNER/REPO/main/docs/screenshot-en.png)
-->

## 📦 Download

| Asset | Size | SHA-256 |
|---|---|---|
| `FF14.Tex.Converter.exe` | 13.2 MB | `C536B0CC8A357ABA93AE6CC875E724EF3D3ECB1690F4D30222B4CE0B83A55B2B` |

Single portable file — no installer, no admin rights, no Python required. `texconv` (Microsoft DirectXTex) is bundled inside.

Verify the download before running it:

```powershell
Get-FileHash "FF14.Tex.Converter.exe" -Algorithm SHA256
```

## ✨ New in v2.1 — 中文 / English

- **Language switch in the top-right corner.** Two little chips, `中文 | EN`, one click. They sit above the header, clear of every control, and add no height to the window.
- **The choice is remembered.** The language is written to the settings file the moment you switch it, so the next launch starts in the same language. Default is 中文.
- **Fully translated, not just labels.** Log lines, error messages, status bar, the format-recommendation reasons and the text `texconv` errors are relayed through — all of it follows the UI language.
- **Headless modes follow too.** `--convert` and `--selftest` print their reports in the language saved in settings.
- History already written to the log stays as it was; only new lines use the new language.

## 🎯 Core features

- **Mixed input, one drop.** PNG **and** TEX files or folders at the same time — each routed by its own rules.
- **Automatic format advice.** `*_d` → BC1, `*_n` (normal) → BC7, `*_rg` → BC5, UI/atlas/effect → BC7 — with the reasoning printed in the log.
- **Fast batching.** Up to 16 files per `texconv` process instead of one process per texture, roughly 10× fewer process startups.
- **Long-edge resizing** that keeps the aspect ratio (1024×512 stays 2:1) and snaps to multiples of 4 for BC blocks.
- **Cancel that actually cancels** — kills the running `texconv` immediately.
- **Atomic writes.** Every TEX goes to a temp file and is renamed into place, so a crash or cancel never leaves a half-written texture.
- **No silent overwrites.** Same-named files landing in one folder get `_2`, `_3`, … suffixes.
- **Remembers everything** — options, window size and position, and language.
- **Self-test and headless conversion** for scripting and build verification.

## 🚀 Quick start

1. Drop PNG files/folders onto the window (or **PNG input → Browse…**).
2. Choose an **Output format**, or leave **Suggest per file name** ticked.
3. **TEX output** empty = write next to the source file. Press **Start PNG→TEX**.

For TEX → TEX: drop `.tex` files or press **Batch TEX convert…**; the chosen output format becomes the target. Output is `*_converted.tex` unless you tick **TEX→TEX overwrites the source file** (it asks first).

## 🎨 Supported formats

| Target | TEX format ID | DXGI | Use for |
|---|---|---|---|
| `BC1_UNORM` | `0x3420` | 71 | Opaque diffuse — half the size of BC7, no smooth alpha |
| `BC3_UNORM` | `0x3431` | 77 | Diffuse with soft transparency |
| `BC5_UNORM` | `0x6230` | 83 | Genuinely two-channel data (RG maps) |
| `BC7_UNORM` | `0x6432` | 98 | Best quality for RGBA — the safe default |
| `B8G8R8A8_UNORM` | `0x1450` | 87 | Uncompressed, lossless, largest |

Full mip chains are always generated, because FFXIV expects them.

## 💻 Command line

```bat
:: same code path as the Start button
"FF14.Tex.Converter.exe" --convert <file-or-folder> [output-dir] [--format BC7_UNORM]

:: end-to-end self check; writes selftest_report.json, exits 0 on success
"FF14.Tex.Converter.exe" --selftest [output-dir]
```

## ⚠️ Good to know

- **BC1 has no smooth alpha.** Fully transparent pixels turn black in game. The tool compresses BC1 as opaque and warns you — use BC3 or BC7 when you need transparency.
- Only FFXIV **2D** TEX is supported. Cube maps, arrays, 3D textures and formats like BC4/BC6H are rejected with a clear error rather than guessed.
- Output paths longer than 250 characters are flagged in the log before they fail.
- Settings and the error log live in `%APPDATA%\Miili\FFXIV贴图批量转换器\`.
- If the app ever refuses to start, check `error.log` in that folder — it contains the full traceback.

## 🙏 Credits

- **[TexTools](https://github.com/TexTools/FFXIV_TexTools_UI)** (GPL-3.0) — `texlib.py` is a Python port of TexTools' implementation of the FFXIV texture container. This project would not exist without it.
- **[Penumbra](https://github.com/xivdev/Penumbra)** — the per-usage format conventions (which role maps to BC1/BC3/BC5/BC7) follow Penumbra's documented behaviour.
- **[Microsoft DirectXTex](https://github.com/microsoft/DirectXTex)** (MIT) — `texconv.exe` performs the block compression; bundled unmodified.
- Coded with **DeepSeek** and **OpenAI Codex** as AI pair-programmers, under human review.

## 📜 License

**GPL-3.0** — `texlib.py` is a Python port of TexTools' GPL-3.0 TEX implementation, so this project is a derivative work and stays GPL-3.0. See the `LICENSE` file in the repository.

GPL-3.0 permits redistributing this tool **even for a fee**, as long as it stays GPL-3.0 and the complete source comes with it — nobody can add a "no commercial use" restriction on top of GPL, including the author.

**Please don't sell it anyway** — that is a request, not a license condition, and it is labelled as such in `ADDITIONAL-TERMS.md`. What *is* enforceable under GPLv3 §7: forks must use a different name and icon, and modified versions must be marked as modified and link back to this repository.

---

## 中文简介

**FF14 Tex Converter v2.1 首次发布。**

把 PNG 批量压成 FFXIV 的 `.tex`，也能把已有 TEX 换成别的压缩格式，全部在一个窗口里完成：拖进去 → 选格式 → 开始。支持 BC1 / BC3 / BC5 / BC7 / BGRA8，按文件名自动推荐格式，按长边等比缩放，进度可取消，写盘用临时文件 + 原子替换，不会留下半个贴图。

这一版新增**中英双语**：右上角「中文 | EN」一键切换，选择会立刻记住，下次启动直接沿用；日志、报错、格式推荐理由同样跟着切换，`--convert` / `--selftest` 也是。

下载 `FF14.Tex.Converter.exe` 双击即用，免安装、不需要 Python；请先核对上面的 SHA-256。
