#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#pylint:disable=W0301
#
#  Copyright 2018- William Martinez Bas <metfar@gmail.com>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#
#import warnings;
#warnings.filterwarnings("ignore", category=UserWarning);

"""
dailynews_gui.py;

Tkinter frontend for dailynews.py.

Version v4:
- keeps the history/run workflow from the previous version;
- renders the selected news file as dark themed cards;
- supports clickable links that open in the default browser;
- still keeps the daily summary and run log tabs simple and robust.
""";

from __future__ import annotations;

import datetime as dt;
import json;
import pathlib;
import queue;
import re;
import subprocess;
import sys;
import threading;
import tkinter as tk;
import webbrowser;
from dataclasses import dataclass;
from dataclasses import field;
from tkinter import messagebox;
from tkinter import ttk;
from tkinter.scrolledtext import ScrolledText;
from typing import Dict;
from typing import List;
from typing import Optional;

APP_TITLE = "dailynews GUI";
FILE_PATTERN = re.compile(r"^(morning_brief|evening_digest|alerts)_(\d{8})_(\d{6})\.md$");
KIND_LABELS = {
    "morning": "Morning brief",
    "evening": "Evening digest",
    "alerts": "Alerts",
};
KIND_PREFIX_MAP = {
    "morning_brief": "morning",
    "evening_digest": "evening",
    "alerts": "alerts",
};
URL_RE = re.compile(r"https?://\S+");

DARK_BG = "#111417";
DARK_PANEL = "#181d21";
DARK_CARD = "#1d2429";
DARK_CARD_ALT = "#162027";
DARK_BORDER = "#2d3b44";
TEXT_MAIN = "#f1f5f7";
TEXT_SOFT = "#a7b6bf";
TEXT_MUTED = "#7f909a";
ACCENT_CYAN = "#00c8ff";
ACCENT_BLUE = "#5dd6ff";
ACCENT_GREEN = "#51d88a";
ACCENT_YELLOW = "#ffd166";
ACCENT_RED = "#ff6b6b";
ACCENT_PURPLE = "#b794f4";


@dataclass
class NewsFileEntry:
    path: pathlib.Path;
    kind: str;
    stamp: dt.datetime;
    date_key: str;
    time_key: str;
    display_name: str;
    title: str;
    generated_local: str = "";
    generated_utc: str = "";
    content: Optional[str] = None;
    parsed: Optional["ParsedDocument"] = None;


@dataclass
class RunRequest:
    mode: str;
    dry_run: bool = False;
    verbose: bool = False;


@dataclass
class RunEvent:
    event_type: str;
    text: str = "";
    returncode: Optional[int] = None;
    mode: str = "";
    created_path: str = "";


@dataclass
class DailyBucket:
    date_key: str;
    morning: Optional[NewsFileEntry] = None;
    evening: Optional[NewsFileEntry] = None;
    alerts: List[NewsFileEntry] = field(default_factory=list);


@dataclass
class ArticleCard:
    title: str;
    severity: str = "";
    source: str = "";
    date: str = "";
    summary: str = "";
    details: str = "";
    link: str = "";
    bullets: List[str] = field(default_factory=list);


@dataclass
class SectionBlock:
    title: str;
    items: List[ArticleCard] = field(default_factory=list);
    paragraphs: List[str] = field(default_factory=list);


@dataclass
class ParsedDocument:
    title: str = "";
    generated_local: str = "";
    generated_utc: str = "";
    host: str = "";
    sections: List[SectionBlock] = field(default_factory=list);


@dataclass
class TreeNodePayload:
    node_type: str;
    entry: NewsFileEntry;
    section_title: str = "";
    article: Optional[ArticleCard] = None;


class DarkCardView(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, background=DARK_BG, highlightthickness=0, bd=0);
        self.canvas = tk.Canvas(self, background=DARK_BG, highlightthickness=0, bd=0, relief=tk.FLAT);
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview);
        self.inner = tk.Frame(self.canvas, background=DARK_BG, bd=0, highlightthickness=0);
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw");
        self.canvas.configure(yscrollcommand=self.scrollbar.set);
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True);
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y);
        self.inner.bind("<Configure>", self._on_inner_configure);
        self.canvas.bind("<Configure>", self._on_canvas_configure);
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+");
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux, add="+");
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux, add="+");

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy();
        self.canvas.yview_moveto(0.0);

    def _on_inner_configure(self, _event: object) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"));

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=max(event.width, 100));

    def _on_mousewheel(self, event: tk.Event) -> None:
        delta = getattr(event, "delta", 0);
        if delta == 0:
            return;
        self.canvas.yview_scroll(int(-1 * (delta / 120)), "units");

    def _on_mousewheel_linux(self, event: tk.Event) -> None:
        num = getattr(event, "num", 0);
        if num == 4:
            self.canvas.yview_scroll(-3, "units");
        elif num == 5:
            self.canvas.yview_scroll(3, "units");


class DailyNewsGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root;
        self.base_dir = pathlib.Path(__file__).resolve().parent;
        self.script_path = self.base_dir / "dailynews.py";
        self.config_path = self.base_dir / "config.json";
        self.output_dir = self._read_output_dir();
        self.entries: List[NewsFileEntry] = [];
        self.tree_payload_by_id: Dict[str, TreeNodePayload] = {};
        self.entry_node_by_path: Dict[str, str] = {};
        self.daily_buckets: Dict[str, DailyBucket] = {};
        self.selected_entry: Optional[NewsFileEntry] = None;
        self.selected_date_key: Optional[str] = None;
        self.selected_first_url: Optional[str] = None;
        self.selected_alert_first_url: Optional[str] = None;
        self.run_thread: Optional[threading.Thread] = None;
        self.run_queue: "queue.Queue[RunEvent]" = queue.Queue();
        self._suspend_tree_select = False;

        self.filter_var = tk.StringVar(value="all");
        self.dry_run_var = tk.BooleanVar(value=False);
        self.verbose_var = tk.BooleanVar(value=False);
        self.status_var = tk.StringVar(value="Ready.");
        self.path_var = tk.StringVar(value="");
        self.meta_var = tk.StringVar(value="No file selected.");
        self.output_dir_var = tk.StringVar(value=str(self.output_dir));

        self.root.title(APP_TITLE);
        self.root.geometry("1320x920");
        self.root.minsize(1000, 700);

        self._configure_style();
        self._build_menu();
        self._build_layout();
        self._refresh_history(select_latest=True);
        self._poll_run_queue();

    def _configure_style(self) -> None:
        style = ttk.Style();
        try:
            style.theme_use("clam");
        except tk.TclError:
            pass;
        style.configure("Title.TLabel", font=("TkDefaultFont", 11, "bold"));
        style.configure("Meta.TLabel", font=("TkDefaultFont", 9));
        style.configure("Status.TLabel", padding=(6, 4));

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root);

        file_menu = tk.Menu(menubar, tearoff=False);
        file_menu.add_command(label="Refresh", command=self.on_refresh);
        file_menu.add_separator();
        file_menu.add_command(label="Exit", command=self.root.destroy);
        menubar.add_cascade(label="File", menu=file_menu);

        run_menu = tk.Menu(menubar, tearoff=False);
        run_menu.add_command(label="Run morning", command=lambda: self.on_run("morning"));
        run_menu.add_command(label="Run evening", command=lambda: self.on_run("evening"));
        run_menu.add_command(label="Run alerts", command=lambda: self.on_run("alerts"));
        menubar.add_cascade(label="Run", menu=run_menu);

        help_menu = tk.Menu(menubar, tearoff=False);
        help_menu.add_command(label="About", command=self.show_about);
        menubar.add_cascade(label="Help", menu=help_menu);

        self.root.config(menu=menubar);

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=8);
        outer.pack(fill=tk.BOTH, expand=True);

        toolbar = ttk.Frame(outer);
        toolbar.pack(fill=tk.X, pady=(0, 8));

        ttk.Button(toolbar, text="Run Morning", command=lambda: self.on_run("morning")).pack(side=tk.LEFT, padx=(0, 4));
        ttk.Button(toolbar, text="Run Evening", command=lambda: self.on_run("evening")).pack(side=tk.LEFT, padx=4);
        ttk.Button(toolbar, text="Run Alerts", command=lambda: self.on_run("alerts")).pack(side=tk.LEFT, padx=4);
        ttk.Button(toolbar, text="Refresh", command=self.on_refresh).pack(side=tk.LEFT, padx=4);
        ttk.Checkbutton(toolbar, text="Dry run", variable=self.dry_run_var).pack(side=tk.LEFT, padx=(16, 4));
        ttk.Checkbutton(toolbar, text="Verbose", variable=self.verbose_var).pack(side=tk.LEFT, padx=4);

        ttk.Label(toolbar, text="Filter:").pack(side=tk.LEFT, padx=(16, 4));
        filter_combo = ttk.Combobox(toolbar, textvariable=self.filter_var, state="readonly", width=14, values=("all", "morning", "evening", "alerts"));
        filter_combo.pack(side=tk.LEFT, padx=4);
        filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_history(select_latest=False));

        ttk.Button(toolbar, text="Settings later", command=self.show_settings_placeholder).pack(side=tk.RIGHT, padx=(4, 0));

        path_frame = ttk.Frame(outer);
        path_frame.pack(fill=tk.X, pady=(0, 8));
        ttk.Label(path_frame, text="Output dir:", style="Meta.TLabel").pack(side=tk.LEFT);
        ttk.Label(path_frame, textvariable=self.output_dir_var, style="Meta.TLabel").pack(side=tk.LEFT, padx=(6, 0));

        main_pane = ttk.Panedwindow(outer, orient=tk.HORIZONTAL);
        main_pane.pack(fill=tk.BOTH, expand=True);

        left_frame = ttk.Frame(main_pane, padding=(0, 0, 8, 0));
        right_frame = ttk.Frame(main_pane);
        main_pane.add(left_frame, weight=1);
        main_pane.add(right_frame, weight=3);

        ttk.Label(left_frame, text="History", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 6));

        tree_container = ttk.Frame(left_frame);
        tree_container.pack(fill=tk.BOTH, expand=True);

        self.tree = ttk.Treeview(tree_container, columns=("kind", "time"), show="tree headings", selectmode="browse");
        self.tree.heading("#0", text="Date / run");
        self.tree.heading("kind", text="Type");
        self.tree.heading("time", text="Time");
        self.tree.column("#0", width=260, stretch=True);
        self.tree.column("kind", width=90, anchor=tk.CENTER, stretch=False);
        self.tree.column("time", width=90, anchor=tk.CENTER, stretch=False);
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True);
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select);

        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree.yview);
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y);
        self.tree.configure(yscrollcommand=tree_scroll.set);

        self.notebook = ttk.Notebook(right_frame);
        self.notebook.pack(fill=tk.BOTH, expand=True);

        viewer_tab = ttk.Frame(self.notebook, padding=8);
        alerts_tab = ttk.Frame(self.notebook, padding=8);
        summary_tab = ttk.Frame(self.notebook, padding=8);
        runlog_tab = ttk.Frame(self.notebook, padding=8);
        self.notebook.add(viewer_tab, text="Selected item");
        self.notebook.add(alerts_tab, text="Alerts");
        self.notebook.add(summary_tab, text="Daily summary");
        self.notebook.add(runlog_tab, text="Run log");
        self.viewer_tab = viewer_tab;
        self.alerts_tab = alerts_tab;

        viewer_meta = ttk.Frame(viewer_tab);
        viewer_meta.pack(fill=tk.X, pady=(0, 6));
        viewer_meta_left = ttk.Frame(viewer_meta);
        viewer_meta_left.pack(side=tk.LEFT, fill=tk.X, expand=True);
        ttk.Label(viewer_meta_left, textvariable=self.meta_var, style="Meta.TLabel").pack(anchor=tk.W);
        ttk.Label(viewer_meta_left, textvariable=self.path_var, style="Meta.TLabel").pack(anchor=tk.W, pady=(2, 0));
        self.open_first_link_button = ttk.Button(viewer_meta, text="Open first link", command=self.open_selected_first_link, state=tk.DISABLED);
        self.open_first_link_button.pack(side=tk.RIGHT, padx=(8, 0));

        self.viewer_cards = DarkCardView(viewer_tab);
        self.viewer_cards.pack(fill=tk.BOTH, expand=True);

        alerts_meta = ttk.Frame(alerts_tab);
        alerts_meta.pack(fill=tk.X, pady=(0, 6));
        ttk.Label(alerts_meta, text="Alerts extracted from the selected run.", style="Meta.TLabel").pack(side=tk.LEFT, anchor=tk.W);
        self.open_alert_first_link_button = ttk.Button(alerts_meta, text="Open first alert link", command=self.open_selected_alert_first_link, state=tk.DISABLED);
        self.open_alert_first_link_button.pack(side=tk.RIGHT, padx=(8, 0));

        self.alert_cards = DarkCardView(alerts_tab);
        self.alert_cards.pack(fill=tk.BOTH, expand=True);

        summary_toolbar = ttk.Frame(summary_tab);
        summary_toolbar.pack(fill=tk.X, pady=(0, 6));
        ttk.Label(summary_toolbar, text="Daily summary based on the selected date.", style="Meta.TLabel").pack(anchor=tk.W);

        self.summary_text = ScrolledText(summary_tab, wrap=tk.WORD, undo=False, font=("TkDefaultFont", 10), padx=12, pady=10, relief=tk.FLAT, borderwidth=0);
        self.summary_text.pack(fill=tk.BOTH, expand=True);
        self.summary_text.configure(state=tk.DISABLED, background="#fcfcfc");

        runlog_toolbar = ttk.Frame(runlog_tab);
        runlog_toolbar.pack(fill=tk.X, pady=(0, 6));
        ttk.Button(runlog_toolbar, text="Clear log", command=self.clear_run_log).pack(side=tk.LEFT);
        ttk.Label(runlog_toolbar, text="Subprocess output from manual runs.", style="Meta.TLabel").pack(side=tk.LEFT, padx=(8, 0));

        self.runlog_text = ScrolledText(runlog_tab, wrap=tk.WORD, undo=False, font=("TkFixedFont", 10));
        self.runlog_text.pack(fill=tk.BOTH, expand=True);
        self.runlog_text.configure(state=tk.DISABLED);

        status_frame = ttk.Frame(outer);
        status_frame.pack(fill=tk.X, pady=(8, 0));
        ttk.Label(status_frame, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT, anchor=tk.W);

    def _read_output_dir(self) -> pathlib.Path:
        default_dir = self.base_dir / "out";
        if not self.config_path.exists():
            return default_dir;
        try:
            with open(self.config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle);
            raw_output = str(config.get("output_dir", "./out") or "./out").strip();
            if not raw_output:
                return default_dir;
            output_dir = pathlib.Path(raw_output);
            if not output_dir.is_absolute():
                output_dir = (self.base_dir / output_dir).resolve();
            return output_dir;
        except Exception:
            return default_dir;

    def _scan_output_files(self) -> List[NewsFileEntry]:
        entries: List[NewsFileEntry] = [];
        output_dir = self._read_output_dir();
        self.output_dir = output_dir;
        self.output_dir_var.set(str(output_dir));
        if not output_dir.exists():
            return entries;

        for item in sorted(output_dir.iterdir()):
            if not item.is_file():
                continue;
            match = FILE_PATTERN.match(item.name);
            if not match:
                continue;
            prefix, date_chunk, time_chunk = match.groups();
            kind = KIND_PREFIX_MAP.get(prefix, "alerts");
            stamp = self._parse_stamp(date_chunk, time_chunk, item);
            generated_local, generated_utc = self._read_file_metadata(item);
            entries.append(
                NewsFileEntry(
                    path=item,
                    kind=kind,
                    stamp=stamp,
                    date_key=stamp.strftime("%Y-%m-%d"),
                    time_key=stamp.strftime("%H:%M:%S"),
                    display_name=f"{stamp.strftime('%H:%M:%S')} | {KIND_LABELS.get(kind, kind.title())}",
                    title=KIND_LABELS.get(kind, kind.title()),
                    generated_local=generated_local,
                    generated_utc=generated_utc,
                    content=None,
                )
            );
        entries.sort(key=lambda x: x.stamp, reverse=True);
        return entries;

    def _parse_stamp(self, date_chunk: str, time_chunk: str, path: pathlib.Path) -> dt.datetime:
        try:
            return dt.datetime.strptime(f"{date_chunk}_{time_chunk}", "%Y%m%d_%H%M%S");
        except ValueError:
            return dt.datetime.fromtimestamp(path.stat().st_mtime);

    def _read_file_metadata(self, path: pathlib.Path) -> tuple[str, str]:
        generated_local = "";
        generated_utc = "";
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for idx, raw_line in enumerate(handle):
                    line = raw_line.rstrip("\n");
                    if line.startswith("Generated at local:"):
                        generated_local = self._extract_code_or_tail(line, "Generated at local:");
                    elif line.startswith("Generated at UTC:"):
                        generated_utc = self._extract_code_or_tail(line, "Generated at UTC:");
                    if idx >= 40 or (generated_local and generated_utc):
                        break;
        except Exception:
            return ("", "");
        return (generated_local, generated_utc);

    def _extract_code_or_tail(self, line: str, prefix: str) -> str:
        if "`" in line:
            parts = line.split("`");
            if len(parts) >= 3:
                return parts[1].strip();
        return line.replace(prefix, "").strip();

    def _read_full_text(self, path: pathlib.Path) -> str:
        try:
            return path.read_text(encoding="utf-8");
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1", errors="replace");
        except Exception as exc:
            return f"Could not read file: {exc}\n";

    def _ensure_entry_loaded(self, entry: NewsFileEntry) -> None:
        if entry.content is not None:
            return;
        entry.content = self._read_full_text(entry.path);
        if not entry.generated_local or not entry.generated_utc:
            generated_local, generated_utc = self._read_file_metadata(entry.path);
            if generated_local:
                entry.generated_local = generated_local;
            if generated_utc:
                entry.generated_utc = generated_utc;

    def _ensure_entry_parsed(self, entry: NewsFileEntry) -> ParsedDocument:
        self._ensure_entry_loaded(entry);
        if entry.parsed is None:
            entry.parsed = self._parse_document(entry.content or "");
        return entry.parsed;

    def _rebuild_buckets(self) -> None:
        buckets: Dict[str, DailyBucket] = {};
        for entry in sorted(self.entries, key=lambda x: x.stamp, reverse=True):
            bucket = buckets.get(entry.date_key);
            if bucket is None:
                bucket = DailyBucket(date_key=entry.date_key);
                buckets[entry.date_key] = bucket;
            if entry.kind == "morning" and bucket.morning is None:
                bucket.morning = entry;
            elif entry.kind == "evening" and bucket.evening is None:
                bucket.evening = entry;
            elif entry.kind == "alerts":
                bucket.alerts.append(entry);
        self.daily_buckets = buckets;

    def _refresh_history(self, select_latest: bool = False, preferred_entry: Optional[pathlib.Path] = None) -> None:
        self.entries = self._scan_output_files();
        self._rebuild_buckets();
        self._populate_tree();
        if preferred_entry is not None:
            self._select_entry_by_path(preferred_entry);
            return;
        if select_latest and self.entries:
            self._select_entry(self.entries[0]);
        elif not self.entries:
            self._clear_viewer("No Markdown outputs found yet.\nRun a profile or refresh the history.");
            self._set_text_widget(self.summary_text, "No daily summary available yet.\n");
            self.meta_var.set("No file selected.");
            self.path_var.set("");
            self.selected_entry = None;
            self.selected_date_key = None;

    def _populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children());
        self.tree_payload_by_id.clear();
        self.entry_node_by_path.clear();
        filtered = self._filtered_entries();
        by_date: Dict[str, List[NewsFileEntry]] = {};
        for entry in filtered:
            by_date.setdefault(entry.date_key, []).append(entry);
        for date_key in sorted(by_date.keys(), reverse=True):
            date_entries = sorted(by_date[date_key], key=lambda x: x.stamp, reverse=True);
            date_id = self.tree.insert("", tk.END, text=self._format_date_label(date_key), values=("", ""), open=True);
            for entry in date_entries:
                time_id = self.tree.insert(date_id, tk.END, text=entry.time_key, values=("", entry.time_key), open=True);
                profile_id = self.tree.insert(time_id, tk.END, text=entry.title, values=(entry.kind, ""), open=False);
                self.tree_payload_by_id[profile_id] = TreeNodePayload(node_type="entry", entry=entry);
                self.entry_node_by_path[str(entry.path.resolve())] = profile_id;
                doc = self._ensure_entry_parsed(entry);
                for section in doc.sections:
                    for article in section.items:
                        article_text = self._make_article_tree_label(section.title, article);
                        article_id = self.tree.insert(profile_id, tk.END, text=article_text, values=("", ""), open=False);
                        self.tree_payload_by_id[article_id] = TreeNodePayload(node_type="article", entry=entry, section_title=section.title, article=article);

    def _filtered_entries(self) -> List[NewsFileEntry]:
        selected_kind = self.filter_var.get().strip().lower();
        if selected_kind in ("", "all"):
            return list(self.entries);
        return [entry for entry in self.entries if entry.kind == selected_kind];

    def _format_date_label(self, date_key: str) -> str:
        try:
            parsed = dt.datetime.strptime(date_key, "%Y-%m-%d").date();
            return parsed.strftime("%Y-%m-%d (%A)");
        except ValueError:
            return date_key;

    def _make_article_tree_label(self, section_title: str, article: ArticleCard, limit: int = 92) -> str:
        prefix = "";
        if article.severity:
            prefix = f"[{article.severity}] ";
        label = prefix + article.title.strip();
        if self._section_is_alert(section_title):
            label = f"{section_title}: {label}";
        if len(label) > limit:
            label = label[:limit - 1] + "…";
        return label;

    def _sync_tree_selection(self, entry: NewsFileEntry) -> None:
        target_tree_id = self.entry_node_by_path.get(str(entry.path.resolve()), "");
        if not target_tree_id:
            return;
        current_selection = self.tree.selection();
        if current_selection and current_selection[0] == target_tree_id:
            return;
        self._suspend_tree_select = True;
        try:
            self.tree.selection_set(target_tree_id);
            self.tree.focus(target_tree_id);
            self.tree.see(target_tree_id);
        finally:
            self._suspend_tree_select = False;

    def _set_meta_for_entry(self, entry: NewsFileEntry, article: Optional[ArticleCard] = None) -> None:
        self.path_var.set(str(entry.path));
        meta = f"{entry.title} | date={entry.date_key} | file_time={entry.time_key}";
        if article is not None:
            meta += f" | article={article.title}";
        if entry.generated_local:
            meta += f" | generated_local={entry.generated_local}";
        if entry.generated_utc:
            meta += f" | generated_utc={entry.generated_utc}";
        self.meta_var.set(meta);

    def _select_entry(self, entry: NewsFileEntry, sync_tree: bool = True) -> None:
        self.selected_entry = entry;
        self.selected_date_key = entry.date_key;
        self._set_meta_for_entry(entry);
        self._render_entry_views(entry);
        self._update_daily_summary(entry.date_key);
        if sync_tree:
            self._sync_tree_selection(entry);

    def _select_article(self, entry: NewsFileEntry, section_title: str, article: ArticleCard) -> None:
        self.selected_entry = entry;
        self.selected_date_key = entry.date_key;
        self._set_meta_for_entry(entry, article=article);
        self._render_article_views(entry, section_title, article);
        self._update_daily_summary(entry.date_key);

    def _select_entry_by_path(self, preferred_path: pathlib.Path) -> None:
        for entry in self.entries:
            if entry.path.resolve() == preferred_path.resolve():
                self._select_entry(entry);
                return;
        if self.entries:
            self._select_entry(self.entries[0]);

    def _normalize_label(self, label: str) -> str:
        normalized = label.strip().lower();
        mapping = {
            "fuente": "source",
            "source": "source",
            "fecha": "date",
            "date": "date",
            "summary": "summary",
            "resumen": "summary",
            "details": "details",
            "detalle": "details",
            "detalles": "details",
            "link": "link",
            "enlace": "link",
        };
        return mapping.get(normalized, normalized);

    def _parse_document(self, text: str) -> ParsedDocument:
        doc = ParsedDocument();
        current_section: Optional[SectionBlock] = None;
        current_item: Optional[ArticleCard] = None;
        lines = text.splitlines();
        index = 0;
        while index < len(lines):
            raw_line = lines[index].rstrip();
            stripped = raw_line.strip();
            if not stripped:
                index += 1;
                continue;
            if stripped.startswith("# "):
                doc.title = stripped[2:].strip();
                index += 1;
                continue;
            if stripped.startswith("Generated at UTC:"):
                doc.generated_utc = self._extract_code_or_tail(stripped, "Generated at UTC:");
                index += 1;
                continue;
            if stripped.startswith("Generated at local:"):
                doc.generated_local = self._extract_code_or_tail(stripped, "Generated at local:");
                index += 1;
                continue;
            if stripped.startswith("Host:"):
                doc.host = self._extract_code_or_tail(stripped, "Host:");
                index += 1;
                continue;
            if stripped.startswith("## "):
                current_section = SectionBlock(title=stripped[3:].strip());
                doc.sections.append(current_section);
                current_item = None;
                index += 1;
                continue;

            urgent_match = re.match(r"^-\s+\*\*\[([^\]]+)\]\*\*\s+(.+)$", stripped);
            if urgent_match:
                if current_section is None:
                    current_section = SectionBlock(title="Items");
                    doc.sections.append(current_section);
                current_item = ArticleCard(title=urgent_match.group(2).strip(), severity=urgent_match.group(1).strip().upper());
                current_section.items.append(current_item);
                index += 1;
                continue;

            bold_item_match = re.match(r"^-\s+\*\*(.+?)\*\*$", stripped);
            if bold_item_match:
                if current_section is None:
                    current_section = SectionBlock(title="Items");
                    doc.sections.append(current_section);
                current_item = ArticleCard(title=bold_item_match.group(1).strip());
                current_section.items.append(current_item);
                index += 1;
                continue;

            plain_bullet_match = re.match(r"^-\s+(.+)$", stripped);
            if plain_bullet_match and current_item is not None:
                body = plain_bullet_match.group(1).strip();
                if ":" in body:
                    label, value = body.split(":", 1);
                    normalized = self._normalize_label(label);
                    value = value.strip();
                    if normalized == "source":
                        current_item.source = value;
                    elif normalized == "date":
                        current_item.date = value;
                    elif normalized == "summary":
                        current_item.summary = value;
                    elif normalized == "details":
                        current_item.details = value;
                    elif normalized == "link":
                        current_item.link = value;
                    else:
                        current_item.bullets.append(body);
                else:
                    current_item.bullets.append(body);
                index += 1;
                continue;

            if URL_RE.fullmatch(stripped) and current_item is not None and not current_item.link:
                current_item.link = stripped;
                index += 1;
                continue;

            if current_item is not None:
                current_item.bullets.append(stripped);
            else:
                if current_section is None:
                    current_section = SectionBlock(title="Overview");
                    doc.sections.append(current_section);
                current_section.paragraphs.append(stripped);
            index += 1;

        return doc;

    def _severity_palette(self, severity: str) -> tuple[str, str, str]:
        normalized = severity.strip().upper();
        if normalized == "URGENT":
            return (ACCENT_RED, "#4b1f22", "#ffd7d7");
        if normalized == "WARNING":
            return (ACCENT_YELLOW, "#4a3a10", "#ffe9a8");
        if normalized == "INFO":
            return (ACCENT_GREEN, "#173d2a", "#c6f6d5");
        return (ACCENT_PURPLE, "#2e2345", "#eadcff");

    def _section_is_alert(self, section_title: str) -> bool:
        normalized = (section_title or "").strip().lower();
        return normalized in ("alerts", "alert", "urgent", "urgentes", "warnings", "warning");

    def _split_doc_sections(self, entry: NewsFileEntry, doc: ParsedDocument) -> tuple[List[SectionBlock], List[SectionBlock]]:
        if entry.kind == "alerts":
            return ([], list(doc.sections));
        normal_sections: List[SectionBlock] = [];
        alert_sections: List[SectionBlock] = [];
        for section in doc.sections:
            if self._section_is_alert(section.title):
                alert_sections.append(section);
            else:
                normal_sections.append(section);
        return (normal_sections, alert_sections);

    def _section_from_article(self, section_title: str, article: ArticleCard) -> SectionBlock:
        return SectionBlock(title=section_title, items=[article], paragraphs=[]);

    def _open_url(self, url: str) -> None:
        cleaned = (url or "").strip();
        if not cleaned:
            return;
        try:
            webbrowser.open_new_tab(cleaned);
            self.status_var.set(f"Opened link in browser: {cleaned}");
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not open URL: {exc}");

    def open_selected_first_link(self) -> None:
        if self.selected_first_url:
            self._open_url(self.selected_first_url);

    def open_selected_alert_first_link(self) -> None:
        if self.selected_alert_first_url:
            self._open_url(self.selected_alert_first_url);

    def _short_url(self, url: str, limit: int = 88) -> str:
        cleaned = (url or "").strip();
        if len(cleaned) <= limit:
            return cleaned;
        return cleaned[:limit - 1] + "…";

    def _set_button_url(self, button: ttk.Button, url: Optional[str]) -> None:
        if url:
            button.configure(state=tk.NORMAL);
        else:
            button.configure(state=tk.DISABLED);

    def _clear_card_view(self, card_view: DarkCardView, button: ttk.Button, message: str = "") -> None:
        card_view.clear();
        self._set_button_url(button, None);
        if message:
            card = tk.Frame(card_view.inner, background=DARK_PANEL, highlightbackground=DARK_BORDER, highlightthickness=1, bd=0, padx=18, pady=18);
            card.pack(fill=tk.X, padx=10, pady=10);
            tk.Label(card, text=message, justify=tk.LEFT, wraplength=900, background=DARK_PANEL, foreground=TEXT_SOFT, font=("TkDefaultFont", 11)).pack(anchor="w");

    def _render_sections_to_view(self, card_view: DarkCardView, button: ttk.Button, entry: NewsFileEntry, doc: ParsedDocument, sections: List[SectionBlock], title_override: str = "", empty_message: str = "No items available in this view.") -> Optional[str]:
        card_view.clear();
        first_link_found = "";
        container = card_view.inner;

        header = tk.Frame(container, background=DARK_PANEL, highlightbackground=DARK_BORDER, highlightthickness=1, bd=0, padx=22, pady=18);
        header.pack(fill=tk.X, padx=10, pady=(10, 8));
        header_title = title_override or doc.title or entry.title;
        tk.Label(header, text=header_title, background=DARK_PANEL, foreground=TEXT_MAIN, font=("TkDefaultFont", 20, "bold")).pack(anchor="w");
        if doc.generated_utc:
            tk.Label(header, text=f"Generated at UTC: {doc.generated_utc}", background=DARK_PANEL, foreground=ACCENT_BLUE, font=("TkFixedFont", 11, "bold")).pack(anchor="w", pady=(12, 0));
        if doc.generated_local:
            tk.Label(header, text=f"Generated at local: {doc.generated_local}", background=DARK_PANEL, foreground=TEXT_MAIN, font=("TkDefaultFont", 11)).pack(anchor="w", pady=(4, 0));
        if doc.host:
            tk.Label(header, text=f"Host: {doc.host}", background=DARK_PANEL, foreground=TEXT_MAIN, font=("TkDefaultFont", 11)).pack(anchor="w", pady=(4, 0));

        if not sections:
            body = tk.Frame(container, background=DARK_PANEL, highlightbackground=DARK_BORDER, highlightthickness=1, bd=0, padx=18, pady=18);
            body.pack(fill=tk.X, padx=10, pady=(0, 10));
            tk.Label(body, text=empty_message, justify=tk.LEFT, wraplength=980, background=DARK_PANEL, foreground=TEXT_SOFT, font=("TkDefaultFont", 11)).pack(anchor="w");
            self._set_button_url(button, None);
            return None;

        for section in sections:
            section_frame = tk.Frame(container, background=DARK_BG, bd=0, highlightthickness=0);
            section_frame.pack(fill=tk.X, padx=10, pady=(6, 2));
            tk.Label(section_frame, text=section.title, background=DARK_BG, foreground=ACCENT_CYAN, font=("TkDefaultFont", 18, "bold")).pack(anchor="w", pady=(6, 4));

            for paragraph in section.paragraphs:
                paragraph_card = tk.Frame(container, background=DARK_CARD_ALT, highlightbackground=DARK_BORDER, highlightthickness=1, bd=0, padx=16, pady=14);
                paragraph_card.pack(fill=tk.X, padx=10, pady=(0, 8));
                tk.Label(paragraph_card, text=paragraph, justify=tk.LEFT, wraplength=980, background=DARK_CARD_ALT, foreground=TEXT_MAIN, font=("TkDefaultFont", 11)).pack(anchor="w");

            for item in section.items:
                card = tk.Frame(container, background=DARK_CARD, highlightbackground=DARK_BORDER, highlightthickness=1, bd=0);
                card.pack(fill=tk.X, padx=10, pady=(0, 10));

                stripe_color = ACCENT_BLUE;
                badge_bg = "";
                badge_fg = "";
                if item.severity:
                    stripe_color, badge_bg, badge_fg = self._severity_palette(item.severity);
                stripe = tk.Frame(card, width=8, background=stripe_color, bd=0, highlightthickness=0);
                stripe.pack(side=tk.LEFT, fill=tk.Y);

                content = tk.Frame(card, background=DARK_CARD, bd=0, highlightthickness=0, padx=16, pady=14);
                content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True);

                title_row = tk.Frame(content, background=DARK_CARD, bd=0, highlightthickness=0);
                title_row.pack(fill=tk.X);
                if item.severity:
                    badge = tk.Label(title_row, text=item.severity, background=badge_bg, foreground=badge_fg, padx=8, pady=2, font=("TkFixedFont", 10, "bold"));
                    badge.pack(side=tk.LEFT, anchor="n", padx=(0, 10));
                tk.Label(title_row, text=item.title, justify=tk.LEFT, wraplength=860, background=DARK_CARD, foreground=TEXT_MAIN, font=("TkDefaultFont", 14, "bold")).pack(side=tk.LEFT, anchor="w", fill=tk.X, expand=True);

                if item.source or item.date:
                    meta_parts = [];
                    if item.source:
                        meta_parts.append(f"Source: {item.source}");
                    if item.date:
                        meta_parts.append(f"Date: {item.date}");
                    tk.Label(content, text="   •   ".join(meta_parts), justify=tk.LEFT, wraplength=930, background=DARK_CARD, foreground=TEXT_SOFT, font=("TkDefaultFont", 10)).pack(anchor="w", pady=(8, 0));

                if item.summary:
                    tk.Label(content, text=item.summary, justify=tk.LEFT, wraplength=930, background=DARK_CARD, foreground=TEXT_MAIN, font=("TkDefaultFont", 11)).pack(anchor="w", pady=(10, 0));

                if item.details:
                    tk.Label(content, text=item.details, justify=tk.LEFT, wraplength=930, background=DARK_CARD, foreground=TEXT_SOFT, font=("TkDefaultFont", 10)).pack(anchor="w", pady=(8, 0));

                for bullet in item.bullets:
                    tk.Label(content, text=f"• {bullet}", justify=tk.LEFT, wraplength=930, background=DARK_CARD, foreground=TEXT_MAIN, font=("TkDefaultFont", 10)).pack(anchor="w", pady=(6, 0));

                if item.link:
                    if not first_link_found:
                        first_link_found = item.link;
                    link_row = tk.Frame(content, background=DARK_CARD, bd=0, highlightthickness=0);
                    link_row.pack(fill=tk.X, pady=(12, 0));
                    tk.Button(link_row, text="Open in browser", command=lambda url=item.link: self._open_url(url), relief=tk.FLAT, bd=0, padx=12, pady=6, background=ACCENT_CYAN, foreground="#00141b", activebackground=ACCENT_BLUE, activeforeground="#00141b", cursor="hand2", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT);
                    link_label = tk.Label(link_row, text=self._short_url(item.link), justify=tk.LEFT, background=DARK_CARD, foreground=ACCENT_BLUE, cursor="hand2", font=("TkDefaultFont", 10, "underline"));
                    link_label.pack(side=tk.LEFT, padx=(12, 0), fill=tk.X, expand=True);
                    link_label.bind("<Button-1>", lambda _event, url=item.link: self._open_url(url));

        self._set_button_url(button, first_link_found or None);
        card_view.canvas.yview_moveto(0.0);
        return first_link_found or None;

    def _render_entry_views(self, entry: NewsFileEntry) -> None:
        doc = self._ensure_entry_parsed(entry);
        content_sections, alert_sections = self._split_doc_sections(entry, doc);
        self.selected_first_url = self._render_sections_to_view(self.viewer_cards, self.open_first_link_button, entry, doc, content_sections, title_override="", empty_message="No non-alert news sections in this run.");
        self.selected_alert_first_url = self._render_sections_to_view(self.alert_cards, self.open_alert_first_link_button, entry, doc, alert_sections, title_override="Alerts", empty_message="No alerts found in this run.");
        if entry.kind == "alerts":
            self.notebook.select(self.alerts_tab);
        else:
            self.notebook.select(self.viewer_tab);

    def _render_article_views(self, entry: NewsFileEntry, section_title: str, article: ArticleCard) -> None:
        doc = self._ensure_entry_parsed(entry);
        content_sections, alert_sections = self._split_doc_sections(entry, doc);
        is_alert = entry.kind == "alerts" or self._section_is_alert(section_title);
        focused_section = [self._section_from_article(section_title, article)];
        if is_alert:
            self.selected_first_url = self._render_sections_to_view(self.viewer_cards, self.open_first_link_button, entry, doc, content_sections, title_override=doc.title or entry.title, empty_message="This run does not contain non-alert news sections.");
            self.selected_alert_first_url = self._render_sections_to_view(self.alert_cards, self.open_alert_first_link_button, entry, doc, focused_section, title_override="Alerts", empty_message="No alerts found in this run.");
            self.notebook.select(self.alerts_tab);
        else:
            self.selected_first_url = self._render_sections_to_view(self.viewer_cards, self.open_first_link_button, entry, doc, focused_section, title_override=doc.title or entry.title, empty_message="No news content available.");
            self.selected_alert_first_url = self._render_sections_to_view(self.alert_cards, self.open_alert_first_link_button, entry, doc, alert_sections, title_override="Alerts", empty_message="No alerts found in this run.");
            self.notebook.select(self.viewer_tab);

    def _update_daily_summary(self, date_key: str) -> None:
        bucket = self.daily_buckets.get(date_key);
        if bucket is None:
            self._set_text_widget(self.summary_text, "No daily summary available for this date.\n");
            return;
        lines: List[str] = [];
        lines.append(f"Date: {date_key}");
        lines.append("");
        if bucket.morning is not None:
            self._ensure_entry_loaded(bucket.morning);
            lines.append("[Morning]");
            lines.append(str(bucket.morning.path));
            lines.append(self._summarize_for_daily_view(bucket.morning.content or ""));
            lines.append("");
        if bucket.evening is not None:
            self._ensure_entry_loaded(bucket.evening);
            lines.append("[Evening]");
            lines.append(str(bucket.evening.path));
            lines.append(self._summarize_for_daily_view(bucket.evening.content or ""));
            lines.append("");
        if bucket.alerts:
            lines.append(f"[Alerts: {len(bucket.alerts)} run(s)]");
            for alert_entry in sorted(bucket.alerts, key=lambda x: x.stamp, reverse=True):
                self._ensure_entry_loaded(alert_entry);
                lines.append(f"- {alert_entry.time_key} -> {alert_entry.path.name}");
                lines.append(self._summarize_for_daily_view(alert_entry.content or "", max_lines=8, indent="  "));
                lines.append("");
        self._set_text_widget(self.summary_text, "\n".join(lines).strip() + "\n");

    def _summarize_for_daily_view(self, text: str, max_lines: int = 12, indent: str = "") -> str:
        raw_lines = [line.rstrip() for line in text.splitlines()];
        kept: List[str] = [];
        for line in raw_lines:
            stripped = line.strip();
            if not stripped:
                continue;
            if stripped.startswith("Generated at ") or stripped.startswith("Host:"):
                continue;
            if stripped.startswith("# "):
                continue;
            kept.append(indent + stripped);
            if len(kept) >= max_lines:
                kept.append(indent + "...");
                break;
        return "\n".join(kept) if kept else indent + "(no content)";

    def _set_text_widget(self, widget: ScrolledText, text: str) -> None:
        widget.configure(state=tk.NORMAL);
        widget.delete("1.0", tk.END);
        widget.insert(tk.END, text);
        widget.configure(state=tk.DISABLED);

    def on_tree_select(self, _event: object) -> None:
        if self._suspend_tree_select:
            return;
        selection = self.tree.selection();
        if not selection:
            return;
        payload = self.tree_payload_by_id.get(selection[0]);
        if payload is None:
            return;
        if payload.node_type == "article" and payload.article is not None:
            self._select_article(payload.entry, payload.section_title, payload.article);
            return;
        self._select_entry(payload.entry, sync_tree=False);

    def on_refresh(self) -> None:
        self.status_var.set("Refreshing history...");
        previously_selected = self.selected_entry.path if self.selected_entry is not None else None;
        self._refresh_history(select_latest=previously_selected is None, preferred_entry=previously_selected);
        self.status_var.set("History refreshed.");

    def show_about(self) -> None:
        messagebox.showinfo(APP_TITLE, "dailynews GUI\n\nTkinter frontend for dailynews.py with dark rendered cards and browser links.");

    def show_settings_placeholder(self) -> None:
        messagebox.showinfo(APP_TITLE, "Settings editor will come later. For now, edit config.json manually.");

    def clear_run_log(self) -> None:
        self._set_text_widget(self.runlog_text, "");

    def on_run(self, mode: str) -> None:
        if self.run_thread is not None and self.run_thread.is_alive():
            messagebox.showwarning(APP_TITLE, "A run is already in progress.");
            return;
        if not self.script_path.exists():
            messagebox.showerror(APP_TITLE, f"Could not find script: {self.script_path}");
            return;
        if not self.config_path.exists():
            messagebox.showerror(APP_TITLE, f"Could not find config: {self.config_path}");
            return;

        request = RunRequest(mode=mode, dry_run=bool(self.dry_run_var.get()), verbose=bool(self.verbose_var.get()));
        self.status_var.set(f"Running {mode}...");
        self._append_run_log(f"\n===== Running {mode} =====\n");
        self.run_thread = threading.Thread(target=self._run_subprocess_worker, args=(request,), daemon=True);
        self.run_thread.start();

    def _run_subprocess_worker(self, request: RunRequest) -> None:
        cmd = [sys.executable, str(self.script_path), "--config", str(self.config_path)];
        if request.mode == "alerts":
            cmd.append("--alerts-only");
        else:
            cmd.extend(["--profile", request.mode]);
        if request.dry_run:
            cmd.append("--dry-run");
        if request.verbose:
            cmd.append("--verbose");

        created_path = "";
        try:
            process = subprocess.Popen(cmd, cwd=str(self.base_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1);
        except Exception as exc:
            self.run_queue.put(RunEvent(event_type="finish", text=f"Could not start process: {exc}\n", returncode=-1, mode=request.mode));
            return;

        assert process.stdout is not None;
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n");
            if "Markdown saved at:" in line:
                created_path = line.split("Markdown saved at:", maxsplit=1)[1].strip();
            self.run_queue.put(RunEvent(event_type="line", text=raw_line, mode=request.mode));
        returncode = process.wait();
        self.run_queue.put(RunEvent(event_type="finish", returncode=returncode, mode=request.mode, created_path=created_path));

    def _poll_run_queue(self) -> None:
        try:
            while True:
                event = self.run_queue.get_nowait();
                if event.event_type == "line":
                    self._append_run_log(event.text);
                elif event.event_type == "finish":
                    if event.text:
                        self._append_run_log(event.text);
                    if event.returncode == 0:
                        self._append_run_log(f"[ok] {event.mode} finished with code 0.\n");
                        preferred_path = pathlib.Path(event.created_path) if event.created_path else None;
                        self._refresh_history(select_latest=True, preferred_entry=preferred_path);
                        self.status_var.set(f"Run completed: {event.mode}.");
                    else:
                        self._append_run_log(f"[error] {event.mode} finished with code {event.returncode}.\n");
                        self.status_var.set(f"Run failed: {event.mode} (code {event.returncode}).");
        except queue.Empty:
            pass;
        self.root.after(250, self._poll_run_queue);

    def _append_run_log(self, text: str) -> None:
        self.runlog_text.configure(state=tk.NORMAL);
        self.runlog_text.insert(tk.END, text);
        self.runlog_text.see(tk.END);
        self.runlog_text.configure(state=tk.DISABLED);


def main() -> int:
    root = tk.Tk();
    app = DailyNewsGui(root);
    _ = app;
    root.mainloop();
    return 0;


if __name__ == "__main__":
    raise SystemExit(main());
