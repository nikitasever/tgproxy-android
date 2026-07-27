import asyncio
import json
import os
import time
import urllib.request

from telethon import TelegramClient
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate

APP_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
STATUS_FILE = os.path.join(APP_DIR, "status.json")

RESULTS_URL_TEMPLATE = "http://{host}:8765/results.json?token={token}"
TOP_N_TO_TEST = 15
PER_CHECK_TIMEOUT = 8


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_status():
    if not os.path.exists(STATUS_FILE):
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_status(working):
    data = {"checked_at": time.time(), "working": working}
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def fetch_candidates(cfg):
    url = RESULTS_URL_TEMPLATE.format(host=cfg["server_host"], token=cfg["http_token"])
    req = urllib.request.Request(url, headers={"User-Agent": "tgproxy-android"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["proxies"][:TOP_N_TO_TEST]


async def _check_one(api_id, api_hash, candidate):
    server, port, secret = candidate["server"], candidate["port"], candidate["secret"]
    client = TelegramClient(
        None, api_id, api_hash,
        connection=ConnectionTcpMTProxyRandomizedIntermediate,
        proxy=(server, port, secret),
        connection_retries=0,
        timeout=PER_CHECK_TIMEOUT,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=PER_CHECK_TIMEOUT)
        ok = client.is_connected()
    except Exception:
        ok = False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return ok


async def _find_working(cfg, candidates):
    for c in candidates:
        ok = await _check_one(cfg["api_id"], cfg["api_hash"], c)
        if ok:
            return c
    return None


def run_check_cycle():
    """Fetch candidates, test them over whatever network is currently active
    on this device, and persist the first working one to status.json.
    Returns the working candidate dict, or None."""
    cfg = load_config()
    candidates = fetch_candidates(cfg)
    working = asyncio.run(_find_working(cfg, candidates))

    prev = _load_status().get("working")
    _save_status(working)

    is_new = working and (not prev or (prev["server"], prev["port"]) != (working["server"], working["port"]))
    if is_new:
        _notify_new_proxy(working)

    return working


def _notify_new_proxy(proxy):
    link = f"https://t.me/proxy?server={proxy['server']}&port={proxy['port']}&secret={proxy['secret']}"
    try:
        from plyer import notification
        notification.notify(
            title="Найден рабочий прокси",
            message=f"{proxy['server']}:{proxy['port']} — тапни, чтобы подключить в Telegram",
        )
    except Exception as e:
        print(f"notification failed (running off-device?): {e}")
    print(f"[tgproxy] new working proxy: {link}")
