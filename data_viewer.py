import flet as ft
import sqlite3
import math
from datetime import datetime, timedelta

DB_PATH = 'avito_data.db'

def get_db_connection():
    """Устанавливает соединение с базой данных SQLite."""
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

def get_all_data():
    """Извлекает все профили и связанные с ними объявления из базы данных."""
    with get_db_connection() as conn:
        profiles = conn.execute("SELECT id, client_id, name FROM profiles").fetchall()
        result = []
        for p in profiles:
            ads = conn.execute(
                """
                SELECT 
                    a.id,
                    a.category,
                    a.comment,
                    a.start_price / 100.0 as start_price,
                    a.max_price / 100.0 as max_price,
                    a.target_place_start,
                    a.target_place_end,
                    a.url,
                    (SELECT price / 100.0 FROM ad_stats WHERE ad_id = a.id ORDER BY timestamp DESC LIMIT 1) as current_price,
                    (SELECT position FROM ad_stats WHERE ad_id = a.id ORDER BY timestamp DESC LIMIT 1) as current_place,
                    (SELECT timestamp FROM ad_stats WHERE ad_id = a.id ORDER BY timestamp DESC LIMIT 1) as last_update
                FROM ads a 
                WHERE a.profile_id = ?
                """,
                (p['id'],)
            ).fetchall()
            result.append({'profile': dict(p), 'ads': [dict(ad) for ad in ads]})
        return result

def get_ad_stats(ad_id, selected_date=None, start_hour=8, end_hour=23):
    """Получает статистику объявления за выбранную дату в указанный период времени."""
    with get_db_connection() as conn:
        if selected_date:
            # Конвертируем date в datetime если нужно
            if hasattr(selected_date, 'date'):  # это datetime объект
                target_date = selected_date
            else:  # это date объект
                target_date = datetime.combine(selected_date, datetime.min.time())
            
            # Данные за конкретную дату в указанный период
            start_date = target_date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            end_date = target_date.replace(hour=end_hour, minute=59, second=59, microsecond=999999)
            cursor = conn.execute('''
                SELECT timestamp, position, price / 100.0
                FROM ad_stats
                WHERE ad_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp
            ''', (ad_id, start_date, end_date))
        else:
            # Последние данные в указанный период текущего дня
            now = datetime.now()
            start_time = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=end_hour, minute=59, second=59, microsecond=999999)
            cursor = conn.execute('''
                SELECT timestamp, position, price / 100.0
                FROM ad_stats
                WHERE ad_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp
            ''', (ad_id, start_time, end_time))
        result = cursor.fetchall()
        return result

def format_price(value):
    """Форматирует число в денежную строку."""
    if value is None:
        return "—"
    try:
        
        return f"{float(value):,.0f}".replace(',', ' ') + " ₽"
    except (ValueError, TypeError):
        return "—"

def format_target_range(start, end):
    """Форматирует диапазон целевых позиций."""
    if start is None and end is None:
        return "—"
    if start is None:
        return f"до {end}"
    if end is None:
        return f"от {start}"
    if start == end:
        return str(start)
    return f"{start}-{end}"

def format_url(url):
    """Форматирует URL для отображения в таблице."""
    if not url:
        return "—"
    # Извлекаем ID объявления из URL для краткого отображения
    if '_' in url:
        try:
            # Извлекаем последнюю часть после последнего подчеркивания
            parts = url.split('_')
            if len(parts) > 1:
                ad_id = parts[-1].split('?')[0]  # Убираем параметры если есть
                return f"...{ad_id}"
        except:
            pass
    return "URL"

def format_datetime(ts):
    """Форматирует время без даты (только часы:минуты)."""
    if not ts:
        return "—"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return str(ts)
    return ts.strftime('%H:%M')

class AdChart(ft.UserControl):
    def __init__(self, ad_id, start_price):
        super().__init__()
        self.ad_id = ad_id
        self.start_price = start_price
        # Устанавливаем дату, когда точно есть данные (сегодня)
        self.selected_date = datetime.now().date()
        self.start_hour = 8  # Начальный час (по умолчанию 8:00)
        self.end_hour = 23   # Конечный час (по умолчанию 23:00, может быть 24 как эксклюзивная граница)
        self.chart_container = ft.Container(
            visible=False, 
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            margin=ft.margin.only(top=2),  # Небольшой отступ от строки данных
            bgcolor=ft.colors.GREY_800,  # Темный фон как на изображении
            border=ft.border.all(2, ft.colors.GREY_600),  # Выраженная обводка
            border_radius=ft.border_radius.only(bottom_left=6, bottom_right=6)  # Скругления снизу
        )
        self.date_picker = ft.DatePicker(
            on_change=self.on_date_changed,
            first_date=datetime.now().date() - timedelta(days=30),
            last_date=datetime.now().date()
        )
        
        # Ползунки для выбора времени
        self.start_time_slider = ft.Slider(
            min=0,
            max=23,
            divisions=23,
            value=8,
            label="Начало: {value}:00",
            on_change=self.on_start_time_changed,
            width=200
        )
        
        # Позволяем выбирать 24 как конец суток (эксклюзивно)
        self.end_time_slider = ft.Slider(
            min=0,
            max=24,
            divisions=24,
            value=23,
            label="Конец: {value}:00",
            on_change=self.on_end_time_changed,
            width=200
        )

    def build(self):
        return ft.Column([
            self.date_picker,
            self.chart_container
        ])

    def on_date_changed(self, e):
        """Обработчик изменения даты"""
        if e.control.value:
            self.selected_date = e.control.value
            self.update_chart()

    def on_start_time_changed(self, e):
        """Обработчик изменения начального времени"""
        new_start = int(e.control.value)
        if new_start >= self.end_hour:
            # Если начальное время >= конечного, сдвигаем конечное время
            self.end_hour = min(24, new_start + 1)
            self.end_time_slider.value = self.end_hour
            # Убираем update() для slider, он будет обновлен автоматически
        self.start_hour = new_start
        self.update_chart()

    def on_end_time_changed(self, e):
        """Обработчик изменения конечного времени"""
        new_end = int(e.control.value)
        if new_end <= self.start_hour:
            # Если конечное время <= начального, сдвигаем начальное время
            self.start_hour = max(0, new_end - 1)
            self.start_time_slider.value = self.start_hour
            # Убираем update() для slider, он будет обновлен автоматически
        self.end_hour = new_end
        self.update_chart()

    def show(self):
        if not self.chart_container.content:
            # Создаем контролы
            controls_container = self._create_controls()
            
            # Показываем индикатор загрузки для графика
            loading_content = ft.Row(
                [ft.ProgressRing(width=16, height=16), ft.Text("Загрузка графика...", color=ft.colors.WHITE)],
                spacing=10,
                alignment=ft.MainAxisAlignment.CENTER,
                height=50
            )
            
            self.chart_container.content = ft.Column([
                controls_container,
                ft.Divider(height=1, color=ft.colors.GREY_300),
                loading_content
            ], spacing=10)
        
        self.chart_container.visible = True
        self.update()
        
        # Загружаем данные асинхронно
        self.update_chart()

    def set_today(self, e):
        """Устанавливает сегодняшнюю дату"""
        self.selected_date = datetime.now().date()
        self.update_chart()
        
    def _create_controls(self):
        """Создает контролы для выбора даты и периода времени"""
        # Создаем контрол выбора даты
        date_button = ft.ElevatedButton(
            content=ft.Row([
                ft.Text(f"{self.selected_date.strftime('%d.%m.%Y')}", size=14),
                ft.Icon(ft.icons.CALENDAR_MONTH, size=16)
            ], tight=True, spacing=5),
            on_click=lambda _: self.page.open(self.date_picker),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                bgcolor=ft.colors.GREY_700,
                color=ft.colors.WHITE
            )
        )
        
        # Контейнер для даты и кнопок
        date_controls = ft.Row([
            ft.Text("Дата:", size=14, weight=ft.FontWeight.W_500, color=ft.colors.WHITE),
            date_button,
            ft.ElevatedButton(
                "Сегодня",
                on_click=self.set_today,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=8),
                    bgcolor=ft.colors.GREY_700,
                    color=ft.colors.WHITE
                )
            )
        ], spacing=10, alignment=ft.MainAxisAlignment.START)
        
        # Контейнер для выбора времени с ползунками
        time_controls = ft.Column([
            ft.Row([
                ft.Text("Период времени:", size=14, weight=ft.FontWeight.W_500, color=ft.colors.WHITE),
                ft.Text(f"{self.start_hour:02d}:00 - {self.end_hour:02d}:00", 
                       size=12, color=ft.colors.BLUE_400, weight=ft.FontWeight.BOLD)
            ], spacing=10),
            ft.Row([
                ft.Text("Начало:", size=12, width=60, color=ft.colors.WHITE),
                self.start_time_slider
            ], spacing=10),
            ft.Row([
                ft.Text("Конец:", size=12, width=60, color=ft.colors.WHITE),
                self.end_time_slider
            ], spacing=10)
        ], spacing=5)
        
        # Общий контейнер для всех контролов
        return ft.Column([
            date_controls,
            time_controls
        ], spacing=10)

    def update_chart(self):
        """Обновляет график для выбранной даты и периода времени"""
        try:
            # Получаем данные для выбранной даты и периода (передаем datetime объект)
            selected_datetime = datetime.combine(self.selected_date, datetime.min.time())
            # Для end_hour == 24 интерпретируем как 23:59:59
            effective_end_hour = 23 if self.end_hour == 24 else self.end_hour
            stats = get_ad_stats(self.ad_id, selected_datetime, self.start_hour, effective_end_hour)
            
            # Создаем контролы
            controls_container = self._create_controls()
            
            if not stats:
                # Нет данных за выбранную дату
                no_data_content = ft.Container(
                    content=ft.Text(
                        "Данных за выбранный день нет", 
                        size=16, 
                        color=ft.colors.WHITE,
                        text_align=ft.TextAlign.CENTER
                    ),
                    width=1010,  # Соответствует новому размеру графика
                    height=185,  # Пропорционально уменьшаем
                    alignment=ft.alignment.center,
                    border=ft.border.all(1, ft.colors.GREY_600),
                    border_radius=4,
                    bgcolor=ft.colors.GREY_800
                )
                
                self.chart_container.content = ft.Column([
                    controls_container,
                    ft.Divider(height=1, color=ft.colors.GREY_300),
                    no_data_content
                ], spacing=10)
            else:
                # Преобразуем данные в правильный формат
                formatted_stats = []
                for row in stats:
                    timestamp, position, price = row
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp)
                    formatted_stats.append({
                        'timestamp': timestamp,
                        'position': position,
                        'price': price
                    })
                
                # Группируем данные по 10-минутным интервалам
                aggregated_stats = self._aggregate_data_by_intervals(formatted_stats)
                
                # Создаем график и статистику
                chart = self._create_simple_chart(aggregated_stats)
                summary = self._create_summary(aggregated_stats)
                
                self.chart_container.content = ft.Column([
                    controls_container,
                    ft.Divider(height=1, color=ft.colors.GREY_300),
                    summary,
                    chart
                ], spacing=10)
                
        except Exception as e:
            # Обработка ошибок
            error_content = ft.Container(
                content=ft.Text(f"Ошибка загрузки данных: {str(e)}", color=ft.colors.RED),
                padding=10
            )
            
            # Создаем контролы для блока ошибки
            controls_container = self._create_controls()
            
            self.chart_container.content = ft.Column([
                controls_container,
                ft.Divider(height=1, color=ft.colors.GREY_300),
                error_content
            ], spacing=10)
        
        self.update()

    def hide(self):
        self.chart_container.visible = False
        self.update()

    def _aggregate_data_by_intervals(self, stats, interval_minutes=10):
        """Группирует данные по интервалам и вычисляет среднее арифметическое для каждого интервала"""
        if not stats:
            return []
        
        from collections import defaultdict
        
        # Словарь для группировки данных по интервалам
        intervals = defaultdict(list)
        
        # Определяем начальную точку для группировки (начало выбранного периода)
        base_date = stats[0]['timestamp'].replace(
            hour=self.start_hour, 
            minute=0, 
            second=0, 
            microsecond=0
        )
        
        # Группируем данные по 10-минутным интервалам
        for stat in stats:
            timestamp = stat['timestamp']
            
            # Вычисляем номер интервала (каждые 10 минут)
            minutes_from_base = int((timestamp - base_date).total_seconds() / 60)
            interval_number = minutes_from_base // interval_minutes
            
            # Время начала интервала
            interval_start = base_date + timedelta(minutes=interval_number * interval_minutes)
            
            intervals[interval_start].append(stat)
        
        # Вычисляем среднее арифметическое для каждого интервала
        aggregated_data = []
        for interval_time in sorted(intervals.keys()):
            interval_stats = intervals[interval_time]
            
            # Вычисляем средние значения
            avg_position = sum(s['position'] for s in interval_stats) / len(interval_stats)
            avg_price = sum(s['price'] for s in interval_stats) / len(interval_stats)
            
            # Добавляем агрегированную запись
            aggregated_data.append({
                'timestamp': interval_time + timedelta(minutes=interval_minutes/2),  # Центр интервала
                'position': round(avg_position, 1),
                'price': round(avg_price, 2),
                'original_count': len(interval_stats)  # Количество исходных записей в интервале
            })
        
        return aggregated_data

    def _create_simple_chart(self, stats):
        """Создает график с подписями осей и улучшенными тултипами для агрегированных данных"""
        if not stats:
            return ft.Container(
                content=ft.Text("Нет данных для отображения", size=14, color=ft.colors.WHITE),
                width=1010,  # Соответствует новому размеру графика + фиксированные шкалы
                height=185,  # Пропорционально уменьшаем
                alignment=ft.alignment.center,
                border=ft.border.all(1, ft.colors.GREY_600),
                border_radius=4,
                bgcolor=ft.colors.GREY_800
            )
        
        positions = [s['position'] for s in stats]
        prices = [s['price'] for s in stats]
        timestamps = [s['timestamp'] for s in stats]
        
        # Нормализуем данные для отображения
        max_pos = max(positions) if positions else 1
        min_pos = min(positions) if positions else 1
        max_price = max(prices) if prices else 1
        min_price = min(prices) if prices else 1
        
        chart_width = 1400  # Увеличиваем до почти максимальной ширины окна
        chart_height = 150  # Уменьшаем в 0.75 раза (200 * 0.75)
        chart_margin_left = 25  # Уменьшаем отступ, так как убрали цифры позиций
        chart_margin_bottom = 25  # Минимальный отступ для временных меток
        chart_margin_top = 10
        chart_margin_right = 25  # Уменьшаем отступ, так как убрали цифры цен
        
        # Рабочая область графика
        plot_width = chart_width - chart_margin_left - chart_margin_right
        plot_height = chart_height - chart_margin_top - chart_margin_bottom
        
        elements = []
        
        # Фоновая область графика - используем темный фон
        bg_area = ft.Container(
            width=plot_width,
            height=plot_height,
            bgcolor=ft.colors.GREY_800,
            border=ft.border.all(1, ft.colors.GREY_600),
            left=chart_margin_left,
            bottom=chart_margin_bottom
        )
        elements.append(bg_area)
        
        # Подписи осей с минимальными отступами
        # Подпись левой оси Y (позиции)
        y_left_label = ft.Container(
            content=ft.Text("Позиция", size=14, weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE_400),
            left=2,
            bottom=chart_height // 2 + 10,
            rotate=ft.Rotate(-1.57)  # -90 градусов
        )
        elements.append(y_left_label)
        
        # Подпись правой оси Y (цена)
        y_right_label = ft.Container(
            content=ft.Text("Цена, ₽", size=14, weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_400),
            right=2,
            bottom=chart_height // 2 + 15,
            rotate=ft.Rotate(1.57)  # 90 градусов
        )
        elements.append(y_right_label)
        
        # Фиксированная шкала позиций (только сетка, без цифр)
        position_values = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 1]
        for i, pos_value in enumerate(position_values):
            # Позиция от нижней части графика (1 = внизу, 100 = вверху)
            y_pos = chart_margin_bottom + ((100 - pos_value) / 99) * plot_height
            
            # Горизонтальная линия сетки только для основных делений (каждые 20)
            if pos_value % 20 == 0:
                grid_line = ft.Container(
                    width=plot_width,
                    height=2,  # Увеличиваем толщину линии
                    bgcolor=ft.colors.GREY_600,  # Темнее для темной темы
                    left=chart_margin_left,
                    bottom=y_pos
                )
                elements.append(grid_line)
        
        # Создаем столбцы и точки данных для агрегированных данных
        
        for i, stat in enumerate(stats):
            pos = stat['position']
            price = stat['price']
            ts = stat['timestamp']
            original_count = stat.get('original_count', 1)  # Количество исходных записей
            
            # Вычисляем позицию по времени относительно выбранного диапазона
            if isinstance(ts, datetime):
                # Время от начала выбранного диапазона в часах
                start_time = ts.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
                end_hour_effective = self.end_hour if self.end_hour < 24 else 24
                end_time = ts.replace(hour=end_hour_effective if end_hour_effective < 24 else 23, minute=0, second=0, microsecond=0)
                if self.end_hour == 24:
                    end_time += timedelta(hours=1)
                
                # Время точки относительно начала диапазона
                time_from_start = (ts - start_time).total_seconds() / 3600  # в часах
                time_range = (end_time - start_time).total_seconds() / 3600  # общий диапазон в часах
                
                # Позиция пропорционально времени в диапазоне
                time_ratio = time_from_start / max(time_range, 0.001)  # избегаем деления на 0
                x_pos = chart_margin_left + time_ratio * plot_width
            else:
                # Fallback для не-datetime объектов
                x_pos = chart_margin_left + (i / max(len(stats) - 1, 1)) * plot_width
            
            # Высота столбца позиции по фиксированной шкале (1-100)
            # Позиция 1 = внизу (высота 0), позиция 100 = вверху (полная высота)
            pos_clamped = max(1, min(100, pos))  # Ограничиваем от 1 до 100
            pos_norm = (100 - pos_clamped) / 99  # Инвертируем: 1 = максимум, 100 = минимум
            bar_height = max(4, pos_norm * plot_height)
            
            # Ширина столбца зависит от количества точек в интервале с промежутками
            base_bar_width = max(12, plot_width / len(stats) * 0.4)  # Уменьшаем коэффициент для больших промежутков
            bar_width = min(base_bar_width, 20)  # Уменьшаем максимальную ширину для лучшего разделения
            
            # Столбец для позиции (более широкий для агрегированных данных)
            bar = ft.Container(
                width=bar_width,
                height=bar_height,
                bgcolor=ft.colors.ORANGE_300,
                border_radius=3,
                left=x_pos - bar_width/2,
                bottom=chart_margin_bottom
            )
            elements.append(bar)
            
            # Высота точки цены по фиксированной шкале (0-100)
            price_clamped = max(0, min(100, price))  # Ограничиваем от 0 до 100
            price_norm = price_clamped / 100  # 0 = внизу, 100 = вверху
            point_y = chart_margin_bottom + price_norm * plot_height
            
            # Размер точки зависит от количества записей в интервале
            point_size = min(16, 8 + original_count)  # Увеличиваем размер для большего количества записей
            
            # Точка для цены с полной информацией в тултипе
            point = ft.Container(
                width=point_size,
                height=point_size,
                bgcolor=ft.colors.BLUE,
                border_radius=point_size/2,
                border=ft.border.all(2, ft.colors.GREY_200),
                left=x_pos - point_size/2,
                bottom=point_y - point_size/2,
                tooltip=ft.Tooltip(
                    message=f"� Интервал: {ts.strftime('%H:%M')}\n💰 Средняя цена: {price:.2f} ₽\n🏆 Средняя позиция: {pos}\n� Записей в интервале: {original_count}",
                    text_style=ft.TextStyle(color=ft.colors.WHITE, size=12),
                    bgcolor=ft.colors.BLACK87,
                    border_radius=8,
                    padding=10
                )
            )
            elements.append(point)
        
        # Создаем временные метки каждый час для лучшей читаемости
        if timestamps:
            first_timestamp = timestamps[0]
            if isinstance(first_timestamp, datetime):
                # Создаем метки времени каждый час в выбранном диапазоне
                start_time = first_timestamp.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
                end_hour_effective = self.end_hour if self.end_hour < 24 else 24
                end_time = first_timestamp.replace(hour=end_hour_effective if end_hour_effective < 24 else 23, minute=0, second=0, microsecond=0)
                if self.end_hour == 24:
                    end_time += timedelta(hours=1)
                
                # Вычисляем количество часов
                total_hours = (end_time - start_time).total_seconds() / 3600
                hour_count = int(total_hours) + 1
                
                # Добавляем метки каждый час
                for i in range(hour_count):
                    current_label_time = start_time + timedelta(hours=i)
                    
                    # Проверяем, что время не превышает конечное время
                    if current_label_time > end_time:
                        break
                    
                    # Позиция на графике пропорционально времени в диапазоне
                    time_from_start = (current_label_time - start_time).total_seconds() / 3600  # в часах
                    time_ratio = time_from_start / max(total_hours, 0.001)
                    x_pos = chart_margin_left + time_ratio * plot_width
                    
                    time_str = current_label_time.strftime('%H:%M')
                    time_label = ft.Container(
                        content=ft.Text(time_str, size=10, color=ft.colors.WHITE, text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.W_500),
                        width=40,
                        left=x_pos - 20,
                        bottom=5
                    )
                    elements.append(time_label)
                    
                    # Вертикальная линия сетки (жирнее)
                    grid_line = ft.Container(
                        width=2,  # Делаем линии жирнее
                        height=plot_height,
                        bgcolor=ft.colors.GREY_600,  # Темнее для темной темы
                        left=x_pos,
                        bottom=chart_margin_bottom
                    )
                    elements.append(grid_line)
        
        return ft.Container(
            content=ft.Stack(elements),
            width=chart_width + 110,  # Увеличенное место для фиксированных шкал (1400+110=1510)
            height=chart_height + 35,  # Минимальное место для подписей
            border=ft.border.all(2, ft.colors.GREY_600),  # Темнее для темной темы
            border_radius=4,
            padding=10,
            margin=ft.margin.symmetric(vertical=10),
            bgcolor=ft.colors.GREY_800
        )

    def _create_summary(self, stats):
        """Создает сводку по агрегированным данным с новыми показателями"""
        if not stats:
            return ft.Row([])
        total_records = sum(s.get('original_count', 1) for s in stats)
        # Среднее место (по всем исходным записям): берём агрегированные значения * кол-во исходных
        weighted_pos_sum = sum(s['position'] * s.get('original_count', 1) for s in stats)
        avg_position = weighted_pos_sum / total_records if total_records else 0
        weighted_price_sum = sum(s['price'] * s.get('original_count', 1) for s in stats)
        avg_price = weighted_price_sum / total_records if total_records else 0

        highest_pos = min(s['position'] for s in stats) if stats else 0
        highest_rate = max(s['price'] for s in stats) if stats else 0

        def create_summary_item(title, value):
            return ft.Container(
                content=ft.Column([
                    ft.Text(title, size=10, color=ft.colors.WHITE70),
                    ft.Text(value, size=12, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE)
                ], spacing=2),
                padding=ft.padding.symmetric(vertical=3, horizontal=6),
                border_radius=4,
                bgcolor=ft.colors.BLUE_GREY_800,
                border=ft.border.all(1, ft.colors.BLUE_GREY_600),
                alignment=ft.alignment.center,
                expand=True
            )

        return ft.Row(
            controls=[
                create_summary_item("Лучшая позиция", f"{highest_pos}"),
                create_summary_item("Максимальная ставка", format_price(highest_rate)),
                create_summary_item("Среднее место в выдаче", f"{avg_position:.1f}"),
                create_summary_item("Средняя цена просмотра", format_price(avg_price)),
            ],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            spacing=5
        )

class AdItem(ft.UserControl):
    def __init__(self, ad):
        super().__init__()
        self.ad = ad
        self.chart_view = AdChart(ad['id'], ad['start_price'])
        self.is_expanded = False

    def copy_url_to_clipboard(self, e, url):
        """Копирует URL в буфер обмена."""
        if url and self.page:
            try:
                self.page.set_clipboard(url)
                # Показываем уведомление об успешном копировании
                self.page.show_snack_bar(
                    ft.SnackBar(
                        content=ft.Text("URL скопирован в буфер обмена", color=ft.colors.WHITE),
                        bgcolor=ft.colors.GREEN_600,
                        duration=3000
                    )
                )
            except Exception as ex:
                # Показываем уведомление об ошибке
                self.page.show_snack_bar(
                    ft.SnackBar(
                        content=ft.Text(f"Ошибка копирования: {str(ex)}", color=ft.colors.WHITE),
                        bgcolor=ft.colors.RED_600,
                        duration=3000
                    )
                )
        else:
            # Показываем уведомление, что URL отсутствует
            if self.page:
                self.page.show_snack_bar(
                    ft.SnackBar(
                        content=ft.Text("URL отсутствует", color=ft.colors.WHITE),
                        bgcolor=ft.colors.ORANGE_600,
                        duration=2000
                    )
                )

    def build(self):
        # Создаем простую строку данных без заголовков в едином стиле
        data_row = ft.Container(
            content=ft.Row([
                ft.Container(ft.TextButton(
                        text=str(self.ad['id']),
                        on_click=lambda e, url=self.ad.get('url'): self.copy_url_to_clipboard(e, url),
                        tooltip="Нажмите, чтобы скопировать URL" if self.ad.get('url') else "URL отсутствует",
                        disabled=not bool(self.ad.get('url')),
                    ), width=100, alignment=ft.alignment.center),
                ft.Container(ft.Text(str(self.ad['category']), size=10, color=ft.colors.WHITE), width=180, alignment=ft.alignment.center),
                ft.Container(ft.Text(format_price(self.ad['start_price']), size=10, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text(format_price(self.ad['max_price']), size=10, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text(format_target_range(self.ad['target_place_start'], self.ad['target_place_end']), size=10, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text(format_price(self.ad['current_price']), size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text(str(self.ad['current_place']), size=10, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text(format_datetime(self.ad['last_update']), size=10, color=ft.colors.WHITE), width=120, alignment=ft.alignment.center),
                ft.Container(ft.Text(str(self.ad['comment']), size=10, color=ft.colors.WHITE), width=180, alignment=ft.alignment.center),
                
            ], spacing=5),
            bgcolor=ft.colors.GREY_800 if not self.is_expanded else ft.colors.GREY_700,  # Темный фон
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.colors.GREY_600)),  # Только нижняя граница для разделения строк
            border_radius=0,  # Убираем скругление для соединения с заголовком
            ink=True,
            on_click=lambda _: self.toggle_details(None)
        )
        
        return ft.Column(
            controls=[
                data_row,
                self.chart_view
            ],
            spacing=0  # Убираем промежуток между элементами для визуального единства
        )

    def toggle_details(self, e):
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            self.chart_view.show()
        else:
            self.chart_view.hide()
        self.update()

class ProfileView(ft.UserControl):
    def __init__(self, profile, ads):
        super().__init__()
        self.profile = profile
        self.ads = ads
        self.ads_container = self._create_ads_view()
        self.ads_container.visible = False
        self.toggle_icon = ft.Icon(ft.icons.ARROW_RIGHT, color=ft.colors.WHITE)

    def _create_ads_view(self):
        """Создает контейнер со списком объявлений."""
        # Создаем общий заголовок таблицы в стиле основного дизайна
        header_row = ft.Container(
            content=ft.Row([
                ft.Container(ft.Text("ID", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=100, alignment=ft.alignment.center),
                ft.Container(ft.Text("Категория", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=180, alignment=ft.alignment.center),
                ft.Container(ft.Text("Начальная цена", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text("Максимальная цена", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text("Целевой диапазон", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text("Текущая цена", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text("Место в выдаче", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=80, alignment=ft.alignment.center),
                ft.Container(ft.Text("Обновлено", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=120, alignment=ft.alignment.center),
                ft.Container(ft.Text("Комментарий", size=10, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=120, alignment=ft.alignment.center),
            ], spacing=5),
            bgcolor=ft.colors.GREY_700,  # Темнее для выделения заголовка
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=ft.border_radius.only(top_left=6, top_right=6),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.colors.GREY_600))  # Только нижняя граница
        )
        
        # Создаем контейнер для всей таблицы с правильными скруглениями
        ads_items = [AdItem(ad) for ad in self.ads]
        table_container = ft.Container(
            content=ft.Column(controls=[
                header_row,
                ft.Column(controls=ads_items, spacing=0)  # Убираем промежутки между строками
            ], spacing=0),
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,  # Обрезаем содержимое по границам
            border=ft.border.all(2, ft.colors.GREY_600)  # Общая обводка таблицы
        )
        
        return ft.Container(
            content=table_container,
            padding=ft.padding.only(top=5)
        )

    def _toggle_ads(self, e):
        """Переключает видимость объявлений и иконку."""
        self.ads_container.visible = not self.ads_container.visible
        self.toggle_icon.name = ft.icons.ARROW_DROP_DOWN if self.ads_container.visible else ft.icons.ARROW_RIGHT
        self.update()

    def build(self):
        """Строит виджет для одного профиля."""
        profile_header = ft.Container(
            content=ft.Row([
                self.toggle_icon,
                ft.Text(f"Профиль: {self.profile['name'] or self.profile['client_id']}", size=18, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
            ]),
            on_click=self._toggle_ads,
            padding=10,
            border_radius=8,
            ink=True,
        )

        return ft.Container(
            content=ft.Column([
                profile_header,
                self.ads_container
            ]),
            padding=15,
            margin=ft.margin.only(bottom=15),
            border=ft.border.all(1, ft.colors.GREY_600),
            border_radius=10,
            bgcolor=ft.colors.GREY_800
        )

def build_data_viewer(page: ft.Page) -> ft.Control:
    """Строит и возвращает контрол для просмотра данных (без запуска ft.app).

    Используется в едином интерфейсе. Сохраняет поведение standalone версии.
    """
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.padding = 20
    page.bgcolor = ft.colors.GREY_900  # Темный фон страницы
    page.theme_mode = ft.ThemeMode.DARK  # Темная тема

    def show_loading():
        """Отображает индикатор загрузки в основной колонке."""
        main_column.controls.clear()
        main_column.controls.append(
            ft.Row(
                [ft.ProgressRing(), ft.Text("Загрузка данных...", color=ft.colors.WHITE)],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10
            )
        )
        page.update()

    def build_view(e=None):
        """Создает и отображает виджеты на основе данных из БД."""
        show_loading()
        all_data = get_all_data()
        main_column.controls.clear()
        if not all_data:
            main_column.controls.append(ft.Text("В базе данных нет профилей. Заполните ее и обновите страницу.", size=16, text_align="center", color=ft.colors.WHITE))
        else:
            main_column.controls.extend([ProfileView(item['profile'], item['ads']) for item in all_data])
        page.update()

    refresh_button = ft.IconButton(
        icon=ft.icons.REFRESH,
        tooltip="Обновить данные",
        on_click=build_view
    )
    
    title_row = ft.Row([
        ft.Text("Данные из базы avito_data.db", size=24, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
        refresh_button
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    main_column = ft.Column(spacing=8, alignment=ft.MainAxisAlignment.START)

    root = ft.Column([title_row, main_column])
    # Первоначальная загрузка данных при старте
    build_view()
    return root

def main(page: ft.Page):
    page.title = "Просмотр данных Avito"
    page.add(build_data_viewer(page))

if __name__ == "__main__":
    ft.app(target=main)
