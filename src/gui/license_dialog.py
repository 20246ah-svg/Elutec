"""
Диалоговое окно управления лицензией и активацией ПО «Элютек».
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox
from ..utils.license_manager import (
    LicenseManager, get_hardware_id,
    LICENSE_STATUS_LICENSED, LICENSE_STATUS_TRIAL_ACTIVE, LICENSE_STATUS_TRIAL_EXPIRED
)
from .theme import get_palette


class LicenseDialog:
    """Диалог активации и информации о лицензии."""
    
    def __init__(self, parent=None, config=None, lic_mgr=None, on_activated=None, block_if_expired=False):
        self.parent = parent
        self.config = config or {}
        self.on_activated = on_activated
        self.block_if_expired = block_if_expired
        self.lic_mgr = lic_mgr if lic_mgr is not None else LicenseManager()
        self.status = self.lic_mgr.get_status()
        self.is_activated = (self.status.get("status") == LICENSE_STATUS_LICENSED)
        
        self.win = tk.Toplevel(parent) if parent else tk.Tk()
        self.win.title("Элютек · Лицензия")
        self.win.geometry("660x580")
        self.win.minsize(600, 520)
        self.win.resizable(True, True)
        
        if parent:
            self.win.transient(parent)
            self.win.grab_set()
            
        self._build_ui()
        
    def _build_ui(self):
        style = ttk.Style(self.win)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        light = bool(self.config.get('light_theme', False))
        colors = get_palette(light)
        bg = colors['background']
        panel = colors['surface']
        panel_alt = colors['surface_alt']
        fg = colors['text']
        border = colors['border']
        accent = colors['accent']
        muted = colors['muted']

        self.win.configure(bg=bg)
        style.configure('.', background=bg, foreground=fg, font=('Segoe UI', 10))
        style.configure('TFrame', background=bg)
        style.configure('App.TFrame', background=bg)
        style.configure('Header.TFrame', background=panel, relief='solid', borderwidth=1,
                        bordercolor=border, lightcolor=border, darkcolor=border)
        style.configure('BrandMark.TLabel', background=accent, foreground=colors['accent_on'],
                        font=('Segoe UI', 14, 'bold'), padding=(9, 5))
        style.configure('HeaderTitle.TLabel', background=panel, foreground=fg,
                        font=('Segoe UI', 14, 'bold'))
        style.configure('HeaderSub.TLabel', background=panel, foreground=muted, font=('Segoe UI', 9))
        style.configure('TLabel', background=panel, foreground=fg)
        style.configure('TLabelframe', background=panel, foreground=fg, bordercolor=border,
                        lightcolor=border, darkcolor=border, relief='solid', borderwidth=1)
        style.configure('TLabelframe.Label', background=panel, foreground=fg,
                        font=('Segoe UI', 9, 'bold'), padding=(4, 0))
        style.configure('TEntry', fieldbackground=panel_alt, foreground=fg, padding=(8, 7),
                        bordercolor=border, lightcolor=border, darkcolor=border, insertcolor=fg)
        style.configure('TButton', background=panel, foreground=fg, padding=(10, 7),
                        borderwidth=1, bordercolor=border, font=('Segoe UI', 9, 'bold'))
        style.map('TButton', background=[('active', colors['surface_hover']), ('pressed', colors['surface_hover'])],
                  bordercolor=[('active', accent)])
        style.configure('Primary.TButton', background=accent, foreground=colors['accent_on'],
                        padding=(13, 9), borderwidth=0, font=('Segoe UI', 9, 'bold'))
        style.map('Primary.TButton', background=[('active', colors['accent_hover']), ('pressed', colors['accent_hover'])])
        style.configure('Quiet.TButton', background=panel, foreground=fg, padding=(10, 7),
                        borderwidth=1, bordercolor=border, font=('Segoe UI', 9, 'bold'))
        style.map('Quiet.TButton', background=[('active', colors['surface_hover']), ('pressed', colors['surface_hover'])],
                  bordercolor=[('active', accent)])
        style.configure('Danger.TButton', background=colors['danger_soft'], foreground=colors['danger'],
                        padding=(10, 7), borderwidth=0, font=('Segoe UI', 9, 'bold'))
        style.configure('TNotebook', background=bg, borderwidth=0)

        outer = ttk.Frame(self.win, padding=18, style='App.TFrame')
        outer.pack(fill='both', expand=True)

        # Bottom navigation remains visible for all license states.
        btn_bar = ttk.Frame(outer, style='App.TFrame')
        btn_bar.pack(side='bottom', fill='x', pady=(12, 0))
        if self.status.get('is_allowed', False):
            ttk.Button(btn_bar, text='Продолжить работу', command=self.win.destroy,
                       style='Primary.TButton').pack(side='right')
        elif self.block_if_expired:
            ttk.Button(btn_bar, text='Выход из программы', command=lambda: sys.exit(0),
                       style='Danger.TButton').pack(side='right')
        else:
            ttk.Button(btn_bar, text='Закрыть', command=self.win.destroy,
                       style='Quiet.TButton').pack(side='right')

        # Product header
        hdr = ttk.Frame(outer, style='Header.TFrame', padding=(15, 12))
        hdr.pack(fill='x', pady=(0, 12))
        ttk.Label(hdr, text='E', style='BrandMark.TLabel', anchor='center').pack(side='left')
        hdr_copy = ttk.Frame(hdr, style='Header.TFrame')
        hdr_copy.pack(side='left', padx=(10, 0))
        ttk.Label(hdr_copy, text='Лицензия и активация', style='HeaderTitle.TLabel').pack(anchor='w')
        ttk.Label(hdr_copy, text='Элютек · SARA RGB анализ', style='HeaderSub.TLabel').pack(anchor='w', pady=(2, 0))

        # Hardware ID
        lf_hwid = ttk.LabelFrame(outer, text='Аппаратный идентификатор', padding=12)
        lf_hwid.pack(fill='x', pady=(0, 10))
        hw_row = ttk.Frame(lf_hwid)
        hw_row.pack(fill='x')
        self.hwid_var = tk.StringVar(value=self.status.get('hwid', get_hardware_id()))
        hw_entry = ttk.Entry(hw_row, textvariable=self.hwid_var, font=('Consolas', 10, 'bold'), state='readonly')
        hw_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))

        def _copy_hwid():
            self.win.clipboard_clear()
            self.win.clipboard_append(self.hwid_var.get())
            self.copy_btn.config(text='Скопировано')
            self.win.after(2000, lambda: self.copy_btn.config(text='Скопировать'))

        self.copy_btn = ttk.Button(hw_row, text='Скопировать', command=_copy_hwid,
                                   width=14, style='Quiet.TButton')
        self.copy_btn.pack(side='right')
        ttk.Label(lf_hwid, text='Передайте этот идентификатор разработчику для выпуска ключа активации.',
                  font=('Segoe UI', 8), foreground=muted).pack(anchor='w', pady=(6, 0))

        # License status
        lf_stat = ttk.LabelFrame(outer, text='Статус лицензии', padding=12)
        lf_stat.pack(fill='x', pady=(0, 10))
        stat_code = self.status.get('status')
        if stat_code == LICENSE_STATUS_LICENSED:
            stat_text = f"Лицензия активна · {self.status.get('lic_type', 'PRO')}"
            stat_color = colors['success']
            desc_text = 'Программа полностью разблокирована и готова к работе.'
        elif stat_code == LICENSE_STATUS_TRIAL_ACTIVE:
            stat_text = f"Демо-режим · {self.status.get('days_left')} дн. / {self.status.get('runs_left')} запусков"
            stat_color = colors['warning']
            desc_text = 'Доступен полный функционал в рамках ознакомительного периода.'
        else:
            stat_text = 'Пробный период завершён'
            stat_color = colors['danger']
            desc_text = 'Для продолжения работы введите постоянный ключ активации.'

        lbl_status = tk.Label(lf_stat, text=stat_text, font=('Segoe UI', 11, 'bold'),
                              fg=stat_color, bg=panel, padx=6, pady=5)
        lbl_status.pack(fill='x')
        ttk.Label(lf_stat, text=desc_text, font=('Segoe UI', 9), foreground=muted).pack(anchor='w', pady=(3, 0))

        # Activation key entry
        lf_key = ttk.LabelFrame(outer, text='Ключ активации', padding=12)
        lf_key.pack(fill='x')
        row_k = ttk.Frame(lf_key)
        row_k.pack(fill='x', pady=2)
        ttk.Label(row_k, text='Ключ:', font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 7))
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(row_k, textvariable=self.key_var, font=('Consolas', 10, 'bold'))
        self.key_entry.pack(side='left', fill='x', expand=True, padx=(0, 7))

        def _paste_key():
            try:
                clip = self.win.clipboard_get().strip()
                if clip:
                    self.key_var.set(clip)
            except Exception:
                pass

        ttk.Button(row_k, text='Вставить', command=_paste_key, width=11,
                   style='Quiet.TButton').pack(side='right')

        row_name = ttk.Frame(lf_key)
        row_name.pack(fill='x', pady=(8, 2))
        ttk.Label(row_name, text='Клиент или организация (необязательно):',
                  font=('Segoe UI', 8), foreground=muted).pack(side='left', padx=(0, 7))
        self.client_var = tk.StringVar()
        ttk.Entry(row_name, textvariable=self.client_var, font=('Segoe UI', 9)).pack(side='left', fill='x', expand=True)

        def _do_activate():
            key = self.key_var.get().strip()
            client = self.client_var.get().strip()
            if not key:
                messagebox.showerror('Ошибка', 'Пожалуйста, вставьте ключ активации в поле «Ключ».', parent=self.win)
                return
            success, msg = self.lic_mgr.activate(key, customer_name=client)
            if success:
                self.is_activated = True
                self.status = self.lic_mgr.get_status()
                if self.on_activated:
                    try:
                        self.on_activated()
                    except Exception as e:
                        print(f'Error in on_activated callback: {e}')
                messagebox.showinfo('Успех', msg, parent=self.win)
                self.win.destroy()
            else:
                messagebox.showerror('Ошибка активации', msg, parent=self.win)

        btn_act_row = ttk.Frame(lf_key)
        btn_act_row.pack(fill='x', pady=(9, 0))
        ttk.Button(btn_act_row, text='Активировать лицензию', command=_do_activate,
                   style='Primary.TButton').pack(side='right')
