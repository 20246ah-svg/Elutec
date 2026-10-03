"""
Диалоговое окно управления лицензией и активацией ПО «Элютек».
"""

import sys
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    _TK_IMPORT_ERROR = None
except ImportError as exc:
    tk = ttk = messagebox = None
    _TK_IMPORT_ERROR = exc
from ..utils.license_manager import (
    LicenseManager, get_hardware_id,
    LICENSE_STATUS_LICENSED, LICENSE_STATUS_TRIAL_ACTIVE, LICENSE_STATUS_TRIAL_EXPIRED
)


class LicenseDialog:
    """Диалог активации и информации о лицензии."""
    
    def __init__(self, parent=None, config=None, lic_mgr=None, on_activated=None, block_if_expired=False):
        if tk is None:
            raise RuntimeError("Tkinter недоступен. Диалог лицензии невозможно открыть.") from _TK_IMPORT_ERROR
        self.parent = parent
        self.config = config or {}
        self.on_activated = on_activated
        self.block_if_expired = block_if_expired
        self.lic_mgr = lic_mgr if lic_mgr is not None else LicenseManager()
        self.status = self.lic_mgr.get_status()
        self.is_activated = (self.status.get("status") == LICENSE_STATUS_LICENSED)
        
        self.win = tk.Toplevel(parent) if parent else tk.Tk()
        self.win.title("🔑 Активация и лицензия — Элютек")
        self.win.geometry("620x540")
        self.win.minsize(580, 500)
        self.win.resizable(True, True)
        
        if parent:
            self.win.transient(parent)
            self.win.grab_set()
            
        self._build_ui()
        
    def _build_ui(self):
        light = bool(self.config.get("light_theme", False))
        bg = "#F2F3F8" if light else "#0E121B"
        panel = "#FFFFFF" if light else "#111827"
        fg = "#0E121B" if light else "#FFFFFF"
        border = "#C6CDE1" if light else "#2A3451"
        accent = "#2A3451" if light else "#A1ADCE"
        brand = "#1E40AF" if light else "#3B82F6"
        
        self.win.configure(bg=bg)
        
        outer = ttk.Frame(self.win, padding=16)
        outer.pack(fill="both", expand=True)

        # 5. Bottom Navigation Bar (pack bottom first to ensure it is always visible!)
        btn_bar = ttk.Frame(outer)
        btn_bar.pack(side="bottom", fill="x", pady=(12, 0))
        
        if self.status.get("is_allowed", False):
            ttk.Button(btn_bar, text="▶ Продолжить работу", command=self.win.destroy).pack(side="right")
        elif self.block_if_expired:
            ttk.Button(btn_bar, text="Выход из программы", command=lambda: sys.exit(0)).pack(side="right")
        else:
            ttk.Button(btn_bar, text="Закрыть", command=self.win.destroy).pack(side="right")
        
        # 1. Header
        hdr = ttk.Frame(outer)
        hdr.pack(fill="x", pady=(0, 10))
        ttk.Label(hdr, text="Элютек: SARA RGB Анализ", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(hdr, text="Управление лицензией и активация оборудования", font=("Segoe UI", 9)).pack(anchor="w")
        
        # 2. Hardware ID Frame
        lf_hwid = ttk.LabelFrame(outer, text=" 💻 Аппаратный идентификатор (Hardware ID) ", padding=10)
        lf_hwid.pack(fill="x", pady=(0, 10))
        
        hw_row = ttk.Frame(lf_hwid)
        hw_row.pack(fill="x")
        
        self.hwid_var = tk.StringVar(value=self.status.get("hwid", get_hardware_id()))
        hw_entry = ttk.Entry(hw_row, textvariable=self.hwid_var, font=("Consolas", 11, "bold"), state="readonly")
        hw_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        def _copy_hwid():
            self.win.clipboard_clear()
            self.win.clipboard_append(self.hwid_var.get())
            self.copy_btn.config(text="✓ Скопировано!")
            self.win.after(2000, lambda: self.copy_btn.config(text="📋 Скопировать"))
            
        self.copy_btn = ttk.Button(hw_row, text="📋 Скопировать", command=_copy_hwid, width=15)
        self.copy_btn.pack(side="right")
        
        ttk.Label(lf_hwid, text="Отправьте этот идентификатор разработчику для получения ключа активации.", font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

        # 3. License Status Frame
        lf_stat = ttk.LabelFrame(outer, text=" 📊 Текущий статус лицензии ", padding=10)
        lf_stat.pack(fill="x", pady=(0, 10))
        
        stat_code = self.status.get("status")
        if stat_code == LICENSE_STATUS_LICENSED:
            stat_text = f"✅ Лицензия активна ({self.status.get('lic_type', 'PRO')})"
            stat_color = "#16A34A"
            desc_text = "Программа полностью разблокирована и готова к работе."
        elif stat_code == LICENSE_STATUS_TRIAL_ACTIVE:
            stat_text = f"⏳ Демо-режим (Осталось: {self.status.get('days_left')} дн. / {self.status.get('runs_left')} запусков)"
            stat_color = "#CA8A04" if light else "#FACC15"
            desc_text = "Вам доступен полный функционал в рамках ознакомительного периода."
        else:
            stat_text = "❌ Пробный период истёк"
            stat_color = "#DC2626"
            desc_text = "Для продолжения работы введите постоянный ключ активации."
            
        lbl_status = tk.Label(lf_stat, text=stat_text, font=("Segoe UI", 11, "bold"), fg=stat_color, bg=panel, padx=6, pady=4)
        lbl_status.pack(fill="x")
        ttk.Label(lf_stat, text=desc_text, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))

        # 4. Activation Key Input Frame
        lf_key = ttk.LabelFrame(outer, text=" 🔑 Ввод ключа активации ", padding=10)
        lf_key.pack(fill="x", pady=(0, 10))
        
        row_k = ttk.Frame(lf_key)
        row_k.pack(fill="x", pady=2)
        ttk.Label(row_k, text="Ключ активации:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(row_k, textvariable=self.key_var, font=("Consolas", 11, "bold"))
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def _paste_key():
            try:
                clip = self.win.clipboard_get().strip()
                if clip:
                    self.key_var.set(clip)
            except Exception:
                pass

        btn_paste_k = ttk.Button(row_k, text="📋 Вставить", command=_paste_key, width=12)
        btn_paste_k.pack(side="right")

        # Optional client name field
        row_name = ttk.Frame(lf_key)
        row_name.pack(fill="x", pady=(6, 2))
        ttk.Label(row_name, text="Клиент / Организация (необязательно):", font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        self.client_var = tk.StringVar()
        ttk.Entry(row_name, textvariable=self.client_var, font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)

        def _do_activate():
            key = self.key_var.get().strip()
            client = self.client_var.get().strip()
            if not key:
                messagebox.showerror("Ошибка", "Пожалуйста, вставьте ключ активации в поле «Ключ активации».", parent=self.win)
                return
            success, msg = self.lic_mgr.activate(key, customer_name=client)
            if success:
                self.is_activated = True
                self.status = self.lic_mgr.get_status()
                if self.on_activated:
                    try:
                        self.on_activated()
                    except Exception as e:
                        print(f"Error in on_activated callback: {e}")
                messagebox.showinfo("✅ Успех", msg, parent=self.win)
                self.win.destroy()
            else:
                messagebox.showerror("❌ Ошибка активации", msg, parent=self.win)
                
        btn_act_row = ttk.Frame(lf_key)
        btn_act_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_act_row, text="🔑 Активировать лицензию", command=_do_activate).pack(side="right")
