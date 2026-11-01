# -*- coding: utf-8 -*-
# FF14 Tex Converter — Copyright (C) 2026 MaellaKnows
# Licensed under the GNU General Public License v3.0; see LICENSE.
# Additional terms under GPLv3 §7 apply: see ADDITIONAL-TERMS.md
"""FFXIV TEX <-> DDS 转换核心库，与 Tk 界面解耦。

本模块只做四件事：
  1. 描述 FFXIV TEX 头与 DXGI/BC 格式的对应关系；
  2. 在 DDS 与 FFXIV TEX 之间做无头（不复制 DDS 头）的双向转换；
  3. 批量调用 Microsoft DirectXTex 的 texconv.exe；
  4. 给出按文件名推断 FFXIV 贴图格式的推荐。

与 v1.0 相比的关键改动：
  * texconv 支持一次传入多个输入文件，因此批量转换不再「每个文件启动一次
    进程」。实测 24 张小图从 12.2s 降到 1.2s（约 10 倍）。
  * DDS/TEX 全程流式读写，不再把整个文件读进内存（4096 贴图省几十 MB）。
  * 单个批次失败时会自动退化为逐文件重试，以定位真正的出错文件。
  * 所有 TEX 写入都是「临时文件 + 原子替换」，中途取消/崩溃不会留下半个文件。
  * 支持取消：正在运行的 texconv 进程会被终止。
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import i18n

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TEX_HEADER_SIZE = 80
TEX_ATTRIBUTE_2D = 0x00800000
MAX_TEX_MIPS = 13          # 头部只有 13 个 mip 偏移槽位

FORMAT_BGRA8 = 0x1450
FORMAT_BC1 = 0x3420
FORMAT_BC3 = 0x3431
FORMAT_BC5 = 0x6230
FORMAT_BC7 = 0x6432

DXGI_B8G8R8A8_UNORM = 87
DXGI_BC1_UNORM = 71
DXGI_BC3_UNORM = 77
DXGI_BC5_UNORM = 83
DXGI_BC7_UNORM = 98

#: 格式名 -> (DXGI, FFXIV TEX 格式 ID, 简称, 每 4x4 块的字节数)
FORMAT_INFO = {
    "B8G8R8A8_UNORM": (DXGI_B8G8R8A8_UNORM, FORMAT_BGRA8, "BGRA8", 4),
    "BC1_UNORM": (DXGI_BC1_UNORM, FORMAT_BC1, "BC1", 8),
    "BC3_UNORM": (DXGI_BC3_UNORM, FORMAT_BC3, "BC3", 16),
    "BC5_UNORM": (DXGI_BC5_UNORM, FORMAT_BC5, "BC5", 16),
    "BC7_UNORM": (DXGI_BC7_UNORM, FORMAT_BC7, "BC7", 16),
}

SUPPORTED_FORMATS = ("BC7_UNORM", "BC5_UNORM", "BC3_UNORM", "BC1_UNORM", "B8G8R8A8_UNORM")

TEX_FORMAT_TO_NAME = {v[1]: k for k, v in FORMAT_INFO.items()}

# texconv 一次调用可处理的文件数上限。数值越大进程启动开销摊得越薄，
# 但单批耗时变长、进度条跳动也越粗。16 是实测的质量/速度平衡点。
DEFAULT_BATCH_SIZE = 16

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TEXCONV_VERSION = "2026.5.8"
TEXCONV_URLS = (
    "https://github.com/Microsoft/DirectXTex/releases/download/may2026/texconv.exe",
    "https://github.com/Microsoft/DirectXTex/releases/latest/download/texconv.exe",
    "https://www.nuget.org/api/v2/package/Microsoft.DirectXTex.Texconv/" + TEXCONV_VERSION,
)
TEXCONV_MIN_SIZE = 100_000


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def human_size(n: int) -> str:
    """1023 -> '1023 B'，2048 -> '2.0 KB'，…"""
    if n < 1024:
        return f"{n} B"
    kb = n / 1024.0
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024.0
    if mb < 1024:
        return f"{mb:.2f} MB"
    return f"{mb / 1024.0:.2f} GB"


def _decode_console(raw: bytes) -> str:
    """texconv 的错误信息是系统 OEM 代码页，直接 UTF-8 解码会变乱码。"""
    for enc in ("utf-8", "mbcs", "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _clean_texconv_output(text: str) -> list[str]:
    lines = []
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("Microsoft (R) DirectX Texture Converter"):
            continue
        if line.startswith("Copyright (C) Microsoft"):
            continue
        lines.append(line)
    return lines


def _error_excerpt(text: str, limit: int = 3) -> str:
    lines = _clean_texconv_output(text)
    if not lines:
        return i18n.t("err.no_output")
    picked = [l for l in lines if "FAILED" in l.upper() or "ERROR" in l.upper()]
    return " / ".join((picked or lines)[-limit:])


def calc_mip_count(width: int, height: int) -> int:
    """完整 mip 链的层数。"""
    n = 1
    while width > 1 or height > 1:
        width = max(1, width // 2)
        height = max(1, height // 2)
        n += 1
    return n


def bc_mip_size(width: int, height: int, block_bytes: int) -> int:
    bx = max(1, (width + 3) // 4)
    by = max(1, (height + 3) // 4)
    return bx * by * block_bytes


def expected_mip_sizes(width: int, height: int, dxgi: int, levels: int) -> list[int]:
    """按 DXGI 格式推算每一级 mip 的字节数。"""
    if levels < 1:
        raise ValueError(i18n.t("err.bad_mip_count"))
    out: list[int] = []
    w, h = width, height
    for _ in range(levels):
        if dxgi == DXGI_B8G8R8A8_UNORM:
            out.append(w * h * 4)
        elif dxgi == DXGI_BC1_UNORM:
            out.append(bc_mip_size(w, h, 8))
        elif dxgi in (DXGI_BC3_UNORM, DXGI_BC5_UNORM, DXGI_BC7_UNORM):
            out.append(bc_mip_size(w, h, 16))
        else:
            raise ValueError(i18n.t("err.unsupported_dxgi", dxgi=dxgi))
        w = max(1, w // 2)
        h = max(1, h // 2)
    return out


def _cancelled(cancel) -> bool:
    return cancel is not None and cancel.is_set()


def _copy_exact(src, dst, count: int, bufsize: int = 1 << 20) -> None:
    """从 src 精确复制 count 字节到 dst。"""
    left = count
    while left > 0:
        chunk = src.read(min(bufsize, left))
        if not chunk:
            raise ValueError(i18n.t("err.incomplete_data", left=f"{left:,}"))
        dst.write(chunk)
        left -= len(chunk)


# ---------------------------------------------------------------------------
# 尺寸计算
# ---------------------------------------------------------------------------

def fit_long_edge(width: int, height: int, target: int) -> tuple[int, int]:
    """把长边缩放到 target，保持宽高比，并把两边对齐到 4 的倍数。

    v1.0 直接把 `-w N -h N` 传给 texconv，非正方形贴图（例如 1024x512 的
    UI 图集）会被强行拉成正方形。这里按长边等比缩放。
    """
    if width <= 0 or height <= 0:
        raise ValueError(i18n.t("err.bad_size"))
    if target <= 0:
        raise ValueError(i18n.t("err.bad_target_size"))
    if width >= height:
        nw, nh = target, int(round(height * target / width))
    else:
        nw, nh = int(round(width * target / height)), target
    nw = max(4, (nw + 2) // 4 * 4)
    nh = max(4, (nh + 2) // 4 * 4)
    return nw, nh


def parse_target_size(text: str) -> int | None:
    """把界面上的尺寸选项解析成长边像素；'原尺寸' -> None。

    兼容 v1.0 保存的 "1024×1024" 这类旧设置。
    """
    if not text:
        return None
    if text.strip() == "原尺寸":
        return None
    m = re.search(r"\d+", text)
    if not m:
        return None
    value = int(m.group())
    return value if value >= 4 else None


# ---------------------------------------------------------------------------
# PNG / TEX 头读取（只读几十字节，不做完整解码）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    has_alpha: bool | None = None


def png_info(path: Path) -> ImageInfo | None:
    """读 PNG 的 IHDR，返回尺寸与是否带 Alpha 通道。失败返回 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(33)
    except OSError:
        return None
    if len(head) < 33 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack_from(">II", head, 16)
    color_type = head[25]
    bit_depth = head[24]
    has_alpha = color_type in (4, 6) or bit_depth == 16 and color_type in (4, 6)
    return ImageInfo(width, height, has_alpha)


@dataclass(frozen=True)
class TexInfo:
    width: int
    height: int
    depth: int
    levels: int
    attribute: int
    tex_format: int
    fmt_name: str | None
    size: int

    def describe(self) -> str:
        name = self.fmt_name or f"0x{self.tex_format:04X}"
        return f"{name}, {self.width}x{self.height}, {self.levels} mip"


def read_tex_header(data: bytes) -> tuple[int, int, int, int, int, int]:
    """解析 80 字节 TEX 头 -> (attribute, tex_format, w, h, depth, levels)。"""
    if len(data) < TEX_HEADER_SIZE:
        raise ValueError(i18n.t("err.too_small"))
    attribute, tex_format, width, height, depth, levels = struct.unpack_from(
        "<IIHHHH", data, 0
    )
    if width < 1 or height < 1 or depth < 1:
        raise ValueError(i18n.t("err.bad_tex_size"))
    if levels < 1 or levels > MAX_TEX_MIPS:
        raise ValueError(i18n.t("err.bad_tex_mips", levels=levels))
    return attribute, tex_format, width, height, depth, levels


def tex_info(path: Path) -> TexInfo:
    with open(path, "rb") as f:
        head = f.read(TEX_HEADER_SIZE)
    attribute, tex_format, width, height, depth, levels = read_tex_header(head)
    return TexInfo(
        width=width,
        height=height,
        depth=depth,
        levels=levels,
        attribute=attribute,
        tex_format=tex_format,
        fmt_name=TEX_FORMAT_TO_NAME.get(tex_format),
        size=path.stat().st_size,
    )


# ---------------------------------------------------------------------------
# DDS -> TEX
# ---------------------------------------------------------------------------

def _parse_dds_header(head: bytes, expected_format: str) -> tuple[int, int, int, int, list[int]]:
    """校验 texconv 输出的 DDS 头，返回 (payload_offset, w, h, levels, mip_sizes)。

    DDS 只是中间产物：格式由我们传给 texconv 的 `-f` 决定，这里只做一致性校验，
    不会去猜用户 PNG 的格式。
    """
    if len(head) < 128 or head[:4] != b"DDS ":
        raise ValueError(i18n.t("err.not_dds"))

    height, width = struct.unpack_from("<II", head, 12)
    levels = struct.unpack_from("<I", head, 28)[0] or 1
    pf_fourcc = struct.unpack_from("<I", head, 84)[0]

    try:
        expected_dxgi, _, _, _ = FORMAT_INFO[expected_format]
    except KeyError:
        raise ValueError(i18n.t("err.unsupported_output", fmt=expected_format))

    payload_offset = 128
    actual_dxgi = None
    if pf_fourcc == 0x30315844:  # "DX10"
        if len(head) < 148:
            raise ValueError(i18n.t("err.dx10_header"))
        actual_dxgi = struct.unpack_from("<I", head, 128)[0]
        payload_offset = 148

    legacy_dxgi = {
        0x31545844: DXGI_BC1_UNORM,  # DXT1
        0x35545844: DXGI_BC3_UNORM,  # DXT5
        0x32495441: DXGI_BC5_UNORM,  # ATI2
    }
    if actual_dxgi is None and pf_fourcc in legacy_dxgi:
        actual_dxgi = legacy_dxgi[pf_fourcc]

    if actual_dxgi is None:
        pf_flags = struct.unpack_from("<I", head, 80)[0]
        pf_rgbbitcount = struct.unpack_from("<I", head, 88)[0]
        if pf_rgbbitcount == 32 and pf_flags & 0x40:
            rmask, gmask, bmask, amask = struct.unpack_from("<IIII", head, 92)
            if (rmask, gmask, bmask, amask) == (
                0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000
            ):
                actual_dxgi = DXGI_B8G8R8A8_UNORM

    if actual_dxgi is not None and actual_dxgi != expected_dxgi:
        raise ValueError(
            i18n.t(
                "err.format_mismatch",
                actual=actual_dxgi,
                expected=expected_format,
                want=expected_dxgi,
            )
        )

    sizes = expected_mip_sizes(width, height, expected_dxgi, levels)
    return payload_offset, width, height, levels, sizes


def build_tex_header(width: int, height: int, levels: int, tex_format: int,
                     mip_sizes: Sequence[int]) -> bytes:
    if levels > MAX_TEX_MIPS:
        raise ValueError(
            i18n.t("err.mip_overflow", levels=levels, max=MAX_TEX_MIPS)
        )
    # FFXIV 的 offset_to_surface 记录的是每一级 mip 的「起始偏移」，不是结尾偏移。
    offsets: list[int] = []
    current = TEX_HEADER_SIZE
    for size in mip_sizes:
        offsets.append(current)
        current += size
    offsets += [0] * (MAX_TEX_MIPS - len(offsets))

    header = struct.pack(
        "<IIHHHH",
        TEX_ATTRIBUTE_2D,
        tex_format,
        width,
        height,
        1,
        levels,
    )
    header += struct.pack("<III", 0, 1, 2)
    header += struct.pack(f"<{MAX_TEX_MIPS}I", *offsets)
    if len(header) != TEX_HEADER_SIZE:
        raise AssertionError(i18n.t("err.tex_header_len"))
    return header


def dds_to_tex(dds_path: Path, tex_path: Path, expected_format: str) -> int:
    """把 texconv 产出的 DDS 封装成 FFXIV TEX，返回写入的字节数。"""
    _, tex_format, _, _ = FORMAT_INFO[expected_format]
    tex_path = Path(tex_path)
    dds_path = Path(dds_path)

    with open(dds_path, "rb") as src:
        head = src.read(148)
        offset, width, height, levels, sizes = _parse_dds_header(head, expected_format)
        payload_size = sum(sizes)

        src.seek(0, os.SEEK_END)
        total = src.tell()
        if total < offset + payload_size:
            raise ValueError(
                i18n.t(
                    "err.dds_short",
                    need=f"{payload_size:,}",
                    have=f"{max(0, total - offset):,}",
                )
            )

        header = build_tex_header(width, height, levels, tex_format, sizes)

        tex_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = tex_path.with_name(f"{tex_path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp_path, "wb") as dst:
                dst.write(header)
                src.seek(offset)
                _copy_exact(src, dst, payload_size)
            if tmp_path.stat().st_size != TEX_HEADER_SIZE + payload_size:
                raise ValueError(i18n.t("err.tex_len_check"))
            os.replace(tmp_path, tex_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
    return TEX_HEADER_SIZE + payload_size


# ---------------------------------------------------------------------------
# TEX -> DDS
# ---------------------------------------------------------------------------

def tex_to_dds(tex_path: Path, dds_path: Path) -> TexInfo:
    """把 FFXIV TEX 的负载包进 DX10 DDS 头，供 texconv 处理。"""
    tex_path = Path(tex_path)
    dds_path = Path(dds_path)

    with open(tex_path, "rb") as src:
        head = src.read(TEX_HEADER_SIZE)
        attribute, tex_format, width, height, depth, levels = read_tex_header(head)
        if depth not in (1, 0):
            raise ValueError(i18n.t("err.tex3d", depth=depth))
        if tex_format not in TEX_FORMAT_TO_NAME:
            raise ValueError(
                i18n.t("err.tex_format", fmt=f"{tex_format:04X}")
            )
        fmt_name = TEX_FORMAT_TO_NAME[tex_format]
        dxgi = FORMAT_INFO[fmt_name][0]

        offsets = struct.unpack_from(f"<{MAX_TEX_MIPS}I", head, 28)
        start = offsets[0] or TEX_HEADER_SIZE
        if start < TEX_HEADER_SIZE:
            raise ValueError(i18n.t("err.tex_offset"))

        sizes = expected_mip_sizes(width, height, dxgi, levels)
        payload_size = sum(sizes)
        src.seek(0, os.SEEK_END)
        total = src.tell()
        if start + payload_size > total:
            raise ValueError(
                i18n.t(
                    "err.tex_short",
                    need=f"{payload_size:,}",
                    have=f"{max(0, total - start):,}",
                )
            )

        flags = 0x0002100F  # CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE
        caps = 0x1000      # TEXTURE
        if levels > 1:
            caps |= 0x8 | 0x400000  # COMPLEX | MIPMAP

        header = bytearray(b"DDS ")
        header += struct.pack("<7I", 124, flags, height, width, sizes[0], 0, levels)
        header += struct.pack("<11I", *([0] * 11))
        header += struct.pack("<8I", 32, 0x4, 0x30315844, 0, 0, 0, 0, 0)  # FOURCC DX10
        header += struct.pack("<5I", caps, 0, 0, 0, 0)
        header += struct.pack("<5I", dxgi, 3, 0, 1, 0)  # DIMENSION_TEXTURE2D
        if len(header) != 148:
            raise AssertionError(i18n.t("err.dds_header_len", n=len(header)))

        dds_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dds_path, "wb") as dst:
            dst.write(header)
            src.seek(start)
            _copy_exact(src, dst, payload_size)

    return TexInfo(
        width=width,
        height=height,
        depth=depth,
        levels=levels,
        attribute=attribute,
        tex_format=tex_format,
        fmt_name=fmt_name,
        size=tex_path.stat().st_size,
    )


# ---------------------------------------------------------------------------
# texconv 定位 / 下载
# ---------------------------------------------------------------------------

def app_dir() -> Path:
    """程序所在目录（兼容 PyInstaller 单文件模式）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_texconv() -> Path | None:
    """按优先级查找 texconv.exe。"""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "tools" / "texconv.exe",
        here / "texconv.exe",
        app_dir() / "tools" / "texconv.exe",
        app_dir() / "texconv.exe",
        Path.cwd() / "tools" / "texconv.exe",
        Path(getattr(sys, "_MEIPASS", here)) / "tools" / "texconv.exe",
    ]
    which = shutil.which("texconv.exe")
    if which:
        candidates.append(Path(which))
    for p in candidates:
        try:
            if p.is_file() and p.stat().st_size > 10_000:
                return p
        except OSError:
            continue
    return None


def _download(url: str, progress: Callable[[str], None] | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "FFXIV-TEX-Converter"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        total = int(resp.headers.get("Content-Length", "0") or 0)
        buf = bytearray()
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            if progress and total:
                progress(i18n.t("log.download_pct", pct=f"{len(buf) / total * 100:.0f}"))
    return bytes(buf)


def download_texconv(dest: Path, progress: Callable[[str], None] | None = None) -> Path:
    """从官方 GitHub Release 下载 texconv.exe（NuGet 作为兜底）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in TEXCONV_URLS:
        try:
            if progress:
                progress(i18n.t("log.downloading", url=url))
            data = _download(url, progress)
            if url.lower().endswith(".nupkg"):
                tmp = dest.with_suffix(".nupkg")
                tmp.write_bytes(data)
                try:
                    with zipfile.ZipFile(tmp) as z:
                        names = [n for n in z.namelist() if n.lower().endswith("texconv.exe")]
                        if not names:
                            raise RuntimeError(i18n.t("err.no_texconv_in_nupkg"))
                        names.sort(key=lambda n: (0 if "win-x64" in n.lower() else 1, len(n)))
                        with z.open(names[0]) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
                finally:
                    tmp.unlink(missing_ok=True)
            else:
                if data[:2] != b"MZ" or len(data) < TEXCONV_MIN_SIZE:
                    raise RuntimeError(i18n.t("err.bad_download"))
                dest.write_bytes(data)
            if dest.is_file() and dest.stat().st_size >= TEXCONV_MIN_SIZE:
                return dest
            raise RuntimeError(i18n.t("err.texconv_verify"))
        except Exception as exc:  # 换下一个源
            errors.append(f"{url} -> {exc}")
    raise RuntimeError(i18n.t("err.download_failed", errors="\n".join(errors)))


def ensure_texconv(progress: Callable[[str], None] | None = None) -> Path:
    found = find_texconv()
    if found:
        return found
    return download_texconv(app_dir() / "tools" / "texconv.exe", progress)


# ---------------------------------------------------------------------------
# 格式推荐
# ---------------------------------------------------------------------------

def recommend_format_for_name(name: str) -> tuple[str, str]:
    """按文件名推断 FFXIV 贴图用途，返回 (格式, 理由)。"""
    stem = Path(name).stem.lower()
    tokens = set(re.split(r"[^a-z0-9]+", stem))
    compact = "_" + re.sub(r"[^a-z0-9]+", "_", stem) + "_"

    # FFXIV 的法线贴图可能用 B 通道存透明度，不能盲目用 BC5。
    if (
        "normal" in tokens or "normalmap" in tokens or "norm" in tokens
        or "nrm" in tokens or "_n_" in compact or compact.endswith("_n_")
        or stem.endswith("_n")
    ):
        return "BC7_UNORM", i18n.t("rec.normal")

    if (
        "rg" in tokens or "rgmap" in tokens or "2channel" in tokens
        or "twochannel" in tokens or stem.endswith("_rg")
    ):
        return "BC5_UNORM", i18n.t("rec.rg")

    if (
        "mask" in tokens or "maskmap" in tokens or "msk" in tokens
        or "roughness" in tokens or "specular" in tokens or "ao" in tokens
        or stem.endswith("_m") or "_m_" in compact
    ):
        return "BC7_UNORM", i18n.t("rec.mask")

    diffuse_name = (
        "diffuse" in stem
        or "albedo" in stem
        or "basecolor" in stem
        or "base_color" in stem
        or "base" in tokens
        or "color" in tokens
        or "colour" in tokens
        or stem.endswith("_d")
        or "_d_" in compact
    )
    if diffuse_name:
        return "BC1_UNORM", i18n.t("rec.diffuse")

    if (
        "icon" in tokens or "ui" in tokens or "atlas" in tokens
        or "decal" in tokens or "effect" in tokens or "vfx" in tokens
    ):
        return "BC7_UNORM", i18n.t("rec.ui")

    if "opaque" in tokens or "noalpha" in tokens or "solid" in tokens:
        return "BC1_UNORM", i18n.t("rec.opaque")

    return "BC7_UNORM", i18n.t("rec.unknown")


# ---------------------------------------------------------------------------
# 转换任务
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """一个待转换文件。"""
    src: Path
    dst: Path
    fmt: str
    kind: str = "png"              # "png" | "tex"
    quality: str = "q"
    resize: tuple[int, int] | None = None
    src_desc: str = ""             # 日志里显示的源信息
    prepared: Path | None = None   # 实际交给 texconv 的输入（TEX 会先转成 DDS）


@dataclass
class RunStats:
    total: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: int = 0
    elapsed: float = 0.0

    def summary(self) -> str:
        parts = [i18n.t("sum.ok", n=self.ok), i18n.t("sum.failed", n=self.failed)]
        if self.skipped:
            parts.append(i18n.t("sum.skipped", n=self.skipped))
        if self.cancelled:
            parts.append(i18n.t("sum.cancelled", n=self.cancelled))
        return " / ".join(parts)


class TexConverter:
    """把一批 Job 交给 texconv 批量处理。

    调用方提供三个回调：
      log(kind, text)        kind in {"info","ok","warn","err"}
      progress(done, total)  每完成一个文件调用一次
      cancel                 threading.Event，被 set 时终止当前 texconv
    """

    def __init__(self, texconv: Path, batch_size: int = DEFAULT_BATCH_SIZE):
        self.texconv = Path(texconv)
        self.batch_size = max(1, int(batch_size))

    # -- 对外入口 ---------------------------------------------------------
    def run(
        self,
        jobs: Sequence[Job],
        *,
        log: Callable[[str, str], None] = lambda kind, text: None,
        progress: Callable[[int, int], None] = lambda done, total: None,
        cancel: threading.Event | None = None,
        temp_parent: Path | None = None,
    ) -> RunStats:
        stats = RunStats(total=len(jobs))
        started = time.perf_counter()
        if not jobs:
            stats.elapsed = time.perf_counter() - started
            return stats

        tmp = self._make_temp(temp_parent)
        done = 0
        total = len(jobs)
        try:
            in_dir = tmp / "in"
            in_dir.mkdir(parents=True, exist_ok=True)

            batches = list(self._make_batches(sorted(jobs, key=lambda j: j.fmt)))
            for index, batch in enumerate(batches, 1):
                if _cancelled(cancel):
                    break

                ready, done = self._prepare_batch(
                    batch, in_dir, stats, log, done, total, progress
                )
                if not ready:
                    continue

                out_dir = tmp / "out" / f"{index:04d}"
                out_dir.mkdir(parents=True, exist_ok=True)
                rc, output = self._run_texconv(self._build_args(ready, out_dir), cancel)

                if rc is None:      # 用户在 texconv 运行时取消
                    break
                if rc != 0:
                    self._isolate_failures(ready, out_dir, cancel, output, log)

                for job in ready:
                    if _cancelled(cancel):
                        break
                    ok, text = self._finish_job(job, out_dir)
                    done += 1
                    if ok:
                        stats.ok += 1
                        log("ok", text)
                    else:
                        stats.failed += 1
                        log("err", text)
                    progress(done, total)
                if _cancelled(cancel):
                    break
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # 没有走完的任务都算「已取消」，不重复计数。
        stats.cancelled = max(0, total - done)
        stats.elapsed = time.perf_counter() - started
        return stats

    # -- 内部实现 ---------------------------------------------------------
    def _make_temp(self, parent: Path | None) -> Path:
        """找一个子进程确实能写入的临时目录，返回新建的临时根目录。"""
        candidates: list[Path | None] = [parent, None, Path.cwd()]
        last_error: Exception | None = None
        for cand in candidates:
            try:
                root = Path(tempfile.mkdtemp(prefix="ffxiv_tex_", dir=str(cand) if cand else None))
                probe = root / ".probe"
                probe.write_bytes(b"0")
                probe.unlink()
                return root
            except OSError as exc:
                last_error = exc
        raise RuntimeError(i18n.t("err.no_temp", err=last_error))

    def _make_batches(self, jobs: Sequence[Job]) -> Iterable[list[Job]]:
        """把任务切成批次：同一格式、同一质量、文件名不重复。

        同名文件（不同子目录下的 body_d.png）不能同批，否则 texconv 会互相覆盖。
        """
        i, n = 0, len(jobs)
        while i < n:
            first = jobs[i]
            i += 1
            batch = [first]
            if first.resize is None:
                stems = {first.src.stem.lower()}
                while i < n:
                    nxt = jobs[i]
                    if (
                        nxt.resize is not None
                        or nxt.fmt != first.fmt
                        or nxt.quality != first.quality
                        or len(batch) >= self.batch_size
                        or nxt.src.stem.lower() in stems
                    ):
                        break
                    stems.add(nxt.src.stem.lower())
                    batch.append(nxt)
                    i += 1
            yield batch

    def _prepare_batch(self, batch, in_dir, stats, log, done, total, progress):
        """TEX 输入先转成 DDS；失败的任务在进入 texconv 前就被剔除。

        返回 (ready_jobs, done)。
        """
        ready: list[Job] = []
        for job in batch:
            try:
                if job.kind == "tex":
                    job.prepared = in_dir / f"{job.src.stem}.dds"
                    tex_to_dds(job.src, job.prepared)
                else:
                    job.prepared = job.src
                ready.append(job)
            except Exception as exc:
                done += 1
                stats.failed += 1
                log("err", i18n.t("log.job_failed", name=job.src.name, err=exc))
                progress(done, total)
        return ready, done

    def _build_args(self, batch: Sequence[Job], out_dir: Path) -> list[str]:
        first = batch[0]
        args = [
            str(self.texconv),
            "-f", first.fmt,
            "-m", "0",          # 生成完整 mip 链，FFXIV 需要
            "-ft", "dds",
            "-y",
            "-o", str(out_dir),
        ]
        if first.fmt == "BC7_UNORM" and first.quality:
            args += ["-bc", first.quality]
        if first.fmt == "BC1_UNORM":
            # FFXIV 的 BC1(0x3420) 是不透明格式。texconv 默认按 0.5 阈值把
            # Alpha 写成 1 bit，被判定为透明的像素颜色会被抹成黑色 —— 在游戏里
            # 就是一块块黑斑。这里把阈值压到 0，让 BC1 按不透明压缩、保留颜色。
            args += ["-at", "0"]
        if first.resize:
            args += ["-w", str(first.resize[0]), "-h", str(first.resize[1]), "-if", "FANT"]
        args += [str(j.prepared) for j in batch]
        return args

    def _run_texconv(self, args: list[str], cancel) -> tuple[int | None, str]:
        """运行 texconv，并允许中途取消。返回 (returncode|None, 输出文本)。"""
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )
        while True:
            try:
                out, _ = proc.communicate(timeout=0.2)
                return proc.returncode, _decode_console(out or b"")
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    try:
                        out, _ = proc.communicate(timeout=5)
                    except Exception:
                        out = b""
                    return None, _decode_console(out or b"")

    def _isolate_failures(self, batch, out_dir, cancel, output, log) -> None:
        """整批失败时逐文件重跑，定位到具体是哪个文件炸了。"""
        for job in batch:
            if _find_dds(out_dir, job.src.stem) is not None:
                continue
            if cancel is not None and cancel.is_set():
                return
            rc, out = self._run_texconv(self._build_args([job], out_dir), cancel)
            if rc == 0:
                continue
            log(
                "warn",
                i18n.t(
                    "log.texconv_report",
                    name=job.src.name,
                    excerpt=_error_excerpt(out or output),
                ),
            )

    def _finish_job(self, job: Job, out_dir: Path) -> tuple[bool, str]:
        dds = _find_dds(out_dir, job.src.stem)
        if dds is None:
            return False, i18n.t("log.job_failed", name=job.src.name, err=i18n.t("err.no_dds"))
        before = None
        if job.kind == "tex" and job.dst != job.src:
            try:
                before = job.src.stat().st_size
            except OSError:
                before = None
        try:
            size = dds_to_tex(dds, job.dst, job.fmt)
        except Exception as exc:
            return False, i18n.t("log.job_failed", name=job.src.name, err=exc)

        if before:
            delta = (size - before) / before * 100
            ratio = f"{human_size(before)} → {human_size(size)} ({delta:+.0f}%)"
        else:
            ratio = human_size(size)
        src_part = f"{job.src.name}"
        if job.src_desc:
            src_part += f" ({job.src_desc})"
        size_part = ""
        if job.resize:
            size_part = i18n.t("log.resized", w=job.resize[0], h=job.resize[1])
        return True, f"✓ {src_part} → {job.dst.name} [{job.fmt}{size_part}, {ratio}]"


def _find_dds(out_dir: Path, stem: str) -> Path | None:
    direct = out_dir / f"{stem}.dds"
    if direct.is_file():
        return direct
    low = f"{stem}.dds".lower()
    try:
        for entry in out_dir.iterdir():
            if entry.is_file() and entry.name.lower() == low:
                return entry
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# 文件扫描
# ---------------------------------------------------------------------------

def scan_paths(
    paths: Sequence[str | Path],
    recursive: bool = True,
) -> tuple[list[Path], list[Path]]:
    """一次遍历收集 PNG 与 TEX，避免 v1.0 里对同一目录反复 rglob。"""
    pngs: list[Path] = []
    texes: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen:
            return
        seen.add(key)
        ext = path.suffix.lower()
        if ext == ".png":
            pngs.append(path)
        elif ext == ".tex":
            texes.append(path)

    for raw in paths:
        p = Path(raw)
        try:
            if p.is_dir():
                if recursive:
                    for dirpath, _dirnames, filenames in os.walk(p):
                        for name in filenames:
                            if name.lower().endswith((".png", ".tex")):
                                add(Path(dirpath) / name)
                else:
                    for entry in p.iterdir():
                        if entry.is_file() and entry.suffix.lower() in (".png", ".tex"):
                            add(entry)
            elif p.is_file():
                add(p)
        except OSError:
            continue

    pngs.sort(key=lambda x: str(x).lower())
    texes.sort(key=lambda x: str(x).lower())
    return pngs, texes


# ---------------------------------------------------------------------------
# 自检（供 EXE 在没有控制台的情况下验证自身是否正常）
# ---------------------------------------------------------------------------

def _write_test_png(path: Path, width: int, height: int) -> None:
    """不依赖 Pillow，直接写一张带 Alpha 的测试 PNG。"""
    import zlib

    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type 0
        for x in range(width):
            rows += bytes((
                (x * 255) // max(1, width - 1),
                (y * 255) // max(1, height - 1),
                ((x + y) * 4) % 256,
                160 + (x * 95) // max(1, width - 1),
            ))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


def run_selftest(work_dir: Path | None = None) -> dict:
    """端到端自检：PNG -> 各格式 TEX -> 读回校验 -> TEX -> TEX。

    返回可直接 json.dumps 的报告；EXE 无控制台时由调用方写入文件。
    """
    report: dict = {"ok": True, "steps": [], "errors": []}
    started = time.perf_counter()
    tmp = None
    try:
        texconv = ensure_texconv(lambda m: report["steps"].append({"info": m}))
        report["texconv"] = str(texconv)
        report["texconv_version"] = _file_version(texconv)

        tmp = Path(tempfile.mkdtemp(prefix="ffxiv_selftest_", dir=str(work_dir) if work_dir else None))
        png = tmp / "selftest_body_d.png"
        _write_test_png(png, 64, 64)
        info = png_info(png)
        report["steps"].append({"png": {"size": [info.width, info.height], "alpha": info.has_alpha}})

        converter = TexConverter(texconv)
        made: dict[str, Path] = {}
        for fmt in SUPPORTED_FORMATS:
            job = Job(src=png, dst=tmp / f"selftest_{fmt}.tex", fmt=fmt, quality="q")
            stats = converter.run([job], log=lambda k, t: report["steps"].append({k: t}))
            if stats.ok != 1 or not job.dst.is_file():
                raise RuntimeError(f"{fmt} 转换失败")
            made[fmt] = job.dst
            ti = tex_info(job.dst)
            expect = expected_mip_sizes(64, 64, FORMAT_INFO[fmt][0], ti.levels)
            if ti.tex_format != FORMAT_INFO[fmt][1]:
                raise RuntimeError(f"{fmt} 的 TEX 格式 ID 不匹配")
            if ti.size != TEX_HEADER_SIZE + sum(expect):
                raise RuntimeError(f"{fmt} 的 TEX 大小不匹配")
            report["steps"].append({
                "tex": {"fmt": fmt, "levels": ti.levels, "size": ti.size,
                        "info": ti.describe()}
            })

        # TEX -> TEX（BC7 源转 BC1 目标）
        src = made["BC7_UNORM"]
        job = Job(src=src, dst=tmp / "selftest_retex.tex", fmt="BC1_UNORM", kind="tex")
        stats = converter.run([job], log=lambda k, t: report["steps"].append({k: t}))
        if stats.ok != 1 or job.dst.stat().st_size >= src.stat().st_size:
            raise RuntimeError("TEX -> TEX 转换失败")
        report["steps"].append({"retex": tex_info(job.dst).describe()})

        # 等比缩放：64x32 -> 长边 128 应为 128x64
        png2 = tmp / "selftest_wide.png"
        _write_test_png(png2, 64, 32)
        nw, nh = fit_long_edge(64, 32, 128)
        if (nw, nh) != (128, 64):
            raise RuntimeError(f"等比缩放计算错误：{nw}x{nh}")
        report["steps"].append({"fit": [nw, nh]})

    except Exception as exc:
        report["ok"] = False
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)

    report["elapsed_s"] = round(time.perf_counter() - started, 3)
    return report


def _file_version(path: Path) -> str:
    """读取 exe 的文件版本（失败返回空串）。"""
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buf):
            return ""
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(
            buf, "\\", ctypes.byref(ptr), ctypes.byref(length)
        ):
            return ""
        fixed = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
        ms, ls = fixed[2], fixed[3]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return ""
