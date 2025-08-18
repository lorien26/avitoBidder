import tomllib
from pathlib import Path

import tomli_w
import json
from dto import AvitoConfig, MobileProxy


def load_avito_config(path: str = "config.json") -> AvitoConfig:
    with open(path, 'r', encoding='utf-8') as file:
        data = json.load(file)
    
    # Обработка мобильных прокси
    mobile_proxies = []
    if 'mobile_proxies' in data:
        for proxy_data in data['mobile_proxies']:
            mobile_proxies.append(MobileProxy(**proxy_data))
        data['mobile_proxies'] = mobile_proxies
    
    return AvitoConfig(**data)


def save_avito_config(config: dict):
    with Path("config.toml").open("wb") as f:
        tomli_w.dump(config, f)
# print(load_avito_config())