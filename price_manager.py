import requests
from loguru import logger
from avito_db import AvitoDB
import datetime

def get_bid_info(token: str, item_id: int):
    url = f"https://api.avito.ru/cpxpromo/1/getBids/{item_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Ошибка получения информации о ставках: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при получении информации о ставках: {e}")
        return None

def update_view_price(token: str, item_id: int, new_price: int, limit : int):
    url = "https://api.avito.ru/cpxpromo/1/setManual"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "actionTypeID": 5,
        "bidPenny": new_price,
        "itemID": item_id,
        "limitPenny": limit
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        # print(f"Status Code: {response.status_code}")
        # print(f"Response Text: {response.text}")
        
        if response.status_code == 200:
            print("✅ Цена успешно обновлена")
            db = AvitoDB()
            try:
                latest_stat = db.conn.execute(
                    "SELECT id FROM ad_stats WHERE ad_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (item_id,)
                ).fetchone()
                
                if latest_stat:
                    latest_stat_id = latest_stat[0]
                    db.conn.execute(
                        "UPDATE ad_stats SET price = ? WHERE id = ?",
                        (new_price, latest_stat_id)
                    )
                    db.conn.commit()
                    print(f"✅ Цена в базе данных для объявления {item_id} обновлена на {new_price}")
                else:
                    print(f"⚠️ Не найдено записей статистики для объявления {item_id} для обновления цены.")
            except Exception as e:
                print(f"❌ Ошибка при обновлении цены в базе данных: {e}")
            finally:
                db.close()
            try:
                return response.json() if response.text.strip() else {"success": True}
            except:
                return {"success": True}
        else:
            print(f"❌ Ошибка API: {response.status_code}")
            try:
                error_data = response.json()
                print(f"Сообщение об ошибке: {error_data.get('message', 'Неизвестная ошибка')}")
            except:
                print(f"Не удалось распарсить ответ: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при обновлении цены просмотра: {e}")
        return None

def check_and_update_prices():
    try:
        from token_utils import refresh_tokens_for_all_profiles
        try:
            refresh_tokens_for_all_profiles()
        except Exception as e:
            logger.warning(f"Не удалось обновить токены перед корректировкой цен: {e}")
    except ImportError:
        logger.warning("token_utils.refresh_tokens_for_all_profiles не найден – пропускаем обновление токенов")

    db = AvitoDB()
    try:
        profiles = db.conn.execute("SELECT id, token FROM profiles").fetchall()
        for profile in profiles:
            profile_id, token = profile
            ads = db.conn.execute(
                "SELECT id, max_price, target_place_start, target_place_end, comment, url, daily_budget FROM ads WHERE profile_id = ? AND active = TRUE",
                (profile_id,)
            ).fetchall()

            for ad in ads:
                ad_id, max_price, target_place_start, target_place_end, comment, url, daily_budget = ad
                try:
                    # Проверка дневного бюджета
                    if daily_budget is not None and daily_budget > 0:
                        today = datetime.date.today()
                        start_of_day = datetime.datetime.combine(today, datetime.time.min)
                        
                        spent_today_result = db.conn.execute(
                            "SELECT SUM(price) FROM ad_stats WHERE ad_id = ? AND timestamp >= ?",
                            (ad_id, start_of_day)
                        ).fetchone()
                        
                        spent_today = spent_today_result[0] if spent_today_result and spent_today_result[0] is not None else 0
                        
                        if spent_today >= daily_budget:
                            logger.info(f"Дневной бюджет для объявления {ad_id} ({daily_budget}) исчерпан. Потрачено: {spent_today}. Пропуск.")
                            continue
                            
                    last_stat = db.conn.execute(
                        "SELECT position, price FROM ad_stats WHERE ad_id = ? ORDER BY timestamp DESC LIMIT 1",
                        (ad_id,)
                    ).fetchone()
                    if not last_stat:
                        logger.debug(f"Нет статистики для объявления {ad_id}")
                        continue
                    current_place, last_price = last_stat
                    if current_place is None:
                        logger.debug(f"Позиция None для объявления {ad_id}")
                        continue
                    logger.debug(f"Ad {ad_id}: pos={current_place} target={target_place_start}-{target_place_end} last_price={last_price}")

                    new_price = None  # гарантируем наличие переменной
                    bid_info = get_bid_info(token, ad_id)
                    if not bid_info:
                        logger.debug(f"Нет bid_info для {ad_id}")
                        continue
                    min_bid = bid_info.get('manual', {}).get('minBidPenny')
                    min_limit = bid_info.get('manual', {}).get('minLimitPenny')
                    if min_bid is None:
                        min_bid = 0
                    if not (target_place_start <= current_place <= target_place_end):
                        if current_place > target_place_end:
                            base = int(last_price) if last_price else min_bid
                            new_price = max(base + 50, min_bid)
                        else:
                            base = int(last_price) if last_price else min_bid
                            dec = base - 50
                            new_price = max(dec, min_bid)
                    else:
                        if last_price:
                            new_price = int(last_price)
                        else:
                            new_price = max(min_bid, 0)
                        mid_point = (target_place_start + target_place_end) / 2
                        if current_place <= mid_point:  # слишком высоко внутри зоны
                            base = int(last_price) if last_price else min_bid
                            new_price = max(base - 50, min_bid)

                    # Финальные ограничения
                    if new_price is None:
                        logger.warning(f"new_price не вычислен для объявления {ad_id} – пропуск")
                        continue
                    if max_price:
                        try:
                            max_p = int(max_price)
                            if new_price > max_p:
                                logger.debug(f"{ad_id}: ограничено max_price {max_p}")
                                new_price = max_p
                        except Exception as e:
                            logger.warning(f"Не удалось привести max_price к int для {ad_id}: {e}")

                    logger.info(f"Объявление {ad_id}: позиция {current_place} -> новая цена {new_price} (старая {last_price})")

                    # Если цена не изменилась – не дергаем API
                    if last_price is not None and int(last_price) == new_price:
                        logger.debug(f"{ad_id}: цена без изменений ({new_price}) – пропуск обновления")
                        continue
                    if new_price < min_bid:
                        new_price = min_bid + 50
                    result = update_view_price(token, int(ad_id), int(new_price), int(max(int(min_limit + 50), int(daily_budget))))
                    if result is None:
                        logger.warning(f"{ad_id}: не удалось обновить цену")
                except Exception as ad_err:
                    logger.exception(f"Ошибка при обработке объявления {ad_id}: {ad_err}")
    finally:
        db.close()

# Пример вызова:
# check_and_update_prices()
# update_view_price('MlMkzCtnSI2aN9wkAaWEgAUnGB3_RgaewSJC6E0Y', 7579176863, 960)