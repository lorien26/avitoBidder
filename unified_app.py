import flet as ft
import threading
import time
import os
import json
import subprocess
import sys
import re
from collections import deque
from load_config import load_avito_config
from config_gui import build_config_editor
from data_viewer import build_data_viewer


class AvitoManagerApp:
    def __init__(self):
        from init_ads import init_db_from_config
        init_db_from_config()
        """Инициализация основных состояний и UI элементов."""
        # Основные состояния приложения
        self.page = None
        self.parser_process = None  # Процесс парсера
        self.is_parser_running = False

        # Кеш конфигурации
        self.config_cached = {"profiles": []}

        # UI элементы
        self.config_info = ft.Text("", color=ft.colors.WHITE)
        self.parser_status = ft.Text("Остановлен", color=ft.colors.RED, size=16)
        self.start_parser_btn = None
        self.stop_parser_btn = None
        self.parser_pid_text = ft.Text("PID: —", size=12, color=ft.colors.WHITE70)

        # Элементы анализа лога
        self.log_summary = ft.Text("(лог ещё не проанализирован)", size=12, selectable=True)
        self._log_analyze_counter = 0

        self._load_config_cached()

    # ---------------- UI -----------------
    def main(self, page: ft.Page):
        self.page = page
        page.title = "Avito Parser Manager"
        page.window.width = 1200
        page.window.height = 800
        page.padding = 20
        page.bgcolor = ft.colors.GREY_900
        page.theme_mode = ft.ThemeMode.DARK

        self.start_parser_btn = ft.ElevatedButton("Запустить парсер", on_click=self.start_parser, bgcolor=ft.colors.GREEN_600, color=ft.colors.WHITE)
        self.stop_parser_btn = ft.ElevatedButton("Остановить парсер", on_click=self.stop_parser, bgcolor=ft.colors.RED_600, color=ft.colors.WHITE, disabled=True)

        self.update_config_info()
        config_view = build_config_editor(page)
        stats_view = build_data_viewer(page)

        tabs = ft.Tabs(selected_index=0, animation_duration=300, tabs=[
            ft.Tab(text="Управление", content=self.create_main_tab()),
            ft.Tab(text="Конфигурация", content=ft.Container(content=config_view, padding=10)),
            ft.Tab(text="Статистика", content=ft.Container(content=stats_view, padding=10)),
        ])
        page.add(tabs)
        self.start_status_updater()

    def create_main_tab(self):
        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Column([
                        ft.Text("Статус парсера:", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.Text("Парсер:", size=14),
                            self.parser_status,
                            self.parser_pid_text
                        ]),
                        ft.Row([
                            self.start_parser_btn,
                            self.stop_parser_btn
                        ], spacing=10)
                    ]),
                    padding=15,
                    bgcolor=ft.colors.GREY_800,
                    border_radius=10,
                    border=ft.border.all(1, ft.colors.GREY_600)
                ),
                ft.Divider(height=20),
                ft.Container(
                    content=ft.Column([
                        ft.Text("Конфигурация:", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(value=self.config_info.value, selectable=True, size=12)
                    ]),
                    padding=15,
                    bgcolor=ft.colors.GREY_800,
                    border_radius=10,
                    border=ft.border.all(1, ft.colors.GREY_600)
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text("🧾 Анализ лога (logs/app.log)", size=18, weight=ft.FontWeight.BOLD),
                            ft.IconButton(icon=ft.icons.REFRESH, tooltip="Обновить", on_click=lambda e: self._update_log_summary(force=True))
                        ]),
                        self.log_summary
                    ], spacing=10),
                    padding=15,
                    bgcolor=ft.colors.GREY_800,
                    border_radius=10,
                    border=ft.border.all(1, ft.colors.GREY_600)
                ),
            ], spacing=15),
            padding=20
        )

    # --------------- Логика ----------------
    def start_parser(self, e):
        """Запускает полный скрипт parser_cls.py как отдельный процесс."""
        if self.is_parser_running:
            return
        try:
            python_exec = sys.executable or "python"
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            env["LOGURU_ENCODING"] = "utf-8"
            cmd = [python_exec, "-X", "utf8", "parser_cls.py"]
            print("Старт команды:", " ".join(cmd))
            self.parser_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            self.is_parser_running = True
            if self.parser_process and self.parser_process.pid:
                self.parser_pid_text.value = f"PID: {self.parser_process.pid}"
            else:
                self.parser_pid_text.value = "PID: ?"
            self.start_parser_btn.disabled = True
            self.stop_parser_btn.disabled = False
            print(f"Процесс парсера запущен (parser_cls.py) PID={self.parser_process.pid}")
            threading.Thread(target=self._stream_parser_output, name="parser-stdout", daemon=True).start()
            threading.Thread(target=self._watch_process_end, name="parser-monitor", daemon=True).start()
        except Exception as err:
            print("Не удалось запустить parser_cls.py:", err)
            self.is_parser_running = False
            self.parser_process = None
        e.page.update()

    def stop_parser(self, e):
        if not self.is_parser_running or not self.parser_process:
            return
        try:
            if self.parser_process.poll() is None:
                print("Останавливаем процесс парсера...")
                self.parser_process.terminate()
                try:
                    self.parser_process.wait(timeout=5)
                except Exception:
                    print("Принудительное завершение процесса парсера")
                    self.parser_process.kill()
        finally:
            self.is_parser_running = False
            self.parser_process = None
            self.start_parser_btn.disabled = False
            self.stop_parser_btn.disabled = True
            self.parser_pid_text.value = "PID: —"
            print("Парсер остановлен")
            e.page.update()

    def _stream_parser_output(self):
        if not self.parser_process or not self.parser_process.stdout:
            return
        try:
            for line in self.parser_process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                print(f"[parser] {line}")
        except Exception as err:
            print("Ошибка чтения вывода парсера:", err)

    def _watch_process_end(self):
        if not self.parser_process:
            return
        code = self.parser_process.wait()
        print(f"[parser-monitor] Процесс завершился с кодом {code}")
        self.is_parser_running = False
        self.parser_process = None
        self.parser_pid_text.value = "PID: —"
        if self.start_parser_btn and self.stop_parser_btn:
            self.start_parser_btn.disabled = False
            self.stop_parser_btn.disabled = True
        if self.page:
            self.page.update()

    def _load_config_cached(self):
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    self.config_cached = json.load(f)
        except Exception:
            self.config_cached = {"profiles": []}

    def update_config_info(self):
        try:
            config = load_avito_config()
            profiles_count = len(config.profiles)
            mobile_proxies_count = len(getattr(config, 'mobile_proxies', []))
            info_lines = [
                f"📁 Профилей в конфигурации: {profiles_count}",
                f"📱 Мобильных прокси: {mobile_proxies_count}",
                f"⏱️ Общая пауза: {getattr(config, 'pause_general', 'не указана')} сек",
                f"🔄 Ротация прокси: {'включена' if getattr(config, 'proxy_rotation_enabled', False) else 'отключена'}",
                f"📊 Макс. запросов на прокси: {getattr(config, 'proxy_max_requests_per_rotation', 'не указано')}",
            ]
            for i, profile in enumerate(config.profiles, 1):
                name = profile.get('name', f"Профиль {i}")
                urls_count = len(profile.get('urls', []))
                info_lines.append(f"  {i}. {name}: {urls_count} объявлений")
            self.config_info.value = "\n".join(info_lines)
        except Exception as e:
            self.config_info.value = f"❌ Ошибка чтения конфигурации: {e}"

    def start_status_updater(self):
        def loop():
            while True:
                try:
                    if self.parser_process and self.parser_process.poll() is not None:
                        self.is_parser_running = False
                        self.parser_process = None
                        self.start_parser_btn.disabled = False
                        self.stop_parser_btn.disabled = True
                    self.parser_status.value = "Работает ✅" if self.is_parser_running else "Остановлен ⏹️"
                    self.parser_status.color = ft.colors.GREEN if self.is_parser_running else ft.colors.RED
                    if self.start_parser_btn:
                        self.start_parser_btn.disabled = self.is_parser_running
                        self.stop_parser_btn.disabled = not self.is_parser_running
                    if not self.is_parser_running:
                        self.parser_pid_text.value = "PID: —"
                    self._log_analyze_counter += 1
                    if self._log_analyze_counter >= 5:
                        self._update_log_summary()
                        self._log_analyze_counter = 0
                    if self.page:
                        self.page.update()
                    time.sleep(1)
                except Exception as err:
                    print("status updater error", err)
                    time.sleep(5)
        threading.Thread(target=loop, daemon=True).start()

    def _read_last_log_lines(self, path: str, max_lines: int = 500) -> list[str]:
        if not os.path.exists(path):
            return []
        dq = deque(maxlen=max_lines)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    dq.append(line.rstrip('\n'))
        except Exception as e:
            return [f"Ошибка чтения лога: {e}"]
        return list(dq)

    def _analyze_log_lines(self, lines: list[str]) -> str:
        if not lines:
            return "Лог пуст или ещё не создан"
        total = len(lines)
        level_counts = {k: 0 for k in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]}
        last_error = None
        last_warning = None
        error_patterns = ["Ошибка", "ERROR", "Traceback", "❌", "💥"]
        warning_patterns = ["WARNING", "⚠️", "warning"]
        cycle_matches = 0
        status200 = 0
        other_status = 0
        proxy_rotations = 0
        for ln in lines:
            m = re.search(r'\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|', ln)
            if m:
                level_counts[m.group(1)] += 1
            if any(pat in ln for pat in error_patterns):
                last_error = ln
            elif any(pat in ln for pat in warning_patterns):
                last_warning = ln
            if 'Попытка' in ln and ': 200' in ln:
                status200 += 1
            elif 'Попытка' in ln and ': ' in ln and ': 200' not in ln:
                other_status += 1
            if 'Проактивная ротация прокси' in ln or 'Переключились с прокси' in ln:
                proxy_rotations += 1
            if 'Парсинг завершен' in ln:
                cycle_matches += 1
        parts = [
            f"Всего строк: {total}",
            "Уровни: " + ", ".join(f"{k}:{v}" for k, v in level_counts.items() if v),
            f"HTTP 200 попыток: {status200}",
            f"Другие статусы: {other_status}",
            f"Ротаций прокси: {proxy_rotations}",
            f"Завершённых циклов: {cycle_matches}",
        ]
        if last_warning:
            parts.append("Последнее предупреждение: " + last_warning[-140:])
        if last_error:
            parts.append("Последняя ошибка: " + last_error[-140:])
        return "\n".join(parts)

    def _update_log_summary(self, force: bool = False):
        try:
            lines = self._read_last_log_lines("logs/app.log")
            summary = self._analyze_log_lines(lines)
            self.log_summary.value = summary
        except Exception as e:
            self.log_summary.value = f"Не удалось проанализировать лог: {e}"
        if self.page:
            self.page.update()


def main():
    app = AvitoManagerApp()
    ft.app(target=app.main, view=ft.AppView.FLET_APP)


if __name__ == "__main__":
    main()
