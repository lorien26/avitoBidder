
import json
from avito_db import AvitoDB

def init_db_from_config(config_path: str = "config.json", db_path: str = "avito_data.db"):
    """
    Универсальная функция инициализации базы данных профилями и объявлениями из конфига Avito.
    Синхронизирует базу данных с конфигом: удаляет отсутствующие профили и объявления.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    db = AvitoDB(db_path)
    
    # Получаем текущие данные из конфига
    config_profiles = {}  # client_id -> profile_data
    config_ads = {}       # ad_id -> ad_data
    
    print("📋 Обработка конфига...")
    
    for profile in config.get("profiles", []):
        client_id = profile.get("client_id")
        client_secret = profile.get("client_secret")
        name = profile.get("name")
        token = profile.get("token")
        
        if not client_id or not client_secret:
            print(f"⚠️ Профиль пропущен: не хватает client_id или client_secret: {profile}")
            continue
            
        config_profiles[client_id] = {
            'client_secret': client_secret,
            'name': name,
            'token': token,
            'urls': profile.get("urls", [])
        }
        
        # Обрабатываем объявления для этого профиля
        for url_pair in profile.get("urls", []):
            ad_url = url_pair.get("ad")
            category = url_pair.get("category")
            max_price = url_pair.get("max_price")
            target_place_start = url_pair.get("target_place_start")
            target_place_end = url_pair.get("target_place_end")
            comment = url_pair.get("comment")
            daily_budget = url_pair.get("daily_budget")
            active = url_pair.get("active", True)  # По умолчанию True для обратной совместимости
            
            if not all([ad_url, category, max_price is not None, 
                       target_place_start is not None, target_place_end is not None]):
                print(f"⚠️ Объявление пропущено: не хватает данных: {url_pair}")
                continue
                
            # Извлекаем ID объявления из URL
            ad_id = ad_url[:ad_url.index('?')].split('_')[-1] if '?' in ad_url else ad_url.split('_')[-1]
            
            config_ads[ad_id] = {
                'client_id': client_id,
                'ad_url': ad_url,
                'category': category,
                'max_price': int(max_price),
                'target_place_start': int(target_place_start),
                'target_place_end': int(target_place_end),
                'comment': comment,
                'daily_budget': daily_budget,
                'active': active
            }
    
    print(f"📊 В конфиге найдено: {len(config_profiles)} профилей, {len(config_ads)} объявлений")
    
    # Получаем текущие данные из БД
    db_profiles = {}      # client_id -> profile_id
    db_ads = set()        # set of ad_ids
    
    print("🔍 Анализ текущих данных в БД...")
    
    # Получаем все профили из БД
    db_profiles_rows = db.conn.execute("SELECT id, client_id FROM profiles").fetchall()
    for profile_id, client_id in db_profiles_rows:
        db_profiles[client_id] = profile_id
    
    # Получаем все объявления из БД
    db_ads_rows = db.conn.execute("SELECT id FROM ads").fetchall()
    for (ad_id,) in db_ads_rows:
        db_ads.add(ad_id)
    
    print(f"📊 В БД найдено: {len(db_profiles)} профилей, {len(db_ads)} объявлений")
    
    # Удаляем профили, которых нет в конфиге
    profiles_to_delete = set(db_profiles.keys()) - set(config_profiles.keys())
    if profiles_to_delete:
        print(f"🗑️ Удаление профилей, отсутствующих в конфиге: {profiles_to_delete}")
        for client_id in profiles_to_delete:
            profile_id = db_profiles[client_id]
            # Удаляем статистику объявлений для этого профиля
            db.conn.execute("""
                DELETE FROM ad_stats 
                WHERE ad_id IN (SELECT id FROM ads WHERE profile_id = ?)
            """, (profile_id,))
            # Удаляем объявления для этого профиля
            db.conn.execute("DELETE FROM ads WHERE profile_id = ?", (profile_id,))
            # Удаляем сам профиль
            db.conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            print(f"  ✅ Удален профиль: {client_id}")
    
    # Удаляем объявления, которых нет в конфиге
    ads_to_delete = db_ads - set(config_ads.keys())
    if ads_to_delete:
        print(f"🗑️ Удаление объявлений, отсутствующих в конфиге: {ads_to_delete}")
        for ad_id in ads_to_delete:
            # Удаляем статистику объявления
            db.conn.execute("DELETE FROM ad_stats WHERE ad_id = ?", (ad_id,))
            # Удаляем объявление
            db.conn.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
            print(f"  ✅ Удалено объявление: {ad_id}")
    
    db.conn.commit()
    
    # Добавляем/обновляем профили из конфига
    print("➕ Добавление/обновление профилей...")
    for client_id, profile_data in config_profiles.items():
        client_secret = profile_data['client_secret']
        name = profile_data['name']
        token = profile_data['token']
        token_created_at = "1970-01-01 00:00:00"
        
        try:
            if client_id in db_profiles:
                # Обновляем существующий профиль
                profile_id = db_profiles[client_id]
                db.conn.execute("""
                    UPDATE profiles 
                    SET client_secret = ?, name = ?, token = ?, token_created_at = ?
                    WHERE id = ?
                """, (client_secret, name, token, token_created_at, profile_id))
                print(f"  🔄 Обновлен профиль: {client_id}")
            else:
                # Создаем новый профиль
                try:
                    profile_id = db.insert_profile(client_id, client_secret, token, token_created_at, name)
                except TypeError:
                    # Fallback для старой версии метода
                    profile_id = db.insert_profile(client_id, client_secret, token)
                    # Обновляем name отдельно
                    db.conn.execute("UPDATE profiles SET name = ? WHERE id = ?", (name, profile_id))
                print(f"  ✅ Добавлен профиль: {client_id}")
                db_profiles[client_id] = profile_id
        except Exception as e:
            print(f"  ❌ Ошибка при обработке профиля {client_id}: {e}")
            continue
    
    db.conn.commit()
    
    # Добавляем/обновляем объявления из конфига
    print("➕ Добавление/обновление объявлений...")
    for ad_id, ad_data in config_ads.items():
        client_id = ad_data['client_id']
        
        if client_id not in db_profiles:
            print(f"  ⚠️ Пропуск объявления {ad_id}: профиль {client_id} не найден в БД")
            continue
            
        profile_id = db_profiles[client_id]
        
        try:
            if ad_id in db_ads:
                # Обновляем существующее объявление
                db.conn.execute("""
                    UPDATE ads 
                    SET category = ?, profile_id = ?, max_price = ?, 
                        target_place_start = ?, target_place_end = ?, 
                        comment = ?, url = ?, daily_budget = ?, active = ?
                    WHERE id = ?
                """, (
                    ad_data['category'], profile_id, ad_data['max_price'],
                    ad_data['target_place_start'], ad_data['target_place_end'],
                    ad_data['comment'], ad_data['ad_url'], ad_data.get('daily_budget'),
                    ad_data.get('active', True), ad_id
                ))
                print(f"  🔄 Обновлено объявление: {ad_id}")
            else:
                # Создаем новое объявление
                db.insert_ad(
                    ad_id, ad_data['category'], profile_id,
                    ad_data['max_price'], 
                    ad_data['target_place_start'], ad_data['target_place_end'], 
                    ad_data['comment'], ad_data['ad_url'], ad_data.get('daily_budget'),
                    ad_data.get('active', True)
                )
                print(f"  ✅ Добавлено объявление: {ad_id}")
        except Exception as e:
            print(f"  ❌ Ошибка при обработке объявления {ad_id}: {e}")
            continue
    
    db.conn.commit()
    
    # Финальная статистика
    final_profiles = db.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    final_ads = db.conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
    final_stats = db.conn.execute("SELECT COUNT(*) FROM ad_stats").fetchone()[0]
    
    print(f"\n📊 Итоговая статистика БД:")
    print(f"   Профилей: {final_profiles}")
    print(f"   Объявлений: {final_ads}")
    print(f"   Записей статистики: {final_stats}")
    
    db.close()
    
    # После инициализации обновляем токены
    try:
        from token_utils import refresh_tokens_for_all_profiles
        refresh_tokens_for_all_profiles(db_path)
        print("🔐 Токены обновлены")
    except ImportError:
        print("⚠️ Не удалось импортировать функцию обновления токенов из token_utils.py")
    
    print("✅ Инициализация базы данных завершена!")

# Пример вызова:
# init_db_from_config("config.json")
