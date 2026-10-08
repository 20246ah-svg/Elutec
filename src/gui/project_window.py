"""Small project browser for creating, opening, and importing ELUTEC projects."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path

from ..data.project_store import ProjectStore
from .theme import get_palette


class ProjectManagerDialog:
    def __init__(self, parent, on_open, current_path=None, light_theme=False):
        self.parent = parent
        self.on_open = on_open
        self.current_path = str(current_path or "")
        self.light_theme = bool(light_theme)
        self.selected_store = None
        self.win = tk.Toplevel(parent)
        self.win.title("Проекты · ELUTEC")
        self.win.geometry("950x520")
        self.win.minsize(820, 420)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._refresh()
        self.win.wait_window()

    def _build(self):
        colors = get_palette(self.light_theme)
        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        bg, surface = colors["background"], colors["surface"]
        fg, muted, border = colors["text"], colors["muted"], colors["border"]
        accent = colors["accent"]
        self.win.configure(bg=bg)
        style.configure("Project.TFrame", background=bg)
        style.configure("ProjectSurface.TFrame", background=surface)
        style.configure("ProjectTitle.TLabel", background=bg, foreground=fg, font=("Segoe UI", 16, "bold"))
        style.configure("ProjectMuted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 9))
        style.configure("Project.TButton", background=surface, foreground=fg, padding=(10, 7),
                        borderwidth=1, bordercolor=border, font=("Segoe UI", 9, "bold"))
        style.map("Project.TButton", background=[("active", colors["surface_hover"])],
                  bordercolor=[("active", accent)])
        style.configure("ProjectPrimary.TButton", background=accent, foreground=colors["accent_on"],
                        padding=(12, 8), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.configure("Project.Treeview", background=surface, fieldbackground=surface,
                        foreground=fg, rowheight=34, borderwidth=0, font=("Segoe UI", 9))
        style.map("Project.Treeview", background=[("selected", colors["accent_soft"])],
                  foreground=[("selected", accent)])
        style.configure("Project.Treeview.Heading", background=colors["surface_alt"], foreground=muted,
                        relief="flat", padding=(8, 7), font=("Segoe UI", 8, "bold"))

        outer = ttk.Frame(self.win, style="Project.TFrame", padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Проекты", style="ProjectTitle.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Откройте недавний проект, создайте новый или перенесите старые результаты.",
                  style="ProjectMuted.TLabel").pack(anchor="w", pady=(4, 13))

        self.tree = ttk.Treeview(
            outer, columns=("name", "sessions", "path"), show="headings", style="Project.Treeview", height=10
        )
        self.tree.heading("name", text="ПРОЕКТ")
        self.tree.heading("sessions", text="СЕССИИ")
        self.tree.heading("path", text="РАСПОЛОЖЕНИЕ")
        self.tree.column("name", width=230, minwidth=150)
        self.tree.column("sessions", width=80, anchor="center", stretch=False)
        self.tree.column("path", width=390, minwidth=180)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-Button-1>", lambda event: self._open_selected())
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        row = ttk.Frame(outer, style="Project.TFrame")
        row.pack(fill="x", pady=(13, 0))
        ttk.Button(row, text="Новый проект…", command=self._create_project,
                   style="ProjectPrimary.TButton").pack(side="left")
        ttk.Button(row, text="Папка проектов…", command=self._choose_workspace,
                   style="Project.TButton").pack(side="left", padx=(7, 0))
        ttk.Button(row, text="Открыть папку…", command=self._open_folder,
                   style="Project.TButton").pack(side="left", padx=(7, 0))
        ttk.Button(row, text="Импортировать старую папку…", command=self._import_legacy,
                   style="Project.TButton").pack(side="left", padx=(7, 0))
        self.open_btn = ttk.Button(row, text="Открыть проект", command=self._open_selected,
                                   style="Project.TButton", state="disabled")
        self.open_btn.pack(side="right")
        ttk.Button(row, text="Отмена", command=self.close, style="Project.TButton").pack(side="right", padx=(0, 7))
        self.status = ttk.Label(outer, text="", style="ProjectMuted.TLabel")
        self.status.pack(anchor="w", pady=(8, 0))

    def _refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, row in enumerate(ProjectStore.recent_projects()):
            try:
                store = ProjectStore(row["path"])
                count = len(store.list_sessions())
            except Exception:
                count = 0
            iid = str(index)
            self.tree.insert("", "end", iid=iid, values=(row.get("name", "Проект"), count, row["path"]))
            if row["path"] == self.current_path:
                self.tree.selection_set(iid)
                self.tree.focus(iid)
        self.status.config(text=f"Папка проектов по умолчанию: {ProjectStore.default_workspace_root()}")
        self._selection_changed()

    def _selection_changed(self, event=None):
        self.open_btn.configure(state="normal" if self.tree.selection() else "disabled")

    def _choose_workspace(self):
        selected = filedialog.askdirectory(
            title="Папка для новых проектов", initialdir=str(ProjectStore.default_workspace_root()), parent=self.win
        )
        if not selected:
            return
        try:
            ProjectStore.set_default_workspace_root(selected)
        except Exception as exc:
            messagebox.showerror("Папка проектов", f"Не удалось сохранить папку:\n{exc}", parent=self.win)
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
            "Импорт результатов", "Название нового проекта:", initialvalue=source.name, parent=self.win
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
            "Исходная папка не изменена.",
            parent=self.win,
        )
        self._accept(store)

    def _open_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        path = self.tree.item(selection[0], "values")[2]
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
        try:
            self.win.grab_release()
        except Exception:
            pass
        if self.win.winfo_exists():
            self.win.destroy()
