"""Project selection and workspace management for ELUTEC."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from ..data.project_store import ProjectStore
from .theme import get_palette


class ProjectManagerDialog:
    """Create, import, and open projects without session/activity dashboards."""

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

        self.win = tk.Toplevel(parent)
        self.win.title("Проекты · ELUTEC")
        self.win.geometry("1120x760")
        self.win.minsize(940, 620)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._refresh()
        if self.initial_section == "projects":
            self.win.after_idle(self._scroll_projects)
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
        style.configure("ProjectTitle.TLabel", background=bg, foreground=fg,
                        font=("Segoe UI", 21, "bold"))
        style.configure("ProjectHeading.TLabel", background=surface, foreground=fg,
                        font=("Segoe UI", 11, "bold"))
        style.configure("ProjectMuted.TLabel", background=bg, foreground=muted,
                        font=("Segoe UI", 9))
        style.configure("ProjectCardMuted.TLabel", background=surface, foreground=muted,
                        font=("Segoe UI", 9))
        style.configure("ProjectBadge.TLabel", background=colors["accent_soft"], foreground=accent,
                        font=("Segoe UI", 8, "bold"), padding=(8, 4))
        style.configure("ProjectPrimary.TButton", background=accent, foreground=colors["accent_on"],
                        padding=(12, 8), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("ProjectPrimary.TButton", background=[("active", colors["accent_hover"])])
        style.configure("Project.TButton", background=surface, foreground=fg,
                        padding=(9, 7), borderwidth=1, bordercolor=border,
                        font=("Segoe UI", 9, "bold"))
        style.map("Project.TButton", background=[("active", colors["surface_hover"])],
                  bordercolor=[("active", accent)])
        style.configure("ProjectWorkspace.TButton", background=surface_alt, foreground=fg,
                        padding=(9, 7), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("ProjectWorkspace.TButton", background=[("active", colors["surface_hover"])])
        style.configure("Vertical.TScrollbar", background=surface_alt, troughcolor=surface,
                        bordercolor=surface, arrowcolor=muted, gripcount=0)

        shell = ttk.Frame(self.win, style="ProjectRoot.TFrame")
        shell.pack(fill="both", expand=True)
        self.rail = tk.Frame(shell, width=60, bg=surface, highlightthickness=0)
        self.rail.pack(side="left", fill="y")
        self.rail.pack_propagate(False)
        self._build_rail(colors)

        content = ttk.Frame(shell, style="ProjectRoot.TFrame")
        content.pack(side="left", fill="both", expand=True)
        self._build_topbar(content, colors)
        self._build_scrollable_projects(content, colors)

    def _build_rail(self, colors):
        mark = tk.Label(
            self.rail, text="E", bg=colors["accent"], fg=colors["accent_on"],
            font=("Segoe UI", 14, "bold"), width=2, height=1, padx=2, pady=5,
        )
        mark.pack(pady=(15, 20))
        self._rail_button("⌂", self._scroll_top, colors, active=True)
        self._rail_button("▦", self._scroll_projects, colors)
        spacer = tk.Frame(self.rail, bg=colors["surface"])
        spacer.pack(fill="both", expand=True)
        self._rail_button("▤", self._choose_workspace, colors)
        self._rail_button("☾" if self.light_theme else "☼", self._toggle_theme, colors)

    def _rail_button(self, glyph, command, colors, active=False):
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
        return button

    def _build_topbar(self, parent, colors):
        topbar = ttk.Frame(parent, style="ProjectTopbar.TFrame", padding=(20, 11, 20, 11))
        topbar.pack(fill="x")
        ttk.Label(topbar, text="ELUTEC · SARA RGB", background=colors["surface"],
                  foreground=colors["text"], font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 18))
        self.workspace_button = ttk.Button(
            topbar, text="Рабочая папка", command=self._choose_workspace,
            style="ProjectWorkspace.TButton",
        )
        self.workspace_button.pack(side="left")

        ttk.Button(
            topbar, text="＋ Новый проект", command=self._create_project,
            style="ProjectPrimary.TButton",
        ).pack(side="right")
        ttk.Button(
            topbar, text="Импортировать…", command=self._import_legacy,
            style="Project.TButton",
        ).pack(side="right", padx=(0, 8))

    def _build_scrollable_projects(self, parent, colors):
        viewport = ttk.Frame(parent, style="ProjectRoot.TFrame")
        viewport.pack(fill="both", expand=True)
        self.dashboard_canvas = tk.Canvas(
            viewport, bg=colors["background"], highlightthickness=0, bd=0,
        )
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.dashboard_canvas.yview)
        self.dashboard_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.dashboard_canvas.pack(side="left", fill="both", expand=True)

        self.page = ttk.Frame(self.dashboard_canvas, style="ProjectRoot.TFrame", padding=(22, 20, 22, 22))
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
        heading.pack(fill="x", pady=(0, 16))
        ttk.Label(heading, text="Проекты", style="ProjectTitle.TLabel").pack(side="left")
        ttk.Button(heading, text="Открыть папку проекта…", command=self._open_folder,
                   style="Project.TButton").pack(side="right", anchor="center")

        self.projects_container = ttk.Frame(self.page, style="ProjectRoot.TFrame")
        self.projects_container.pack(fill="x")

    def _on_mousewheel(self, event):
        try:
            if self.win.winfo_exists():
                delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
                if delta:
                    self.dashboard_canvas.yview_scroll(delta, "units")
        except tk.TclError:
            return

    def _scroll_top(self):
        self.dashboard_canvas.yview_moveto(0.0)

    def _scroll_projects(self):
        self._scroll_top()

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
        self._unbind_mousewheel()
        for child in self.win.winfo_children():
            child.destroy()
        self._build()
        self._refresh()
        self.win.after_idle(lambda: self.dashboard_canvas.yview_moveto(scroll_position))

    def _unbind_mousewheel(self):
        try:
            self.dashboard_canvas.unbind_all("<MouseWheel>")
            self.dashboard_canvas.unbind_all("<Button-4>")
            self.dashboard_canvas.unbind_all("<Button-5>")
        except (AttributeError, tk.TclError):
            pass

    def _collect_project_rows(self):
        rows = []
        seen = set()
        recent = ProjectStore.recent_projects()
        recent_paths = {str(Path(row.get("path", "")).expanduser().resolve()) for row in recent}
        if self.current_path and self.current_path not in recent_paths:
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
                rows.append({
                    "path": path,
                    "name": str(store.manifest.get("name") or row.get("name") or Path(path).name),
                    "description": str(store.manifest.get("description") or "").strip(),
                })
                seen.add(path)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return rows

    def _refresh(self):
        self.project_rows = self._collect_project_rows()
        workspace = ProjectStore.default_workspace_root()
        self.workspace_button.configure(text=f"{workspace.name or 'Рабочая папка'}  ▾")
        self._render_projects()
        self.win.update_idletasks()
        self.dashboard_canvas.configure(scrollregion=self.dashboard_canvas.bbox("all"))

    def _render_projects(self):
        for child in self.projects_container.winfo_children():
            child.destroy()
        colors = get_palette(self.light_theme)
        if not self.project_rows:
            empty = ttk.Frame(self.projects_container, style="ProjectPanel.TFrame", padding=20)
            empty.grid(row=0, column=0, sticky="ew")
            ttk.Label(empty, text="Проектов пока нет", style="ProjectHeading.TLabel").pack(anchor="w")
            ttk.Button(empty, text="＋ Создать проект", command=self._create_project,
                       style="ProjectPrimary.TButton").pack(anchor="w", pady=(13, 0))
            return

        for column in range(3):
            self.projects_container.columnconfigure(column, weight=1, uniform="project-cards")
        for index, project in enumerate(self.project_rows):
            row_num, col_num = divmod(index, 3)
            card = ttk.Frame(self.projects_container, style="ProjectPanel.TFrame", padding=14)
            card.grid(
                row=row_num, column=col_num, sticky="nsew",
                padx=(0 if col_num == 0 else 6, 6 if col_num < 2 else 0), pady=(0, 12),
            )
            if project["path"] == self.current_path:
                ttk.Label(card, text="ТЕКУЩИЙ", style="ProjectBadge.TLabel").pack(anchor="w")
            ttk.Label(
                card, text=project["name"], background=colors["surface"], foreground=colors["text"],
                font=("Segoe UI", 12, "bold"), wraplength=270, justify="left",
            ).pack(anchor="w", fill="x", pady=(5, 4) if project["path"] == self.current_path else (0, 4))
            if project["description"]:
                ttk.Label(
                    card, text=project["description"], style="ProjectCardMuted.TLabel",
                    wraplength=270, justify="left",
                ).pack(anchor="w", fill="x", pady=(0, 11))
            else:
                ttk.Frame(card, height=8, style="ProjectPanel.TFrame").pack(fill="x")
            ttk.Button(
                card, text="Открыть проект", command=lambda path=project["path"]: self._open_path(path),
                style="ProjectWorkspace.TButton",
            ).pack(anchor="w", pady=(2, 0))

    def _choose_workspace(self):
        selected = filedialog.askdirectory(
            title="Папка проектов ELUTEC",
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
            if answer:
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

    def _accept(self, store):
        self.selected_store = store
        self.close()
        if self.on_open:
            self.on_open(store)

    def close(self):
        self._unbind_mousewheel()
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        try:
            if self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
