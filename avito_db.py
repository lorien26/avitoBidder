import sqlite3
from typing import Any, List, Tuple, Optional
import datetime

class AvitoDB:
    def __init__(self, db_path: str = "avito_data.db"):
        self.conn = sqlite3.connect(db_path)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Таблица профилей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE,
                client_secret TEXT,
                name TEXT,
                token TEXT,
                token_created_at DATETIME
            )
        ''')
        
        # Проверяем, существует ли колонка 'name'
        cursor.execute("PRAGMA table_info(profiles)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'name' not in columns:
            try:
                cursor.execute('ALTER TABLE profiles ADD COLUMN name TEXT')
                self.conn.commit()
                print("Столбец 'name' успешно добавлен в таблицу 'profiles'.")
            except sqlite3.OperationalError as e:
                # Это может произойти в конкурентной среде, если другая сессия уже добавила столбец
                if "duplicate column name" not in str(e):
                    raise
        # Основная таблица объявлений
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ads (
                id TEXT PRIMARY KEY,
                category TEXT,
                profile_id INTEGER,
                start_price INTEGER,
                max_price INTEGER,
                target_place_start INTEGER,
                target_place_end INTEGER,
                comment TEXT,
                url TEXT,
                FOREIGN KEY(profile_id) REFERENCES profiles(id)
            )
        ''')
        # История стоимости и позиций
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ad_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_id INTEGER,
                timestamp DATETIME,
                position INTEGER,
                price REAL,
                FOREIGN KEY (ad_id) REFERENCES ads (id)
            )
        ''')
        self.conn.commit()

    def insert_profile(self, client_id: str, client_secret: str, token: str = None, token_created_at: Optional[str] = None, name: str = None) -> int:
        import datetime
        cursor = self.conn.cursor()
        if token_created_at is None:
            token_created_at = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
        cursor.execute('''
            INSERT OR IGNORE INTO profiles (client_id, client_secret, token, token_created_at, name)
            VALUES (?, ?, ?, ?, ?)
        ''', (client_id, client_secret, token, token_created_at, name))
        self.conn.commit()
        cursor.execute('SELECT id FROM profiles WHERE client_id = ?', (client_id,))
        row = cursor.fetchone()
        return row[0] if row else None

    def insert_ad(self, ad_id: str, category: str, profile_id: int, start_price: int = None, max_price: int = None, target_place_start: int = None, target_place_end: int = None, comment: str = None, url: str = None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO ads (id, category, profile_id, start_price, max_price, target_place_start, target_place_end, comment, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ad_id, category, profile_id, start_price, max_price, target_place_start, target_place_end, comment, url))
        self.conn.commit()

    def insert_ad_stat(self, ad_id: str, price: int, position: int, timestamp: Optional[datetime.datetime] = None):
        cursor = self.conn.cursor()
        if timestamp is None:
            timestamp = datetime.datetime.now()
        cursor.execute('''
            INSERT INTO ad_stats (ad_id, timestamp, price, position)
            VALUES (?, ?, ?, ?)
        ''', (ad_id, timestamp, price, position))
        self.conn.commit()

    def get_ad(self, ad_id: str) -> Optional[Tuple[Any, ...]]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM ads WHERE id = ?', (ad_id,))
        return cursor.fetchone()

    def get_ad_stats(self, ad_id):
        """Fetches statistics for a given ad for the last 7 days."""
        cursor = self.conn.cursor()
        seven_days_ago = datetime.datetime.now() - datetime.timedelta(days=7)
        cursor.execute('''
            SELECT timestamp, position, price
            FROM ad_stats
            WHERE ad_id = ? AND timestamp >= ?
            ORDER BY timestamp
        ''', (ad_id, seven_days_ago))
        return cursor.fetchall()

    def get_all_ads(self) -> List[Tuple[Any, ...]]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM ads')
        return cursor.fetchall()

    def get_profile(self, client_id: str) -> Optional[Tuple[Any, ...]]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM profiles WHERE client_id = ?', (client_id,))
        return cursor.fetchone()

    def update_profile_token(self, client_id: str, token: str):
        import datetime
        cursor = self.conn.cursor()
        token_created_at = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
        cursor.execute('UPDATE profiles SET token = ?, token_created_at = ? WHERE client_id = ?', (token, token_created_at, client_id))
        self.conn.commit()
        
    def delete_profile_and_related_data(self, client_id: str) -> bool:
        """Удаляет профиль и все связанные с ним данные (объявления и статистику)"""
        cursor = self.conn.cursor()
        
        # Получаем ID профиля
        cursor.execute('SELECT id FROM profiles WHERE client_id = ?', (client_id,))
        profile_row = cursor.fetchone()
        if not profile_row:
            return False
            
        profile_id = profile_row[0]
        
        # Удаляем статистику объявлений для этого профиля
        cursor.execute('''
            DELETE FROM ad_stats 
            WHERE ad_id IN (SELECT id FROM ads WHERE profile_id = ?)
        ''', (profile_id,))
        
        # Удаляем объявления для этого профиля
        cursor.execute('DELETE FROM ads WHERE profile_id = ?', (profile_id,))
        
        # Удаляем сам профиль
        cursor.execute('DELETE FROM profiles WHERE id = ?', (profile_id,))
        
        self.conn.commit()
        return True
    
    def delete_ad_and_related_data(self, ad_id: str) -> bool:
        """Удаляет объявление и всю связанную с ним статистику"""
        cursor = self.conn.cursor()
        
        # Проверяем, существует ли объявление
        cursor.execute('SELECT id FROM ads WHERE id = ?', (ad_id,))
        if not cursor.fetchone():
            return False
        
        # Удаляем статистику объявления
        cursor.execute('DELETE FROM ad_stats WHERE ad_id = ?', (ad_id,))
        
        # Удаляем объявление
        cursor.execute('DELETE FROM ads WHERE id = ?', (ad_id,))
        
        self.conn.commit()
        return True
    
    def get_all_profile_client_ids(self) -> List[str]:
        """Возвращает список всех client_id из базы данных"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT client_id FROM profiles')
        return [row[0] for row in cursor.fetchall()]
    
    def get_all_ad_ids(self) -> List[str]:
        """Возвращает список всех ID объявлений из базы данных"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM ads')
        return [row[0] for row in cursor.fetchall()]

    def close(self):
        self.conn.close()

# Пример использования:
# db = AvitoDB()
# profile_id = db.insert_profile('client_id', 'client_secret', 'token')
# db.insert_ad('ad_id', 'category_url', profile_id)
# db.insert_ad_stat('ad_id', 10.5, 2, 1)
# print(db.get_ad_stats('ad_id'))
# db.close()
