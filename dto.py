from ctypes import Union
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Union


@dataclass
class Proxy:
    proxy_string: str
    change_ip_link: str


@dataclass
class ProxySplit:
    ip_port: str
    login: str
    password: str
    change_ip_link: str


@dataclass
class MobileProxy:
    proxy_string: str
    proxy_change_url: str
    name: str = "Mobile Proxy"
    active: bool = True


@dataclass
class AvitoConfig:
    profiles: List[
        Dict[
            str, Union[str, List[Dict[str, str]]]
            ]
        ]
    proxy_string: Optional[str] = None
    proxy_change_url: Optional[str] = None
    mobile_proxies: List[MobileProxy] = field(default_factory=list)
    count: int = 1
    geo: Optional[str] = None
    pause_general: int = 60
    pause_between_links: int = 5
    max_count_of_retry: int = 5
    proxy_rotation_enabled: bool = True
    proxy_rotation_mode: str = "round_robin"  # round_robin, random, smart
    proxy_max_requests_per_rotation: int = 20
    proxy_switch_on_error: bool = True
