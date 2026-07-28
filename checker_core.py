import asyncio
import json
import os
import re
import ssl
import threading
import time
import urllib.request
import uuid

from telethon import TelegramClient
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate

APP_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
VERSION_FILE = os.path.join(APP_DIR, "version.json")
STATUS_FILE = os.path.join(APP_DIR, "status.json")
INSTALL_CODE_FILE = os.path.join(APP_DIR, "install_code.txt")
CANDIDATES_CACHE_FILE = os.path.join(APP_DIR, "cached_candidates.json")
LIVE_LOG_FILE = os.path.join(APP_DIR, "live_log.json")
LIVE_LOG_MAX_LINES = 60

RESULTS_URL_TEMPLATE = "https://{host}:8765/results.json?token={token}"
NOTIFY_URL_TEMPLATE = "https://{host}:8765/notify?token={token}"
BOT_USERNAME = "proxy_parserbot"
GITHUB_REPO = "nikitasever/tgproxy-android"
UPDATE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# the results endpoint uses a self-signed cert (private token-protected
# endpoint, not a public site) - skip verification instead of bundling a CA
_INSECURE_SSL_CONTEXT = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_INSECURE_SSL_CONTEXT.check_hostname = False
_INSECURE_SSL_CONTEXT.verify_mode = ssl.CERT_NONE
TOP_N_TO_TEST = 500
PER_CHECK_TIMEOUT = 15
# DNS + TCP connect over a real mobile network (cellular/VPN) is much
# slower and less consistent than on a desktop LAN - a short timeout here
# was reading as "0 alive" on-device even though the same candidates were
# genuinely reachable, just not within 3s
TCP_PREFILTER_TIMEOUT = 6
MTPROTO_CHECK_LIMIT = 30


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


def request_runtime_permissions():
    """Ask for the dangerous/runtime permissions the app actually needs
    (notifications on Android 13+ won't show without an explicit grant -
    the manifest entry alone isn't enough).

    Only requests the ones not already granted - calling
    request_permissions() unconditionally on every launch was re-prompting
    the user for notification access each time they opened the app, even
    after they'd already granted it."""
    try:
        from android.permissions import request_permissions, check_permission, Permission
        perms = [Permission.INTERNET, Permission.FOREGROUND_SERVICE, Permission.WAKE_LOCK]
        if hasattr(Permission, "POST_NOTIFICATIONS"):
            perms.append(Permission.POST_NOTIFICATIONS)
        missing = [p for p in perms if not check_permission(p)]
        if missing:
            request_permissions(missing)
    except Exception as e:
        print(f"request_runtime_permissions unavailable (running off-device?): {e}")


def request_ignore_battery_optimizations():
    """Prompt the user to exempt the app from battery optimization, so
    Android doesn't kill the background 30-minute check service to save
    power. Shows a normal system permission dialog; no-ops if already
    exempted or not running on-device."""
    try:
        from jnius import autoclass
        Context = autoclass("android.content.Context")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        power_manager = activity.getSystemService(Context.POWER_SERVICE)
        package_name = activity.getPackageName()
        if not power_manager.isIgnoringBatteryOptimizations(package_name):
            intent = Intent()
            intent.setAction("android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS")
            intent.setData(Uri.parse(f"package:{package_name}"))
            activity.startActivity(intent)
    except Exception as e:
        print(f"request_ignore_battery_optimizations unavailable (running off-device?): {e}")


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


def bot_start_uri(install_code):
    # tg:// is handled only by the Telegram app itself (never a browser) and
    # doesn't need to resolve t.me over the network, so it isn't affected by
    # a down/blocked VPN the way an https://t.me/... link would be
    return f"tg://resolve?domain={BOT_USERNAME}&start={install_code}"


def proxy_tg_uri(proxy):
    return f"tg://proxy?server={proxy['server']}&port={proxy['port']}&secret={proxy['secret']}"


_log_lock = threading.Lock()


def _log_reset():
    with open(LIVE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump({"checking": True, "lines": []}, f)


def _log(line):
    """Blocking disk I/O - never call this directly from inside a coroutine
    that's running on the same event loop as the proxy checks (see
    _log_async). A synchronous file write there stalls the whole loop for
    its duration, which was silently making in-flight MTProto handshakes
    miss their real responses and get misreported as timeouts."""
    with _log_lock:
        try:
            with open(LIVE_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"checking": True, "lines": []}
        data["lines"] = (data.get("lines") or [])[-(LIVE_LOG_MAX_LINES - 1):] + [line]
        with open(LIVE_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)


async def _log_async(line):
    await asyncio.to_thread(_log, line)


def _log_finish():
    try:
        with open(LIVE_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"lines": []}
    data["checking"] = False
    with open(LIVE_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_live_log():
    if not os.path.exists(LIVE_LOG_FILE):
        return {"checking": False, "lines": []}
    try:
        with open(LIVE_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"checking": False, "lines": []}


def get_local_build_number():
    if not os.path.exists(VERSION_FILE):
        return 0
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("build_number", 0))
    except Exception:
        return 0


def check_for_update():
    """Look up the latest published GitHub Release and compare its build
    number (baked into the release name at CI time) against this install's
    own version.json. Returns (remote_build_number, apk_download_url, error)
    - error is None on success, otherwise a short string explaining why the
    check failed (surfaced in the UI instead of silently vanishing, since
    api.github.com being unreachable without a VPN is a real possibility
    on this network)."""
    try:
        # Android's Python build has no system CA bundle wired into the ssl
        # module, so plain urlopen() cert verification fails even for a
        # perfectly valid host like api.github.com - use certifi's bundle
        # explicitly instead of turning verification off.
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        req = urllib.request.Request(UPDATE_API_URL, headers={"User-Agent": "tgproxycheck-app"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        m = re.search(r"build #(\d+)", data.get("name", ""))
        remote_build = int(m.group(1)) if m else None
        apk_url = next(
            (a["browser_download_url"] for a in data.get("assets", []) if a["name"].endswith(".apk")),
            None,
        )
        if remote_build is None or apk_url is None:
            return None, None, "не распознан формат релиза"
        return remote_build, apk_url, None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"check_for_update failed: {err}")
        return None, None, err


def download_update(url):
    """Hand the APK URL to Android's own DownloadManager - it downloads
    directly (no browser tab involved). Returns (download_id, error); the
    caller polls get_download_progress() and calls open_downloaded_apk()
    itself once done, rather than relying on the user noticing (and being
    allowed to see) DownloadManager's own completed-download notification,
    which some vendor Android skins suppress silently."""
    try:
        from jnius import autoclass
        Context = autoclass("android.content.Context")
        Uri = autoclass("android.net.Uri")
        Environment = autoclass("android.os.Environment")
        DownloadManager = autoclass("android.app.DownloadManager")
        Request = autoclass("android.app.DownloadManager$Request")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity

        request = Request(Uri.parse(url))
        request.setTitle("TG Proxy Checker - обновление")
        request.setDescription("Загрузка новой версии")
        request.setNotificationVisibility(Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
        request.setMimeType("application/vnd.android.package-archive")
        request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "tgproxycheck-update.apk")
        # downloads over metered/mobile data are already allowed by default;
        # setAllowedOverMeteredNetworks() itself isn't resolvable via jnius
        # reflection on some devices (AttributeError), so don't call it

        dm = activity.getSystemService(Context.DOWNLOAD_SERVICE)
        download_id = dm.enqueue(request)
        return download_id, None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print(f"download_update failed: {err}")
        return None, err


def get_download_progress(download_id):
    """Poll DownloadManager for a download started by download_update().
    Returns (status, downloaded_bytes, total_bytes, error) where status is
    one of 'pending'/'running'/'paused'/'successful'/'failed'/'unknown'."""
    try:
        from jnius import autoclass
        Context = autoclass("android.content.Context")
        DownloadManager = autoclass("android.app.DownloadManager")
        Query = autoclass("android.app.DownloadManager$Query")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        dm = activity.getSystemService(Context.DOWNLOAD_SERVICE)

        query = Query()
        query.setFilterById([download_id])
        cursor = dm.query(query)
        try:
            if not cursor.moveToFirst():
                return "unknown", 0, 0, None
            status = cursor.getInt(cursor.getColumnIndex(DownloadManager.COLUMN_STATUS))
            downloaded = cursor.getLong(cursor.getColumnIndex(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
            total = cursor.getLong(cursor.getColumnIndex(DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
            reason = cursor.getInt(cursor.getColumnIndex(DownloadManager.COLUMN_REASON))
        finally:
            cursor.close()

        status_map = {
            DownloadManager.STATUS_PENDING: "pending",
            DownloadManager.STATUS_RUNNING: "running",
            DownloadManager.STATUS_PAUSED: "paused",
            DownloadManager.STATUS_SUCCESSFUL: "successful",
            DownloadManager.STATUS_FAILED: "failed",
        }
        status_name = status_map.get(status, "unknown")
        err = f"код ошибки {reason}" if status_name == "failed" else None
        return status_name, downloaded, total, err
    except Exception as e:
        return "unknown", 0, 0, f"{type(e).__name__}: {e}"


def open_downloaded_apk(download_id):
    """Launch the package installer directly on the file DownloadManager
    just finished downloading - the URI it hands back is already a proper
    content:// URI from its own provider, so no FileProvider setup is
    needed on our side."""
    try:
        from jnius import autoclass
        Context = autoclass("android.content.Context")
        Intent = autoclass("android.content.Intent")
        DownloadManager = autoclass("android.app.DownloadManager")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        dm = activity.getSystemService(Context.DOWNLOAD_SERVICE)
        uri = dm.getUriForDownloadedFile(download_id)
        intent = Intent(Intent.ACTION_VIEW)
        intent.setDataAndType(uri, "application/vnd.android.package-archive")
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION)
        activity.startActivity(intent)
        return True
    except Exception as e:
        print(f"open_downloaded_apk failed: {e}")
        return False


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


def _save_status(working_list, error=None, offline=False, cache_age_min=None):
    data = {
        "checked_at": time.time(),
        "working_list": working_list,
        "error": error,
        "offline": offline,
        "cache_age_min": cache_age_min,
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def _is_domain_proxy(server):
    # dedicated proxy-hosting subdomains (e.g. ru04max.freesurfer.club) tend
    # to be far more reliable in real use than random scraped bare IPs, even
    # when their raw TCP ping is higher - sorting the whole pool by latency
    # alone was pushing most of them out of the tested window entirely
    return not server.replace(".", "").isdigit()


def fetch_candidates(cfg):
    url = RESULTS_URL_TEMPLATE.format(host=cfg["server_host"], token=cfg["http_token"])
    req = urllib.request.Request(url, headers={"User-Agent": "tgproxy-android"})
    with urllib.request.urlopen(req, timeout=15, context=_INSECURE_SSL_CONTEXT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    all_proxies = data["proxies"]  # already sorted by latency_ms ascending
    domain_proxies = [p for p in all_proxies if _is_domain_proxy(p["server"])]
    ip_proxies = [p for p in all_proxies if not _is_domain_proxy(p["server"])]
    # domain-hosted proxies go first (empirically more reliable), but IP
    # ones are never fully excluded - a budget that zeroed ip_budget out
    # once meant a DNS hiccup on just the domain names could tank the
    # whole run down to 0 candidates actually reachable
    candidates = (domain_proxies + ip_proxies)[:TOP_N_TO_TEST]

    with open(CANDIDATES_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"candidates": candidates, "cached_at": time.time()}, f)
    return candidates


def _load_cached_candidates():
    """Last successfully fetched candidate list, kept on-device so the app
    can keep checking/using a proxy even if the parsing server on the VPS
    is temporarily unreachable."""
    if not os.path.exists(CANDIDATES_CACHE_FILE):
        return None
    try:
        with open(CANDIDATES_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


async def _tcp_check(server, port, timeout=TCP_PREFILTER_TIMEOUT):
    """Cheap liveness probe: just open a raw TCP socket to server:port and
    measure how long the connect takes, no MTProto handshake involved. This
    is what a plain 'ping' check looks like (e.g. the reference Android app
    at ComradeBingo/Proxy-Telegram-Android does exactly this) - it can run
    at very high concurrency since it costs almost no CPU, unlike the
    pure-Python MTProto crypto handshake below. Used as a first pass to
    throw out dead hosts fast, before spending the expensive handshake
    check only on the ones that are actually reachable."""
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port), timeout=timeout
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, elapsed_ms, None
    except asyncio.TimeoutError:
        return False, None, f"таймаут {timeout}с"
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


async def _check_one(api_id, api_hash, candidate):
    """Returns (ok, reason) - reason is None on success, otherwise a short
    description of why it failed (timeout vs. connection refused vs. some
    other exception), so the live log can show the actual cause instead of
    just a flat 'not responding'."""
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
        reason = None if ok else "не подключился"
    except asyncio.TimeoutError:
        ok, reason = False, f"таймаут {PER_CHECK_TIMEOUT}с"
    except Exception as e:
        ok, reason = False, f"{type(e).__name__}"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return ok, reason


async def _tcp_prefilter(candidates):
    """Stage 1: raw TCP connect to every candidate, high concurrency, cheap.
    Returns the subset that's actually reachable right now, sorted by TCP
    connect time - throwing out dead hosts here means the slow MTProto
    handshake stage below only ever runs on hosts that are actually up."""
    # a phone's radio/DNS resolver chokes far sooner than a desktop's does -
    # 80 simultaneous DNS lookups + connects on mobile data was plausibly
    # part of why every single one was timing out together
    sem = asyncio.Semaphore(25)
    fail_reasons = {}

    async def _bounded(c):
        async with sem:
            ok, tcp_ms, reason = await _tcp_check(c["server"], c["port"])
            if not ok:
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
            return (c, tcp_ms) if ok else None

    results = await asyncio.gather(*[_bounded(c) for c in candidates])
    alive = [r for r in results if r]
    alive.sort(key=lambda r: r[1])
    summary = f"↻ TCP: живых {len(alive)} из {len(candidates)}"
    if fail_reasons:
        top = sorted(fail_reasons.items(), key=lambda kv: -kv[1])[:3]
        summary += " (" + ", ".join(f"{reason}: {count}" for reason, count in top) + ")"
    await _log_async(summary)
    return [c for c, _tcp_ms in alive]


async def _find_all_working(cfg, candidates, offline=False, cache_age_min=None):
    """Test candidates concurrently (bounded) instead of stopping at the
    first hit - lets the UI show a real list of working proxies to pick
    from, not just one.

    Two stages: first a cheap TCP-only liveness pass over every candidate
    (see _tcp_prefilter), then the real MTProto handshake only on the
    TCP-alive survivors, capped to MTPROTO_CHECK_LIMIT. This matters because
    Telethon's crypto (AES-IGE for the MTProto handshake) runs in pure
    Python here (no cryptg/pycryptodome accelerator installed), which is
    CPU-heavy per connection - running the handshake against every single
    fetched candidate (including plenty that are simply offline) wasted
    most of the check budget on hosts that were never going to answer, and
    kept handshake concurrency low enough that a run could occasionally
    time out across the board.

    Persists status.json after every single hit (not just once at the end):
    the UI polls that file, so a working proxy shows up the moment it's
    found instead of only after the whole run finishes - and if the app
    process gets killed mid-check (backgrounded and reaped by Android), the
    results found so far survive instead of vanishing entirely."""
    alive = await _tcp_prefilter(candidates)
    to_handshake = alive[:MTPROTO_CHECK_LIMIT]
    if len(alive) > MTPROTO_CHECK_LIMIT:
        await _log_async(f"↻ Хендшейк проверяю топ-{MTPROTO_CHECK_LIMIT} из {len(alive)} живых")

    sem = asyncio.Semaphore(4)
    working = []
    save_lock = asyncio.Lock()

    async def _bounded(c):
        async with sem:
            await _log_async(f"→ {c['server']}:{c['port']} — проверка MTProto-хендшейка...")
            ok, reason = await _check_one(cfg["api_id"], cfg["api_hash"], c)
            suffix = f" ({reason})" if reason else ""
            await _log_async(f"{'✓' if ok else '✗'} {c['server']}:{c['port']} — {'работает' if ok else 'не отвечает'}{suffix}")
            if ok:
                async with save_lock:
                    working.append(c)
                    working.sort(key=lambda x: x.get("latency_ms", 10 ** 9))
                    snapshot = list(working)
                await asyncio.to_thread(_save_status, snapshot, None, offline, cache_age_min)
        return c if ok else None

    results = await asyncio.gather(*[_bounded(c) for c in to_handshake])
    final = [c for c in results if c]
    final.sort(key=lambda c: c.get("latency_ms", 10 ** 9))
    return final


def run_check_cycle():
    """Fetch candidates, test them over whatever network is currently active
    on this device, and persist every working one (sorted by ping) to
    status.json. Returns the list of working candidates (best first,
    possibly empty).

    If the parsing server itself is unreachable (down, blocked, VPS issue),
    falls back to the last candidate list this device successfully fetched
    and keeps re-testing/using those instead of just failing - the app
    stays usable even without a live connection to the backend. Only raises
    (and records an error) if there's no cached list to fall back to."""
    _log_reset()
    cfg = load_config()
    offline = False
    cache_age_min = None
    try:
        _log(f"→ Запрос списка кандидатов у {cfg['server_host']}:8765...")
        candidates = fetch_candidates(cfg)
        _log(f"✓ Получено кандидатов: {len(candidates)}")
    except Exception as e:
        _log(f"✗ Сервер недоступен: {type(e).__name__}: {e}")
        cached = _load_cached_candidates()
        if not cached or not cached.get("candidates"):
            import traceback
            err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            _save_status([], error=err_text)
            _log_finish()
            raise
        candidates = cached["candidates"]
        offline = True
        cache_age_min = int((time.time() - cached.get("cached_at", time.time())) / 60)
        _log(f"↻ Использую сохранённый список ({len(candidates)} шт., от {cache_age_min} мин назад)")

    try:
        working_list = asyncio.run(_find_all_working(cfg, candidates, offline, cache_age_min))
    except Exception as e:
        import traceback
        err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _save_status([], error=err_text)
        _log(f"✗ Ошибка проверки: {type(e).__name__}: {e}")
        _log_finish()
        raise

    prev_list = _load_status().get("working_list") or []
    prev_best = prev_list[0] if prev_list else None
    best = working_list[0] if working_list else None

    _save_status(working_list, offline=offline, cache_age_min=cache_age_min)
    _log(f"Готово: рабочих {len(working_list)} из {len(candidates)}")
    _log_finish()

    is_new = best and (not prev_best or (prev_best["server"], prev_best["port"]) != (best["server"], best["port"]))
    if is_new:
        _notify_new_proxy(cfg, best, len(working_list))

    return working_list


_PROXY_LINK_RE = re.compile(
    r"(?:https?://t\.me/proxy|tg://proxy)\?[^\s]*server=([^&\s]+)&(?:amp;)?port=(\d+)&(?:amp;)?secret=([A-Za-z0-9_\-=]+)"
)
_PROXY_TRIPLE_RE = re.compile(r"^\s*([\w.\-]+)[:\s]+(\d+)[:\s]+([A-Za-z0-9_\-=]+)\s*$")


def parse_proxy_input(text):
    """Same accepted formats as the bot's /check command: a t.me/tg:// proxy
    link, or a plain server:port:secret triple."""
    m = _PROXY_LINK_RE.search(text)
    if m:
        return m.group(1).rstrip("."), int(m.group(2)), m.group(3)
    m = _PROXY_TRIPLE_RE.match(text)
    if m:
        return m.group(1), int(m.group(2)), m.group(3)
    return None


def check_single_proxy(cfg, server, port, secret):
    """Manual one-off check triggered from the in-app dialog, mirroring the
    bot's /check command. Returns (ok, reason)."""
    candidate = {"server": server, "port": port, "secret": secret}
    return asyncio.run(_check_one(cfg["api_id"], cfg["api_hash"], candidate))


def proxy_link(proxy):
    return f"https://t.me/proxy?server={proxy['server']}&port={proxy['port']}&secret={proxy['secret']}"


def _notify_new_proxy(cfg, proxy, total_count):
    link = proxy_link(proxy)
    try:
        from plyer import notification
        notification.notify(
            title="Найден рабочий прокси",
            message=f"{proxy['server']}:{proxy['port']} — тапни, чтобы подключить в Telegram",
        )
    except Exception as e:
        print(f"notification failed (running off-device?): {e}")

    extra = f" (всего рабочих: {total_count})" if total_count > 1 else ""
    send_telegram_notify(
        cfg,
        f"✅ Найден рабочий прокси для твоего устройства{extra}:\n"
        f"{proxy['server']}:{proxy['port']} — пинг {proxy.get('latency_ms', '?')} мс\n\n{link}",
    )
    print(f"[tgproxy] new working proxy: {link}")
