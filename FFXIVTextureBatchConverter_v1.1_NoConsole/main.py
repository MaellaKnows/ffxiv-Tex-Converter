# -*- coding: utf-8 -*-
"""FFXIV 贴图批量转换器 —— 图形界面。

转换逻辑全部在 texlib.py；本文件只负责界面、拖放、设置与线程调度。
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import texlib
from texlib import (
    Job,
    RunStats,
    TexConverter,
    app_dir,
    png_info,
    recommend_format_for_name,
    scan_paths,
    tex_info,
)

APP_TITLE = "FFXIV贴图批量转换器 | version 2.0 | Miili 制造"

if getattr(sys, "frozen", False):
    # PyInstaller --onefile 会把文件解压到临时 _MEI 目录，配置要放 AppData。
    _config_root = Path(os.environ.get("APPDATA", Path.home())) / "Miili" / "FFXIV贴图批量转换器"
else:
    _config_root = Path(__file__).with_name("config")

SETTINGS_FILE = _config_root / "ffxiv_tex_converter_v1_1_settings.json"
# v1.0 的设置文件只用来做一次性迁移，之后统一写新文件。
LEGACY_SETTINGS_FILE = _config_root / "ffxiv_png_to_tex_v1_0_settings.json"
# 无控制台的 EXE 出错时什么都看不到，留一份可排查的日志。
LOG_FILE = _config_root / "error.log"

SIZE_CHOICES = ("原尺寸", "512（长边）", "1024（长边）", "2048（长边）", "4096（长边）")

WM_DROPFILES = 0x0233
GWL_WNDPROC = -4

LOG_COLORS = {
    "ok": "#0a7d24",
    "err": "#c02b1b",
    "warn": "#a86400",
    "info": "#5a5a5a",
}


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    for path in (SETTINGS_FILE, LEGACY_SETTINGS_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def log_exception(context: str, exc: BaseException | None = None) -> None:
    """把异常写进日志文件，方便排查无控制台 EXE 的问题。"""
    import datetime
    import traceback

    text = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {context}\n"
    if exc is not None:
        text += "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        text += traceback.format_exc()
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


def save_settings(data: dict) -> str | None:
    """保存设置；失败时返回错误描述而不是静默吞掉。"""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def normalize_size_choice(text: str | None) -> str:
    """把旧版本保存的 '1024×1024' 迁移成新的「长边」写法。"""
    if not text:
        return SIZE_CHOICES[0]
    text = text.strip()
    if text in SIZE_CHOICES:
        return text
    n = texlib.parse_target_size(text)
    return f"{n}（长边）" if n else SIZE_CHOICES[0]


# ---------------------------------------------------------------------------
# 拖放（Windows 原生 WM_DROPFILES）
# ---------------------------------------------------------------------------

_old_wndproc = None
_drop_callback = None
_wndproc_ref = None
_drop_hwnd = None


def enable_windows_drop(hwnd, callback) -> bool:
    """在 Tk 顶层窗口上启用资源管理器拖放。

    64 位 Python 下必须显式声明 ctypes 签名，否则函数指针会被截断，
    PyInstaller 打包后尤其容易静默失败。
    """
    global _old_wndproc, _drop_callback, _wndproc_ref, _drop_hwnd

    if os.name != "nt":
        return False

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        from ctypes import wintypes

        HWND = wintypes.HWND
        UINT = wintypes.UINT
        WPARAM = wintypes.WPARAM
        LPARAM = wintypes.LPARAM
        LRESULT = ctypes.c_ssize_t

        user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_void_p]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, HWND, UINT, WPARAM, LPARAM]
        user32.CallWindowProcW.restype = LRESULT

        shell32.DragAcceptFiles.argtypes = [HWND, wintypes.BOOL]
        shell32.DragAcceptFiles.restype = None
        shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, UINT, wintypes.LPWSTR, UINT]
        shell32.DragQueryFileW.restype = UINT
        shell32.DragFinish.argtypes = [wintypes.HANDLE]
        shell32.DragFinish.restype = None

        # 程序以管理员权限启动时，Explorer 的拖放会被 UIPI 拦掉，这里放行。
        try:
            user32.ChangeWindowMessageFilterEx.argtypes = [
                HWND, UINT, wintypes.DWORD, ctypes.c_void_p
            ]
            user32.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
            user32.ChangeWindowMessageFilterEx(hwnd, WM_DROPFILES, 1, None)
        except Exception:
            pass

        _drop_callback = callback

        old_proc = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
        if not old_proc:
            raise OSError(ctypes.get_last_error(), "GetWindowLongPtrW failed")
        _old_wndproc = old_proc

        CALLBACK = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

        @CALLBACK
        def wndproc(h, msg, wp, lp):
            if msg == WM_DROPFILES:
                try:
                    count = shell32.DragQueryFileW(wintypes.HANDLE(wp), 0xFFFFFFFF, None, 0)
                    paths = []
                    for i in range(count):
                        n = shell32.DragQueryFileW(wintypes.HANDLE(wp), i, None, 0)
                        buf = ctypes.create_unicode_buffer(n + 1)
                        shell32.DragQueryFileW(wintypes.HANDLE(wp), i, buf, n + 1)
                        paths.append(buf.value)
                    shell32.DragFinish(wintypes.HANDLE(wp))
                    if _drop_callback:
                        try:
                            _drop_callback(paths)
                        except Exception:
                            pass
                    return 0
                except Exception:
                    try:
                        shell32.DragFinish(wintypes.HANDLE(wp))
                    except Exception:
                        pass

            return user32.CallWindowProcW(
                ctypes.c_void_p(_old_wndproc), h, msg, wp, lp
            )

        _wndproc_ref = wndproc
        _drop_hwnd = hwnd

        ctypes.set_last_error(0)
        if not user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.cast(wndproc, ctypes.c_void_p)):
            raise OSError(ctypes.get_last_error(), "SetWindowLongPtrW failed")

        shell32.DragAcceptFiles(hwnd, True)
        return True

    except Exception:
        _old_wndproc = None
        _drop_callback = None
        _wndproc_ref = None
        _drop_hwnd = None
        return False


# ---------------------------------------------------------------------------
# 界面
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk, scale: float = 1.0):
        self.root = root
        self.scale = scale
        self.q: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self._run_started = 0.0

        s = load_settings()
        self._saved_geometry = s.get("geometry", "")

        self.input_var = tk.StringVar(value="")  # PNG 来源路径每次启动重新选择，不持久化
        self.output_var = tk.StringVar(value=s.get("output", ""))
        self.format_var = tk.StringVar(value=s.get("format", "BC7_UNORM"))
        self.quality_var = tk.StringVar(value=s.get("quality", "q"))
        self.size_var = tk.StringVar(value=normalize_size_choice(s.get("size")))
        self.recommend_var = tk.StringVar(value="未检测")
        self.recommend_reason_var = tk.StringVar(value="选择 PNG 后会按文件名推荐格式")
        self.auto_recommend_var = tk.BooleanVar(value=bool(s.get("auto_recommend", True)))
        self.recursive_var = tk.BooleanVar(value=bool(s.get("recursive", True)))
        self.overwrite_var = tk.BooleanVar(value=bool(s.get("overwrite", True)))
        self.tex_overwrite_source_var = tk.BooleanVar(value=bool(s.get("tex_overwrite_source", False)))
        self.skip_same_var = tk.BooleanVar(value=bool(s.get("skip_same", True)))
        self.status_var = tk.StringVar(value="准备就绪")
        self.percent_var = tk.StringVar(value="0%")
        self.progress_var = tk.DoubleVar(value=0)

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(80, self.process_events)
        self.root.after(250, self._apply_rounded_corners)

    # -- 窗口 -------------------------------------------------------------
    def _apply_rounded_corners(self) -> None:
        """Windows 11/较新 Windows 上请求轻微圆角；不支持时静默忽略。"""
        if os.name != "nt":
            return
        try:
            hwnd = self.root.winfo_id()
            value = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(value), ctypes.sizeof(value)
            )
        except Exception:
            pass

    def _parse_geometry(self, geometry: str):
        import re

        m = re.fullmatch(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", geometry or "")
        if not m:
            return None
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))

    def _finalize_geometry(self) -> None:
        """按控件真实需求定尺寸：不同 DPI / 字体缩放下都不会被裁切。"""
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        max_w = int(screen_w * 0.96)
        max_h = int(screen_h * 0.90)

        width = min(max(req_w, int(820 * self.scale)), max_w)
        height = min(max(req_h, int(650 * self.scale)), max_h)
        x = y = None

        saved = self._parse_geometry(self._saved_geometry)
        if saved:
            sw, sh, sx, sy = saved
            width = min(max(sw, min(req_w, max_w)), max_w)
            height = min(max(sh, min(req_h, max_h)), max_h)
            # 只保留仍在屏幕内的位置，避免换显示器后窗口跑丢。
            if 0 <= sx <= screen_w - 120 and 0 <= sy <= screen_h - 120:
                x, y = sx, sy

        self.root.minsize(min(int(760 * self.scale), max_w), min(int(590 * self.scale), max_h))
        if x is None:
            self.root.geometry(f"{width}x{height}")
        else:
            self.root.geometry(f"{width}x{height}+{x}+{y}")

    def build_ui(self) -> None:
        root = self.root
        root.title(APP_TITLE)
        self._apply_icon()

        header = ttk.Frame(root)
        header.pack(fill="x", padx=16, pady=(12, 0))
        ttk.Label(
            header, text="FFXIV 贴图批量转换器", style="Header.TLabel"
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="PNG → TEX  ·  TEX → TEX  ·  BC1 / BC3 / BC5 / BC7 / BGRA8",
            style="Subheader.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        main = ttk.Frame(root)
        main.pack(fill="both", expand=True, padx=14, pady=10)
        for col, weight in ((0, 0), (1, 1), (2, 0), (3, 0)):
            main.columnconfigure(col, weight=weight)
        main.rowconfigure(10, weight=1)

        drop = ttk.LabelFrame(main, text="拖放")
        drop.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        self.drop_label = ttk.Label(
            drop,
            text="把 PNG / TEX 文件或文件夹拖到这里\n"
                 "PNG 会被压缩成 TEX；TEX 会转成「输出格式」里选的格式\n"
                 "支持一次拖入多个项目",
            anchor="center", justify="center", font=("Segoe UI", 10),
        )
        self.drop_label.pack(fill="x", padx=14, pady=12)

        self.add_path_row(main, 1, "PNG 输入", self.input_var, self.choose_input)
        self.add_path_row(main, 2, "TEX 输出", self.output_var, self.choose_output)

        ttk.Label(
            main,
            text="提示：TEX 输出留空时，生成的 TEX 会放在源文件旁边；"
                 "勾选「直接覆盖源文件」后，TEX→TEX 会原地替换。",
            foreground="#666666",
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(main, text="输出格式").grid(row=4, column=0, sticky="w", pady=6)
        self.format_box = ttk.Combobox(
            main, textvariable=self.format_var,
            values=texlib.SUPPORTED_FORMATS, state="readonly", width=22,
        )
        self.format_box.grid(row=4, column=1, sticky="w", padx=8)
        ttk.Label(
            main,
            text="BC1 0x3420 · BC3 0x3431 · BC5 0x6230 · BC7 0x6432 · BGRA8 0x1450",
        ).grid(row=4, column=2, columnspan=2, sticky="w")

        ttk.Label(main, text="图片尺寸").grid(row=5, column=0, sticky="w", pady=6)
        size_box = ttk.Combobox(
            main, textvariable=self.size_var, values=SIZE_CHOICES,
            state="readonly", width=22,
        )
        size_box.grid(row=5, column=1, sticky="w", padx=8)
        ttk.Label(main, text="按长边等比缩放，不会把非正方形贴图拉变形").grid(
            row=5, column=2, columnspan=2, sticky="w"
        )

        ttk.Label(main, text="自动推荐").grid(row=6, column=0, sticky="nw", pady=6)
        rec = ttk.Frame(main)
        rec.grid(row=6, column=1, columnspan=3, sticky="ew", padx=8, pady=2)
        rec.columnconfigure(0, weight=1)
        # v1.0 在这里把 Label 和 Checkbutton 放进了同一个 grid 单元格，文字互相覆盖。
        ttk.Label(rec, textvariable=self.recommend_var, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(
            rec, text="按文件名逐个推荐（PNG）", variable=self.auto_recommend_var
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        ttk.Button(rec, text="推荐当前 PNG", command=self.auto_recommend, width=14).grid(
            row=0, column=2, sticky="e", padx=(8, 0)
        )
        ttk.Label(
            rec, textvariable=self.recommend_reason_var, foreground="#555555", wraplength=700
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        ttk.Label(main, text="压缩质量").grid(row=7, column=0, sticky="w", pady=6)
        quality = ttk.Combobox(
            main, textvariable=self.quality_var, values=("q", "x"),
            state="readonly", width=22,
        )
        quality.grid(row=7, column=1, sticky="w", padx=8)
        ttk.Label(main, text="q = 快速；x = 最高质量（仅 BC7 生效）").grid(
            row=7, column=2, columnspan=2, sticky="w"
        )

        opts = ttk.Frame(main)
        opts.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(6, 8))
        ttk.Checkbutton(opts, text="递归扫描子文件夹", variable=self.recursive_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(opts, text="覆盖已存在的输出文件", variable=self.overwrite_var).grid(
            row=0, column=1, sticky="w", padx=(18, 0)
        )
        ttk.Checkbutton(
            opts, text="TEX→TEX 直接覆盖源文件", variable=self.tex_overwrite_source_var
        ).grid(row=0, column=2, sticky="w", padx=(18, 0))
        ttk.Checkbutton(
            opts, text="TEX 已是目标格式时跳过重压缩", variable=self.skip_same_var
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Label(main, text="转换结果 / 日志").grid(
            row=9, column=0, sticky="w", pady=(2, 4)
        )
        ttk.Button(main, text="清空日志", command=self.clear_log, width=10).grid(
            row=9, column=3, sticky="e", pady=(2, 4)
        )

        log_frame = ttk.Frame(main)
        log_frame.grid(row=10, column=0, columnspan=4, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(
            log_frame, wrap="none", font=("Consolas", 9), height=6,
            background="#fffefe", foreground="#332b40", insertbackground="#7456a6",
            selectbackground="#ded3ee", selectforeground="#302744",
            relief="flat", borderwidth=0, padx=10, pady=8,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log.xview)
        xsb.grid(row=1, column=0, sticky="ew")
        self.log.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        for tag, color in LOG_COLORS.items():
            self.log.tag_configure(tag, foreground=color)
        self.log.tag_configure("head", foreground="#1f3a8a", font=("Consolas", 9, "bold"))

        prog = ttk.Frame(main)
        prog.grid(row=11, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        prog.columnconfigure(0, weight=1)
        self.progressbar = ttk.Progressbar(prog, variable=self.progress_var, maximum=100)
        self.progressbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(prog, textvariable=self.percent_var, width=6, anchor="e").grid(
            row=0, column=1, padx=(8, 0)
        )

        bottom = ttk.Frame(main)
        bottom.grid(row=12, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

        self.start_button = ttk.Button(
            bottom, text="开始 PNG→TEX", command=self.start, width=16, style="Primary.TButton"
        )
        self.start_button.grid(row=0, column=1, padx=4)
        self.tex_button = ttk.Button(
            bottom, text="批量 TEX 格式转换…", command=self.choose_tex_files, width=20
        )
        self.tex_button.grid(row=0, column=2, padx=4)
        self.cancel_button = ttk.Button(
            bottom, text="取消", command=self.on_cancel, width=8, state="disabled"
        )
        self.cancel_button.grid(row=0, column=3, padx=4)
        ttk.Button(bottom, text="打开输出文件夹", command=self.open_output, width=16).grid(
            row=0, column=4, padx=(4, 0)
        )

        self.root.update_idletasks()
        if not enable_windows_drop(self.root.winfo_id(), self.on_drop):
            self.drop_label.configure(
                text="Windows 原生拖放未启用\n\n仍可使用下方的路径选择与按钮"
            )

        if texlib.find_texconv():
            self.status_var.set("准备就绪 · texconv 已就绪")
        else:
            self.status_var.set("准备就绪 · 首次转换将自动下载 texconv")

        self._finalize_geometry()

    def _apply_icon(self) -> None:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        for name in ("icon.ico", "tools/icon.ico"):
            path = base / name
            try:
                if path.is_file():
                    self.root.iconbitmap(default=str(path))
                    return
            except Exception:
                continue

    def add_path_row(self, parent, row, label, var, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(parent, text="选择…", command=command, width=8).grid(
            row=row, column=2, sticky="w"
        )

    # -- 日志与状态 -------------------------------------------------------
    def log_line(self, kind: str, text: str) -> None:
        self.log.insert("end", text + "\n", kind)
        self.log.see("end")
        # 超大任务时截断旧日志，避免 Text 控件越拖越慢。
        try:
            lines = int(self.log.index("end-1c").split(".")[0])
            if lines > 6000:
                self.log.delete("1.0", "2000.0")
        except Exception:
            pass

    def clear_log(self) -> None:
        self.log.delete("1.0", "end")

    def _set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.tex_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")

    # -- 选择路径 ---------------------------------------------------------
    def choose_input(self) -> None:
        path = filedialog.askdirectory(title="选择包含 PNG 的输入文件夹")
        if path:
            self.input_var.set(path)
            self._refresh_recommendation()

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="选择 TEX 输出文件夹")
        if path:
            self.output_var.set(path)

    def _refresh_recommendation(self) -> None:
        if not self.auto_recommend_var.get():
            self.recommend_var.set("已关闭自动推荐")
            self.recommend_reason_var.set("所有 PNG 都会用「输出格式」里手动选择的格式。")
            return
        raw = self.input_var.get().strip()
        if raw and Path(raw).is_file() and Path(raw).suffix.lower() == ".png":
            self._show_recommendation(Path(raw))
            return
        # 目录不在这里扫描：几千个文件会让「选择文件夹」卡住。
        self.recommend_var.set("按文件名逐个推荐")
        self.recommend_reason_var.set("转换时每张 PNG 都会按自己的文件名推荐格式。")

    def _show_recommendation(self, path: Path, apply: bool = False):
        fmt, reason = recommend_format_for_name(path.name)
        self.recommend_var.set(f"{path.name}  →  {fmt}")
        self.recommend_reason_var.set(reason)
        if apply:
            self.format_var.set(fmt)
        return fmt, reason

    def auto_recommend(self) -> None:
        raw = self.input_var.get().strip()
        if not raw:
            messagebox.showinfo(APP_TITLE, "请先选择 PNG 文件或包含 PNG 的文件夹。")
            return
        pngs, _tex = scan_paths([raw], self.recursive_var.get())
        if not pngs:
            messagebox.showinfo(APP_TITLE, "没有找到 PNG。")
            return
        fmt, _reason = self._show_recommendation(pngs[0], apply=True)
        self.log_line("info", f"★ 推荐（按 {pngs[0].name}）：{fmt}")

    # -- 拖放 -------------------------------------------------------------
    def on_drop(self, paths) -> None:
        if self.running:
            self.log_line("warn", "⚠ 正在转换，请等当前任务结束或点「取消」。")
            return
        # 拖入文件夹时顺手把「PNG 输入」填上，这样输出目录能保留子目录结构。
        if not self.input_var.get().strip():
            dirs = [str(Path(p)) for p in paths if Path(p).is_dir()]
            if dirs:
                try:
                    self.input_var.set(os.path.commonpath(dirs))
                except ValueError:
                    self.input_var.set(dirs[0])
        pngs, texes = scan_paths(paths, self.recursive_var.get())
        if not pngs and not texes:
            self.log_line("warn", "⚠ 拖入的内容里没有 PNG 或 TEX。")
            return
        if pngs:
            self._show_recommendation(pngs[0])
        self._launch(pngs, texes)

    # -- 任务构建 ---------------------------------------------------------
    def _settings_snapshot(self) -> dict:
        return {
            # PNG 输入来源不保存；其余选项与所有复选框状态会记忆。
            "output": self.output_var.get().strip(),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "size": self.size_var.get(),
            "auto_recommend": self.auto_recommend_var.get(),
            "recursive": self.recursive_var.get(),
            "overwrite": self.overwrite_var.get(),
            "tex_overwrite_source": self.tex_overwrite_source_var.get(),
            "skip_same": self.skip_same_var.get(),
        }

    def _launch(self, pngs: list[Path], texes: list[Path]) -> None:
        if self.running or (not pngs and not texes):
            return
        if texes and self.tex_overwrite_source_var.get():
            if not messagebox.askyesno(
                APP_TITLE,
                f"将直接覆盖选中的 {len(texes)} 个源 TEX 文件。\n\n"
                "原文件会被替换且无法自动恢复，确定继续吗？",
            ):
                return

        settings = self._settings_snapshot()
        # 「PNG 输入」不写进设置文件（每次启动重新选择），但这次运行要用它
        # 计算输出目录下的相对路径，所以只在内存里的运行参数中带上。
        run_settings = {**settings, "input": self.input_var.get().strip()}
        save_settings({**settings, "geometry": self.root.geometry()})

        self.clear_log()
        self.cancel_event.clear()
        self.progress_var.set(0)
        self.percent_var.set("0%")
        self._run_started = time.perf_counter()
        self._set_running(True)
        self.status_var.set("正在准备…")
        self.log_line("head", f"开始转换：PNG {len(pngs)} 个，TEX {len(texes)} 个")
        if settings["auto_recommend"] and pngs:
            self.log_line("info", "自动推荐已启用：每个 PNG 按文件名单独选择格式。")
        if settings["output"]:
            self.log_line("info", f"输出目录：{settings['output']}")
        else:
            self.log_line("info", "TEX 输出目录为空：生成的 TEX 放在源文件旁边。")

        threading.Thread(
            target=self.worker, args=(pngs, texes, run_settings), daemon=True
        ).start()

    def worker(self, pngs: list[Path], texes: list[Path], settings: dict) -> None:
        started = time.perf_counter()
        log = lambda kind, text: self.q.put(("log", (kind, text)))  # noqa: E731

        try:
            jobs, stats = self.build_jobs(pngs, texes, settings, log)
        except Exception as exc:
            log("err", f"✗ 构建任务失败：{exc}")
            self.q.put(("done", RunStats(elapsed=time.perf_counter() - started)))
            return

        if not jobs:
            stats.elapsed = time.perf_counter() - started
            self.q.put(("done", stats))
            return

        try:
            texconv = texlib.ensure_texconv(lambda m: log("info", m))
            log("info", f"texconv：{texconv}")
        except Exception as exc:
            log("err", f"✗ 无法准备 texconv：{exc}")
            failed = RunStats(total=stats.total, failed=len(jobs),
                              skipped=stats.skipped, elapsed=time.perf_counter() - started)
            self.q.put(("done", failed))
            return

        converter = TexConverter(texconv)
        result = converter.run(
            jobs,
            log=log,
            progress=lambda done, total: self.q.put(("progress", done, total)),
            cancel=self.cancel_event,
        )
        result.skipped += stats.skipped
        result.total += stats.skipped
        self.q.put(("done", result))

    @staticmethod
    def build_jobs(pngs, texes, settings, log) -> tuple[list[Job], RunStats]:
        """把文件列表变成 Job；顺带处理跳过、命名冲突、Alpha 提醒。"""
        out_root = Path(settings["output"]) if settings["output"] else None
        input_root = Path(settings["input"]) if settings.get("input") else None
        target = texlib.parse_target_size(settings["size"])
        auto_format = settings["auto_recommend"]
        manual_format = settings["format"]
        quality = settings["quality"]
        overwrite = settings["overwrite"]
        skip_same = settings["skip_same"]
        overwrite_tex = settings["tex_overwrite_source"]

        jobs: list[Job] = []
        stats = RunStats()
        used_dst: set[str] = set()
        bc1_alpha = 0

        def unique_dst(dst: Path) -> Path:
            key = os.path.normcase(str(dst))
            if key not in used_dst:
                used_dst.add(key)
                return dst
            # 不同子目录里的同名文件落到同一输出目录时，追加序号避免互相覆盖。
            n = 2
            while True:
                candidate = dst.with_name(f"{dst.stem}_{n}{dst.suffix}")
                if os.path.normcase(str(candidate)) not in used_dst:
                    used_dst.add(os.path.normcase(str(candidate)))
                    return candidate
                n += 1

        for png in pngs:
            info = png_info(png)
            if info is None:
                stats.skipped += 1
                log("warn", f"⚠ 跳过无法识别的 PNG：{png.name}")
                continue

            fmt = recommend_format_for_name(png.name)[0] if auto_format else manual_format

            if out_root is None:
                dst = png.with_suffix(".tex")
            else:
                try:
                    rel = png.relative_to(input_root) if input_root else Path(png.name)
                except ValueError:
                    rel = Path(png.name)
                dst = out_root / rel.with_suffix(".tex")
            dst = unique_dst(dst)

            if dst.exists() and not overwrite:
                stats.skipped += 1
                log("warn", f"↷ 跳过（已存在）：{dst.name}")
                continue
            if len(str(dst)) > 250:
                log("warn", f"⚠ 路径过长可能失败：{dst}")

            resize = None
            if target and max(info.width, info.height) != target:
                try:
                    resize = texlib.fit_long_edge(info.width, info.height, target)
                except ValueError:
                    resize = None

            if fmt == "BC1_UNORM" and info.has_alpha:
                bc1_alpha += 1

            desc = f"{info.width}x{info.height}"
            if resize:
                desc += f" → {resize[0]}x{resize[1]}"
            jobs.append(
                Job(src=png, dst=dst, fmt=fmt, kind="png", quality=quality,
                    resize=resize, src_desc=desc)
            )

        for tex in texes:
            try:
                info = tex_info(tex)
            except Exception as exc:
                stats.skipped += 1
                log("warn", f"⚠ 跳过无法解析的 TEX：{tex.name}（{exc}）")
                continue

            if skip_same and info.fmt_name == manual_format and not target:
                stats.skipped += 1
                log("info", f"↷ 跳过（已是 {manual_format}）：{tex.name}")
                continue

            if overwrite_tex:
                dst = tex
            elif out_root is not None:
                dst = out_root / tex.name
            else:
                dst = tex.with_name(tex.stem + "_converted.tex")
            if not overwrite_tex and os.path.normcase(str(dst)) == os.path.normcase(str(tex)):
                dst = tex.with_name(tex.stem + "_converted.tex")
            dst = unique_dst(dst)

            if dst.exists() and dst != tex and not overwrite:
                stats.skipped += 1
                log("warn", f"↷ 跳过（已存在）：{dst.name}")
                continue

            resize = None
            if target and max(info.width, info.height) != target:
                try:
                    resize = texlib.fit_long_edge(info.width, info.height, target)
                except ValueError:
                    resize = None

            jobs.append(
                Job(src=tex, dst=dst, fmt=manual_format, kind="tex", quality=quality,
                    resize=resize, src_desc=info.describe())
            )

        stats.total = len(jobs) + stats.skipped
        if bc1_alpha:
            log(
                "warn",
                f"⚠ 有 {bc1_alpha} 张 PNG 使用 BC1 且带 Alpha 通道："
                "BC1 不支持平滑透明，完全透明的像素在 FFXIV 里会变黑；"
                "需要透明请改用 BC3 / BC7。",
            )
        if stats.skipped:
            log("info", f"已跳过 {stats.skipped} 个文件，待转换 {len(jobs)} 个。")
        if not jobs:
            log("warn", "没有需要转换的文件。")
        return jobs, stats

    # -- 按钮动作 ---------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        raw = self.input_var.get().strip()
        if not raw:
            messagebox.showwarning(APP_TITLE, "请选择 PNG 输入文件夹。")
            return
        pngs, _tex = scan_paths([raw], self.recursive_var.get())
        if not pngs:
            messagebox.showwarning(
                APP_TITLE,
                "输入路径里没有 PNG。\n\n如果是 TEX 文件，请用「批量 TEX 格式转换…」或直接拖入。",
            )
            return
        self._show_recommendation(pngs[0])
        self._launch(pngs, [])

    def choose_tex_files(self) -> None:
        if self.running:
            messagebox.showinfo(APP_TITLE, "当前正在转换，请等待完成。")
            return
        files = filedialog.askopenfilenames(
            title="选择要转换格式的 FFXIV TEX 文件",
            filetypes=[("FFXIV TEX", "*.tex *.TEX"), ("所有文件", "*.*")],
        )
        if not files:
            return
        texes = [Path(x) for x in files if Path(x).is_file() and Path(x).suffix.lower() == ".tex"]
        if not texes:
            messagebox.showwarning(APP_TITLE, "没有选择有效的 .tex 文件。")
            return
        self._launch([], texes)

    def on_cancel(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set("正在取消…（会终止当前的 texconv 进程）")

    def open_output(self) -> None:
        target = self.output_var.get().strip() or self.input_var.get().strip()
        if not target:
            messagebox.showinfo(APP_TITLE, "还没有设置输入或输出文件夹。")
            return
        path = Path(target)
        if path.is_file():
            path = path.parent
        if not path.exists():
            messagebox.showinfo(APP_TITLE, "文件夹尚不存在。")
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"无法打开文件夹：{exc}")

    # -- 事件循环 ---------------------------------------------------------
    def process_events(self) -> None:
        try:
            while True:
                ev = self.q.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self.log_line(ev[1][0], ev[1][1])
                elif kind == "progress":
                    self._update_progress(ev[1], ev[2])
                elif kind == "done":
                    self._on_done(ev[1])
        except queue.Empty:
            pass
        self.root.after(80, self.process_events)

    def _update_progress(self, done: int, total: int) -> None:
        total = max(1, total)
        pct = done / total * 100
        self.progress_var.set(pct)
        self.percent_var.set(f"{pct:.0f}%")
        elapsed = time.perf_counter() - self._run_started
        rate = done / elapsed if elapsed > 0.05 and done else 0
        eta = (total - done) / rate if rate else 0
        self.status_var.set(
            f"转换中 {done}/{total} · 已用 {elapsed:.0f}s" + (f" · 剩余约 {eta:.0f}s" if rate else "")
        )

    def _on_done(self, stats: RunStats) -> None:
        self._set_running(False)
        if stats.cancelled == 0:
            self.progress_var.set(100 if stats.total else 0)
            self.percent_var.set("100%" if stats.total else "0%")
        self.status_var.set(f"{'已取消' if stats.cancelled else '完成'}：{stats.summary()} · 用时 {stats.elapsed:.1f}s")
        self.log_line(
            "warn" if stats.failed or stats.cancelled else "ok",
            f"— {stats.summary()}，用时 {stats.elapsed:.1f}s —",
        )

    def on_close(self) -> None:
        try:
            if self.running:
                if not messagebox.askyesno(APP_TITLE, "正在转换，确定要退出吗？"):
                    return
                self.cancel_event.set()
            error = save_settings(
                {**self._settings_snapshot(), "geometry": self.root.geometry()}
            )
            if error:
                log_exception(f"保存设置失败：{error}")
        except Exception:
            log_exception("退出流程异常")
        finally:
            self.root.destroy()


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

def enable_dpi_awareness() -> float:
    """开启 DPI 感知，返回系统缩放比例（150% -> 1.5）。"""
    if os.name != "nt":
        return 1.0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return max(1.0, min(3.0, dpi / 96.0))
    except Exception:
        return 1.0


def run_selftest_cli(argv: list[str]) -> int:
    """--selftest [输出目录]：无界面自检，结果写入 selftest_report.json。"""
    out_dir = app_dir()
    for i, arg in enumerate(argv):
        if arg == "--selftest" and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out_dir = Path(argv[i + 1])
    report = texlib.run_selftest(out_dir)

    target = Path(out_dir) / "selftest_report.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        import tempfile
        target = Path(tempfile.gettempdir()) / "selftest_report.json"
        try:
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    try:
        if sys.stdout is not None:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        pass
    return 0 if report.get("ok") else 1


def run_convert_cli(argv: list[str]) -> int:
    """--convert <输入> [输出目录] [--format 格式]：无界面批量转换。

    走的是和界面「开始」按钮完全相同的 build_jobs + TexConverter 流程，
    因此可以用它直接验证打包后的 EXE 是否真能转换（结果写入 convert_report.json）。
    """
    args = [a for a in argv[1:] if a != "--convert"]
    fmt = "BC7_UNORM"
    if "--format" in args:
        i = args.index("--format")
        if i + 1 < len(args):
            fmt = args[i + 1]
            del args[i:i + 2]
        else:
            return 2
    if not args or fmt not in texlib.SUPPORTED_FORMATS:
        return 2

    src = Path(args[0])
    out_dir = Path(args[1]) if len(args) > 1 else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    def log(kind: str, text: str) -> None:
        lines.append(text)

    pngs, texes = texlib.scan_paths([src], True)
    settings = {
        "input": str(src) if src.is_dir() else "",
        "output": str(out_dir) if out_dir else "",
        "format": fmt,
        "quality": "q",
        "size": "原尺寸",
        "auto_recommend": False,
        "overwrite": True,
        "tex_overwrite_source": False,
        "skip_same": True,
    }

    report: dict = {"ok": False, "mode": "convert", "input": str(src),
                    "format": fmt, "output": str(out_dir) if out_dir else "", "log": lines}
    try:
        jobs, stats = App.build_jobs(pngs, texes, settings, log)
        if jobs:
            converter = texlib.TexConverter(
                texlib.ensure_texconv(lambda m: log("info", m))
            )
            result = converter.run(jobs, log=log)
            result.skipped += stats.skipped
            result.total += stats.skipped
            stats = result
        report["ok"] = stats.ok > 0 and stats.failed == 0
        report["summary"] = stats.summary()
        report["total"] = stats.total
        report["ok_count"] = stats.ok
        report["failed"] = stats.failed
        report["skipped"] = stats.skipped
    except Exception as exc:
        log("err", f"转换失败：{exc}")
        report["error"] = f"{type(exc).__name__}: {exc}"

    target = (out_dir or app_dir()) / "convert_report.json"
    try:
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    try:
        if sys.stdout is not None:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        pass
    return 0 if report["ok"] else 1


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return run_selftest_cli(sys.argv)
    if "--convert" in sys.argv[1:]:
        return run_convert_cli(sys.argv)

    sys.excepthook = lambda etype, value, tb: log_exception("未捕获异常", value)
    scale = enable_dpi_awareness()
    root = None
    try:
        root = tk.Tk()
        # Tk 回调里的异常默认只打到 stderr，打包成 EXE 后等于消失。
        root.report_callback_exception = lambda etype, value, tb: log_exception("界面回调异常", value)
        style = ttk.Style(root)
        try:
            style.theme_use("vista")
        except Exception:
            style.theme_use("clam")

        # Miili 风格：柔和薰衣草底色、深紫文字与清晰的主操作按钮。
        bg, panel, ink, muted = "#f5f3fa", "#ffffff", "#302744", "#706780"
        accent, accent_hover = "#7456a6", "#62458f"
        style.configure(".", font=("Segoe UI", 9), background=bg, foreground=ink)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=ink)
        style.configure("Muted.TLabel", background=bg, foreground=muted)
        style.configure("Header.TLabel", background=bg, foreground="#4c356f", font=("Segoe UI", 18, "bold"))
        style.configure("Subheader.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("TLabelframe", background=panel, bordercolor="#ded6eb", relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=bg, foreground=accent, font=("Segoe UI", 9, "bold"))
        style.configure("TEntry", padding=(7, 6), fieldbackground=panel)
        style.configure("TCombobox", padding=(6, 5), fieldbackground=panel)
        style.configure("TButton", padding=(9, 6), background="#ebe5f4", foreground=ink, borderwidth=0)
        style.map("TButton", background=[("active", "#ded3ee"), ("disabled", "#eeeaf3")])
        style.configure("Primary.TButton", padding=(12, 7), background=accent, foreground="#ffffff", font=("Segoe UI", 9, "bold"))
        style.map("Primary.TButton", background=[("active", accent_hover), ("disabled", "#bcb0ce")], foreground=[("disabled", "#f7f4fa")])
        style.configure("Horizontal.TProgressbar", troughcolor="#e7e0ef", background=accent, thickness=10)
        root.configure(background=bg)
        App(root, scale=scale)
        root.mainloop()
        return 0
    except Exception as exc:
        log_exception("程序启动失败", exc)
        try:
            messagebox.showerror(APP_TITLE, "程序启动时发生错误，详细信息已写入：\n" + str(LOG_FILE) + "\n\n错误：" + str(exc), parent=root)
        except Exception:
            pass
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
