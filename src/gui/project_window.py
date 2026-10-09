"""Project workspace dashboard inspired by ELUTEC's Overview reference."""
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from ..data.project_store import ProjectStore
from .theme import get_palette


class ProjectManagerDialog:
    """Browse recent ELUTEC projects and sessions without hiding project actions."""

    def __init__(self, parent, on_open, current_path=None, light_theme=False, initial_section="overview",
                 on_theme_change=None):
        self.parent = parent
        self.on_open = on_open
        self.on_theme_change = on_theme_change
        self.current_path = str(Path(current_path).expanduser().resolve()) if current_path else ""
        self.light_theme = bool(light_theme)
        self.initial_section = str(initial_section or "overview")
        self.selected_store = None
        self.project_rows = []
        self.session_rows = []

        self.win = tk.Toplevel(parent)
        self.win.title("Рабочее пространство · ELUTEC")
        self.win.geometry("1240x800")
        self.win.minsize(980, 660)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._refresh()
        if self.initial_section == "projects":
            self.win.after_idle(self._scroll_projects)
        elif self.initial_section == "activity":
            self.win.after_idle(self._scroll_activity)
        self.win.wait_window()

    def _build(self):
        colors = get_palette(self.light_theme)
        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = colors["background"]
        surface = colors["surface"]
        surface_alt = colors["surface_alt"]
        fg = colors["text"]
        muted = colors["muted"]
        border = colors["border"]
        accent = colors["accent"]

        self.win.configure(bg=bg)
        style.configure("ProjectRoot.TFrame", background=bg)
        style.configure("ProjectTopbar.TFrame", background=surface)
        style.configure("ProjectPanel.TFrame", background=surface, relief="solid", borderwidth=1,
                        bordercolor=border, lightcolor=border, darkcolor=border)
        style.configure("ProjectInset.TFrame", background=surface_alt)
        style.configure("ProjectTitle.TLabel", background=bg, foreground=fg,
                        font=("Segoe UI", 22, "bold"))
        style.configure("ProjectHeading.TLabel", background=surface, foreground=fg,
                        font=("Segoe UI", 11, "bold"))
        style.configure("ProjectMuted.TLabel", background=bg, foreground=muted,
                        font=("Segoe UI", 9))
        style.configure("ProjectCardMuted.TLabel", background=surface, foreground=muted,
                        font=("Segoe UI", 9))
        style.configure("ProjectEyebrow.TLabel", background=surface, foreground=muted,
                        font=("Segoe UI", 8, "bold"))
        style.configure("ProjectValue.TLabel", background=surface, foreground=fg,
                        font=("Segoe UI", 20, "bold"))
        style.configure("ProjectBadge.TLabel", background=colors["accent_soft"], foreground=accent,
                        font=("Segoe UI", 8, "bold"), padding=(8, 4))
        style.configure("ProjectPrimary.TButton", background=accent, foreground=colors["accent_on"],
                        padding=(14, 9), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("ProjectPrimary.TButton", background=[("active", colors["accent_hover"])])
        style.configure("Project.TButton", background=surface, foreground=fg,
                        padding=(10, 8), borderwidth=1, bordercolor=border,
                        font=("Segoe UI", 9, "bold"))
        style.map("Project.TButton", background=[("active", colors["surface_hover"])],
                  bordercolor=[("active", accent)])
        style.configure("ProjectWorkspace.TButton", background=surface_alt, foreground=fg,
                        padding=(10, 7), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("ProjectWorkspace.TButton", background=[("active", colors["surface_hover"])])

        shell = ttk.Frame(self.win, style="ProjectRoot.TFrame")
        shell.pack(fill="both", expand=True)
        self.rail = tk.Frame(shell, width=64, bg=surface, highlightthickness=0)
        self.rail.pack(side="left", fill="y")
        self.rail.pack_propagate(False)
        self._build_rail(colors)

        content = ttk.Frame(shell, style="ProjectRoot.TFrame")
        content.pack(side="left", fill="both", expand=True)
        self._build_topbar(content, colors, style)
        self._build_scrollable_dashboard(content, colors)

    def _build_rail(self, colors):
        mark = tk.Label(
            self.rail, text="E", bg=colors["accent"], fg=colors["accent_on"],
            font=("Segoe UI", 14, "bold"), width=2, height=1, padx=2, pady=5,
        )
        mark.pack(pady=(16, 23))
        self._rail_button("⌂", "Обзор", self._scroll_top, active=True, colors=colors)
        self._rail_button("▦", "Проекты", self._scroll_projects, colors=colors)
        self._rail_button("◷", "Активность", self._scroll_activity, colors=colors)
        spacer = tk.Frame(self.rail, bg=colors["surface"])
        spacer.pack(fill="both", expand=True)
        self._rail_button("▤", "Папка проектов", self._choose_workspace, colors=colors)
        self._rail_button("☾" if self.light_theme else "☼", "Сменить тему",
                          self._toggle_theme, colors=colors)
        tk.Label(self.rail, text="SARA\nRGB", bg=colors["surface"], fg=colors["muted"],
                 font=("Segoe UI", 7, "bold"), justify="center").pack(side="bottom", pady=(5, 15))

    def _rail_button(self, glyph, tooltip, command, colors, active=False):
        button = tk.Button(
            self.rail, text=glyph, command=command, cursor="hand2", bd=0,
            relief="flat", font=("Segoe UI Symbol", 16), width=3, height=1,
            bg=colors["accent_soft"] if active else colors["surface"],
            fg=colors["accent"] if active else colors["muted"],
            activebackground=colors["surface_hover"], activeforeground=colors["accent"],
            takefocus=False,
        )
        button.pack(pady=3)
        button.bind("<Enter>", lambda _event, b=button: b.configure(bg=colors["surface_hover"]))
        button.bind("<Leave>", lambda _event, b=button: b.configure(
            bg=colors["accent_soft"] if active else colors["surface"]
        ))
        button.configure(takefocus=False)
        return button

    def _build_topbar(self, parent, colors, style):
        topbar = ttk.Frame(parent, style="ProjectTopbar.TFrame", padding=(22, 12, 22, 12))
        topbar.pack(fill="x")
        brand = ttk.Frame(topbar, style="ProjectTopbar.TFrame")
        brand.pack(side="left", padx=(0, 18))
        ttk.Label(brand, text="ELUTEC  /  LAB SYSTEMS", background=colors["surface"],
                  foreground=colors["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
        ttk.Label(brand, text="SARA RGB", background=colors["surface"], foreground=colors["text"],
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(2, 0))

        ttk.Separator(topbar, orient="vertical").pack(side="left", fill="y", padx=(0, 16), pady=3)
        self.workspace_button = ttk.Button(
            topbar, text="Рабочая папка", command=self._choose_workspace,
            style="ProjectWorkspace.TButton",
        )
        self.workspace_button.pack(side="left")
        self.workspace_path_label = ttk.Label(topbar, text="", background=colors["surface"],
                                               foreground=colors["muted"], font=("Segoe UI", 8))
        self.workspace_path_label.pack(side="left", padx=(9, 0))

        ttk.Button(
            topbar, text="＋  Новый проект", command=self._create_project,
            style="ProjectPrimary.TButton",
        ).pack(side="right")
        ttk.Button(
            topbar, text="Импортировать…", command=self._import_legacy,
            style="Project.TButton",
        ).pack(side="right", padx=(0, 8))

    def _build_scrollable_dashboard(self, parent, colors):
        viewport = ttk.Frame(parent, style="ProjectRoot.TFrame")
        viewport.pack(fill="both", expand=True)
        self.dashboard_canvas = tk.Canvas(
            viewport, bg=colors["background"], highlightthickness=0, bd=0,
        )
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.dashboard_canvas.yview)
        self.dashboard_canvas.configure(yscrollcommand=scrollbar.set)
        self.dashboard_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.page = ttk.Frame(self.dashboard_canvas, style="ProjectRoot.TFrame", padding=(24, 20, 24, 22))
        self.page_window = self.dashboard_canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", lambda _event: self.dashboard_canvas.configure(
            scrollregion=self.dashboard_canvas.bbox("all")
        ))
        self.dashboard_canvas.bind("<Configure>", lambda event: self.dashboard_canvas.itemconfigure(
            self.page_window, width=event.width
        ))
        self.dashboard_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.dashboard_canvas.bind_all("<Button-4>", lambda _event: self.dashboard_canvas.yview_scroll(-1, "units"))
        self.dashboard_canvas.bind_all("<Button-5>", lambda _event: self.dashboard_canvas.yview_scroll(1, "units"))

        heading = ttk.Frame(self.page, style="ProjectRoot.TFrame")
        heading.pack(fill="x", pady=(0, 15))
        title_copy = ttk.Frame(heading, style="ProjectRoot.TFrame")
        title_copy.pack(side="left", fill="x", expand=True)
        ttk.Label(title_copy, text="WORKSPACE / OVERVIEW", foreground=colors["accent"],
                  background=colors["background"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
        ttk.Label(title_copy, text="Обзор", style="ProjectTitle.TLabel").pack(anchor="w", pady=(3, 2))
        ttk.Label(title_copy, text="Проекты, измерения и последние сессии ELUTEC в одном месте.",
                  style="ProjectMuted.TLabel").pack(anchor="w")
        self.project_count_badge = ttk.Label(heading, text="0 проектов", style="ProjectBadge.TLabel")
        self.project_count_badge.pack(side="right", anchor="center", padx=(8, 0), pady=(14, 0))

        self.stats_row = ttk.Frame(self.page, style="ProjectRoot.TFrame")
        self.stats_row.pack(fill="x", pady=(0, 14))
        for col in range(3):
            self.stats_row.columnconfigure(col, weight=1, uniform="stats")
        self.stat_projects = self._make_stat_card(self.stats_row, 0, "ПРОЕКТЫ", "0", "В рабочем пространстве")
        self.stat_sessions = self._make_stat_card(self.stats_row, 1, "СЕССИИ", "0", "Сохранённые измерения")
        self.stat_latest = self._make_stat_card(self.stats_row, 2, "ПОСЛЕДНЯЯ СЕССИЯ", "—", "Пока нет измерений")

        dashboard = ttk.Frame(self.page, style="ProjectRoot.TFrame")
        dashboard.pack(fill="x", pady=(0, 18))
        dashboard.columnconfigure(0, weight=3, uniform="overview")
        dashboard.columnconfigure(1, weight=2, uniform="overview")
        self.activity_card = ttk.Frame(dashboard, style="ProjectPanel.TFrame", padding=16)
        self.activity_card.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.feed_card = ttk.Frame(dashboard, style="ProjectPanel.TFrame", padding=16)
        self.feed_card.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._build_activity_card(colors)
        self._build_feed_card(colors)

        project_heading = ttk.Frame(self.page, style="ProjectRoot.TFrame")
        project_heading.pack(fill="x", pady=(0, 9))
        project_heading.columnconfigure(0, weight=1)
        project_title_block = ttk.Frame(project_heading, style="ProjectRoot.TFrame")
        project_title_block.pack(side="left", fill="x", expand=True)
        ttk.Label(project_title_block, text="WORKSPACE / PROJECTS", foreground=colors["accent"],
                  background=colors["background"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
        ttk.Label(project_title_block, text="Проекты", foreground=colors["text"],
                  background=colors["background"], font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(2, 0))
        self.projects_hint = ttk.Label(project_heading, text="Недавно открытые", style="ProjectMuted.TLabel")
        self.projects_hint.pack(side="right", anchor="s", pady=(0, 2))

        self.projects_container = ttk.Frame(self.page, style="ProjectRoot.TFrame")
        self.projects_container.pack(fill="x")
        self.project_card_columns = 3
        self.projects_container.bind("<Configure>", self._on_projects_configure)

        actions = ttk.Frame(self.page, style="ProjectRoot.TFrame")
        actions.pack(fill="x", pady=(16, 0))
        ttk.Button(actions, text="Открыть папку проекта…", command=self._open_folder,
                   style="Project.TButton").pack(side="left")
        ttk.Button(actions, text="Папка проектов…", command=self._choose_workspace,
                   style="Project.TButton").pack(side="left", padx=(8, 0))
        self.status_label = ttk.Label(actions, text="", style="ProjectMuted.TLabel")
        self.status_label.pack(side="right")

    def _make_stat_card(self, parent, column, label, value, detail):
        card = ttk.Frame(parent, style="ProjectPanel.TFrame", padding=(15, 12))
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 6 if column < 2 else 0))
        ttk.Label(card, text=label, style="ProjectEyebrow.TLabel").pack(anchor="w")
        value_label = ttk.Label(card, text=value, style="ProjectValue.TLabel")
        value_label.pack(anchor="w", pady=(5, 1))
        detail_label = ttk.Label(card, text=detail, style="ProjectCardMuted.TLabel")
        detail_label.pack(anchor="w")
        return value_label, detail_label

    def _build_activity_card(self, colors):
        header = ttk.Frame(self.activity_card, style="ProjectPanel.TFrame")
        header.pack(fill="x")
        copy = ttk.Frame(header, style="ProjectPanel.TFrame")
        copy.pack(side="left", fill="x", expand=True)
        ttk.Label(copy, text="ACTIVITY / LAST 14 DAYS", style="ProjectEyebrow.TLabel").pack(anchor="w")
        ttk.Label(copy, text="Активность сессий", style="ProjectHeading.TLabel").pack(anchor="w", pady=(3, 0))
        self.activity_summary = ttk.Label(header, text="0 сессий", style="ProjectBadge.TLabel")
        self.activity_summary.pack(side="right", anchor="n")
        self.activity_chart = tk.Canvas(
            self.activity_card, height=162, bg=colors["surface"], highlightthickness=0, bd=0,
        )
        self.activity_chart.pack(fill="x", expand=True, pady=(8, 0))
        self.activity_chart.bind("<Configure>", lambda _event: self._draw_activity_chart())
        self._draw_activity_chart()

    def _build_feed_card(self, colors):
        header = ttk.Frame(self.feed_card, style="ProjectPanel.TFrame")
        header.pack(fill="x", pady=(0, 6))
        copy = ttk.Frame(header, style="ProjectPanel.TFrame")
        copy.pack(side="left", fill="x", expand=True)
        ttk.Label(copy, text="SESSION / RECENT", style="ProjectEyebrow.TLabel").pack(anchor="w")
        ttk.Label(copy, text="Последние сессии", style="ProjectHeading.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Button(header, text="Обновить", command=self._refresh, style="ProjectWorkspace.TButton").pack(side="right")
        self.feed_rows = ttk.Frame(self.feed_card, style="ProjectPanel.TFrame")
        self.feed_rows.pack(fill="both", expand=True, pady=(6, 0))

    def _on_projects_configure(self, _event=None):
        for widget in self.projects_container.winfo_children():
            widget.grid_configure(columnspan=1)

    def _on_mousewheel(self, event):
        try:
            if self.win.winfo_exists():
                delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
                if delta:
                    self.dashboard_canvas.yview_scroll(delta, "units")
        except tk.TclError:
            return

    def _scroll_to(self, widget):
        try:
            self.win.update_idletasks()
            total = max(1, self.dashboard_canvas.bbox("all")[3])
            self.dashboard_canvas.yview_moveto(max(0.0, widget.winfo_y() / total))
        except (tk.TclError, TypeError):
            pass

    def _toggle_theme(self):
        try:
            scroll_position = float(self.dashboard_canvas.yview()[0])
        except (tk.TclError, IndexError, TypeError, ValueError):
            scroll_position = 0.0
        self.light_theme = not self.light_theme
        if callable(self.on_theme_change):
            try:
                self.on_theme_change(self.light_theme)
            except Exception:
                pass
        try:
            self.dashboard_canvas.unbind_all("<MouseWheel>")
            self.dashboard_canvas.unbind_all("<Button-4>")
            self.dashboard_canvas.unbind_all("<Button-5>")
        except (AttributeError, tk.TclError):
            pass
        for child in self.win.winfo_children():
            child.destroy()
        self._build()
        self._refresh()
        self.dashboard_canvas.yview_moveto(scroll_position)

    def _scroll_top(self):
        self.dashboard_canvas.yview_moveto(0.0)

    def _scroll_projects(self):
        self._scroll_to(self.projects_container)

    def _scroll_activity(self):
        self._scroll_to(self.activity_card)

    @staticmethod
    def _parse_datetime(value):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.astimezone()
            return parsed.astimezone()
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _format_date(cls, value):
        parsed = cls._parse_datetime(value)
        if parsed is None:
            return "Дата не указана"
        today = datetime.now().astimezone().date()
        if parsed.date() == today:
            return "Сегодня · " + parsed.strftime("%H:%M")
        if parsed.date() == today - timedelta(days=1):
            return "Вчера · " + parsed.strftime("%H:%M")
        return parsed.strftime("%d.%m.%Y")

    @staticmethod
    def _project_count_label(count):
        remainder_10, remainder_100 = count % 10, count % 100
        if remainder_10 == 1 and remainder_100 != 11:
            noun = "проект"
        elif 2 <= remainder_10 <= 4 and not 12 <= remainder_100 <= 14:
            noun = "проекта"
        else:
            noun = "проектов"
        return f"{count} {noun}"

    def _collect_project_rows(self):
        rows = []
        seen = set()
        recent = ProjectStore.recent_projects()
        if self.current_path and self.current_path not in {str(Path(r.get("path", "")).resolve()) for r in recent}:
            try:
                current = ProjectStore(self.current_path)
                recent.insert(0, {"path": str(current.root), "name": current.manifest.get("name", current.root.name)})
            except (OSError, ValueError):
                pass
        for row in recent:
            try:
                path = str(Path(row["path"]).expanduser().resolve())
                if path in seen:
                    continue
                store = ProjectStore(path)
                sessions = store.list_sessions()
                data = {
                    "path": path,
                    "name": str(store.manifest.get("name") or row.get("name") or Path(path).name),
                    "description": str(store.manifest.get("description") or "Измерения SARA RGB"),
                    "updated_at": store.manifest.get("updated_at", ""),
                    "sessions": sessions,
                    "store": store,
                }
                rows.append(data)
                seen.add(path)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return rows

    def _refresh(self):
        self.project_rows = self._collect_project_rows()
        self.session_rows = []
        for project in self.project_rows:
            for session in project["sessions"]:
                item = dict(session)
                item["_project_name"] = project["name"]
                item["_project_path"] = project["path"]
                self.session_rows.append(item)
        self.session_rows.sort(
            key=lambda row: (self._parse_datetime(row.get("started_at") or row.get("created_at")) or
                             datetime.fromtimestamp(0).astimezone()).timestamp(),
            reverse=True,
        )

        total_sessions = sum(len(project["sessions"]) for project in self.project_rows)
        latest = self.session_rows[0] if self.session_rows else None
        self.stat_projects[0].configure(text=str(len(self.project_rows)))
        self.stat_projects[1].configure(text="Недавно открытые проекты")
        self.stat_sessions[0].configure(text=str(total_sessions))
        self.stat_sessions[1].configure(text="Сохранённые измерения")
        self.stat_latest[0].configure(text=self._format_date(latest.get("started_at") or latest.get("created_at"))
                                      if latest else "—")
        latest_name = (latest.get("display_name") or latest.get("project_name") or "Сессия") if latest else "Пока нет измерений"
        if len(str(latest_name)) > 34:
            latest_name = str(latest_name)[:31] + "…"
        self.stat_latest[1].configure(text=latest_name)
        self.project_count_badge.configure(text=self._project_count_label(len(self.project_rows)))
        workspace = ProjectStore.default_workspace_root()
        self.workspace_button.configure(text="Main Workspace  ▾")
        workspace_text = str(workspace)
        if len(workspace_text) > 52:
            workspace_text = "…" + workspace_text[-51:]
        self.workspace_path_label.configure(text=workspace_text)
        self.status_label.configure(text=f"Хранение: {workspace}")
        self._render_feed()
        self._render_projects()
        self._draw_activity_chart()

    def _render_feed(self):
        for child in self.feed_rows.winfo_children():
            child.destroy()
        if not self.session_rows:
            empty = ttk.Frame(self.feed_rows, style="ProjectInset.TFrame", padding=13)
            empty.pack(fill="x", pady=(4, 0))
            ttk.Label(empty, text="Пока нет завершённых измерений", background=get_palette(self.light_theme)["surface_alt"],
                      foreground=get_palette(self.light_theme)["text"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            ttk.Label(empty, text="После анализа здесь появятся сессии, результаты и время запуска.",
                      background=get_palette(self.light_theme)["surface_alt"],
                      foreground=get_palette(self.light_theme)["muted"], wraplength=300,
                      font=("Segoe UI", 8)).pack(anchor="w", pady=(5, 0))
            return

        colors = get_palette(self.light_theme)
        status_labels = {
            "completed": ("Готово", colors["success"]),
            "running": ("В работе", colors["accent"]),
            "failed": ("Ошибка", colors["danger"]),
        }
        for session in self.session_rows[:4]:
            row = ttk.Frame(self.feed_rows, style="ProjectPanel.TFrame", padding=(0, 8))
            row.pack(fill="x")
            status_text, status_color = status_labels.get(str(session.get("status", "")).lower(),
                                                           ("Сессия", colors["muted"]))
            marker = tk.Canvas(row, width=25, height=25, bg=colors["surface"], highlightthickness=0)
            marker.pack(side="left", padx=(0, 9), anchor="n")
            marker.create_oval(6, 6, 19, 19, fill=status_color, outline="")
            copy = ttk.Frame(row, style="ProjectPanel.TFrame")
            copy.pack(side="left", fill="x", expand=True)
            title = session.get("display_name") or session.get("sample_id") or "Измерение SARA RGB"
            ttk.Label(copy, text=str(title)[:42], background=colors["surface"], foreground=colors["text"],
                      font=("Segoe UI", 9, "bold")).pack(anchor="w")
            subtitle = "{}  ·  {}".format(session.get("_project_name", "Проект"),
                                           self._format_date(session.get("started_at") or session.get("created_at")))
            ttk.Label(copy, text=subtitle, background=colors["surface"], foreground=colors["muted"],
                      font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))
            ttk.Label(row, text=status_text, background=colors["surface"], foreground=status_color,
                      font=("Segoe UI", 8, "bold")).pack(side="right", anchor="n")
            ttk.Separator(self.feed_rows, orient="horizontal").pack(fill="x")

    def _render_projects(self):
        for child in self.projects_container.winfo_children():
            child.destroy()
        colors = get_palette(self.light_theme)
        if not self.project_rows:
            empty = ttk.Frame(self.projects_container, style="ProjectPanel.TFrame", padding=20)
            empty.grid(row=0, column=0, sticky="ew")
            ttk.Label(empty, text="Начните с рабочего проекта", background=colors["surface"],
                      foreground=colors["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w")
            ttk.Label(empty, text="Создайте проект для хранения профилей, сессий и экспортированных измерений.",
                      background=colors["surface"], foreground=colors["muted"],
                      font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 13))
            ttk.Button(empty, text="＋  Создать проект", command=self._create_project,
                       style="ProjectPrimary.TButton").pack(anchor="w")
            return

        for column in range(3):
            self.projects_container.columnconfigure(column, weight=1, uniform="project-cards")
        for index, project in enumerate(self.project_rows):
            row_num, col_num = divmod(index, 3)
            card = ttk.Frame(self.projects_container, style="ProjectPanel.TFrame", padding=14)
            card.grid(row=row_num, column=col_num, sticky="nsew", padx=(0 if col_num == 0 else 6, 6 if col_num < 2 else 0),
                      pady=(0, 12))
            is_current = project["path"] == self.current_path
            top = ttk.Frame(card, style="ProjectPanel.TFrame")
            top.pack(fill="x")
            dot = tk.Canvas(top, width=12, height=12, bg=colors["surface"], highlightthickness=0)
            dot.pack(side="left", padx=(0, 7), pady=(2, 0))
            dot.create_oval(2, 2, 10, 10, fill=colors["success"] if is_current else colors["accent"], outline="")
            ttk.Label(top, text="АКТИВНЫЙ" if is_current else "ПРОЕКТ", style="ProjectEyebrow.TLabel").pack(side="left")
            ttk.Label(top, text=f"{len(project['sessions'])} сесс." , style="ProjectBadge.TLabel").pack(side="right")
            ttk.Label(card, text=project["name"], background=colors["surface"], foreground=colors["text"],
                      font=("Segoe UI", 12, "bold"), wraplength=270,
                      justify="left").pack(anchor="w", fill="x", pady=(11, 3))
            ttk.Label(card, text=project["description"][:78], background=colors["surface"],
                      foreground=colors["muted"], font=("Segoe UI", 8), wraplength=280,
                      justify="left").pack(anchor="w", fill="x")
            ttk.Separator(card, orient="horizontal").pack(fill="x", pady=(12, 8))
            last = project["sessions"][0] if project["sessions"] else None
            last_text = self._format_date(last.get("started_at") or last.get("created_at")) if last else "Пока без сессий"
            ttk.Label(card, text=f"Последнее измерение  ·  {last_text}", background=colors["surface"],
                      foreground=colors["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 10))
            ttk.Button(card, text="Открыть проект", command=lambda path=project["path"]: self._open_path(path),
                       style="ProjectWorkspace.TButton").pack(anchor="w")

    def _draw_activity_chart(self):
        canvas = getattr(self, "activity_chart", None)
        if canvas is None:
            return
        colors = get_palette(self.light_theme)
        canvas.delete("all")
        width = max(240, canvas.winfo_width())
        height = max(120, canvas.winfo_height())
        left, right, top, bottom = 14, width - 14, 15, height - 28
        if right <= left:
            return
        today = datetime.now().astimezone().date()
        start_day = today - timedelta(days=13)
        counts = [0] * 14
        for session in self.session_rows:
            parsed = self._parse_datetime(session.get("started_at") or session.get("created_at"))
            if parsed is None:
                continue
            index = (parsed.date() - start_day).days
            if 0 <= index < len(counts):
                counts[index] += 1
        for fraction in (0.25, 0.5, 0.75, 1.0):
            y = bottom - (bottom - top) * fraction
            canvas.create_line(left, y, right, y, fill=colors["chart_grid"], width=1)
        max_value = max(counts) if counts else 0
        if hasattr(self, "activity_summary"):
            self.activity_summary.configure(text=f"{sum(counts)} за 14 дней")
        points = []
        for index, value in enumerate(counts):
            x = left + (right - left) * index / (len(counts) - 1)
            ratio = value / max_value if max_value else 0
            y = bottom - ratio * (bottom - top - 6)
            points.append((x, y))
        if max_value:
            area = [left, bottom]
            for x, y in points:
                area.extend((x, y))
            area.extend((right, bottom))
            canvas.create_polygon(*area, fill=colors["accent_soft"], outline="", smooth=True)
            flat_points = [coord for pair in points for coord in pair]
            canvas.create_line(*flat_points, fill=colors["accent"], width=2.5, smooth=True)
            for x, y in points:
                if y < bottom - 1:
                    canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=colors["accent"], outline=colors["surface"], width=1)
        else:
            canvas.create_line(left, bottom, right, bottom, fill=colors["border"], width=2)
            empty_text = ("За последние 14 дней сессий не было" if self.session_rows
                          else "Сессии появятся после первого анализа")
            canvas.create_text((left + right) / 2, (top + bottom) / 2,
                               text=empty_text, fill=colors["muted"], font=("Segoe UI", 9))
        canvas.create_text(left, height - 9, text="14 дней назад", anchor="w",
                           fill=colors["muted"], font=("Segoe UI", 8))
        canvas.create_text((left + right) / 2, height - 9, text="7 дней",
                           fill=colors["muted"], font=("Segoe UI", 8))
        canvas.create_text(right, height - 9, text="Сегодня", anchor="e",
                           fill=colors["muted"], font=("Segoe UI", 8))

    def _choose_workspace(self):
        selected = filedialog.askdirectory(
            title="Папка рабочего пространства ELUTEC",
            initialdir=str(ProjectStore.default_workspace_root()), parent=self.win,
        )
        if not selected:
            return
        try:
            ProjectStore.set_default_workspace_root(selected)
        except Exception as exc:
            messagebox.showerror("Рабочая папка", f"Не удалось сохранить папку:\n{exc}", parent=self.win)
            return
        self._refresh()

    def _create_project(self):
        name = simpledialog.askstring("Новый проект", "Название проекта:", parent=self.win)
        if not name or not name.strip():
            return
        try:
            store = ProjectStore.create_project(name.strip())
        except Exception as exc:
            messagebox.showerror("Проект", f"Не удалось создать проект:\n{exc}", parent=self.win)
            return
        self._accept(store)

    def _open_folder(self):
        selected = filedialog.askdirectory(title="Выберите папку проекта", parent=self.win)
        if not selected:
            return
        try:
            store = ProjectStore.open_project(selected)
        except Exception:
            answer = messagebox.askyesno(
                "Нет манифеста проекта",
                "В выбранной папке нет project.json. Импортировать её как старую папку результатов?",
                parent=self.win,
            )
            if not answer:
                return
            self._import_from(selected)
            return
        self._accept(store)

    def _import_legacy(self):
        selected = filedialog.askdirectory(title="Выберите старую папку с результатами", parent=self.win)
        if selected:
            self._import_from(selected)

    def _import_from(self, selected):
        source = Path(selected)
        name = simpledialog.askstring(
            "Импорт результатов", "Название нового проекта:", initialvalue=source.name, parent=self.win,
        )
        if not name or not name.strip():
            return
        try:
            store, result = ProjectStore.import_legacy_folder(selected, name.strip())
        except Exception as exc:
            messagebox.showerror("Импорт", f"Не удалось импортировать папку:\n{exc}", parent=self.win)
            return
        messagebox.showinfo(
            "Импорт завершён",
            f"Создан проект «{store.manifest['name']}».\n"
            f"Сессий найдено: {result['sessions']}\n"
            f"Прочих файлов скопировано: {result['unmatched']}\n\n"
            "Исходная папка не изменена.", parent=self.win,
        )
        self._accept(store)

    def _open_path(self, path):
        try:
            store = ProjectStore.open_project(path)
        except Exception as exc:
            messagebox.showerror("Проект", f"Не удалось открыть проект:\n{exc}", parent=self.win)
            self._refresh()
            return
        self._accept(store)

    def _open_selected(self):
        if self.current_path:
            self._open_path(self.current_path)
        elif self.project_rows:
            self._open_path(self.project_rows[0]["path"])

    def _accept(self, store):
        self.selected_store = store
        self.close()
        if self.on_open:
            self.on_open(store)

    def close(self):
        try:
            self.dashboard_canvas.unbind_all("<MouseWheel>")
            self.dashboard_canvas.unbind_all("<Button-4>")
            self.dashboard_canvas.unbind_all("<Button-5>")
        except (AttributeError, tk.TclError):
            pass
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        try:
            if self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
