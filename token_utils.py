import datetime
import requests
from avito_db import AvitoDB

def refresh_tokens_for_all_profiles(db_path: str = "avito_data.db"):
    """
    Обновляет токены для всех профилей, если с момента последнего обновления прошло более 23 часов.
    """
    db = AvitoDB(db_path)
    profiles = db.conn.execute("SELECT id, client_id, client_secret, token, token_created_at FROM profiles").fetchall()
    now = datetime.datetime.now()
    for profile in profiles:
        profile_id, client_id, client_secret, token, token_created_at = profile
        if token_created_at:
            last_time = datetime.datetime.fromisoformat(token_created_at)
            hours_passed = (now - last_time).total_seconds() / 3600
        else:
            hours_passed = 24  # если нет даты, считаем что давно
        if hours_passed >= 23:
            url = 'https://api.avito.ru/token'
            payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials"
            }
            headers = {"content-type": "application/x-www-form-urlencoded"}
            try:
                response = requests.post(url, headers=headers, data=payload)
                response.raise_for_status()
                data = response.json()
                print(data)
                if 'access_token' not in data:
                    print(f"Ошибка в ответе Avito API для профиля {client_id}: {data}")
                    continue
                new_token = data['access_token']
                db.update_profile_token(client_id, new_token)
                print(f"Токен для профиля {client_id} обновлён.")
            except requests.exceptions.RequestException as e:
                print(f"Ошибка при обновлении токена для профиля {client_id}: {e}")
    db.close()
