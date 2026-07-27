import asyncio
import json
import os
import ssl
import time
import urllib.request
import uuid

from telethon import TelegramClient
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate

APP_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
STATUS_FILE = os.path.join(APP_DIR, "status.json")
INSTALL_CODE_FILE = os.path.join(APP_DIR, "install_code.txt")

RESULTS_URL_TEMPLATE = "https://{host}:8765/results.json?token={token}"
NOTIFY_URL_TEMPLATE = "https://{host}:8765/notify?token={token}"
BOT_USERNAME = "proxy_parserbot"

# the results endpoint uses a self-signed cert (private token-protected
# endpoint, not a public site) - skip verification instead of bundling a CA
_INSECURE_SSL_CONTEXT = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_INSECURE_SSL_CONTEXT.check_hostname = False
_INSECURE_SSL_CONTEXT.verify_mode = ssl.CERT_NONE
TOP_N_TO_TEST = 15
PER_CHECK_TIMEOUT = 8


def get_install_code():
    """Stable per-install identifier, generated once and reused - lets the
    server link this specific device to whichever Telegram chat opens the
    matching /start deep link."""
    if os.path.exists(INSTALL_CODE_FILE):
        with open(INSTALL_CODE_FILE, "r", encoding="utf-8") as f:
            code = f.read().strip()
        if code:
            return code
    code = uuid.uuid4().hex
    with open(INSTALL_CODE_FILE, "w", encoding="utf-8") as f:
        f.write(code)
    return code


def is_first_run():
    return not os.path.exists(INSTALL_CODE_FILE)


def open_url_on_device(url):
    """Open a URL/deep-link via an Android ACTION_VIEW intent. No-op (with a
    printed message) when not running on-device, e.g. local testing."""
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        activity = PythonActivity.mActivity
        intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
    except Exception as e:
        print(f"open_url_on_device unavailable (running off-device?): {e}")


def send_telegram_notify(cfg, text):
    """Ask the server to DM `text` to whichever Telegram chat this install is
    linked to. Silently skipped if not linked yet or the request fails -
    the Android notification is the guaranteed delivery path."""
    try:
        url = NOTIFY_URL_TEMPLATE.format(host=cfg["server_host"], token=cfg["http_token"])
        body = json.dumps({"install_code": get_install_code(), "text": text}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15, context=_INSECURE_SSL_CONTEXT)
    except Exception as e:
        print(f"send_telegram_notify failed: {e}")


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


def _save_status(working, error=None):
    data = {"checked_at": time.time(), "working": working, "error": error}
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def fetch_candidates(cfg):
    url = RESULTS_URL_TEMPLATE.format(host=cfg["server_host"], token=cfg["http_token"])
    req = urllib.request.Request(url, headers={"User-Agent": "tgproxy-android"})
    with urllib.request.urlopen(req, timeout=15, context=_INSECURE_SSL_CONTEXT) as resp:
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
    Returns the working candidate dict, or None. On failure, the error is
    saved to status.json (visible in the UI) instead of vanishing silently."""
    try:
        cfg = load_config()
        candidates = fetch_candidates(cfg)
        working = asyncio.run(_find_working(cfg, candidates))
    except Exception as e:
        import traceback
        err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _save_status(None, error=err_text)
        raise

    prev = _load_status().get("working")
    _save_status(working)

    is_new = working and (not prev or (prev["server"], prev["port"]) != (working["server"], working["port"]))
    if is_new:
        _notify_new_proxy(cfg, working)

    return working


def _notify_new_proxy(cfg, proxy):
    link = f"https://t.me/proxy?server={proxy['server']}&port={proxy['port']}&secret={proxy['secret']}"
    try:
        from plyer import notification
        notification.notify(
            title="Найден рабочий прокси",
            message=f"{proxy['server']}:{proxy['port']} — тапни, чтобы подключить в Telegram",
        )
    except Exception as e:
        print(f"notification failed (running off-device?): {e}")

    send_telegram_notify(
        cfg,
        f"✅ Найден рабочий прокси для твоего устройства:\n"
        f"{proxy['server']}:{proxy['port']} — пинг {proxy.get('latency_ms', '?')} мс\n\n{link}",
    )
    print(f"[tgproxy] new working proxy: {link}")
