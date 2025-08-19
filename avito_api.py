import requests
from typing import Optional, Tuple, Dict
from loguru import logger
import time

_account_id_cache: Dict[str, Tuple[str, float]] = {}
_ACCOUNT_ID_TTL = 3600 * 24  # 1 день

USER_INFO_ENDPOINTS = [
    "https://api.avito.ru/core/v1/accounts/self",  # предполагаемый основной
]

BALANCE_URL_TEMPLATE = "https://api.avito.ru/core/v1/accounts/{account_id}/balance"


def _extract_account_id(data: dict) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    # Прямые ключи
    for k in ["id", "account_id", "accountId", "user_id", "userId"]:
        v = data.get(k)
        if isinstance(v, (int, str)) and str(v).strip():
            return str(v)
    # Вложенные контейнеры
    for outer in ["result", "data", "account", "user"]:
        inner = data.get(outer)
        if isinstance(inner, dict):
            for k in ["id"]:
                v = inner.get(k)
                if isinstance(v, (int, str)) and str(v).strip():
                    return str(v)
    return None


def _get_account_id(token: str, timeout: float = 6) -> Optional[str]:
    now = time.time()
    cached = _account_id_cache.get(token)
    if cached and now - cached[1] < _ACCOUNT_ID_TTL:
        return cached[0]
    headers = {"Authorization": f"Bearer {token}"}
    for url in USER_INFO_ENDPOINTS:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                logger.debug(f"UserInfo {url} -> {resp.status_code}")
                continue
            data = resp.json() if resp.text else {}
            account_id = _extract_account_id(data)
            if account_id:
                _account_id_cache[token] = (account_id, now)
                logger.debug(f"UserInfo: найден account_id={account_id}")
                return account_id
            logger.debug(f"UserInfo: не удалось извлечь id из ответа {data}")
        except Exception as e:
            logger.debug(f"UserInfo ошибка {url}: {e}")
    return None


def get_account_balance(token: str, timeout: float = 6) -> Optional[float]:
    if not token:
        return None
    account_id = _get_account_id(token, timeout=timeout)
    if not account_id:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    url = BALANCE_URL_TEMPLATE.format(account_id=account_id)
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.debug(f"Баланс {url} -> {resp.status_code}")
            return None
        data = resp.json() if resp.text else {}

        return data['real'] / 100.0
    except Exception as e:
        logger.debug(f"Баланс ошибка: {e}")
        return None
