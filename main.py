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

import i18n
import texlib
from i18n import t
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


def app_title() -> str:
    """窗口标题和对话框标题跟界面语言保持一致。"""
    return t("app.title")


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

# 「图片尺寸」在设置里按长边像素存，界面文案随语言切换。
SIZE_TARGETS = (None, 512, 1024, 2048, 4096)

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


def size_label(target: int | None) -> str:
    """长边像素 -> 当前语言下的下拉框文案。"""
    return t("size.original") if target is None else t("size.edge", n=target)


def size_labels() -> tuple[str, ...]:
    return tuple(size_label(n) for n in SIZE_TARGETS)


def size_target_from_label(text: str | None) -> int | None:
    """下拉框文案 -> 长边像素；「原尺寸 / Original」都返回 None。

    两种语言、以及旧版本保存的 '1024×1024' 都能解析，因为只看数字。
    """
    return texlib.parse_target_size(text or "")


def normalize_size_choice(text: str | None) -> str:
    """把旧版本保存的 '1024×1024' 迁移成当前语言的长边写法。"""
    return size_label(size_target_from_label(text))


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
        # 语言必须在建界面之前确定，文案初始化就靠它。
        i18n.set_lang(s.get("lang"))
        self._saved_geometry = s.get("geometry", "")
        # 需要跟随语言刷新文字的控件：(控件, 文案键, 格式化参数)
        self._i18n_widgets: list[tuple[tk.Widget, str, dict]] = []
        self._drop_key = "drop.text"
        self.lang_chips: dict[str, tk.Label] = {}

        self.input_var = tk.StringVar(value="")  # PNG 来源路径每次启动重新选择，不持久化
        self.output_var = tk.StringVar(value=s.get("output", ""))
        self.format_var = tk.StringVar(value=s.get("format", "BC7_UNORM"))
        self.quality_var = tk.StringVar(value=s.get("quality", "q"))
        self.size_var = tk.StringVar(value=normalize_size_choice(s.get("size")))
        self.recommend_var = tk.StringVar(value=t("rec.none"))
        self.recommend_reason_var = tk.StringVar(value=t("rec.placeholder"))
        self.auto_recommend_var = tk.BooleanVar(value=bool(s.get("auto_recommend", True)))
        self.recursive_var = tk.BooleanVar(value=bool(s.get("recursive", True)))
        self.overwrite_var = tk.BooleanVar(value=bool(s.get("overwrite", True)))
        self.tex_overwrite_source_var = tk.BooleanVar(value=bool(s.get("tex_overwrite_source", False)))
        self.skip_same_var = tk.BooleanVar(value=bool(s.get("skip_same", True)))
        self.status_var = tk.StringVar(value=t("status.ready_texconv"))
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
        root.title(app_title())
        self._apply_icon()

        header = ttk.Frame(root)
        header.pack(fill="x", padx=16, pady=(12, 0))
        header.columnconfigure(0, weight=1)

        title_box = ttk.Frame(header)
        title_box.grid(row=0, column=0, sticky="w")
        self._text(ttk.Label(title_box, style="Header.TLabel"), "app.header").pack(anchor="w")
        self._text(
            ttk.Label(title_box, style="Subheader.TLabel"), "app.subtitle"
        ).pack(anchor="w", pady=(3, 0))

        # 语言开关放在标题右侧的空白处，远离所有操作控件。
        self._build_lang_switch(header).grid(
            row=0, column=1, sticky="ne", padx=(12, 0), pady=(2, 0)
        )

        self._build_body()

    def _text(self, widget, key: str, **kwargs):
        """登记一个静态文案控件，切换语言时自动重设文字。"""
        self._i18n_widgets.append((widget, key, kwargs))
        widget.configure(text=t(key, **kwargs))
        return widget

    def _build_lang_switch(self, parent) -> tk.Frame:
        """右上角的「中文 / EN」开关：两个小色块，点击即切换。"""
        holder = tk.Frame(
            parent, bg=self.root.cget("background"), bd=0, highlightthickness=0
        )
        for index, code in enumerate(i18n.LANGUAGES):
            chip = tk.Label(
                holder,
                text=i18n.LANGUAGE_NAMES[code],
                font=("Segoe UI", 9),
                padx=9,
                pady=1,
                bd=0,
                highlightthickness=0,
                cursor="hand2",
                takefocus=False,
            )
            chip.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0 if index == 0 else 3, 0),
            )
            chip.bind("<Button-1>", lambda _event, c=code: self.set_language(c))
            self.lang_chips[code] = chip
        self._paint_lang_switch()
        return holder

    def _paint_lang_switch(self) -> None:
        current = i18n.get_lang()
        for code, chip in self.lang_chips.items():
            active = code == current
            chip.configure(
                background="#7456a6" if active else "#e7e0f2",
                foreground="#ffffff" if active else "#4c356f",
                font=("Segoe UI", 9, "bold" if active else "normal"),
            )

    def _set_ready_status(self) -> None:
        if texlib.find_texconv():
            self.status_var.set(t("status.ready_texconv"))
        else:
            self.status_var.set(t("status.ready_download"))

    def _build_body(self) -> None:
        root = self.root
        main = ttk.Frame(root)
        main.pack(fill="both", expand=True, padx=14, pady=10)
        for col, weight in ((0, 0), (1, 1), (2, 0), (3, 0)):
            main.columnconfigure(col, weight=weight)
        main.rowconfigure(10, weight=1)

        drop = ttk.LabelFrame(main)
        self._text(drop, "drop.frame")
        drop.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        self.drop_label = ttk.Label(
            drop,
            text=t(self._drop_key),
            anchor="center", justify="center", font=("Segoe UI", 10),
        )
        self.drop_label.pack(fill="x", padx=14, pady=12)

        self.add_path_row(main, 1, "lbl.input", self.input_var, self.choose_input)
        self.add_path_row(main, 2, "lbl.output", self.output_var, self.choose_output)

        self._text(
            ttk.Label(main, foreground="#666666"), "hint.output"
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self._text(ttk.Label(main), "lbl.format").grid(row=4, column=0, sticky="w", pady=6)
        self.format_box = ttk.Combobox(
            main, textvariable=self.format_var,
            values=texlib.SUPPORTED_FORMATS, state="readonly", width=22,
        )
        self.format_box.grid(row=4, column=1, sticky="w", padx=8)
        ttk.Label(
            main,
            text="BC1 0x3420 · BC3 0x3431 · BC5 0x6230 · BC7 0x6432 · BGRA8 0x1450",
        ).grid(row=4, column=2, columnspan=2, sticky="w")

        self._text(ttk.Label(main), "lbl.size").grid(row=5, column=0, sticky="w", pady=6)
        self.size_box = ttk.Combobox(
            main, textvariable=self.size_var, values=size_labels(),
            state="readonly", width=22,
        )
        self.size_box.grid(row=5, column=1, sticky="w", padx=8)
        self._text(ttk.Label(main), "hint.size").grid(
            row=5, column=2, columnspan=2, sticky="w"
        )

        self._text(ttk.Label(main), "lbl.recommend").grid(
            row=6, column=0, sticky="nw", pady=6
        )
        rec = ttk.Frame(main)
        rec.grid(row=6, column=1, columnspan=3, sticky="ew", padx=8, pady=2)
        rec.columnconfigure(0, weight=1)
        # v1.0 在这里把 Label 和 Checkbutton 放进了同一个 grid 单元格，文字互相覆盖。
        ttk.Label(rec, textvariable=self.recommend_var, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self._text(
            ttk.Checkbutton(
                rec, variable=self.auto_recommend_var,
                command=self._on_auto_recommend_toggle,
            ),
            "chk.auto_recommend",
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        self._text(
            ttk.Button(rec, command=self.auto_recommend, width=22), "btn.recommend"
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Label(
            rec, textvariable=self.recommend_reason_var, foreground="#555555", wraplength=700
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self._text(ttk.Label(main), "lbl.quality").grid(row=7, column=0, sticky="w", pady=6)
        quality = ttk.Combobox(
            main, textvariable=self.quality_var, values=("q", "x"),
            state="readonly", width=22,
        )
        quality.grid(row=7, column=1, sticky="w", padx=8)
        self._text(ttk.Label(main), "hint.quality").grid(
            row=7, column=2, columnspan=2, sticky="w"
        )

        opts = ttk.Frame(main)
        opts.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(6, 8))
        self._text(
            ttk.Checkbutton(opts, variable=self.recursive_var), "chk.recursive"
        ).grid(row=0, column=0, sticky="w")
        self._text(
            ttk.Checkbutton(opts, variable=self.overwrite_var), "chk.overwrite"
        ).grid(row=0, column=1, sticky="w", padx=(18, 0))
        self._text(
            ttk.Checkbutton(opts, variable=self.tex_overwrite_source_var), "chk.tex_overwrite"
        ).grid(row=0, column=2, sticky="w", padx=(18, 0))
        self._text(
            ttk.Checkbutton(opts, variable=self.skip_same_var), "chk.skip_same"
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._text(ttk.Label(main), "lbl.log").grid(
            row=9, column=0, sticky="w", pady=(2, 4)
        )
        self._text(ttk.Button(main, command=self.clear_log, width=10), "btn.clear_log").grid(
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
            bottom, command=self.start, width=16, style="Primary.TButton"
        )
        self._text(self.start_button, "btn.start")
        self.start_button.grid(row=0, column=1, padx=4)
        self.tex_button = ttk.Button(bottom, command=self.choose_tex_files, width=21)
        self._text(self.tex_button, "btn.batch_tex")
        self.tex_button.grid(row=0, column=2, padx=4)
        self.cancel_button = ttk.Button(bottom, command=self.on_cancel, width=8, state="disabled")
        self._text(self.cancel_button, "btn.cancel")
        self.cancel_button.grid(row=0, column=3, padx=4)
        self._text(
            ttk.Button(bottom, command=self.open_output, width=19), "btn.open_output"
        ).grid(row=0, column=4, padx=(4, 0))

        self.root.update_idletasks()
        # 拖放是否可用决定这里显示哪段文字；切换语言时按同一个键重设。
        self._drop_key = (
            "drop.text"
            if enable_windows_drop(self.root.winfo_id(), self.on_drop)
            else "drop.text_disabled"
        )
        self.drop_label.configure(text=t(self._drop_key))

        self._set_ready_status()
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

    def add_path_row(self, parent, row, key: str, var, command) -> None:
        self._text(ttk.Label(parent), key).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=8)
        self._text(ttk.Button(parent, command=command, width=8), "btn.browse").grid(
            row=row, column=2, sticky="w"
        )

    # -- 语言 -------------------------------------------------------------
    def set_language(self, lang: str) -> None:
        """切换界面语言，并立刻写进设置文件（下次启动沿用）。"""
        lang = i18n.normalize(lang)
        if lang == i18n.get_lang():
            self._paint_lang_switch()
            return

        # 尺寸下拉是「显示文案」，换语言前先记下它代表的长边像素。
        size_target = size_target_from_label(self.size_var.get())
        i18n.set_lang(lang)

        for widget, key, kwargs in self._i18n_widgets:
            try:
                widget.configure(text=t(key, **kwargs))
            except Exception:
                continue
        self.root.title(app_title())
        self.size_box.configure(values=size_labels())
        self.size_var.set(size_label(size_target))
        self.drop_label.configure(text=t(self._drop_key))
        self._paint_lang_switch()

        # 正在转换时状态栏由进度回调持续改写，这里不要抢它的内容。
        if not self.running:
            self._set_ready_status()
        if self.input_var.get().strip():
            self._refresh_recommendation()
        else:
            self.recommend_var.set(t("rec.none"))
            self.recommend_reason_var.set(t("rec.placeholder"))

        error = save_settings(
            {**self._settings_snapshot(), "geometry": self.root.geometry()}
        )
        if error:
            log_exception(f"保存语言设置失败：{error}")

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
        path = filedialog.askdirectory(title=t("dlg.input"))
        if path:
            self.input_var.set(path)
            self._refresh_recommendation()

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title=t("dlg.output"))
        if path:
            self.output_var.set(path)

    def _on_auto_recommend_toggle(self) -> None:
        self._refresh_recommendation()

    def _refresh_recommendation(self) -> None:
        if not self.auto_recommend_var.get():
            self.recommend_var.set(t("rec.disabled"))
            self.recommend_reason_var.set(t("rec.disabled_reason"))
            return
        raw = self.input_var.get().strip()
        if raw and Path(raw).is_file() and Path(raw).suffix.lower() == ".png":
            self._show_recommendation(Path(raw))
            return
        # 目录不在这里扫描：几千个文件会让「选择文件夹」卡住。
        self.recommend_var.set(t("rec.by_name"))
        self.recommend_reason_var.set(t("rec.by_name_reason"))

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
            messagebox.showinfo(app_title(), t("msg.pick_png_first"))
            return
        pngs, _tex = scan_paths([raw], self.recursive_var.get())
        if not pngs:
            messagebox.showinfo(app_title(), t("msg.no_png"))
            return
        fmt, _reason = self._show_recommendation(pngs[0], apply=True)
        self.log_line("info", t("log.recommend", name=pngs[0].name, fmt=fmt))

    # -- 拖放 -------------------------------------------------------------
    def on_drop(self, paths) -> None:
        if self.running:
            self.log_line("warn", t("drop.busy"))
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
            self.log_line("warn", t("drop.noitems"))
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
            # 上次选的语言要记住，下次启动直接沿用。
            "lang": i18n.get_lang(),
        }

    def _launch(self, pngs: list[Path], texes: list[Path]) -> None:
        if self.running or (not pngs and not texes):
            return
        if texes and self.tex_overwrite_source_var.get():
            if not messagebox.askyesno(
                app_title(),
                t("msg.overwrite_tex", n=len(texes)),
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
        self.status_var.set(t("status.preparing"))
        self.log_line("head", t("log.start", png=len(pngs), tex=len(texes)))
        if settings["auto_recommend"] and pngs:
            self.log_line("info", t("log.auto_recommend_on"))
        if settings["output"]:
            self.log_line("info", t("log.output_dir", path=settings["output"]))
        else:
            self.log_line("info", t("log.output_empty"))

        threading.Thread(
            target=self.worker, args=(pngs, texes, run_settings), daemon=True
        ).start()

    def worker(self, pngs: list[Path], texes: list[Path], settings: dict) -> None:
        started = time.perf_counter()
        log = lambda kind, text: self.q.put(("log", (kind, text)))  # noqa: E731

        try:
            jobs, stats = self.build_jobs(pngs, texes, settings, log)
        except Exception as exc:
            log("err", t("log.build_failed", err=exc))
            self.q.put(("done", RunStats(elapsed=time.perf_counter() - started)))
            return

        if not jobs:
            stats.elapsed = time.perf_counter() - started
            self.q.put(("done", stats))
            return

        try:
            texconv = texlib.ensure_texconv(lambda m: log("info", m))
            log("info", t("log.texconv", path=texconv))
        except Exception as exc:
            log("err", t("log.texconv_failed", err=exc))
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
                log("warn", t("log.skip_bad_png", name=png.name))
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
                log("warn", t("log.skip_exists", name=dst.name))
                continue
            if len(str(dst)) > 250:
                log("warn", t("log.long_path", path=dst))

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
                log("warn", t("log.skip_bad_tex", name=tex.name, err=exc))
                continue

            if skip_same and info.fmt_name == manual_format and not target:
                stats.skipped += 1
                log("info", t("log.skip_same", fmt=manual_format, name=tex.name))
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
                log("warn", t("log.skip_exists", name=dst.name))
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
            log("warn", t("log.bc1_alpha", n=bc1_alpha))
        if stats.skipped:
            log("info", t("log.skipped", n=stats.skipped, m=len(jobs)))
        if not jobs:
            log("warn", t("log.nothing_to_do"))
        return jobs, stats

    # -- 按钮动作 ---------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        raw = self.input_var.get().strip()
        if not raw:
            messagebox.showwarning(app_title(), t("msg.pick_input"))
            return
        pngs, _tex = scan_paths([raw], self.recursive_var.get())
        if not pngs:
            messagebox.showwarning(app_title(), t("msg.input_no_png"))
            return
        self._show_recommendation(pngs[0])
        self._launch(pngs, [])

    def choose_tex_files(self) -> None:
        if self.running:
            messagebox.showinfo(app_title(), t("msg.busy_wait"))
            return
        files = filedialog.askopenfilenames(
            title=t("dlg.tex_files"),
            filetypes=[("FFXIV TEX", "*.tex *.TEX"), (t("dlg.all_files"), "*.*")],
        )
        if not files:
            return
        texes = [Path(x) for x in files if Path(x).is_file() and Path(x).suffix.lower() == ".tex"]
        if not texes:
            messagebox.showwarning(app_title(), t("msg.no_tex"))
            return
        self._launch([], texes)

    def on_cancel(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set(t("status.cancelling"))

    def open_output(self) -> None:
        target = self.output_var.get().strip() or self.input_var.get().strip()
        if not target:
            messagebox.showinfo(app_title(), t("msg.no_folders"))
            return
        path = Path(target)
        if path.is_file():
            path = path.parent
        if not path.exists():
            messagebox.showinfo(app_title(), t("msg.folder_missing"))
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror(app_title(), t("msg.open_failed", err=exc))

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
        text = t("status.running", done=done, total=total, elapsed=f"{elapsed:.0f}")
        if rate:
            text += t("status.eta", eta=f"{eta:.0f}")
        self.status_var.set(text)

    def _on_done(self, stats: RunStats) -> None:
        self._set_running(False)
        if stats.cancelled == 0:
            self.progress_var.set(100 if stats.total else 0)
            self.percent_var.set("100%" if stats.total else "0%")
        state = t("status.state_cancelled") if stats.cancelled else t("status.state_done")
        self.status_var.set(
            t("status.done", state=state, summary=stats.summary(),
              elapsed=f"{stats.elapsed:.1f}")
        )
        self.log_line(
            "warn" if stats.failed or stats.cancelled else "ok",
            t("log.summary_line", summary=stats.summary(), elapsed=f"{stats.elapsed:.1f}"),
        )

    def on_close(self) -> None:
        try:
            if self.running:
                if not messagebox.askyesno(app_title(), t("msg.confirm_exit")):
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
        "size": size_label(None),
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
        log("err", t("log.convert_failed", err=exc))
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
    # 先把上次选的语言装好：无界面模式（--selftest / --convert）的日志也跟着走。
    i18n.set_lang(load_settings().get("lang"))

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
            messagebox.showerror(
                app_title(),
                t("msg.startup_failed", log=LOG_FILE, err=exc),
                parent=root,
            )
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
