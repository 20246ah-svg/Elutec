#!/usr/bin/env python3
"""
Графическое мини-приложение для генерации лицензионных ключей «Элютек».
Используется разработчиком и администратором для автономного выпуска ключей клиентам.

Запуск:
    python tools/keygen_gui.py
    или двойной клик по keygen.bat
"""

import sys
import os
import csv
import uuid
import hmac
import hashlib
import platform
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

# Внутренний секретный ключ подписи лицензий (Master Secret)
_MASTER_SALT = b"ELUTEK-SARA-RGB-ANALYSIS-PROT-2026-v12"


def get_hardware_id() -> str:
    """Возвращает аппаратный идентификатор машины (Hardware ID)."""
    raw_components = [
        platform.machine(),
        platform.processor(),
        platform.system()
    ]
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                if guid:
                    raw_components.append(str(guid).strip())
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        mid = f.read().strip()
                        if mid:
                            raw_components.append(mid)
                            break
                except Exception:
                    pass

    try:
        node = uuid.getnode()
        if node and node != 0:
            raw_components.append(f"{node:012x}")
    except Exception:
        pass

    raw_str = "|".join(raw_components)
    digest = hashlib.sha256(raw_str.encode("utf-8")).hexdigest().upper()
    return f"ELU-{digest[0:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"


def generate_activation_key(hwid: str, lic_type: str = "PRO") -> str:
    """Генерирует криптографический ключ активации для указанного Hardware ID."""
    clean_hwid = str(hwid).strip().upper().replace(" ", "")
    clean_type = str(lic_type).strip().upper()
    payload = f"{clean_hwid}:{clean_type}".encode("utf-8")
    sig = hmac.new(_MASTER_SALT, payload, hashlib.sha256).hexdigest().upper()
    return f"KEY-{sig[0:4]}-{sig[4:8]}-{sig[8:12]}-{sig[12:16]}"


def verify_activation_key(key: str, hwid: str) -> tuple:
    """Проверяет валидность ключа активации для указанного HWID."""
    if not key or not isinstance(key, str):
        return False, "", "Ключ не указан."
    clean_key = key.strip().upper().replace(" ", "")
    target_hwid = hwid.strip().upper().replace(" ", "")
    
    for lic_type in ("PRO", "ENTERPRISE", "PERPETUAL", "STANDARD", "EXTENDED", "1 ГОД", "2 ГОДА", "5 ЛЕТ", "TRIAL"):
        expected = generate_activation_key(target_hwid, lic_type=lic_type)
        if clean_key == expected:
            return True, lic_type, f"Лицензия «{lic_type}» успешно подтверждена."
    expected_pro = generate_activation_key(target_hwid, "PRO")
    if clean_key == expected_pro:
        return True, "PRO", "Лицензия PRO успешно подтверждена."
    return False, "", "Неверный ключ для данного оборудования."


HISTORY_CSV_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "generated_licenses.csv"))


class KeygenApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🔑 Генератор лицензий — Элютек SARA RGB")
        self.root.geometry("740x780")
        self.root.minsize(680, 680)
        
        self.current_local_hwid = get_hardware_id()
        self._setup_style()
        self._build_ui()
        self._load_history()

    def _setup_style(self):
        self.bg = "#0B0F19"
        self.panel = "#131B2E"
        self.panel_card = "#182238"
        self.panel_light = "#1E293B"
        self.fg = "#F8FAFC"
        self.fg_muted = "#94A3B8"
        self.accent = "#3B82F6"
        self.accent_hover = "#2563EB"
        self.success = "#10B981"
        self.success_hover = "#059669"
        self.border = "#2A3756"

        self.root.configure(bg=self.bg)
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", font=("Segoe UI", 9), background=self.bg, foreground=self.fg)
        style.configure("TFrame", background=self.bg)
        style.configure("TLabel", background=self.bg, foreground=self.fg)
        
        style.configure(
            "TLabelframe",
            background=self.bg,
            foreground="#60A5FA",
            bordercolor=self.border,
            relief="solid",
            borderwidth=1
        )
        style.configure(
            "TLabelframe.Label",
            background=self.bg,
            foreground="#60A5FA",
            font=("Segoe UI", 10, "bold")
        )
        
        style.configure(
            "TEntry",
            fieldbackground=self.panel,
            foreground=self.fg,
            bordercolor=self.border,
            lightcolor=self.accent,
            padding=5
        )
        style.configure(
            "TCombobox",
            fieldbackground=self.panel,
            background=self.panel_light,
            foreground=self.fg,
            bordercolor=self.border,
            padding=4
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.panel)],
            selectbackground=[("readonly", self.accent)],
            selectforeground=[("readonly", "#FFFFFF")]
        )
        
        # Primary Generate Button
        style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            background="#2563EB",
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(12, 9)
        )
        style.map("Primary.TButton", background=[("active", "#1D4ED8"), ("pressed", "#1E40AF")])

        # Secondary Button
        style.configure(
            "Secondary.TButton",
            font=("Segoe UI", 9),
            background=self.panel_light,
            foreground=self.fg,
            borderwidth=1,
            bordercolor=self.border,
            padding=(8, 6)
        )
        style.map("Secondary.TButton", background=[("active", "#334155"), ("pressed", "#1E293B")])

        # Success Copy Button
        style.configure(
            "Success.TButton",
            font=("Segoe UI", 9, "bold"),
            background="#059669",
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(10, 7)
        )
        style.map("Success.TButton", background=[("active", "#047857"), ("pressed", "#065F46")])

        # Treeview Dark Styling
        style.configure(
            "Treeview",
            background="#131B2E",
            foreground="#F1F5F9",
            fieldbackground="#131B2E",
            bordercolor=self.border,
            rowheight=24,
            font=("Segoe UI", 9)
        )
        style.configure(
            "Treeview.Heading",
            background="#1E293B",
            foreground="#93C5FD",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padding=4
        )
        style.map(
            "Treeview",
            background=[("selected", "#2563EB")],
            foreground=[("selected", "#FFFFFF")]
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#334155")]
        )

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        # 1. Заголовок
        hdr = ttk.Frame(main)
        hdr.pack(fill="x", pady=(0, 12))
        ttk.Label(
            hdr,
            text="🔑 Элютек: Генератор лицензионных ключей",
            font=("Segoe UI", 15, "bold"),
            foreground="#60A5FA"
        ).pack(anchor="w")
        ttk.Label(
            hdr,
            text="Автономный выпуск ключей активации для клиентских компьютеров (Offline)",
            font=("Segoe UI", 9),
            foreground=self.fg_muted
        ).pack(anchor="w", pady=(2, 0))

        # 2. Блок ввода Hardware ID
        lf_hwid = ttk.LabelFrame(main, text=" 💻 Аппаратный ID клиента (Hardware ID) ", padding=12)
        lf_hwid.pack(fill="x", pady=(0, 10))

        row_hw = ttk.Frame(lf_hwid)
        row_hw.pack(fill="x")

        self.hwid_var = tk.StringVar(value="")
        self.entry_hwid = ttk.Entry(row_hw, textvariable=self.hwid_var, font=("Consolas", 11, "bold"))
        self.entry_hwid.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_hwid.bind("<Return>", lambda e: self.generate_key())

        btn_paste = ttk.Button(row_hw, text="📋 Вставить", style="Secondary.TButton", command=self._paste_hwid, width=12)
        btn_paste.pack(side="left", padx=(0, 6))

        btn_my_pc = ttk.Button(row_hw, text="💻 Этот ПК", style="Secondary.TButton", command=self._use_local_hwid, width=12)
        btn_my_pc.pack(side="left")

        ttk.Label(
            lf_hwid,
            text="Формат: ELU-XXXX-XXXX-XXXX-XXXX (клиент копирует из окна программы в меню «Лицензия»)",
            font=("Segoe UI", 8),
            foreground=self.fg_muted
        ).pack(anchor="w", pady=(5, 0))

        # 3. Параметры лицензии (Чёткая табличная сетка без обрезки текста)
        lf_params = ttk.LabelFrame(main, text=" ⚙️ Параметры выдаваемой лицензии ", padding=12)
        lf_params.pack(fill="x", pady=(0, 10))

        grid_p = ttk.Frame(lf_params)
        grid_p.pack(fill="x")
        grid_p.columnconfigure(1, weight=1)
        grid_p.columnconfigure(3, weight=1)

        # Строка 0: Тип лицензии и Срок
        ttk.Label(grid_p, text="Тип лицензии:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.type_var = tk.StringVar(value="PRO (Бессрочная)")
        self.types_combo = ttk.Combobox(
            grid_p,
            textvariable=self.type_var,
            values=["PRO (Бессрочная)", "1 Год (Standard)", "2 Года (Extended)", "5 Лет (Enterprise)", "TRIAL (30 дней)"],
            state="readonly"
        )
        self.types_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=4)
        self.types_combo.bind("<<ComboboxSelected>>", self._on_type_changed)

        ttk.Label(grid_p, text="Срок действия:", font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
        self.validity_var = tk.StringVar(value="Бессрочная")
        self.entry_val = ttk.Entry(grid_p, textvariable=self.validity_var, state="readonly", width=16)
        self.entry_val.grid(row=0, column=3, sticky="ew", pady=4)

        # Строка 1: Клиент / Организация (ПОЛНЫЙ ТЕКСТ)
        ttk.Label(grid_p, text="Клиент / Организация:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        self.client_var = tk.StringVar()
        entry_client = ttk.Entry(grid_p, textvariable=self.client_var, font=("Segoe UI", 9))
        entry_client.grid(row=1, column=1, columnspan=3, sticky="ew", pady=6)

        # Строка 2: Примечание / Заказ (ПОЛНЫЙ ТЕКСТ)
        ttk.Label(grid_p, text="Примечание / Заказ:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.note_var = tk.StringVar()
        entry_note = ttk.Entry(grid_p, textvariable=self.note_var, font=("Segoe UI", 9))
        entry_note.grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)

        # 4. Кнопка генерации
        btn_gen = ttk.Button(
            main,
            text="⚡ СГЕНЕРИРОВАТЬ КЛЮЧ АКТИВАЦИИ",
            style="Primary.TButton",
            command=self.generate_key
        )
        btn_gen.pack(fill="x", pady=(2, 10))

        # 5. Результат генерации
        lf_res = ttk.LabelFrame(main, text=" 🎁 Сгенерированный ключ активации ", padding=12)
        lf_res.pack(fill="x", pady=(0, 10))

        self.key_var = tk.StringVar(value="KEY-XXXX-XXXX-XXXX-XXXX")
        
        # Стилизованный блок вывода ключа
        card_key = tk.Frame(lf_res, bg="#0F172A", highlightbackground="#1E3A8A", highlightthickness=1, padx=12, pady=10)
        card_key.pack(fill="x", pady=(0, 8))
        
        lbl_key = tk.Label(
            card_key,
            textvariable=self.key_var,
            font=("Consolas", 15, "bold"),
            bg="#0F172A",
            fg="#10B981"
        )
        lbl_key.pack()

        row_actions = ttk.Frame(lf_res)
        row_actions.pack(fill="x")

        self.btn_copy_key = ttk.Button(
            row_actions,
            text="📋 Скопировать только ключ",
            style="Success.TButton",
            command=self._copy_key_only
        )
        self.btn_copy_key.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_copy_msg = ttk.Button(
            row_actions,
            text="✉️ Скопировать ответ клиенту",
            style="Secondary.TButton",
            command=self._copy_client_message
        )
        self.btn_copy_msg.pack(side="right", fill="x", expand=True, padx=(4, 0))

        self.status_badge = tk.Label(
            lf_res,
            text="⏳ Введите Hardware ID и нажмите «Сгенерировать»",
            font=("Segoe UI", 9),
            bg=self.bg,
            fg=self.fg_muted
        )
        self.status_badge.pack(anchor="w", pady=(6, 0))

        # 6. Журнал выданных ключей
        lf_hist = ttk.LabelFrame(main, text=" 📜 История выданных ключей (Лог) ", padding=10)
        lf_hist.pack(fill="both", expand=True)

        hist_tools = ttk.Frame(lf_hist)
        hist_tools.pack(fill="x", pady=(0, 6))
        ttk.Label(
            hist_tools,
            text="Все выданные лицензии сохраняются автоматически:",
            font=("Segoe UI", 8),
            foreground=self.fg_muted
        ).pack(side="left")
        
        btn_open_csv = ttk.Button(
            hist_tools,
            text="📂 Открыть CSV",
            style="Secondary.TButton",
            command=self._open_history_file
        )
        btn_open_csv.pack(side="right")

        tree_frame = ttk.Frame(lf_hist)
        tree_frame.pack(fill="both", expand=True)

        cols = ("date", "client", "hwid", "type", "key")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=5, selectmode="browse")
        self.tree.heading("date", text="Дата / Время")
        self.tree.heading("client", text="Клиент")
        self.tree.heading("hwid", text="Hardware ID")
        self.tree.heading("type", text="Тип")
        self.tree.heading("key", text="Ключ активации")

        self.tree.column("date", width=125, anchor="center")
        self.tree.column("client", width=140, anchor="w")
        self.tree.column("hwid", width=180, anchor="center")
        self.tree.column("type", width=80, anchor="center")
        self.tree.column("key", width=190, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_tree_double_click)

    def _on_type_changed(self, event=None):
        val = self.type_var.get()
        if "PRO" in val:
            self.validity_var.set("Бессрочная")
        elif "1 Год" in val:
            self.validity_var.set("1 год (365 дн.)")
        elif "2 Года" in val:
            self.validity_var.set("2 года (730 дн.)")
        elif "5 Лет" in val:
            self.validity_var.set("5 лет (1825 дн.)")
        elif "TRIAL" in val:
            self.validity_var.set("30 дней")

    def _paste_hwid(self):
        try:
            val = self.root.clipboard_get().strip()
            self.hwid_var.set(val)
            self._flash_status("✓ ID вставлен из буфера обмена", self.accent)
        except Exception:
            messagebox.showwarning("Внимание", "Буфер обмена пуст", parent=self.root)

    def _use_local_hwid(self):
        self.hwid_var.set(self.current_local_hwid)
        self._flash_status(f"✓ Установлен Hardware ID текущего ПК: {self.current_local_hwid}", self.accent)

    def generate_key(self):
        raw_hwid = self.hwid_var.get().strip().upper()
        if not raw_hwid:
            messagebox.showerror("Ошибка", "Пожалуйста, введите или вставьте Hardware ID клиента.", parent=self.root)
            self.entry_hwid.focus()
            return

        if not raw_hwid.startswith("ELU-") or len(raw_hwid.split("-")) != 5:
            if not messagebox.askyesno(
                "Предупреждение",
                f"Введённый HWID «{raw_hwid}» отличается от стандартного формата (ELU-XXXX-XXXX-XXXX-XXXX).\n\n"
                "Вы уверены, что хотите продолжить генерацию?",
                parent=self.root
            ):
                return

        # Извлечение чистого типа лицензии
        combo_val = self.type_var.get()
        if "PRO" in combo_val:
            lic_type = "PRO"
        elif "1 Год" in combo_val:
            lic_type = "STANDARD"
        elif "2 Года" in combo_val:
            lic_type = "EXTENDED"
        elif "5 Лет" in combo_val:
            lic_type = "ENTERPRISE"
        else:
            lic_type = "PRO"

        customer = self.client_var.get().strip()
        note = self.note_var.get().strip()

        key = generate_activation_key(raw_hwid, lic_type=lic_type)
        self.key_var.set(key)

        # Верификация
        is_valid, verified_type, _ = verify_activation_key(key, raw_hwid)
        if is_valid:
            self.status_badge.config(
                text=f"✅ Ключ успешно сгенерирован и проверен (Тип: {lic_type})",
                fg=self.success
            )
        else:
            self.status_badge.config(text="⚠️ Ошибка валидации ключа", fg="#EF4444")

        # Запись в историю
        self._save_to_history(raw_hwid, customer, lic_type, key, note)

    def _copy_key_only(self):
        key = self.key_var.get().strip()
        if not key or key.startswith("KEY-XXXX"):
            messagebox.showwarning("Внимание", "Сначала сгенерируйте ключ.", parent=self.root)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        self._flash_status("✓ Ключ скопирован в буфер обмена!", self.success)
        self.btn_copy_key.config(text="✓ Ключ скопирован!")
        self.root.after(2000, lambda: self.btn_copy_key.config(text="📋 Скопировать только ключ"))

    def _copy_client_message(self):
        key = self.key_var.get().strip()
        hwid = self.hwid_var.get().strip().upper()
        if not key or key.startswith("KEY-XXXX"):
            messagebox.showwarning("Внимание", "Сначала сгенерируйте ключ.", parent=self.root)
            return

        lic_type = self.type_var.get()
        validity = self.validity_var.get()
        customer = self.client_var.get().strip()

        greeting = f"Здравствуйте{', ' + customer if customer else ''}!"
        msg = (
            f"{greeting}\n\n"
            f"Ваш ключ активации для программы «Элютек: SARA RGB Анализ»:\n\n"
            f"🔑 Ключ активации: {key}\n"
            f"💻 Аппаратный ID (HWID): {hwid}\n"
            f"📊 Лицензия: {lic_type} ({validity})\n\n"
            f"Инструкция по активации:\n"
            f"1. Запустите программу «Элютек» на вашем ПК.\n"
            f"2. Нажмите кнопку «🔑 Лицензия» в правом верхнем углу окна.\n"
            f"3. Вставьте полученный ключ в поле «Ключ активации» и нажмите «Активировать лицензию».\n\n"
            f"Программа активируется навсегда и готова к работе даже БЕЗ интернета."
        )

        self.root.clipboard_clear()
        self.root.clipboard_append(msg)
        self._flash_status("✓ Текст сообщения клиенту скопирован в буфер обмена!", self.accent)
        self.btn_copy_msg.config(text="✓ Сообщение скопировано!")
        self.root.after(2000, lambda: self.btn_copy_msg.config(text="✉️ Скопировать ответ клиенту"))

    def _flash_status(self, text, color):
        self.status_badge.config(text=text, fg=color)

    def _save_to_history(self, hwid, client, lic_type, key, note):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = [now_str, client or "—", hwid, lic_type, key, note]

        file_exists = os.path.isfile(HISTORY_CSV_FILE)
        try:
            with open(HISTORY_CSV_FILE, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                if not file_exists:
                    writer.writerow(["Дата/Время", "Клиент", "Hardware ID", "Тип лицензии", "Ключ активации", "Примечание"])
                writer.writerow(record)
        except Exception as e:
            print(f"Ошибка записи в CSV: {e}")

        self.tree.insert("", 0, values=(now_str, client or "—", hwid, lic_type, key))

    def _load_history(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not os.path.isfile(HISTORY_CSV_FILE):
            return

        try:
            with open(HISTORY_CSV_FILE, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter=";")
                rows = list(reader)
                if rows:
                    for row in rows[1:]:
                        if len(row) >= 5:
                            self.tree.insert("", 0, values=(row[0], row[1], row[2], row[3], row[4]))
        except Exception as e:
            print(f"Ошибка чтения истории: {e}")

    def _open_history_file(self):
        if not os.path.isfile(HISTORY_CSV_FILE):
            try:
                with open(HISTORY_CSV_FILE, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f, delimiter=";")
                    writer.writerow(["Дата/Время", "Клиент", "Hardware ID", "Тип лицензии", "Ключ активации", "Примечание"])
            except Exception:
                pass

        try:
            if sys.platform == "win32":
                os.startfile(HISTORY_CSV_FILE)
            elif sys.platform == "darwin":
                subprocess.run(["open", HISTORY_CSV_FILE])
            else:
                subprocess.run(["xdg-open", HISTORY_CSV_FILE])
        except Exception as e:
            messagebox.showinfo("История", f"Файл журнала находится по пути:\n{HISTORY_CSV_FILE}", parent=self.root)

    def _on_tree_double_click(self, event):
        item = self.tree.selection()
        if not item:
            return
        vals = self.tree.item(item[0], "values")
        if vals and len(vals) >= 5:
            client, hwid, ltype, key = vals[1], vals[2], vals[3], vals[4]
            self.hwid_var.set(hwid)
            self.client_var.set(client if client != "—" else "")
            self.key_var.set(key)
            self._flash_status(f"✓ Выбрана лицензия для {client} ({hwid})", self.accent)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = KeygenApp()
    app.run()
