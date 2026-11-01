# FF14 Tex Converter

**Batch PNG → TEX and TEX → TEX conversion for FINAL FANTASY XIV, in one window.**
把 PNG 批量压成 FFXIV TEX，也能把已有 TEX 换成别的压缩格式。

<p align="center">
  <a href="https://github.com/MaellaKnows/ffxiv-Tex-Converter/releases/latest/download/FF14.Tex.Converter.exe">
    <img src="https://img.shields.io/badge/Download_FF14_Tex_Converter-v2.1-7456a6?style=for-the-badge&logo=windows&logoColor=white" alt="Download FF14 Tex Converter">
  </a>
</p>

<p align="center">
  <a href="https://github.com/MaellaKnows/ffxiv-Tex-Converter/releases/latest"><img src="https://img.shields.io/badge/version-2.1-7456a6?style=flat-square" alt="Version 2.1"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4?style=flat-square" alt="Windows 10 / 11">
  <img src="https://img.shields.io/badge/UI-中文%20%7C%20English-7456a6?style=flat-square" alt="中文 / English UI">
  <img src="https://img.shields.io/badge/license-GPL--3.0-green?style=flat-square" alt="GPL-3.0">
</p>

独立运行的 Windows 桌面工具——**不需要 Dalamud、不注入游戏、不是插件加载器**，直接读写 FFXIV 的 `.tex` 容器，实际压缩交给微软的 `texconv`。
A standalone Windows desktop tool — **no Dalamud, no game injection, no plugin loader** — it reads and writes FFXIV `.tex` containers directly and calls Microsoft's `texconv` for the actual BC compression.

| 中文 | English |
|:---:|:---:|
| ![中文界面](docs/screenshot-cn.png) | ![English UI](docs/screenshot-en.png) |

**目录 / Contents：** [中文](#中文) · [English](#english)

---

## 中文

### 功能

- **一次拖入，混合输入。** PNG 和 TEX 可以一起拖进窗口，各自按自己的规则处理。
- **自动推荐格式。** 根据文件名给出建议：`*_d` → BC1、`*_n`（法线）→ BC7、`*_rg` → BC5、UI/图集/特效 → BC7，理由会写进日志。
- **批量提速。** 每个 `texconv` 进程最多处理 16 个文件，而不是一张贴图启动一次进程（进程启动次数约为原来的 1/10）。
- **按长边等比缩放。** 非正方形贴图不会被拉变形（1024×512 仍是 2:1），宽高自动对齐到 4 的倍数以适配 BC 块。
- **真的能取消。** 点「取消」立刻结束正在运行的 `texconv`。
- **进度与剩余时间**，日志逐条显示输出体积和压缩比（按结果上色）。
- **原子写入。** 每个 TEX 先写临时文件再改名替换，崩溃或取消都不会留下半个文件。
- **不会静默覆盖。** 落到同一目录的同名文件会自动加 `_2`、`_3` 后缀。
- **记住设置。** 选项、窗口大小与位置、界面语言都保存在 `%APPDATA%\Miili\FFXIV贴图批量转换器\`。
- **中英双语界面。** 中文 / English 一键切换，并记住选择。
- **自检与无界面模式。** 方便验证构建、也方便写脚本批量处理。

### 支持的格式

| 目标格式 | TEX 格式 ID | DXGI | 体积 | 适用场景 |
|---|---|---|---|---|
| `BC1_UNORM` | `0x3420` | 71 | 8 字节 / 4×4 块 | 不透明漫反射，体积约为 BC7 的一半；**不支持平滑透明** |
| `BC3_UNORM` | `0x3431` | 77 | 16 字节 / 4×4 块 | 带柔和透明的漫反射 |
| `BC5_UNORM` | `0x6230` | 83 | 16 字节 / 4×4 块 | 真正的双通道数据（RG 贴图） |
| `BC7_UNORM` | `0x6432` | 98 | 16 字节 / 4×4 块 | RGBA 最佳画质，安全的默认值，最慢 |
| `B8G8R8A8_UNORM` | `0x1450` | 87 | 4 字节 / 像素 | 不压缩、无损、体积最大 |

`texconv` 已随包提供，不需要额外安装。始终生成完整 mip 链，因为 FFXIV 需要它。

### 系统要求

- Windows 10 / 11（x64）。压缩器本身是 Windows 程序。
- 其它什么都不需要——只有从源码构建时才需要 Python。

### 安装

1. **[⬇ 下载 `FF14.Tex.Converter.exe`](https://github.com/MaellaKnows/ffxiv-Tex-Converter/releases/latest/download/FF14.Tex.Converter.exe)**（约 13 MB）——也可以从 [Release 页面](https://github.com/MaellaKnows/ffxiv-Tex-Converter/releases/latest) 或压缩包里的 `dist/` 获取。
2. 放到任意位置双击运行。单文件、免安装、不需要管理员权限。

设置与错误日志写在 `%APPDATA%\Miili\FFXIV贴图批量转换器\`。

### 使用

#### PNG → TEX

1. 把 PNG 文件或文件夹拖到窗口，或点 **PNG 输入 → 选择…**。
2. 选择**输出格式**，或保持勾选**按文件名逐个推荐**。
3. **TEX 输出**留空 = 生成在源文件旁边；选择目录则会保留子目录结构。
4. 点 **开始 PNG→TEX**。

#### TEX → TEX

把 `.tex` 文件拖进来，或点 **批量 TEX 格式转换…**。当前选的输出格式就是目标格式。默认输出 `*_converted.tex`；勾选 **TEX→TEX 直接覆盖源文件** 可原地替换（会先弹窗确认）。源文件已经是目标格式时默认跳过，避免二次压缩掉画质。

### 界面语言

右上角的 **中文 | EN** 两个小块可以切换整个界面——标签、日志、报错、格式推荐理由和状态栏都会跟着变。选择会立刻写入设置文件（`"lang": "cn" | "en"`），下次启动自动沿用。默认是中文；删掉该字段即可恢复默认。

### 命令行

```bat
:: 与「开始」按钮完全相同的流程
"FF14.Tex.Converter.exe" --convert <文件或文件夹> [输出目录] [--format BC7_UNORM]

:: 端到端自检；生成 selftest_report.json，成功返回 0
"FF14.Tex.Converter.exe" --selftest [输出目录]
```

`--convert` 会把 `convert_report.json` 写进输出目录，只有全部文件成功才返回 `0`。两种模式都跟随设置里保存的语言，所以日志会是你上次用的语言。

### 从源码构建

```bat
:: 一键：检查 Python、安装 PyInstaller、下载 texconv、打包、改名
BUILD_EXE.bat

:: 或者手动来
py -m pip install --upgrade pyinstaller
py prepare_texconv.py
py -m PyInstaller --noconfirm --clean FFXIVTextureBatchConverter.spec
py rename_output.py
```

也可以直接跑源码：`py main.py`。需要 Python 3.10+ 并且带 Tk。

### 工程结构

```
main.py                            界面、拖放、设置、线程调度
texlib.py                          TEX/DDS 读写、texconv 批量调度、格式推荐
i18n.py                            中英文案（唯一的文案来源）
FFXIVTextureBatchConverter.spec    PyInstaller 打包配置
prepare_texconv.py                 打包前下载 texconv.exe
rename_output.py                   打包后重命名 EXE
BUILD_EXE.bat / CLEAN_BUILD.bat    一键构建 / 清理
tools/texconv.exe                  微软 DirectXTex 压缩器
docs/                              截图
README.txt                         详细变更记录（中文）
```

### 注意事项与已知限制

- **BC1 没有平滑透明度。** 完全透明的像素在游戏里会变成黑色。本工具按不透明方式压 BC1 并给出警告；需要透明请用 BC3 或 BC7。
- 只支持 FFXIV 的 **2D** TEX。立方体贴图、数组贴图、3D 贴图，以及 BC4/BC6H 等格式会明确报错，而不是瞎猜。
- Windows 路径长度限制：输出路径超过 250 字符时会在日志里提前警告。
- BC7 的 `x` 质量明显比 `q` 慢；用在关键贴图上，别用在几千个图标上。
- 设置与错误日志在 `%APPDATA%\Miili\FFXIV贴图批量转换器\`。程序起不来时先看那里的 `error.log`，里面有完整堆栈。

### 致谢

这个项目是站在别人的工作之上的。FFXIV TEX 容器的布局、上面的格式 ID、mip 链结构以及 BC1 的 Alpha 行为，都是由下面这些项目先做出来的：

- **[TexTools](https://github.com/TexTools/FFXIV_TexTools_UI)**（GPL-3.0）——`texlib.py` 是 TexTools 中 FFXIV 贴图容器实现的 Python 移植。没有它就没有这个项目。
- **[Penumbra](https://github.com/xivdev/Penumbra)**（xivdev）——按用途推荐格式的约定（哪种贴图对应 BC1/BC3/BC5/BC7）沿用其文档中描述的行为。
- **[Microsoft DirectXTex](https://github.com/microsoft/DirectXTex)**（MIT）——`texconv.exe` 负责实际的块压缩，随包提供且未做修改。
- **Python** 与 **Tkinter**——运行时与界面库。

如果你维护上述项目，希望调整署名措辞，开个 issue 就行，会尽快改。

### 实现方式

代码由 AI 编程代理作为主要实现者、在人工指导下写成：

- **[DeepSeek](https://www.deepseek.com/)**——架构、TEX/DDS 容器逻辑、Tk 界面、双语层与测试。
- **OpenAI Codex**——重构、缺陷排查与测试自动化。

需求、审阅与发布由 **Miili** 负责。

### 许可证

**GPL-3.0**——因为 `texlib.py` 是 TexTools（GPL-3.0）TEX 实现的 Python 移植。完整文本见 [LICENSE](LICENSE)；GPLv3 §7 允许的附加条款见 [ADDITIONAL-TERMS.md](ADDITIONAL-TERMS.md)。

GPL-3.0 允许任何人使用、研究、修改和再分发本工具——**包括收费分发**——只要结果仍然保持 GPL-3.0，并把完整源码交给每一位接收者。这项自由任何人都拿不走，包括作者。

**作者请求大家不要售卖本工具，因为所有代码都来自于社区。** 这是一个请求，不是授权条件：它没有法律效力，也不限制 GPL-3.0 赋予你的任何权利。原文与说明都在 [ADDITIONAL-TERMS.md](ADDITIONAL-TERMS.md) 里，写得明明白白。

许可证**真正可以强制执行**的是这两条：

| | |
|---|---|
| 🏷️ **名称与图标不授权** | 分支必须使用不同的名字和不同的图标。没人能顶着「FF14 Tex Converter」的名字和这个图标发付费版。 |
| ✍️ **修改版必须注明** | 改过代码的版本必须清楚标注为修改版/非官方版，并回链到本仓库，不能冒充原版。 |
| 🔓 **付费分发必须附源码** | 这是 GPL-3.0 自带的（不是作者加的）：卖出去的版本必须把完整源码以同样的许可证交给每位买家。「付费闭源分支」这条路走不通。 |

`tools/texconv.exe` 是微软 DirectXTex，按 MIT 许可证分发，随包提供且未修改。

### 免责声明

非官方粉丝工具。与 Square Enix、TexTools 团队、Penumbra 团队及微软均无关联，也未获其背书或支持。FINAL FANTASY XIV 是 Square Enix Holdings Co., Ltd. 的商标。使用风险自负，覆盖任何贴图前请先备份。

---

## English

### Features

- **One drop, mixed input.** Drag PNG **and** TEX files/folders in at the same time; each is routed by its own rules.
- **Auto format suggestion.** Reads the file name and picks a sensible target: `*_d` → BC1, `*_n` (normal) → BC7, `*_rg` → BC5, UI/atlas/effect → BC7, and so on — with the reason printed in the log.
- **Fast batching.** Up to 16 files per `texconv` process instead of one process per texture (~10× fewer process startups).
- **Long-edge resizing** that never distorts non-square textures (1024×512 stays 2:1) and snaps to multiples of 4 for BC blocks.
- **Cancel that actually cancels** — kills the running `texconv` immediately.
- **Progress with ETA**, per-file log with output size and compression ratio (colored by result).
- **Atomic writes** — every TEX is written to a temp file and renamed, so a crash or cancel never leaves a half-written texture.
- **No silent overwrites** — same-named files landing in one output folder get `_2`, `_3`, … suffixes.
- **Remembers everything** — options, window size/position and UI language live in `%APPDATA%\Miili\FFXIV贴图批量转换器\`.
- **Bilingual UI** — 中文 / English, one click, remembered.
- **Self-test and headless mode** — verify a build or script a batch without the GUI.

### Supported formats

| Target | TEX format ID | DXGI | Size | When to use |
|---|---|---|---|---|
| `BC1_UNORM` | `0x3420` | 71 | 8 B / 4×4 block | Opaque diffuse. Half the size of BC7. **No smooth alpha.** |
| `BC3_UNORM` | `0x3431` | 77 | 16 B / 4×4 block | Diffuse with soft transparency. |
| `BC5_UNORM` | `0x6230` | 83 | 16 B / 4×4 block | Genuinely two-channel data (RG maps). |
| `BC7_UNORM` | `0x6432` | 98 | 16 B / 4×4 block | Best quality for RGBA; the safe default. Slowest. |
| `B8G8R8A8_UNORM` | `0x1450` | 87 | 4 B / pixel | Uncompressed, lossless, largest. |

`texconv` is bundled, so nothing else needs to be installed. Full mip chains are always generated, because FFXIV expects them.

### Requirements

- Windows 10 / 11 (x64). The tool ships a Windows-only compressor.
- Nothing else — Python is only needed if you build from source.

### Install

1. **[⬇ Download `FF14.Tex.Converter.exe`](https://github.com/MaellaKnows/ffxiv-Tex-Converter/releases/latest/download/FF14.Tex.Converter.exe)** (~13 MB) — or grab it from the [Releases page](https://github.com/MaellaKnows/ffxiv-Tex-Converter/releases/latest), or from `dist/` in the archive.
2. Put it anywhere and run it. It is a single file; no installer, no admin rights.

Settings and the error log are written to `%APPDATA%\Miili\FFXIV贴图批量转换器\`.

### Usage

#### PNG → TEX

1. Drop PNG files/folders onto the window, or use **PNG input → Browse…**.
2. Pick an **Output format** (or leave **Suggest per file name** ticked).
3. **TEX output** empty = write next to the source file; pick a folder to mirror the subfolder structure.
4. Press **Start PNG→TEX**.

#### TEX → TEX

Drop `.tex` files, or press **Batch TEX convert…**. The selected output format becomes the target. Output is `*_converted.tex` by default; tick **TEX→TEX overwrites the source file** to replace in place (it asks first). TEX already in the target format is skipped by default to avoid re-compression loss.

### Language

The **中文 | EN** chips in the top-right corner switch the whole interface — labels, log messages, error text, format suggestions and the status bar. The choice is written to the settings file (`"lang": "cn" | "en"`) immediately and restored on the next launch. Default is 中文. Delete the field to fall back to it.

### Command line

```bat
:: same code path as the Start button
"FF14.Tex.Converter.exe" --convert <file-or-folder> [output-dir] [--format BC7_UNORM]

:: end-to-end self check; writes selftest_report.json, exits 0 on success
"FF14.Tex.Converter.exe" --selftest [output-dir]
```

`--convert` writes `convert_report.json` into the output folder and returns `0` only if every file succeeded. Both modes follow the language saved in settings, so logs come out in the language you last used.

### Build from source

```bat
:: one click: checks Python, installs PyInstaller, fetches texconv, builds, renames
BUILD_EXE.bat

:: or manually
py -m pip install --upgrade pyinstaller
py prepare_texconv.py
py -m PyInstaller --noconfirm --clean FFXIVTextureBatchConverter.spec
py rename_output.py
```

Running the sources directly works too: `py main.py`. Requires Python 3.10+ with Tk.

### Project layout

```
main.py                            UI, drag & drop, settings, threading
texlib.py                          TEX/DDS read-write, texconv batching, format advice
i18n.py                            中文 / English strings (single source of truth)
FFXIVTextureBatchConverter.spec    PyInstaller build config
prepare_texconv.py                 fetch texconv.exe before packaging
rename_output.py                   post-build rename of the EXE
BUILD_EXE.bat / CLEAN_BUILD.bat    one-click build / clean
tools/texconv.exe                  Microsoft DirectXTex compressor
docs/                              screenshots
README.txt                         detailed changelog and notes (中文)
```

### Notes and known limits

- **BC1 has no smooth alpha.** Fully transparent pixels become black in game. The tool compresses BC1 as opaque and warns you; use BC3 or BC7 when you need transparency.
- Only FFXIV **2D** TEX is supported. Cube maps, texture arrays, 3D textures and formats such as BC4/BC6H are rejected with a clear error rather than guessed.
- Windows path limit: output paths over 250 characters are flagged in the log before they fail.
- BC7 with `x` quality is noticeably slower than `q`; use it for hero assets, not for thousands of icons.
- Settings and the error log live in `%APPDATA%\Miili\FFXIV贴图批量转换器\`. If the app ever refuses to start, check `error.log` in that folder — it contains the full traceback.

### Credits

This project stands on other people's work. The FFXIV TEX container layout, the format IDs above, the mip-chain layout and the BC1 alpha behaviour were all reverse-engineered and published by these projects first:

- **[TexTools](https://github.com/TexTools/FFXIV_TexTools_UI)** (GPL-3.0) — `texlib.py` is a Python port of TexTools' implementation of the FFXIV texture container. This project would not exist without it.
- **[Penumbra](https://github.com/xivdev/Penumbra)** (xivdev) — the per-usage format conventions (which role maps to BC1/BC3/BC5/BC7) follow Penumbra's documented behaviour.
- **[Microsoft DirectXTex](https://github.com/microsoft/DirectXTex)** (MIT) — `texconv.exe` does all the actual block compression; the bundled copy is unmodified.
- **Python** and **Tkinter** — runtime and GUI toolkit.

If you maintain one of these projects and want the wording or attribution changed, please open an issue — it will be fixed quickly.

### How this was built

The code was written with AI coding agents as the main implementers, under human direction and review:

- **[DeepSeek](https://www.deepseek.com/)** — architecture, TEX/DDS container logic, the Tk UI, the bilingual layer and the test harness.
- **OpenAI Codex** — refactoring, bug hunting and test automation.

审阅、需求与发布由 **Miili** 负责。

### License

**GPL-3.0** — because `texlib.py` is a Python port of TexTools' GPL-3.0 TEX implementation. Full text in [LICENSE](LICENSE); the additional terms GPLv3 §7 allows are in [ADDITIONAL-TERMS.md](ADDITIONAL-TERMS.md).

GPL-3.0 lets anyone use, study, modify and redistribute this tool — **including selling it** — as long as the result stays GPL-3.0 and every recipient gets the complete source. No one, including the author, can take that freedom away.

**The author asks that you don't sell it.** That is a request, not a license condition: it has no legal force, and it does not limit anything GPL-3.0 grants. It is written out in full, and honestly labelled, in [ADDITIONAL-TERMS.md](ADDITIONAL-TERMS.md).

What the license *does* make enforceable, under §7:

| | |
|---|---|
| 🏷️ **The name and icon are not licensed** | A fork must use a different name and a different icon. Nobody can ship a paid build called "FF14 Tex Converter" with this logo. |
| ✍️ **Modified versions must say so** | If you change the code, the result must be clearly marked as a modified/unofficial version and must link back here. It cannot pass itself off as the original. |
| 🔓 **Paid forks must ship the source** | GPL-3.0 — not a restriction the author added — means a sold build has to hand every buyer the full source under the same license. The "paywalled closed-source fork" model is dead on arrival. |

`tools/texconv.exe` is Microsoft DirectXTex, distributed under the MIT license and included unmodified.

### Disclaimer

Unofficial fan tool. Not affiliated with, endorsed by, or supported by Square Enix, the TexTools team, the Penumbra team or Microsoft. FINAL FANTASY XIV is a trademark of Square Enix Holdings Co., Ltd. Use at your own risk and keep backups of any texture you overwrite.
