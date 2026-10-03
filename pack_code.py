# -*- coding: utf-8 -*-
"""
Сборщик всех файлов проекта в один файл FULL_PROJECT_CODE.txt
Запуск: ДВОЙНОЙ ЩЕЛЧОК мыши по файлу pack.pyw
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox
import subprocess

# Расширения файлов кода и настроек, которые пойдут в сборку
ALLOWED_EXTENSIONS = {
    '.py', '.pyw', '.ui', '.json', '.yaml', '.yml', '.ini', 
    '.toml', '.cfg', '.conf', '.txt', '.qss', '.css', '.html', 
    '.js', '.sh', '.bat', '.csv', '.md', '.iss'
}

# Папки, которые гарантированно пропускаются (тяжелые библиотеки, кэш, видео)
IGNORE_DIRS = {
    'venv', '.venv', 'env', '.env', '__pycache__', '.git', 
    '.idea', '.vscode', 'build', 'dist', 'node_modules', 
    '.mypy_cache', '.pytest_cache', 'site-packages', 'logs', 'records'
}

def pack_project():
    try:
        root = tk.Tk()
        root.withdraw()
        has_tk = True
    except Exception:
        has_tk = False

    # Папка проекта — там, где лежит этот скрипт
    project_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    output_filename = "FULL_PROJECT_CODE.txt"
    output_path = os.path.join(project_dir, output_filename)

    packed_count = 0
    total_lines = 0

    try:
        with open(output_path, 'w', encoding='utf-8') as out_file:
            out_file.write("# " + "=" * 70 + "\n")
            out_file.write(f"# ПОЛНЫЙ ИСХОДНЫЙ КОД ПРОЕКТА\n")
            out_file.write(f"# Папка: {project_dir}\n")
            out_file.write("# " + "=" * 70 + "\n\n")

            for root_dir, dirs, files in os.walk(project_dir):
                # Исключаем лишние папки
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]

                for file in sorted(files):
                    ext = os.path.splitext(file)[1].lower()
                    full_path = os.path.join(root_dir, file)

                    # Не читаем сам выходной файл и скрипт сборщика
                    if full_path == output_path or file in ('pack.py', 'pack.pyw', 'pack_code.py', output_filename):
                        continue

                    if ext in ALLOWED_EXTENSIONS:
                        rel_path = os.path.relpath(full_path, project_dir)
                        
                        out_file.write(f"\n\n{'=' * 75}\n")
                        out_file.write(f"### FILE: {rel_path}\n")
                        out_file.write(f"{'=' * 75}\n\n")

                        try:
                            with open(full_path, 'r', encoding='utf-8', errors='replace') as in_file:
                                content = in_file.read()
                                out_file.write(content)
                                total_lines += content.count('\n') + 1
                                packed_count += 1
                        except Exception as read_err:
                            out_file.write(f"# [Ошибка чтения файла: {read_err}]\n")

        size_kb = os.path.getsize(output_path) / 1024
        print(f"✅ Упаковано файлов: {packed_count}, строк: {total_lines}, размер: {size_kb:.1f} КБ -> {output_path}")

        # Подсвечиваем готовый файл в проводнике Windows
        try:
            if sys.platform == 'win32':
                subprocess.Popen(f'explorer /select,"{output_path}"')
        except Exception:
            pass

        if has_tk:
            messagebox.showinfo(
                "Готово!", 
                f"Весь проект успешно упакован в один файл!\n\n"
                f"• Файлов объединено: {packed_count}\n"
                f"• Строк кода: {total_lines}\n"
                f"• Размер файла: {size_kb:.1f} КБ\n\n"
                f"Создан файл:\n{output_filename}\n\n"
                f"Перетащите его мышкой в это окно чата!"
            )

    except Exception as e:
        if has_tk:
            messagebox.showerror("Ошибка", f"Не удалось упаковать проект:\n{e}")
        else:
            print(f"❌ Ошибка: {e}")

if __name__ == '__main__':
    pack_project()

