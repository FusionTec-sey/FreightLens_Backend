"""Diagnostics for the Maersk login: prints WHY it worked or failed.

Both lines are written to the container log, e.g.
  [Maersk] login OK   | egress_ip=1.2.3.4 | proxy=none
  [Maersk] login FAILED HTTP 403 | egress_ip=1.2.3.4 | proxy=none | server=AkamaiGHost | body=...
Compare the egress_ip / proxy between the working and the failing deployment.
"""
import os
import platform
import ssl
from urllib.parse import urlparse

import requests
import urllib3

_egress_cache = {}


def _egress_ip(proxies):
    """Public IP the server uses to reach the internet (looked up once per process)."""
    key = str(sorted((proxies or {}).items()))
    if key not in _egress_cache:
        try:
            _egress_cache[key] = requests.get(
                "https://api.ipify.org", proxies=proxies or {}, timeout=5
            ).text.strip()
        except Exception as err:
            _egress_cache[key] = f"unknown ({type(err).__name__})"
    return _egress_cache[key]


def _proxy_summary(proxies):
    """Proxies in effect, without credentials. requests also honours HTTP(S)_PROXY from the environment."""
    found = []
    for name in ("TRACKING_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        value = (proxies or {}).get("https") if name == "TRACKING_PROXY" else os.getenv(name)
        if value:
            host = urlparse(value).hostname or "set"
            found.append(f"{name}={host}")
    return ",".join(found) or "none"


def log_login_result(response, proxies=None):
    ip = _egress_ip(proxies)
    proxy = _proxy_summary(proxies)
    if response.status_code == 200:
        print(f"[Maersk] login OK | egress_ip={ip} | proxy={proxy}")
        return

    server = response.headers.get("Server", "-")
    extra = {k: v for k, v in response.headers.items() if k.lower().startswith(("x-", "akamai", "reference"))}
    body = (response.text or "").strip().replace("\n", " ")[:300]
    hint = ""
    if response.status_code == 403:
        hint = " | meaning=Maersk refused this server (its outbound IP / network), the credentials were not judged"
    elif response.status_code in (400, 401):
        hint = " | meaning=Maersk rejected the client id / secret"
    print(
        f"[Maersk] login FAILED HTTP {response.status_code} | egress_ip={ip} | proxy={proxy} | server={server}"
        f"{hint} | headers={extra} | body={body}"
    )
    print(
        f"[Maersk] runtime | python={platform.python_version()} requests={requests.__version__} "
        f"urllib3={urllib3.__version__} openssl={ssl.OPENSSL_VERSION}"
    )
