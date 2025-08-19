import asyncio
import html
import json
import random
import time
import urllib3
from urllib.parse import unquote, urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
from curl_cffi import requests
from curl_cffi.requests import RequestsError
from loguru import logger
from pydantic import ValidationError
from requests.cookies import RequestsCookieJar
from common_data import HEADERS
from dto import Proxy, AvitoConfig
from get_cookies import get_cookies
from load_config import load_avito_config
from models import ItemsResponse, Item
from avito_db import AvitoDB
from price_manager import check_and_update_prices, get_bid_info
from init_ads import init_db_from_config
# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEBUG_MODE = False

logger.add("logs/app.log", rotation="5 MB", retention="10 days", level="DEBUG")


class AvitoParse:
    def __init__(
            self,
            config: AvitoConfig,
            stop_event=None
    ):
        # Базовая конфигурация
        self.config = config
        self.stop_event = stop_event

        # Прокси
        self.mobile_proxies = self._load_mobile_proxies()
        self.current_proxy_index = 0
        self.proxy_obj = self.get_current_proxy_obj()

        # HTTP / сессия / cookies
        self.cookies = None
        self.session = requests.Session()

        # Счетчики и состояния
        self.requests_count = 0
        self.max_requests_per_ip = getattr(config, 'proxy_max_requests_per_rotation', 20)
        self.failed_requests_count = 0  # Счетчик неудачных запросов подряд
        self.proxy_requests_count = 0  # Счетчик запросов для текущего прокси
        self.last_ip_change = 0  # метка времени последней смены IP

        # Работа с БД
        self.db = AvitoDB()

    def _load_mobile_proxies(self) -> list:
        """Загружает активные мобильные прокси из конфига"""
        if hasattr(self.config, 'mobile_proxies') and self.config.mobile_proxies:
            active_proxies = [proxy for proxy in self.config.mobile_proxies if proxy.active]
            if active_proxies:
                logger.info(f"Загружено {len(active_proxies)} активных мобильных прокси")
                return active_proxies

        # Fallback к старой конфигурации
        if all([self.config.proxy_string, self.config.proxy_change_url]):
            from dto import MobileProxy
            fallback_proxy = MobileProxy(
                proxy_string=self.config.proxy_string,
                proxy_change_url=self.config.proxy_change_url,
                name="Legacy Proxy",
                active=True
            )
            logger.info("Используется legacy прокси конфигурация")
            return [fallback_proxy]

        logger.warning("Мобильные прокси не настроены")
        return []

    def get_current_proxy_obj(self) -> Proxy | None:
        """Возвращает объект текущего прокси"""
        if not self.mobile_proxies:
            logger.info("Работаем без прокси")
            return None
        current_proxy = self.mobile_proxies[self.current_proxy_index]
        return Proxy(
            proxy_string=current_proxy.proxy_string,
            change_ip_link=current_proxy.proxy_change_url
        )

    def rotate_proxy(self) -> bool:
        """Переключается на следующий прокси в списке"""
        if len(self.mobile_proxies) <= 1:
            return False
        old_index = self.current_proxy_index
        rotation_mode = getattr(self.config, 'proxy_rotation_mode', 'round_robin')
        if rotation_mode == 'random':
            available_indices = [i for i in range(len(self.mobile_proxies)) if i != self.current_proxy_index]
            if available_indices:
                self.current_proxy_index = random.choice(available_indices)
        else:
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.mobile_proxies)
        self.proxy_obj = self.get_current_proxy_obj()
        self.proxy_requests_count = 0
        current_proxy = self.mobile_proxies[self.current_proxy_index]
        logger.info(f"🔄 Переключились с прокси #{old_index} на прокси #{self.current_proxy_index} ({current_proxy.name})")
        return True

    def get_proxy_obj(self) -> Proxy | None:
        return self.get_current_proxy_obj()

    def get_cookies(self, max_retries: int = 5, delay: float = 2.0) -> dict | None:
        for attempt in range(1, max_retries + 1):
            try:
                cookies = asyncio.run(get_cookies(proxy=self.proxy_obj, headless=True))
                if cookies and isinstance(cookies, dict) and len(cookies) > 0:
                    logger.info(f"[get_cookies] Успешно получены cookies с попытки {attempt}")
                    return cookies
                else:
                    raise ValueError("Пустой результат cookies или неверный формат")
            except Exception as e:
                logger.warning(f"[get_cookies] Попытка {attempt} не удалась: {e}")
                if attempt < max_retries:
                    logger.info(f"[get_cookies] Ожидание {delay * attempt} секунд перед следующей попыткой...")
                    time.sleep(delay * attempt)
                else:
                    logger.error(f"[get_cookies] Все {max_retries} попытки не удались")
                    return None

    def save_cookies(self) -> None:
        with open("cookies.json", "w") as f:
            json.dump(self.session.cookies.get_dict(), f)

    def load_cookies(self) -> None:
        try:
            with open("cookies.json", "r") as f:
                cookies = json.load(f)
                jar = RequestsCookieJar()
                for k, v in cookies.items():
                    jar.set(k, v)
                self.session.cookies.update(jar)
        except FileNotFoundError:
            pass

    def fetch_data(self, url: str, retries: int = 5, backoff_factor: float = 1) -> str | None:
        proxy_data = None
        if self.proxy_obj:
            proxy_data = {"https": f"http://{self.proxy_obj.proxy_string}"}
        base_jitter = random.uniform(0.15, 0.4)
        time.sleep(base_jitter)
        for attempt in range(1, retries + 1):
            if self.stop_event and self.stop_event.is_set():
                return
            try:
                response = self.session.get(
                    url=url,
                    headers=HEADERS,
                    proxies=proxy_data,
                    cookies=self.cookies,
                    timeout=30,
                    verify=False,
                    allow_redirects=True
                )
                logger.debug(f"Попытка {attempt}: {response.status_code}")
                if response.status_code == 200:
                    self.failed_requests_count = 0
                    self.save_cookies()
                    time.sleep(random.uniform(0.25, 0.8))
                    return response.text
                if response.status_code >= 500:
                    logger.warning(f"Ошибка сервера {response.status_code}")
                    raise RequestsError(f"Ошибка сервера: {response.status_code}")
                if response.status_code == 429:
                    logger.warning(f"Rate limit {response.status_code}")
                    self.failed_requests_count += 1
                    if time.time() - self.last_ip_change > 15:
                        if self.change_ip(max_attempts=2):
                            self.last_ip_change = time.time()
                            continue
                    raise RequestsError(f"Слишком много запросов: {response.status_code}")
                if response.status_code in [403, 302, 401, 422]:
                    logger.warning(f"Блокировка {response.status_code}")
                    self.failed_requests_count += 1
                    time.sleep(random.uniform(2.0, 5.0))
                    if time.time() - self.last_ip_change > 15:
                        if self.change_ip(max_attempts=2):
                            self.last_ip_change = time.time()
                            continue
                    raise RequestsError(f"Заблокирован: {response.status_code}")
                logger.warning(f"⚠️ Неожиданный статус {response.status_code}")
                self.failed_requests_count += 1
                raise RequestsError(f"Неожиданный статус: {response.status_code}")
            except (RequestsError, Exception) as e:
                error_msg = str(e)
                mult = 3 if any(k in error_msg.upper() for k in ["SSL", "TIMEOUT", "CONNECTION"]) else 1
                sleep_time = backoff_factor * attempt * mult + random.uniform(0.1, 0.6)
                if self.failed_requests_count >= 2 and time.time() - self.last_ip_change > 15:
                    if self.change_ip(max_attempts=2):
                        self.last_ip_change = time.time()
                        continue
                if attempt < retries:
                    time.sleep(min(sleep_time, 15))
                else:
                    return None

    def parse(self):
        self.load_cookies()
        profiles = self.db.conn.execute("SELECT id, client_id, client_secret, token FROM profiles").fetchall()
        throttle_factor = 1.0
        for profile in profiles:
            profile_id, client_id, client_secret, token = profile
            ads = self.db.conn.execute("SELECT id, category, max_price, target_place_start, target_place_end, comment, url FROM ads WHERE profile_id = ? AND active = TRUE", (profile_id,)).fetchall()
            ads = list(ads)
            random.shuffle(ads)
            for ad in ads:
                ad_id, category, max_price, target_place_start, target_place_end, comment, url = ad
                last_stat = self.db.conn.execute(
                    "SELECT price FROM ad_stats WHERE ad_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (ad_id,)
                ).fetchone()
                if last_stat and last_stat[0] is not None:
                    price_of_view = int(last_stat[0])
                else:
                    bid_info = get_bid_info(token, ad_id)
                    if bid_info and bid_info.get('manual', {}).get('minBidPenny') is not None:
                        price_of_view = bid_info.get('manual', {}).get('minBidPenny')
                    else:
                        price_of_view = 0
                target_id = ad_id
                for pages in range(1, 3):
                    if self.stop_event and self.stop_event.is_set():
                        return
                    time.sleep(random.uniform(1.2, 2.8) * throttle_factor)
                    html_code = self.fetch_data(url=category, retries=self.config.max_count_of_retry)
                    if not html_code:
                        throttle_factor = min(throttle_factor * 1.3, 5.0)
                        break
                    throttle_factor = max(throttle_factor * 0.95, 0.7)
                    data_from_page = self.find_json_on_page(html_code=html_code)
                    try:
                        ads_models = ItemsResponse(**data_from_page.get("catalog", {}))
                    except ValidationError as err:
                        logger.error(f"Ошибка валидации: {err}")
                        break
                    ads_list = self._clean_null_ads(ads=ads_models.items)
                    current_index = self.find_place_of_target_ad(target_id, ads_list)
                    print("id: ", target_id)
                    print("Current index: ", current_index)
                    
                    if current_index != 0:
                        self.db.insert_ad_stat(ad_id, price_of_view, current_index)
                        break
                    if pages == 2:
                        self.db.insert_ad_stat(ad_id, price_of_view, 100)
                        break
                    url = self.get_next_page_url(url=url)

    @staticmethod
    def _clean_null_ads(ads: list[Item]) -> list[Item]:
        return [ad for ad in ads if ad.id]

    @staticmethod
    def find_place_of_target_ad(target_id, ads):
        for i, ad in enumerate(ads):
            if str(ad.id) == str(target_id):
                return i + 1
        return 0

    @staticmethod
    def extarct_ad_id(s):
        return s[:s.index('?')].split('_')[-1] if '?' in s else s.split('_')[-1]

    @staticmethod
    def find_json_on_page(html_code, data_type: str = "mime") -> dict:
        soup = BeautifulSoup(html_code, "html.parser")
        try:
            for _script in soup.select('script'):
                if data_type == 'mime':
                    if _script.get('type') == 'mime/invalid' and _script.get('data-mfe-state') == 'true':
                        mime_data = json.loads(html.unescape(_script.text)).get('data', {})
                        return mime_data
        except Exception as err:
            logger.error(f"Ошибка при поиске информации на странице: {err}")
        return {}

    def change_ip(self, max_attempts: int = 3) -> bool:
        if not self.mobile_proxies:
            logger.warning("⚠️ Смена IP невозможна - мобильные прокси не настроены")
            return False
        current_proxy = self.mobile_proxies[self.current_proxy_index]
        logger.info(f"🔄 Начинаю агрессивную смену IP для прокси {current_proxy.name}...")
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Попытка смены IP {attempt}/{max_attempts} на прокси {current_proxy.name}")
                res = requests.get(
                    url=current_proxy.proxy_change_url,
                    timeout=20,
                    verify=False
                )
                if res.status_code == 200:
                    self.requests_count = 0
                    self.failed_requests_count = 0
                    self.proxy_requests_count = 0
                    wait_time = random.randint(1, 5)
                    logger.info(f"✅ IP успешно изменен на прокси {current_proxy.name}! Пауза {wait_time} сек для стабилизации")
                    time.sleep(wait_time)
                    logger.info("🍪 Обновляю cookies с новым IP...")
                    self.cookies = self.get_cookies(max_retries=2)
                    return True
                else:
                    logger.warning(f"Ошибка смены IP на прокси {current_proxy.name}: статус {res.status_code}")
            except Exception as err:
                logger.error(f"Ошибка при смене IP на прокси {current_proxy.name} (попытка {attempt}): {err}")
            if attempt < max_attempts:
                wait_time = random.randint(1, 2) * attempt
                logger.info(f"Повтор смены IP через {wait_time} секунд...")
                time.sleep(wait_time)
        logger.warning("Смена IP на текущем прокси не удалась, пробуем ротацию прокси...")
        if len(self.mobile_proxies) > 1 and getattr(self.config, 'proxy_switch_on_error', True):
            if self.rotate_proxy():
                logger.info("🔄 Прокси переключен, пробуем смену IP на новом прокси...")
                new_proxy = self.mobile_proxies[self.current_proxy_index]
                try:
                    res = requests.get(
                        url=new_proxy.proxy_change_url,
                        timeout=20,
                        verify=False
                    )
                    if res.status_code == 200:
                        self.requests_count = 0
                        self.failed_requests_count = 0
                        self.proxy_requests_count = 0
                        wait_time = random.randint(1, 5)
                        logger.info(f"✅ IP успешно изменен на новом прокси {new_proxy.name}! Пауза {wait_time} сек")
                        time.sleep(wait_time)
                        self.cookies = self.get_cookies(max_retries=2)
                        return True
                except Exception as err:
                    logger.error(f"Ошибка смены IP на новом прокси {new_proxy.name}: {err}")
        logger.error("Все попытки смены IP и ротации прокси неуспешны!")
        logger.info("Принудительное обновление cookies...")
        self.cookies = self.get_cookies(max_retries=1)
        return False

    @staticmethod
    def get_next_page_url(url: str):
        try:
            url_parts = urlparse(url)
            query_params = parse_qs(url_parts.query)
            current_page = int(query_params.get('p', [1])[0])
            query_params['p'] = current_page + 1
            new_query = urlencode(query_params, doseq=True)
            next_url = urlunparse((url_parts.scheme, url_parts.netloc, url_parts.path, url_parts.params, new_query, url_parts.fragment))
            return next_url
        except Exception as err:
            logger.error(f"Не смог сформировать ссылку на следующую страницу для {url}. Ошибка: {err}")

import requests  # уже используется curl_cffi.requests выше; этот импорт может быть лишним для стандартного requests, оставлен если где-то нужен



if __name__ == "__main__":
    print("Запуск инициализации бд")
    init_db_from_config()
    print("Успешно инициализирована")
    
    while True:
        try:
            config = load_avito_config("config.json")
            parser = AvitoParse(config)
            parser.parse()
            
            # Нормализуем паузу (защита от отрицательных/None значений, вызывающих OSError: [Errno 22] Invalid argument)
            raw_pause = getattr(config, 'pause_general', 60)
            try:
                pause_val = int(raw_pause)
            except Exception:
                pause_val = 60
            if pause_val < 0:
                logger.warning(f"Получено отрицательное значение pause_general={raw_pause}. Принудительно устанавливаем 30 сек")
                pause_val = 30

            logger.info(f"Парсинг завершен. Пауза {pause_val} сек")
            print("Updating prices")
            check_and_update_prices()
            
            try:
                time.sleep(pause_val)
            except OSError as e:
                logger.error(f"Ошибка сна (pause={pause_val}): {e}. Используем запасную паузу 30 сек")
                time.sleep(30)
            
        except Exception as err:
            # Полный traceback для диагностики
            logger.exception(f"Произошла ошибка в основном цикле: {err}")
            error_msg = str(err)
            try:
                if config and hasattr(config, 'proxy_change_url') and config.proxy_change_url:
                    logger.warning("Экстренная смена IP из-за ошибки")
                    emergency_parser = AvitoParse(config)
                    emergency_parser.change_ip(max_attempts=3)
            except:
                pass
            
            # Для SSL ошибок делаем более длительную паузу
            if any(keyword in error_msg for keyword in ["SSL", "UNEXPECTED_EOF", "Max retries exceeded", "Connection"]):
                logger.warning("🌐 Обнаружена проблема с соединением, увеличиваем паузу до 90 секунд")
                time.sleep(60)
            else:
                time.sleep(30)
