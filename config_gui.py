import flet as ft
import json
import os
import subprocess  # оставляем импорт если где-то еще понадобится (можно удалить при желании)

def load_config():
    if not os.path.exists("config.json"):
        return {"profiles": []}
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    # Загружаем исходный конфиг, чтобы сохранить дополнительные поля
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            original_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        original_config = {}
    
    # Обновляем только profiles, остальные поля оставляем как есть
    updated_config = original_config.copy()
    updated_config["profiles"] = config["profiles"]
    
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(updated_config, f, ensure_ascii=False, indent=2)

def run_parser():
    # Функция сохранена для совместимости, но больше не используется (запуск осуществляется из unified_app)
    pass

def build_config_editor(page: ft.Page) -> ft.Control:
    """Строит и возвращает корневой контрол редактора конфигурации без запуска ft.app.

    Можно встраивать в другие приложения (например, общий unified интерфейс).
    Оригинальная логика и внешний вид сохранены. Возвращает контейнер со всем UI.
    """
    page.scroll = ft.ScrollMode.AUTO
    config = load_config()
    profiles = config.get("profiles", [])
    profile_controls = []

    def safe_int(val):
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0
    # Буфер для профилей до сохранения
    config_buffer = {"profiles": []}
    def is_valid_profile(p):
        # Проверка профиля: все поля заполнены, типы корректны
        if not p["client_id"].value.strip() or not p["client_secret"].value.strip() or not p["name"].value.strip():
            return False
        for url_row in p["urls"]:
            if not url_row["ad"].value.strip() or not url_row["category"].value.strip():
                return False
            # Проверяем, что числовые поля действительно числа и не пустые
            for key in ["max_price", "target_place_start", "target_place_end"]:
                val = url_row[key].value.strip()
                if val == "" or not val.isdigit():
                    return False
            # Комментарий может быть пустым, поэтому не проверяем его
        return True

    # Кнопка save_btn должна быть объявлена заранее, чтобы использоваться в update_config_buffer
    save_btn = ft.ElevatedButton("Сохранить", on_click=lambda e: save_config_from_buffer(), disabled=True)

    def update_config_buffer():
        new_profiles = []
        all_valid = True
        for p in profile_controls:
            urls = []
            for url_row in p["urls"]:
                # Умножаем max_price на 100 при сохранении
                max_price_val = safe_int(url_row["max_price"].value) * 100
                
                urls.append({
                    "ad": url_row["ad"].value,
                    "category": url_row["category"].value,
                    "max_price": max_price_val,
                    "target_place_start": safe_int(url_row["target_place_start"].value),
                    "target_place_end": safe_int(url_row["target_place_end"].value),
                    "comment": url_row["comment"].value,
                    "daily_budget": safe_int(url_row["daily_budget"].value),
                    "active": url_row["active"].value
                })
            new_profiles.append({
                "client_id": p["client_id"].value,
                "client_secret": p["client_secret"].value,
                "name": p["name"].value,
                "urls": urls
            })
            if not is_valid_profile(p):
                all_valid = False
        config_buffer["profiles"] = new_profiles
        save_btn.disabled = not all_valid
        page.update()

    def save_config_from_buffer(e=None):
        config["profiles"] = config_buffer["profiles"]
        save_config(config)
        snackbar = ft.SnackBar(ft.Text("Конфиг успешно сохранён!"), open=True)
        page.overlay.append(snackbar)
        page.update()

    def add_url_row(urls_column, url_data=None, p=None):
        url_data = url_data or {}
        ad = ft.TextField(
            label="ad",
            value=url_data.get("ad", ""),
            width=200,
            on_change=lambda e: update_config_buffer()
        )
        category = ft.TextField(
            label="category",
            value=url_data.get("category", ""),
            width=200,
            on_change=lambda e: update_config_buffer()
        )
        max_price = ft.TextField(
            label="max_price", 
            value=str(url_data.get("max_price", 0) // 100 if url_data.get("max_price") else ""),
            width=100,
            on_change=lambda e: update_config_buffer(),
            input_filter=ft.NumbersOnlyInputFilter()
        )
        target_place_start = ft.TextField(
            label="target_place_start",
            value=str(url_data.get("target_place_start", "")),
            width=100,
            on_change=lambda e: update_config_buffer(),
            input_filter=ft.NumbersOnlyInputFilter()
        )
        target_place_end = ft.TextField(
            label="target_place_end",
            value=str(url_data.get("target_place_end", "")),
            width=100,
            on_change=lambda e: update_config_buffer(),
            input_filter=ft.NumbersOnlyInputFilter()
        )
        comment = ft.TextField(
            label="comment",
            value=str(url_data.get("comment", "")),
            width=200,
            on_change=lambda e: update_config_buffer()
        )
        daily_budget = ft.TextField(
            label="daily_budget",
            value=str(url_data.get("daily_budget", "")),
            width=100,
            on_change=lambda e: update_config_buffer(),
            input_filter=ft.NumbersOnlyInputFilter()
        )
        active_switch = ft.Switch(
            label="Active",
            value=url_data.get("active", True),
            on_change=lambda e: update_config_buffer()
        )
        row = {
            "ad": ad,
            "category": category,
            "max_price": max_price,
            "target_place_start": target_place_start,
            "target_place_end": target_place_end,
            "comment": comment,
            "daily_budget": daily_budget,
            "active": active_switch
        }
        row_controls = None
        def delete_url_row(e):
            if row_controls in urls_column.controls:
                urls_column.controls.remove(row_controls)
            if p is not None and row in p["urls"]:
                p["urls"].remove(row)
            update_config_buffer()
            page.update()
        row_controls = ft.Row([
            ad, category, max_price, target_place_start, target_place_end,
            comment, daily_budget, active_switch, ft.IconButton(icon=ft.icons.DELETE, on_click=delete_url_row)
        ])
        urls_column.controls.append(row_controls)
        return row


    profiles_column = ft.Column([])

    def add_profile(profile_data=None):
        profile_data = profile_data or {}
        client_id = ft.TextField(label="client_id", value=profile_data.get("client_id", ""), width=200, on_change=lambda e: update_config_buffer())
        client_secret = ft.TextField(label="client_secret", value=profile_data.get("client_secret", ""), width=200, on_change=lambda e: update_config_buffer())
        name = ft.TextField(label="name", value=profile_data.get("name", ""), width=200, on_change=lambda e: update_config_buffer())
        urls_column = ft.Column([])
        urls = []
        p = {"client_id": client_id, "client_secret": client_secret, "name": name, "urls": urls}
        for url_data in profile_data.get("urls", []):
            urls.append(add_url_row(urls_column, url_data, p))
        def add_url_click(e):
            urls.append(add_url_row(urls_column, p=p))
            update_config_buffer()
            page.update()
        add_url_btn = ft.ElevatedButton("Добавить объявление", on_click=add_url_click)
        def delete_profile(e):
            if profile_box in profiles_column.controls:
                profiles_column.controls.remove(profile_box)
            if p in profile_controls:
                profile_controls.remove(p)
            update_config_buffer()
            page.update()
        profile_box = ft.Container(
            content=ft.Column([
                ft.Row([client_id, client_secret, name, ft.IconButton(icon=ft.icons.DELETE, on_click=delete_profile)]),
                urls_column,
                add_url_btn
            ]),
            border=ft.border.all(1, ft.colors.GREY),
            padding=10,
            margin=10
        )
        profile_controls.append(p)
        profiles_column.controls.append(profile_box)
        return p

    for prof in profiles:
        add_profile(prof)

    def add_profile_click(e):
        add_profile()
        update_config_buffer()
        page.update()

    add_profile_btn = ft.ElevatedButton("Добавить профиль", on_click=add_profile_click)
    # save_btn объявлен выше
    # Кнопку запуска парсера убираем – запуск теперь только через основное управление
    # run_btn = ft.ElevatedButton("Запустить парсер", on_click=lambda e: run_parser())
    root = ft.Column([
        ft.Text("Редактирование config.json", size=24, weight=ft.FontWeight.BOLD),
        profiles_column,
    ft.Row([add_profile_btn, save_btn], spacing=10)
    ], spacing=15)
    return root

def main(page: ft.Page):
    page.title = "Редактор конфигурации"
    page.add(build_config_editor(page))

if __name__ == "__main__":  # Сохраняем прежнее поведение при автономном запуске
    ft.app(target=main)
