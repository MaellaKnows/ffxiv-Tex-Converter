# -*- coding: utf-8 -*-
"""界面与日志文案的多语言（中文 / English）支持。

main.py 与 texlib.py 都通过 t() 取文案；切换语言只改这里的全局状态，
已经写进日志的历史行保持原样，不会因为切换语言而错乱。
"""

from __future__ import annotations

LANGUAGES = ("cn", "en")
DEFAULT_LANG = "cn"
LANGUAGE_NAMES = {"cn": "中文", "en": "EN"}

_current = DEFAULT_LANG


def normalize(lang: str | None) -> str:
    """把设置里读到的任意写法（zh-CN / cn / en-US …）归一成 cn 或 en。"""
    text = (lang or "").strip().lower()
    if text.startswith("zh") or text in ("cn", "chs", "cht"):
        return "cn"
    if text.startswith("en"):
        return "en"
    return DEFAULT_LANG


def get_lang() -> str:
    return _current


def set_lang(lang: str | None) -> str:
    global _current
    _current = normalize(lang)
    return _current


# ---------------------------------------------------------------------------
# 文案表：键名统一用「区域.用途」，两边必须完全对齐
# ---------------------------------------------------------------------------

STRINGS: dict[str, dict[str, str]] = {
    "cn": {
        # -- 窗口 --------------------------------------------------------
        "app.title": "FFXIV贴图批量转换器 | version 2.1 | Miili 制造",
        "app.header": "FFXIV 贴图批量转换器",
        "app.subtitle": "PNG → TEX  ·  TEX → TEX  ·  BC1 / BC3 / BC5 / BC7 / BGRA8",

        # -- 拖放 --------------------------------------------------------
        "drop.frame": "拖放",
        "drop.text": (
            "把 PNG / TEX 文件或文件夹拖到这里\n"
            "PNG 会被压缩成 TEX；TEX 会转成「输出格式」里选的格式\n"
            "支持一次拖入多个项目"
        ),
        "drop.text_disabled": "Windows 原生拖放未启用\n\n仍可使用下方的路径选择与按钮",
        "drop.noitems": "⚠ 拖入的内容里没有 PNG 或 TEX。",
        "drop.busy": "⚠ 正在转换，请等当前任务结束或点「取消」。",

        # -- 控件 --------------------------------------------------------
        "lbl.input": "PNG 输入",
        "lbl.output": "TEX 输出",
        "lbl.format": "输出格式",
        "lbl.size": "图片尺寸",
        "lbl.recommend": "自动推荐",
        "lbl.quality": "压缩质量",
        "lbl.log": "转换结果 / 日志",
        "btn.browse": "选择…",
        "btn.recommend": "推荐当前 PNG",
        "btn.clear_log": "清空日志",
        "btn.start": "开始 PNG→TEX",
        "btn.batch_tex": "批量 TEX 格式转换…",
        "btn.cancel": "取消",
        "btn.open_output": "打开输出文件夹",
        "hint.output": (
            "提示：TEX 输出留空时，生成的 TEX 会放在源文件旁边；"
            "勾选「直接覆盖源文件」后，TEX→TEX 会原地替换。"
        ),
        "hint.size": "按长边等比缩放，不会把非正方形贴图拉变形",
        "hint.quality": "q = 快速；x = 最高质量（仅 BC7 生效）",
        "chk.auto_recommend": "按文件名逐个推荐（PNG）",
        "chk.recursive": "递归扫描子文件夹",
        "chk.overwrite": "覆盖已存在的输出文件",
        "chk.tex_overwrite": "TEX→TEX 直接覆盖源文件",
        "chk.skip_same": "TEX 已是目标格式时跳过重压缩",

        # -- 尺寸下拉 ----------------------------------------------------
        "size.original": "原尺寸",
        "size.edge": "{n}（长边）",

        # -- 状态栏 ------------------------------------------------------
        "status.ready_texconv": "准备就绪 · texconv 已就绪",
        "status.ready_download": "准备就绪 · 首次转换将自动下载 texconv",
        "status.preparing": "正在准备…",
        "status.cancelling": "正在取消…（会终止当前的 texconv 进程）",
        "status.running": "转换中 {done}/{total} · 已用 {elapsed}s",
        "status.eta": " · 剩余约 {eta}s",
        "status.done": "{state}：{summary} · 用时 {elapsed}s",
        "status.state_done": "完成",
        "status.state_cancelled": "已取消",

        # -- 自动推荐 ----------------------------------------------------
        "rec.none": "未检测",
        "rec.placeholder": "选择 PNG 后会按文件名推荐格式",
        "rec.disabled": "已关闭自动推荐",
        "rec.disabled_reason": "所有 PNG 都会用「输出格式」里手动选择的格式。",
        "rec.by_name": "按文件名逐个推荐",
        "rec.by_name_reason": "转换时每张 PNG 都会按自己的文件名推荐格式。",

        # -- 对话框 ------------------------------------------------------
        "dlg.input": "选择包含 PNG 的输入文件夹",
        "dlg.output": "选择 TEX 输出文件夹",
        "dlg.tex_files": "选择要转换格式的 FFXIV TEX 文件",
        "dlg.all_files": "所有文件",
        "msg.pick_png_first": "请先选择 PNG 文件或包含 PNG 的文件夹。",
        "msg.no_png": "没有找到 PNG。",
        "msg.pick_input": "请选择 PNG 输入文件夹。",
        "msg.input_no_png": (
            "输入路径里没有 PNG。\n\n"
            "如果是 TEX 文件，请用「批量 TEX 格式转换…」或直接拖入。"
        ),
        "msg.busy_wait": "当前正在转换，请等待完成。",
        "msg.confirm_exit": "正在转换，确定要退出吗？",
        "msg.no_folders": "还没有设置输入或输出文件夹。",
        "msg.folder_missing": "文件夹尚不存在。",
        "msg.open_failed": "无法打开文件夹：{err}",
        "msg.overwrite_tex": (
            "将直接覆盖选中的 {n} 个源 TEX 文件。\n\n"
            "原文件会被替换且无法自动恢复，确定继续吗？"
        ),
        "msg.no_tex": "没有选择有效的 .tex 文件。",
        "msg.startup_failed": (
            "程序启动时发生错误，详细信息已写入：\n{log}\n\n错误：{err}"
        ),

        # -- 日志 --------------------------------------------------------
        "log.start": "开始转换：PNG {png} 个，TEX {tex} 个",
        "log.auto_recommend_on": "自动推荐已启用：每个 PNG 按文件名单独选择格式。",
        "log.output_dir": "输出目录：{path}",
        "log.output_empty": "TEX 输出目录为空：生成的 TEX 放在源文件旁边。",
        "log.build_failed": "✗ 构建任务失败：{err}",
        "log.convert_failed": "转换失败：{err}",
        "log.texconv": "texconv：{path}",
        "log.texconv_failed": "✗ 无法准备 texconv：{err}",
        "log.skip_bad_png": "⚠ 跳过无法识别的 PNG：{name}",
        "log.skip_exists": "↷ 跳过（已存在）：{name}",
        "log.long_path": "⚠ 路径过长可能失败：{path}",
        "log.skip_bad_tex": "⚠ 跳过无法解析的 TEX：{name}（{err}）",
        "log.skip_same": "↷ 跳过（已是 {fmt}）：{name}",
        "log.bc1_alpha": (
            "⚠ 有 {n} 张 PNG 使用 BC1 且带 Alpha 通道："
            "BC1 不支持平滑透明，完全透明的像素在 FFXIV 里会变黑；"
            "需要透明请改用 BC3 / BC7。"
        ),
        "log.skipped": "已跳过 {n} 个文件，待转换 {m} 个。",
        "log.nothing_to_do": "没有需要转换的文件。",
        "log.recommend": "★ 推荐（按 {name}）：{fmt}",
        "log.summary_line": "— {summary}，用时 {elapsed}s —",
        "log.downloading": "正在下载 texconv：{url}",
        "log.download_pct": "下载 texconv… {pct}%",
        "log.texconv_report": "texconv 报告：{name} -> {excerpt}",
        "log.resized": ", 缩放到 {w}x{h}",
        "log.job_failed": "✗ {name}: {err}",

        # -- 汇总 --------------------------------------------------------
        "sum.ok": "成功 {n}",
        "sum.failed": "失败 {n}",
        "sum.skipped": "跳过 {n}",
        "sum.cancelled": "已取消 {n}",

        # -- 推荐理由 ----------------------------------------------------
        "rec.normal": (
            "Normal/法线：推荐 BC7，保留完整通道；"
            "如需其他格式，可关闭自动推荐后手动选择。"
        ),
        "rec.rg": "检测到 RG/双通道：BC5 适合真正只使用 R+G 的数据。",
        "rec.mask": (
            "Mask/Specular/AO：FFXIV 不同 Shader 的通道打包可能不同，"
            "默认 BC7 保留完整通道。"
        ),
        "rec.diffuse": "Diffuse/Albedo/Color：推荐 BC1；若贴图需要 Alpha，请改用 BC3/BC7。",
        "rec.ui": "UI/Icon/Atlas/Effect：推荐 BC7，适合可能含 Alpha 的 RGBA 贴图。",
        "rec.opaque": "明确无 Alpha：推荐 BC1，文件体积约为 BC7 的一半。",
        "rec.unknown": "未识别贴图类型：推荐 BC7 作为 FFXIV 通用高质量默认值。",

        # -- TEX/DDS 错误 ------------------------------------------------
        "err.incomplete_data": "数据不完整：还差 {left} 字节。",
        "err.bad_mip_count": "mipmap 数量无效。",
        "err.unsupported_dxgi": "不支持的 DXGI 格式：{dxgi}",
        "err.bad_size": "图片尺寸无效。",
        "err.bad_target_size": "目标尺寸无效。",
        "err.too_small": "文件太小，不是有效的 FFXIV TEX。",
        "err.bad_tex_size": "TEX 头中的尺寸无效。",
        "err.bad_tex_mips": "TEX 头中的 mipmap 数量无效（{levels}）。",
        "err.not_dds": "texconv 输出不是有效的 DDS。",
        "err.unsupported_output": "不支持的输出格式：{fmt}",
        "err.dx10_header": "DDS 的 DX10 扩展头不完整。",
        "err.format_mismatch": (
            "texconv 输出格式异常：DDS DXGI={actual}，"
            "但本次要求的是 {expected}（DXGI={want}）。"
        ),
        "err.mip_overflow": (
            "mip 层数 {levels} 超过 FFXIV TEX 头能记录的 {max} 层，请减小图片尺寸。"
        ),
        "err.dds_short": "DDS 数据不完整：需要 {need} 字节，实际只有 {have} 字节。",
        "err.tex_len_check": "生成 TEX 的长度校验失败。",
        "err.tex3d": "暂不支持 3D/立方体贴图（depth={depth}）。",
        "err.tex_format": (
            "暂不支持该 TEX 格式 ID：0x{fmt}。支持 BGRA8 / BC1 / BC3 / BC5 / BC7。"
        ),
        "err.tex_offset": "TEX mip 数据偏移无效。",
        "err.tex_short": "TEX mip 数据不完整：需要 {need} 字节，文件只有 {have} 字节。",
        "err.dds_header_len": "DDS 头长度错误：{n}",
        "err.tex_header_len": "内部错误：TEX 头不是 80 字节。",
        "err.no_dds": "texconv 没有生成 DDS。",
        "err.no_output": "texconv 未返回任何信息。",
        "err.no_texconv_in_nupkg": "NuGet 包内没有 texconv.exe。",
        "err.bad_download": "下载到的不是有效的 texconv.exe。",
        "err.texconv_verify": "texconv.exe 校验失败。",
        "err.download_failed": "无法下载 texconv：\n{errors}",
        "err.no_temp": "无法创建临时目录：{err}",
    },

    "en": {
        "app.title": "FFXIV Texture Batch Converter | version 2.1 | by Miili",
        "app.header": "FFXIV Texture Batch Converter",
        "app.subtitle": "PNG → TEX  ·  TEX → TEX  ·  BC1 / BC3 / BC5 / BC7 / BGRA8",

        "drop.frame": "Drop",
        "drop.text": (
            "Drag PNG / TEX files or folders here\n"
            "PNG is compressed into TEX; TEX is converted to the format chosen in \"Output format\"\n"
            "Several items can be dropped at once"
        ),
        "drop.text_disabled": "Native Windows drag & drop is unavailable\n\nYou can still use the path fields and buttons below",
        "drop.noitems": "⚠ Nothing that was dropped is a PNG or TEX.",
        "drop.busy": "⚠ A conversion is running. Wait for it to finish or press \"Cancel\".",

        "lbl.input": "PNG input",
        "lbl.output": "TEX output",
        "lbl.format": "Output format",
        "lbl.size": "Image size",
        "lbl.recommend": "Suggest",
        "lbl.quality": "Quality",
        "lbl.log": "Results / Log",
        "btn.browse": "Browse…",
        "btn.recommend": "Suggest for current PNG",
        "btn.clear_log": "Clear log",
        "btn.start": "Start PNG→TEX",
        "btn.batch_tex": "Batch TEX convert…",
        "btn.cancel": "Cancel",
        "btn.open_output": "Open output folder",
        "hint.output": (
            "Tip: leave \"TEX output\" empty to write TEX next to the source file; "
            "with \"overwrite source\" ticked, TEX→TEX replaces the files in place."
        ),
        "hint.size": "Scales by the long edge; non-square textures keep their aspect ratio",
        "hint.quality": "q = fast; x = highest quality (BC7 only)",
        "chk.auto_recommend": "Suggest per file name (PNG)",
        "chk.recursive": "Scan subfolders",
        "chk.overwrite": "Overwrite existing output files",
        "chk.tex_overwrite": "TEX→TEX overwrites the source file",
        "chk.skip_same": "Skip TEX that already uses the target format",

        "size.original": "Original",
        "size.edge": "{n} (long edge)",

        "status.ready_texconv": "Ready · texconv found",
        "status.ready_download": "Ready · texconv will be downloaded on the first run",
        "status.preparing": "Preparing…",
        "status.cancelling": "Cancelling… (terminating the running texconv process)",
        "status.running": "Converting {done}/{total} · {elapsed}s elapsed",
        "status.eta": " · ~{eta}s left",
        "status.done": "{state}: {summary} · {elapsed}s",
        "status.state_done": "Done",
        "status.state_cancelled": "Cancelled",

        "rec.none": "Not detected",
        "rec.placeholder": "Pick a PNG and the format is suggested from its file name",
        "rec.disabled": "Auto suggest is off",
        "rec.disabled_reason": "Every PNG uses the format chosen manually in \"Output format\".",
        "rec.by_name": "Suggest per file name",
        "rec.by_name_reason": "Each PNG is matched to a format by its own file name while converting.",

        "dlg.input": "Select the folder that contains the PNG files",
        "dlg.output": "Select the TEX output folder",
        "dlg.tex_files": "Select the FFXIV TEX files to convert",
        "dlg.all_files": "All files",
        "msg.pick_png_first": "Please select a PNG file or a folder that contains PNGs.",
        "msg.no_png": "No PNG found.",
        "msg.pick_input": "Please choose the PNG input folder.",
        "msg.input_no_png": (
            "The input path contains no PNG.\n\n"
            "For TEX files use \"Batch TEX convert…\" or drop them into the window."
        ),
        "msg.busy_wait": "A conversion is running. Please wait until it finishes.",
        "msg.confirm_exit": "A conversion is running. Quit anyway?",
        "msg.no_folders": "No input or output folder has been set yet.",
        "msg.folder_missing": "That folder does not exist yet.",
        "msg.open_failed": "Could not open the folder: {err}",
        "msg.overwrite_tex": (
            "This will overwrite {n} selected source TEX file(s).\n\n"
            "The originals are replaced and cannot be restored automatically. Continue?"
        ),
        "msg.no_tex": "No valid .tex file was selected.",
        "msg.startup_failed": (
            "An error occurred while starting the program.\n"
            "Details were written to:\n{log}\n\nError: {err}"
        ),

        "log.start": "Starting: {png} PNG, {tex} TEX",
        "log.auto_recommend_on": "Auto suggest is on: each PNG gets a format from its file name.",
        "log.output_dir": "Output folder: {path}",
        "log.output_empty": "TEX output folder is empty: TEX files are written next to their source.",
        "log.build_failed": "✗ Failed to build the job list: {err}",
        "log.convert_failed": "Conversion failed: {err}",
        "log.texconv": "texconv: {path}",
        "log.texconv_failed": "✗ Could not prepare texconv: {err}",
        "log.skip_bad_png": "⚠ Skipping unrecognised PNG: {name}",
        "log.skip_exists": "↷ Skipping (already exists): {name}",
        "log.long_path": "⚠ Path may be too long and fail: {path}",
        "log.skip_bad_tex": "⚠ Skipping unreadable TEX: {name} ({err})",
        "log.skip_same": "↷ Skipping (already {fmt}): {name}",
        "log.bc1_alpha": (
            "⚠ {n} PNG file(s) use BC1 but carry an alpha channel: "
            "BC1 cannot store smooth transparency, and fully transparent pixels turn black in FFXIV. "
            "Use BC3 / BC7 when you need transparency."
        ),
        "log.skipped": "Skipped {n} file(s); {m} left to convert.",
        "log.nothing_to_do": "Nothing to convert.",
        "log.recommend": "★ Suggestion (from {name}): {fmt}",
        "log.summary_line": "— {summary}, {elapsed}s —",
        "log.downloading": "Downloading texconv: {url}",
        "log.download_pct": "Downloading texconv… {pct}%",
        "log.texconv_report": "texconv reported: {name} -> {excerpt}",
        "log.resized": ", resized to {w}x{h}",
        "log.job_failed": "✗ {name}: {err}",

        "sum.ok": "OK {n}",
        "sum.failed": "Failed {n}",
        "sum.skipped": "Skipped {n}",
        "sum.cancelled": "Cancelled {n}",

        "rec.normal": (
            "Normal map: BC7 keeps every channel. "
            "For another format, turn auto suggest off and pick it manually."
        ),
        "rec.rg": "RG / two-channel map detected: BC5 fits data that really uses only R+G.",
        "rec.mask": (
            "Mask / specular / AO: FFXIV shaders pack channels differently, "
            "so BC7 keeps every channel by default."
        ),
        "rec.diffuse": "Diffuse / albedo / colour: BC1 recommended; use BC3 or BC7 if the texture needs alpha.",
        "rec.ui": "UI / icon / atlas / effect: BC7 recommended for RGBA textures that may contain alpha.",
        "rec.opaque": "Clearly opaque: BC1 recommended, roughly half the size of BC7.",
        "rec.unknown": "Unrecognised texture type: BC7 is the general high-quality default for FFXIV.",

        "err.incomplete_data": "Incomplete data: {left} bytes missing.",
        "err.bad_mip_count": "Invalid mipmap count.",
        "err.unsupported_dxgi": "Unsupported DXGI format: {dxgi}",
        "err.bad_size": "Invalid image size.",
        "err.bad_target_size": "Invalid target size.",
        "err.too_small": "The file is too small to be a valid FFXIV TEX.",
        "err.bad_tex_size": "The TEX header contains an invalid size.",
        "err.bad_tex_mips": "The TEX header contains an invalid mipmap count ({levels}).",
        "err.not_dds": "texconv did not produce a valid DDS.",
        "err.unsupported_output": "Unsupported output format: {fmt}",
        "err.dx10_header": "The DDS DX10 header is incomplete.",
        "err.format_mismatch": (
            "Unexpected texconv output format: DDS DXGI={actual}, "
            "but {expected} (DXGI={want}) was requested."
        ),
        "err.mip_overflow": (
            "The mip count {levels} exceeds the {max} levels an FFXIV TEX header can hold. "
            "Reduce the image size."
        ),
        "err.dds_short": "Incomplete DDS data: {need} bytes needed, only {have} available.",
        "err.tex_len_check": "The generated TEX failed its length check.",
        "err.tex3d": "3D / cube maps are not supported yet (depth={depth}).",
        "err.tex_format": (
            "Unsupported TEX format ID: 0x{fmt}. "
            "Supported: BGRA8 / BC1 / BC3 / BC5 / BC7."
        ),
        "err.tex_offset": "Invalid TEX mip data offset.",
        "err.tex_short": "Incomplete TEX mip data: {need} bytes needed, the file has {have}.",
        "err.dds_header_len": "Wrong DDS header length: {n}",
        "err.tex_header_len": "Internal error: the TEX header is not 80 bytes.",
        "err.no_dds": "texconv produced no DDS.",
        "err.no_output": "texconv returned no output.",
        "err.no_texconv_in_nupkg": "The NuGet package contains no texconv.exe.",
        "err.bad_download": "The download is not a valid texconv.exe.",
        "err.texconv_verify": "texconv.exe failed verification.",
        "err.download_failed": "Could not download texconv:\n{errors}",
        "err.no_temp": "Could not create a temporary folder: {err}",
    },
}


def t(key: str, **kwargs) -> str:
    """取当前语言的文案；缺键时退回中文，再退回键名本身。"""
    table = STRINGS.get(_current, STRINGS[DEFAULT_LANG])
    text = table.get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANG].get(key, key)
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text
