from __future__ import annotations

import ctypes
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import psutil
from PIL import Image, ImageDraw, ImageTk

from codex_cloud import (
    discover_codex_local_storage_dirs,
    local_storage_signature,
    sync_codex_cloud_pets,
)
from pet_core import PetRecord, PetRepository


APP_TITLE = "桌宠管理台"
APP_VERSION = "1.0.6"

PALETTE = {
    "bg": "#F3F6F8",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "sidebar": "#EDF2F5",
    "ink": "#142331",
    "muted": "#66788A",
    "faint": "#93A2B1",
    "border": "#D7E1E8",
    "accent": "#137C8B",
    "accent_dark": "#0B6571",
    "accent_soft": "#E2F2F3",
    "success": "#2E8668",
    "success_soft": "#E8F5EF",
    "danger": "#B34A4A",
    "danger_soft": "#FBECEC",
    "warning": "#A56B20",
    "warning_soft": "#FFF3DE",
    "disabled": "#7D8D9B",
}

FONT_FAMILY = "Microsoft YaHei UI"
FONT_DISPLAY = (FONT_FAMILY, 22, "bold")
FONT_TITLE = (FONT_FAMILY, 15, "bold")
FONT_SECTION = (FONT_FAMILY, 11, "bold")
FONT_BODY = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_TINY = (FONT_FAMILY, 8)

CELL_WIDTH = 192
CELL_HEIGHT = 208

STATE_SPECS = [
    ("idle", "待机", 0, 6, [280, 110, 110, 140, 140, 320]),
    ("running-right", "向右移动", 1, 8, [120] * 7 + [220]),
    ("running-left", "向左移动", 2, 8, [120] * 7 + [220]),
    ("waving", "挥手", 3, 4, [140, 140, 140, 280]),
    ("jumping", "跳跃", 4, 5, [140, 140, 140, 140, 280]),
    ("failed", "失败", 5, 8, [140] * 7 + [240]),
    ("waiting", "等待", 6, 6, [150] * 5 + [260]),
    ("running", "工作", 7, 6, [120] * 5 + [220]),
    ("review", "检查", 8, 6, [150] * 5 + [280]),
]


@dataclass(frozen=True)
class ProgramSpec:
    key: str
    name: str
    description: str
    executable: Path
    arguments: tuple[str, ...] = ()

    @property
    def installed(self) -> bool:
        return self.executable.is_file()


def button(
    parent,
    text: str,
    command,
    kind: str = "secondary",
    width: int | None = None,
) -> tk.Button:
    colors = {
        "primary": (PALETTE["accent"], "#FFFFFF", PALETTE["accent_dark"]),
        "success": (PALETTE["success"], "#FFFFFF", "#257356"),
        "danger": (PALETTE["danger_soft"], PALETTE["danger"], "#F7DADA"),
        "secondary": (PALETTE["surface"], PALETTE["ink"], PALETTE["accent_soft"]),
        "ghost": (PALETTE["surface_alt"], PALETTE["muted"], PALETTE["accent_soft"]),
    }
    bg, fg, active_bg = colors[kind]
    control = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=fg,
        relief="flat",
        bd=0,
        padx=13,
        pady=7,
        font=(FONT_FAMILY, 9, "bold"),
        cursor="hand2",
        highlightthickness=1 if kind in ("secondary", "ghost") else 0,
        highlightbackground=PALETTE["border"],
        highlightcolor=PALETTE["accent"],
        width=width or 0,
    )
    return control


class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg: str, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.canvas = tk.Canvas(
            self,
            bg=bg,
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.body = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_body(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def scroll_wheel(self, delta: int):
        steps = wheel_steps(delta)
        if steps:
            self.canvas.yview_scroll(steps, "units")


class ThumbnailCache:
    def __init__(self):
        self.cache: dict[tuple[str, float], ImageTk.PhotoImage] = {}

    def get(self, record: PetRecord, size=(52, 56)) -> ImageTk.PhotoImage:
        if not record.sheet_path or not record.sheet_path.is_file():
            return self.placeholder(size)
        key = (str(record.sheet_path), record.sheet_path.stat().st_mtime)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        with Image.open(record.sheet_path) as atlas:
            crop = atlas.convert("RGBA").crop((0, 0, CELL_WIDTH, CELL_HEIGHT))
            crop.thumbnail(size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", size, (0, 0, 0, 0))
            canvas.alpha_composite(
                crop,
                ((size[0] - crop.width) // 2, (size[1] - crop.height) // 2),
            )
        photo = ImageTk.PhotoImage(canvas)
        self.cache[key] = photo
        return photo

    def placeholder(self, size=(52, 56)) -> ImageTk.PhotoImage:
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            (4, 4, size[0] - 4, size[1] - 4),
            radius=10,
            fill="#E7EDF1",
            outline="#CCD7DF",
        )
        draw.ellipse((18, 15, 34, 31), fill="#91A2B0")
        draw.rounded_rectangle((15, 32, 37, 45), radius=8, fill="#91A2B0")
        return ImageTk.PhotoImage(canvas)


class PetPreview(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            bg=PALETTE["surface_alt"],
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self.record: PetRecord | None = None
        self.atlas: Image.Image | None = None
        self.state_index = 0
        self.frame_index = 0
        self.after_id = None
        self.photo = None
        self.bind("<Configure>", lambda _event: self._render())

    def set_pet(self, record: PetRecord | None):
        self.record = record
        self.atlas = None
        self.frame_index = 0
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        if record and record.sheet_path and record.sheet_path.is_file():
            try:
                self.atlas = Image.open(record.sheet_path).convert("RGBA")
            except Exception:
                self.atlas = None
        self._render()
        self._schedule()

    def set_state(self, index: int):
        self.state_index = max(0, min(index, len(STATE_SPECS) - 1))
        self.frame_index = 0
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self._render()
        self._schedule()

    def _schedule(self):
        if not self.atlas:
            return
        _state, _label, _row, _count, durations = STATE_SPECS[self.state_index]
        delay = durations[min(self.frame_index, len(durations) - 1)]
        self.after_id = self.after(delay, self._next)

    def _next(self):
        self.after_id = None
        if not self.atlas:
            return
        _state, _label, _row, count, _durations = STATE_SPECS[self.state_index]
        self.frame_index = (self.frame_index + 1) % count
        self._render()
        self._schedule()

    def _render(self):
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        for x in range(22, width - 8, 24):
            for y in range(20, height - 10, 24):
                self.create_oval(x, y, x + 2, y + 2, fill="#DEE6EB", outline="")
        self.create_oval(
            width / 2 - 118,
            height - 58,
            width / 2 + 118,
            height - 26,
            fill="#DCE6EA",
            outline="",
        )
        self.create_oval(
            width / 2 - 72,
            height - 50,
            width / 2 + 72,
            height - 34,
            fill="#CBD8DE",
            outline="",
        )
        if not self.record or not self.atlas:
            self.create_text(
                width / 2,
                height / 2 - 8,
                text="选择一个人物查看动画",
                fill=PALETTE["muted"],
                font=(FONT_FAMILY, 11),
            )
            return
        _state, _label, row, _count, _durations = STATE_SPECS[self.state_index]
        column = min(self.frame_index, 7)
        source = self.atlas.crop(
            (
                column * CELL_WIDTH,
                row * CELL_HEIGHT,
                (column + 1) * CELL_WIDTH,
                (row + 1) * CELL_HEIGHT,
            )
        )
        max_width = max(180, width - 82)
        max_height = max(220, height - 92)
        scale = min(max_width / CELL_WIDTH, max_height / CELL_HEIGHT, 1.86)
        target_size = (
            max(1, round(CELL_WIDTH * scale)),
            max(1, round(CELL_HEIGHT * scale)),
        )
        frame = source.resize(target_size, Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(frame)
        self.create_image(
            width / 2,
            height - 54,
            image=self.photo,
            anchor="s",
        )
        self.create_text(
            18,
            18,
            anchor="nw",
            text=STATE_SPECS[self.state_index][1],
            fill=PALETTE["accent_dark"],
            font=(FONT_FAMILY, 9, "bold"),
        )


class EditDialog(tk.Toplevel):
    def __init__(self, parent, record: PetRecord):
        super().__init__(parent)
        self.title("编辑人物信息")
        self.configure(bg=PALETTE["surface"])
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        width, height = 470, 300
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

        body = tk.Frame(self, bg=PALETTE["surface"], padx=26, pady=22)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text="编辑人物信息",
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=(FONT_FAMILY, 16, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            body,
            text="修改会同步写入 Mini 与 Pets 的人物配置。",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x", pady=(4, 18))

        self.name_var = tk.StringVar(value=record.display_name)
        self.desc_var = tk.StringVar(value=record.description)
        self._field(body, "显示名称", self.name_var)
        self._field(body, "人物简介", self.desc_var)

        footer = tk.Frame(body, bg=PALETTE["surface"])
        footer.pack(fill="x", side="bottom", pady=(18, 0))
        button(footer, "取消", self.destroy, "ghost").pack(side="right")
        button(footer, "保存", self._save, "primary").pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _event: self._save())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.name_entry.focus_set()

    def _field(self, parent, label: str, variable: tk.StringVar):
        tk.Label(
            parent,
            text=label,
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=(FONT_FAMILY, 9, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 6))
        entry = tk.Entry(
            parent,
            textvariable=variable,
            bg=PALETTE["surface_alt"],
            fg=PALETTE["ink"],
            relief="flat",
            bd=0,
            font=FONT_BODY,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
            insertbackground=PALETTE["ink"],
        )
        entry.pack(fill="x", ipady=8, pady=(0, 14))
        if label == "显示名称":
            self.name_entry = entry

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("名称为空", "显示名称不能为空。", parent=self)
            return
        self.result = (name, self.desc_var.get().strip())
        self.destroy()


class PetManagerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.repository = PetRepository()
        self.records: list[PetRecord] = []
        self.filtered: list[PetRecord] = []
        self.selected_id: str | None = None
        self.filter_mode = "all"
        self.thumbnails = ThumbnailCache()
        self.records_by_id: dict[str, PetRecord] = {}
        self.after_program_refresh = None
        self.after_pet_poll = None
        self.after_cloud_poll = None
        self.after_cloud_result = None
        self.after_cloud_start = None
        self.after_status_reset = None
        self.closing = False
        self.cloud_sync_running = False
        self.cloud_result_queue = queue.Queue()
        self.last_pet_signature = None
        self.last_cloud_signature = None
        self.cloud_storage_paths = discover_codex_local_storage_dirs()
        self.programs = self._build_programs()
        self.program_widgets: dict[str, tuple[tk.Label, tk.Button]] = {}

        self._configure_root()
        self._build_ui()
        self.refresh(select_first=True)
        self._refresh_programs()
        self.after_cloud_start = self.root.after(
            200, lambda: self._request_cloud_sync(force=True)
        )
        self._schedule_local_poll()
        self._schedule_cloud_poll()

    def _configure_root(self):
        self.root.title(f"{APP_TITLE} · Mini & Pets")
        self.root.configure(bg=PALETTE["bg"])
        width, height = 1280, 820
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1080, 700)
        self.root.option_add("*Font", FONT_BODY)
        try:
            icon = Path(__file__).with_name("assets") / "app.ico"
            if not icon.is_file():
                icon = Path(__file__).with_name("app.ico")
            self.root.iconbitmap(str(icon))
        except Exception:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind_all("<MouseWheel>", self._route_mousewheel, add="+")
        self.root.bind("<Control-r>", lambda _event: self.manual_refresh())
        self.root.bind("<Delete>", lambda _event: self.delete_selected())
        self.root.bind("<F2>", lambda _event: self.edit_selected())

    def _build_programs(self) -> list[ProgramSpec]:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return [
            ProgramSpec(
                key="bailong",
                name="白龙桌宠",
                description="BailongPet v0.4.1",
                executable=local / "Programs" / "BailongPet" / "BailongPet.exe",
            ),
            ProgramSpec(
                key="white-dragon",
                name="白色大肥龙桌宠",
                description="dsh-pet · v4.4.0",
                executable=local
                / "Programs"
                / "dsh-pet-standalone-webm-chat"
                / "dsh-pet-standalone-webm-chat.exe",
                arguments=("--slot", "0"),
            ),
        ]

    def _build_ui(self):
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, minsize=24)
        self.root.grid_rowconfigure(0, minsize=104)
        self.root.grid_columnconfigure(0, weight=1)

        header = tk.Frame(self.root, bg=PALETTE["surface"], height=104)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)
        brand = tk.Frame(header, bg=PALETTE["surface"])
        brand.grid(row=0, column=0, sticky="w", padx=24, pady=16)
        tk.Label(
            brand,
            text=APP_TITLE,
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=FONT_DISPLAY,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="管理 Codex Mini & Pets 中显示的人物",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(header, bg=PALETTE["surface"])
        actions.grid(row=0, column=2, sticky="e", padx=24)
        self.stats_label = tk.Label(
            actions,
            text="",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=FONT_SMALL,
        )
        self.stats_label.pack(side="left", padx=(0, 16))
        button(actions, "刷新", self.manual_refresh, "secondary").pack(
            side="left", padx=(0, 8)
        )
        self.import_button = button(actions, "导入人物", self._show_import_menu, "primary")
        self.import_button.pack(side="left")

        main = tk.Frame(self.root, bg=PALETTE["bg"])
        main.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 4))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)
        main.grid_columnconfigure(0, minsize=320, weight=0)
        main.grid_columnconfigure(1, minsize=360, weight=1)
        main.grid_columnconfigure(2, minsize=356, weight=0)

        self.library_panel = tk.Frame(
            main,
            width=320,
            bg=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
        )
        self.library_panel.grid_propagate(False)
        self.library_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.library_panel.grid_rowconfigure(3, weight=1)
        self.library_panel.grid_columnconfigure(0, weight=1)

        library_head = tk.Frame(self.library_panel, bg=PALETTE["surface"])
        library_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        library_head.grid_columnconfigure(0, weight=1)
        tk.Label(
            library_head,
            text="人物库",
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=FONT_TITLE,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.library_count = tk.Label(
            library_head,
            text="0",
            bg=PALETTE["accent_soft"],
            fg=PALETTE["accent_dark"],
            font=FONT_TINY,
            padx=8,
            pady=2,
        )
        self.library_count.grid(row=0, column=1, sticky="e")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self._apply_filter())
        search = tk.Entry(
            self.library_panel,
            textvariable=self.search_var,
            bg=PALETTE["surface_alt"],
            fg=PALETTE["ink"],
            relief="flat",
            bd=0,
            font=FONT_BODY,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
            insertbackground=PALETTE["ink"],
        )
        search.grid(row=1, column=0, sticky="ew", padx=16, ipady=8)

        filters = tk.Frame(self.library_panel, bg=PALETTE["surface"])
        filters.grid(row=2, column=0, sticky="ew", padx=16, pady=12)
        self.filter_widgets = {}
        for key, label in (
            ("all", "全部"),
            ("enabled", "本地启用"),
            ("disabled", "本地停用"),
        ):
            chip = tk.Label(
                filters,
                text=label,
                bg=PALETTE["surface_alt"],
                fg=PALETTE["muted"],
                font=FONT_TINY,
                padx=10,
                pady=5,
                cursor="hand2",
            )
            chip.pack(side="left", padx=(0, 6))
            chip.bind("<Button-1>", lambda _event, mode=key: self._set_filter(mode))
            self.filter_widgets[key] = chip

        self.list_scroll = ScrollFrame(self.library_panel, bg=PALETTE["surface"])
        self.list_scroll.grid(row=3, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        note = tk.Label(
            self.library_panel,
            text="云端人物只读；本地人物停用后不会出现在列表中",
            bg=PALETTE["surface_alt"],
            fg=PALETTE["muted"],
            font=FONT_TINY,
            anchor="w",
            justify="left",
            wraplength=254,
            padx=14,
            pady=10,
        )
        note.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))

        self.preview_panel = tk.Frame(
            main,
            bg=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
        )
        self.preview_panel.grid(row=0, column=1, sticky="nsew")
        self.preview_panel.grid_rowconfigure(1, weight=1)
        self.preview_panel.grid_columnconfigure(0, weight=1)

        preview_head = tk.Frame(self.preview_panel, bg=PALETTE["surface"])
        preview_head.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 8))
        preview_head.grid_columnconfigure(0, weight=1)
        tk.Label(
            preview_head,
            text="动画预览",
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=FONT_TITLE,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.state_var = tk.StringVar(value=STATE_SPECS[0][1])
        self.state_combo = ttk.Combobox(
            preview_head,
            textvariable=self.state_var,
            values=[item[1] for item in STATE_SPECS],
            state="readonly",
            width=12,
            font=FONT_SMALL,
        )
        self.state_combo.grid(row=0, column=1, sticky="e")
        self.state_combo.bind("<<ComboboxSelected>>", self._state_changed)

        self.preview = PetPreview(self.preview_panel)
        self.preview.grid(row=1, column=0, sticky="nsew", padx=18)

        preview_footer = tk.Frame(self.preview_panel, bg=PALETTE["surface"])
        preview_footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(10, 16))
        preview_footer.grid_columnconfigure(0, weight=1)
        self.preview_hint = tk.Label(
            preview_footer,
            text="",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
            wraplength=300,
        )
        self.preview_hint.grid(row=0, column=0, sticky="w")
        self.quick_toggle = button(
            preview_footer,
            "停用人物",
            self.toggle_selected,
            "danger",
        )
        self.quick_toggle.grid(row=0, column=1, sticky="e")

        self.detail_panel = tk.Frame(
            main,
            width=356,
            bg=PALETTE["surface"],
            highlightbackground=PALETTE["border"],
            highlightthickness=1,
        )
        self.detail_panel.grid_propagate(False)
        self.detail_panel.pack_propagate(False)
        self.detail_panel.grid(row=0, column=2, sticky="nsew", padx=(14, 0))
        self.detail_scroll = ScrollFrame(self.detail_panel, bg=PALETTE["surface"])
        self.detail_scroll.pack(fill="both", expand=True)
        self.detail_body = tk.Frame(self.detail_scroll.body, bg=PALETTE["surface"])
        self.detail_body.pack(fill="both", expand=True, padx=18, pady=18)

        tk.Label(
            self.root,
            text=f"v{APP_VERSION} · 本地管理，不上传人物文件",
            bg=PALETTE["bg"],
            fg=PALETTE["faint"],
            font=FONT_TINY,
            anchor="e",
        ).grid(row=2, column=0, sticky="e", padx=24, pady=(0, 5))

    def _set_filter(self, mode: str):
        self.filter_mode = mode
        self._apply_filter()

    def _route_mousewheel(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if isinstance(widget, ScrollFrame):
                widget.scroll_wheel(event.delta)
                return "break"
            widget = widget.master
        return None

    def _update_filter_chips(self):
        for key, widget in self.filter_widgets.items():
            active = key == self.filter_mode
            widget.configure(
                bg=PALETTE["accent_soft"] if active else PALETTE["surface_alt"],
                fg=PALETTE["accent_dark"] if active else PALETTE["muted"],
            )

    def refresh(self, select_first: bool = False):
        previous = self.selected_id
        try:
            self.records = self.repository.scan()
        except Exception as error:
            messagebox.showerror("扫描失败", str(error), parent=self.root)
            return
        self.records_by_id = {record.id: record for record in self.records}
        if previous in self.records_by_id:
            self.selected_id = previous
        elif select_first or not self.selected_id:
            self.selected_id = self.records[0].id if self.records else None
        else:
            self.selected_id = None
        self.stats_label.configure(text=self._stats_text())
        self.library_count.configure(text=str(len(self.records)))
        self.last_pet_signature = self.repository.signature()
        self._apply_filter()

    def manual_refresh(self):
        self.refresh()
        self._status("正在同步 Codex 本地与云端人物…")
        self._request_cloud_sync(force=True)

    def _schedule_local_poll(self):
        if self.closing:
            return
        self.after_pet_poll = self.root.after(3000, self._poll_local_changes)

    def _poll_local_changes(self):
        try:
            signature = self.repository.signature()
            if signature != self.last_pet_signature:
                self.refresh()
                self._status("检测到 Codex 新人物，已自动刷新")
        finally:
            self._schedule_local_poll()

    def _schedule_cloud_poll(self):
        if self.closing:
            return
        self.after_cloud_poll = self.root.after(15000, self._poll_cloud_changes)

    def _poll_cloud_changes(self):
        try:
            self.cloud_storage_paths = discover_codex_local_storage_dirs()
            self._request_cloud_sync()
        finally:
            self._schedule_cloud_poll()

    def _request_cloud_sync(self, force: bool = False):
        if self.closing or self.cloud_sync_running:
            return
        self.cloud_storage_paths = discover_codex_local_storage_dirs()
        signature = local_storage_signature(self.cloud_storage_paths)
        if not force and signature == self.last_cloud_signature:
            return
        self.last_cloud_signature = signature
        self.cloud_sync_running = True
        worker = threading.Thread(target=self._cloud_sync_worker, daemon=True)
        worker.start()
        if self.after_cloud_result is None:
            self.after_cloud_result = self.root.after(300, self._poll_cloud_result)

    def _cloud_sync_worker(self):
        try:
            result = sync_codex_cloud_pets(
                self.repository.cloud_dir,
                paths=self.cloud_storage_paths,
            )
            self.cloud_result_queue.put(("ok", result))
        except Exception as error:
            self.cloud_result_queue.put(("error", str(error)))

    def _poll_cloud_result(self):
        self.after_cloud_result = None
        try:
            status, payload = self.cloud_result_queue.get_nowait()
        except queue.Empty:
            self.after_cloud_result = self.root.after(300, self._poll_cloud_result)
            return
        self.cloud_sync_running = False
        if status == "error":
            self.last_cloud_signature = None
            self._status(f"云端人物同步失败：{shorten(payload, 60)}")
            return
        if payload.changed:
            self.refresh()
        if payload.discovered:
            self._status(
                f"已同步 {payload.discovered} 个云端人物"
                + (f" · {payload.failed} 个失败" if payload.failed else "")
            )
        elif payload.failed:
            self._status(f"云端人物缓存读取完成 · {payload.failed} 个图集暂不可用")
        elif payload.errors and not payload.discovered:
            self._status(f"云端人物缓存读取失败：{shorten(payload.errors[0], 54)}")
        if payload.failed or (payload.errors and not payload.discovered):
            self.last_cloud_signature = None

    def _apply_filter(self):
        query = self.search_var.get().strip().casefold()
        self.filtered = []
        for record in self.records:
            if self.filter_mode == "enabled" and (
                not record.enabled or record.is_cloud
            ):
                continue
            if self.filter_mode == "disabled" and (
                record.enabled or record.is_cloud
            ):
                continue
            if query and query not in (
                record.display_name + " " + record.description + " " + record.id
            ).casefold():
                continue
            self.filtered.append(record)
        self._update_filter_chips()
        if self.selected_id not in {record.id for record in self.filtered}:
            self.selected_id = self.filtered[0].id if self.filtered else None
        self._render_list()
        self._render_detail()

    def _render_list(self):
        for child in self.list_scroll.body.winfo_children():
            child.destroy()
        if not self.filtered:
            tk.Label(
                self.list_scroll.body,
                text="没有符合条件的人物",
                bg=PALETTE["surface"],
                fg=PALETTE["muted"],
                font=FONT_BODY,
                pady=30,
            ).pack(fill="x")
            return
        for record in self.filtered:
            self._build_list_row(record)

    def _build_list_row(self, record: PetRecord):
        selected = record.id == self.selected_id
        bg = PALETTE["accent_soft"] if selected else PALETTE["surface"]
        row = tk.Frame(
            self.list_scroll.body,
            bg=bg,
            cursor="hand2",
            padx=10,
            pady=8,
        )
        row.pack(fill="x", padx=4, pady=2)
        thumb = tk.Label(row, bg=bg, image=self.thumbnails.get(record))
        thumb.image = self.thumbnails.get(record)
        thumb.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 10))
        name_color = PALETTE["ink"] if record.valid else PALETTE["danger"]
        name = tk.Label(
            row,
            text=shorten(record.display_name, 22),
            bg=bg,
            fg=name_color,
            font=(FONT_FAMILY, 10, "bold"),
            anchor="w",
        )
        name.grid(row=0, column=1, sticky="ew")
        row.grid_columnconfigure(1, weight=1)
        meta = tk.Label(
            row,
            text=f"{record.version_label} · {record.source_label}",
            bg=bg,
            fg=PALETTE["muted"] if record.enabled else PALETTE["disabled"],
            font=FONT_TINY,
            anchor="w",
        )
        meta.grid(row=1, column=1, sticky="ew", pady=(2, 0))
        dot_color = PALETTE["success"] if record.enabled else PALETTE["disabled"]
        dot = tk.Canvas(row, width=12, height=12, bg=bg, highlightthickness=0)
        dot.create_oval(3, 3, 9, 9, fill=dot_color, outline="")
        dot.grid(row=0, column=2, sticky="ne")

        widgets = (row, thumb, name, meta, dot)
        for widget in widgets:
            widget.bind("<Button-1>", lambda _event, pet_id=record.id: self.select_pet(pet_id))
            widget.bind(
                "<Enter>",
                lambda _event, r=row, w=widgets, s=selected: self._hover_row(r, w, s, True),
            )
            widget.bind(
                "<Leave>",
                lambda _event, r=row, w=widgets, s=selected: self._hover_row(r, w, s, False),
            )

    def _hover_row(self, row, widgets, selected, entering):
        if selected:
            return
        bg = PALETTE["surface_alt"] if entering else PALETTE["surface"]
        for widget in widgets:
            if isinstance(widget, tk.Canvas):
                widget.configure(bg=bg)
            else:
                widget.configure(bg=bg)

    def select_pet(self, pet_id: str):
        self.selected_id = pet_id
        self._render_list()
        self._render_detail()

    def _render_detail(self):
        for child in self.detail_body.winfo_children():
            child.destroy()
        record = self.records_by_id.get(self.selected_id or "")
        if not record:
            tk.Label(
                self.detail_body,
                text="选择一个人物",
                bg=PALETTE["surface"],
                fg=PALETTE["muted"],
                font=FONT_TITLE,
            ).pack(pady=30)
            self.preview.set_pet(None)
            self.preview_hint.configure(text="")
            self.quick_toggle.configure(state="disabled")
            return

        if record.is_cloud:
            self.quick_toggle.configure(
                state="disabled",
                text="Codex 云端只读",
                bg=PALETTE["surface_alt"],
                fg=PALETTE["muted"],
                activebackground=PALETTE["surface_alt"],
                activeforeground=PALETTE["muted"],
            )
        else:
            self.quick_toggle.configure(
                state="normal",
                text="停用人物" if record.enabled else "启用到 Mini & Pets",
                bg=PALETTE["danger_soft"] if record.enabled else PALETTE["success"],
                fg=PALETTE["danger"] if record.enabled else "#FFFFFF",
                activebackground="#F7DADA" if record.enabled else "#257356",
                activeforeground=PALETTE["danger"] if record.enabled else "#FFFFFF",
            )
        self.preview.set_pet(record)
        self.preview_hint.configure(
            text=f"{record.display_name} · {STATE_SPECS[self.preview.state_index][1]}"
        )

        title_row = tk.Frame(self.detail_body, bg=PALETTE["surface"])
        title_row.pack(fill="x")
        title_row.grid_columnconfigure(0, weight=1)
        tk.Label(
            title_row,
            text=shorten(record.display_name, 28),
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=(FONT_FAMILY, 18, "bold"),
            anchor="w",
            justify="left",
            wraplength=230,
        ).grid(row=0, column=0, sticky="w")
        status_bg = PALETTE["success_soft"] if record.enabled else PALETTE["surface_alt"]
        status_fg = PALETTE["success"] if record.enabled else PALETTE["muted"]
        tk.Label(
            title_row,
            text=record.status_label,
            bg=status_bg,
            fg=status_fg,
            font=FONT_TINY,
            padx=8,
            pady=3,
        ).grid(row=0, column=1, sticky="e")

        description = record.description or "未填写人物简介。"
        tk.Label(
            self.detail_body,
            text=description,
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=FONT_BODY,
            justify="left",
            anchor="w",
            wraplength=310,
        ).pack(fill="x", pady=(8, 16))

        separator(self.detail_body).pack(fill="x", pady=(0, 14))
        self._detail_row("格式", record.version_label)
        self._detail_row(
            "图集",
            f"{record.width} × {record.height}" if record.valid else "不可用",
        )
        self._detail_row("大小", human_size(record.bytes))
        self._detail_row("来源", record.source_label)
        self._detail_row("ID", record.id)
        if not record.valid:
            tk.Label(
                self.detail_body,
                text=record.error,
                bg=PALETTE["danger_soft"],
                fg=PALETTE["danger"],
                font=FONT_SMALL,
                justify="left",
                anchor="w",
                wraplength=310,
                padx=10,
                pady=8,
            ).pack(fill="x", pady=(10, 0))

        action_grid = tk.Frame(self.detail_body, bg=PALETTE["surface"])
        action_grid.pack(fill="x", pady=(18, 0))
        action_grid.grid_columnconfigure((0, 1), weight=1)
        edit_action = button(action_grid, "编辑信息", self.edit_selected, "secondary")
        edit_action.grid(
            row=0, column=0, sticky="ew", padx=(0, 4), pady=4
        )
        button(action_grid, "打开目录", self.open_selected_folder, "secondary").grid(
            row=0, column=1, sticky="ew", padx=(4, 0), pady=4
        )
        only_action = button(action_grid, "仅保留此人物", self.only_selected, "ghost")
        only_action.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=4
        )
        delete_action = button(action_grid, "删除人物", self.delete_selected, "danger")
        delete_action.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=4
        )
        if record.is_cloud:
            edit_action.configure(state="disabled")
            only_action.configure(state="disabled")
            delete_action.configure(state="disabled")

        separator(self.detail_body).pack(fill="x", pady=(20, 14))
        tk.Label(
            self.detail_body,
            text="桌宠程序",
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=FONT_SECTION,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))
        self.program_widgets = {}
        for program in self.programs:
            self._build_program_row(program)

    def _detail_row(self, label: str, value: str):
        row = tk.Frame(self.detail_body, bg=PALETTE["surface"])
        row.pack(fill="x", pady=3)
        tk.Label(
            row,
            text=label,
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=FONT_SMALL,
            width=7,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            row,
            text=value,
            bg=PALETTE["surface"],
            fg=PALETTE["ink"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
            wraplength=248,
        ).pack(side="left", fill="x", expand=True)

    def _build_program_row(self, program: ProgramSpec):
        row = tk.Frame(self.detail_body, bg=PALETTE["surface_alt"], padx=10, pady=9)
        row.pack(fill="x", pady=3)
        row.grid_columnconfigure(0, weight=1)
        tk.Label(
            row,
            text=program.name,
            bg=PALETTE["surface_alt"],
            fg=PALETTE["ink"],
            font=(FONT_FAMILY, 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        status = tk.Label(
            row,
            text="",
            bg=PALETTE["surface_alt"],
            fg=PALETTE["muted"],
            font=FONT_TINY,
            anchor="w",
        )
        status.grid(row=1, column=0, sticky="w", pady=(2, 0))
        action = button(row, "启动", lambda spec=program: self._toggle_program(spec), "ghost")
        action.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))
        self.program_widgets[program.key] = (status, action)

    def _state_changed(self, _event=None):
        index = next(
            (i for i, spec in enumerate(STATE_SPECS) if spec[1] == self.state_var.get()),
            0,
        )
        self.preview.set_state(index)
        record = self.records_by_id.get(self.selected_id or "")
        if record:
            self.preview_hint.configure(
                text=f"{record.display_name} · {STATE_SPECS[index][1]}"
            )

    def toggle_selected(self):
        record = self.records_by_id.get(self.selected_id or "")
        if not record or not record.valid:
            return
        if record.is_cloud:
            self._status("Codex 云端人物请在 Codex 设置中切换")
            return
        try:
            if record.enabled:
                self.repository.disable(record.id)
                message = f"已停用「{record.display_name}」，它不会出现在 Mini & Pets。"
            else:
                self.repository.enable(record.id)
                message = f"已启用「{record.display_name}」，重新打开 Mini & Pets 即可看到。"
            self.refresh()
            self._status(message)
        except Exception as error:
            messagebox.showerror("操作失败", str(error), parent=self.root)

    def only_selected(self):
        record = self.records_by_id.get(self.selected_id or "")
        if not record:
            return
        if record.is_cloud:
            self._status("Codex 云端人物不能作为本地保留目标")
            return
        others = [
            item
            for item in self.records
            if item.id != record.id and item.enabled and not item.is_cloud
        ]
        if not others:
            if not record.enabled:
                self.toggle_selected()
            return
        if not messagebox.askyesno(
            "仅保留此人物",
            f"将停用另外 {len(others)} 个人物，只保留「{record.display_name}」。\n"
            "此操作可在人物库中随时恢复。",
            parent=self.root,
        ):
            return
        try:
            for other in others:
                self.repository.disable(other.id)
            if not record.enabled:
                self.repository.enable(record.id)
            self.refresh()
            self._status(f"本地人物目前只保留「{record.display_name}」")
        except Exception as error:
            messagebox.showerror("操作失败", str(error), parent=self.root)

    def edit_selected(self):
        record = self.records_by_id.get(self.selected_id or "")
        if not record:
            return
        if record.is_cloud:
            self._status("Codex 云端人物请在 Codex 设置中修改")
            return
        dialog = EditDialog(self.root, record)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        try:
            self.repository.update_metadata(record.id, *dialog.result)
            self.refresh()
            self._status("人物信息已更新")
        except Exception as error:
            messagebox.showerror("更新失败", str(error), parent=self.root)

    def delete_selected(self):
        record = self.records_by_id.get(self.selected_id or "")
        if not record:
            return
        if record.is_cloud:
            self._status("Codex 云端人物不能被管理台删除")
            return
        if not messagebox.askyesno(
            "删除人物",
            f"确定永久删除「{record.display_name}」？\n"
            "人物配置和图集都会从 Mini & Pets 目录中移除。",
            parent=self.root,
        ):
            return
        try:
            self.repository.delete(record.id)
            self.selected_id = None
            self.refresh(select_first=True)
            self._status("人物已删除")
        except Exception as error:
            messagebox.showerror("删除失败", str(error), parent=self.root)

    def open_selected_folder(self):
        record = self.records_by_id.get(self.selected_id or "")
        if record and record.primary_dir:
            os.startfile(str(record.primary_dir))

    def _show_import_menu(self):
        menu = tk.Menu(self.root, tearoff=0, font=FONT_BODY)
        menu.add_command(label="导入 ZIP 人物包", command=self.import_zip)
        menu.add_command(label="导入人物文件夹", command=self.import_folder)
        x = self.import_button.winfo_rootx()
        y = self.import_button.winfo_rooty() + self.import_button.winfo_height()
        menu.tk_popup(x, y)

    def import_zip(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择人物 ZIP",
            filetypes=[("ZIP 人物包", "*.zip")],
        )
        if not path:
            return
        try:
            imported = self.repository.import_zip(Path(path))
            self.refresh(select_first=True)
            self._status(f"已导入 {len(imported)} 个人物")
        except Exception as error:
            messagebox.showerror("导入失败", str(error), parent=self.root)

    def import_folder(self):
        path = filedialog.askdirectory(parent=self.root, title="选择人物文件夹")
        if not path:
            return
        try:
            imported = self.repository.import_folder(Path(path))
            self.refresh(select_first=True)
            self._status(f"已导入 {len(imported)} 个人物")
        except Exception as error:
            messagebox.showerror("导入失败", str(error), parent=self.root)

    def _program_processes(self, spec: ProgramSpec):
        found = []
        expected = str(spec.executable.resolve()).casefold()
        for process in psutil.process_iter(["exe"]):
            try:
                exe = process.info.get("exe")
                if exe and str(Path(exe).resolve()).casefold() == expected:
                    found.append(process)
            except (psutil.Error, OSError):
                continue
        return found

    def _toggle_program(self, spec: ProgramSpec):
        try:
            processes = self._program_processes(spec)
            if processes:
                for process in processes:
                    process.terminate()
                _gone, alive = psutil.wait_procs(processes, timeout=4)
                for process in alive:
                    process.kill()
                self._status(f"{spec.name} 已停止")
            else:
                if not spec.installed:
                    messagebox.showwarning(
                        "程序未安装",
                        f"没有找到 {spec.executable}",
                        parent=self.root,
                    )
                    return
                subprocess.Popen(
                    [str(spec.executable), *spec.arguments],
                    cwd=str(spec.executable.parent),
                )
                self._status(f"{spec.name} 已启动")
            self.root.after(450, self._refresh_programs)
        except Exception as error:
            messagebox.showerror("操作失败", str(error), parent=self.root)

    def _refresh_programs(self):
        for spec in self.programs:
            widgets = self.program_widgets.get(spec.key)
            if not widgets:
                continue
            status, action = widgets
            running = self._program_processes(spec)
            if not spec.installed:
                status.configure(text="未安装", fg=PALETTE["muted"])
                action.configure(text="不可用", state="disabled")
            elif running:
                status.configure(text=f"运行中 · PID {running[0].pid}", fg=PALETTE["success"])
                action.configure(
                    text="停止",
                    state="normal",
                    bg=PALETTE["danger_soft"],
                    fg=PALETTE["danger"],
                )
            else:
                status.configure(text=spec.description, fg=PALETTE["muted"])
                action.configure(
                    text="启动",
                    state="normal",
                    bg=PALETTE["success_soft"],
                    fg=PALETTE["success"],
                )
        if self.after_program_refresh:
            self.root.after_cancel(self.after_program_refresh)
        self.after_program_refresh = self.root.after(3000, self._refresh_programs)

    def _status(self, text: str):
        self.stats_label.configure(text=text)
        if self.after_status_reset:
            self.root.after_cancel(self.after_status_reset)
        self.after_status_reset = self.root.after(4000, self._restore_stats)

    def _restore_stats(self):
        self.after_status_reset = None
        self.stats_label.configure(text=self._stats_text())

    def _stats_text(self) -> str:
        local_active = sum(
            1 for item in self.records if item.enabled and not item.is_cloud
        )
        cloud_count = sum(1 for item in self.records if item.is_cloud)
        if cloud_count:
            return (
                f"{local_active} 本地启用 · {cloud_count} 云端缓存 · "
                f"{len(self.records)} 个人物"
            )
        return f"{local_active} 本地启用 · {len(self.records)} 个人物"

    def _close(self):
        self.closing = True
        for callback in (
            self.after_program_refresh,
            self.after_pet_poll,
            self.after_cloud_poll,
            self.after_cloud_result,
            self.after_cloud_start,
            self.after_status_reset,
        ):
            if callback:
                try:
                    self.root.after_cancel(callback)
                except tk.TclError:
                    pass
        if self.preview.after_id:
            try:
                self.root.after_cancel(self.preview.after_id)
            except tk.TclError:
                pass
        self.root.quit()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def separator(parent) -> tk.Frame:
    return tk.Frame(parent, bg=PALETTE["border"], height=1)


def human_size(size: int) -> str:
    if size <= 0:
        return "未知"
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def shorten(value: str, limit: int) -> str:
    value = str(value)
    return value if len(value) <= limit else value[: max(1, limit - 1)] + "…"


def wheel_steps(delta: int) -> int:
    """Keep touchpad deltas useful while capping oversized wheel events."""
    if not delta:
        return 0
    steps = int(-delta / 120)
    if steps == 0:
        steps = -1 if delta > 0 else 1
    return max(-5, min(5, steps))


def main():
    root = tk.Tk()
    app = PetManagerApp(root)
    if "--smoke-test" in sys.argv:
        root.after(1200, app._close)
    root.mainloop()


if __name__ == "__main__":
    main()
