import time
import traceback

from checker_core import run_check_cycle, load_config

CHECK_INTERVAL_SECONDS = 30 * 60


def notify_android(title, text, link):
    """Real Android notification with a tap action that opens the proxy
    link directly in Telegram. Falls back silently if not running on device
    (e.g. if this module is ever imported for local testing)."""
    try:
        from jnius import autoclass, cast

        PythonActivity = autoclass("org.kivy.android.PythonService")
        Context = autoclass("android.content.Context")
        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        PendingIntent = autoclass("android.app.PendingIntent")
        NotificationBuilder = autoclass("android.app.Notification$Builder")
        NotificationManager = autoclass("android.app.NotificationManager")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        Build = autoclass("android.os.Build")

        service = PythonActivity.mService
        ns = service.getSystemService(Context.NOTIFICATION_SERVICE)
        manager = cast(NotificationManager, ns)

        channel_id = "tgproxy_channel"
        if Build.VERSION.SDK_INT >= 26:
            channel = NotificationChannel(
                channel_id, "TG Proxy Checker",
                NotificationManager.IMPORTANCE_DEFAULT,
            )
            manager.createNotificationChannel(channel)

        intent = Intent(Intent.ACTION_VIEW, Uri.parse(link))
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        flags = PendingIntent.FLAG_UPDATE_CURRENT
        if Build.VERSION.SDK_INT >= 23:
            flags = flags | PendingIntent.FLAG_IMMUTABLE
        pending = PendingIntent.getActivity(service, 0, intent, flags)

        builder = NotificationBuilder(service, channel_id) if Build.VERSION.SDK_INT >= 26 else NotificationBuilder(service)
        builder.setContentTitle(title)
        builder.setContentText(text)
        builder.setContentIntent(pending)
        builder.setAutoCancel(True)
        builder.setSmallIcon(service.getApplicationInfo().icon)

        manager.notify(2, builder.build())
    except Exception as e:
        print(f"[tgproxy service] android notification failed: {e}")
        traceback.print_exc()


def main_loop():
    while True:
        try:
            cfg = load_config()
            prev_working = None
            try:
                from checker_core import _load_status
                prev_working = _load_status().get("working")
            except Exception:
                pass

            working = run_check_cycle()

            if working:
                is_new = not prev_working or (
                    (prev_working["server"], prev_working["port"]) != (working["server"], working["port"])
                )
                if is_new:
                    link = f"https://t.me/proxy?server={working['server']}&port={working['port']}&secret={working['secret']}"
                    notify_android(
                        "Найден рабочий прокси",
                        f"{working['server']}:{working['port']} — тапни, чтобы подключить",
                        link,
                    )
        except Exception as e:
            print(f"[tgproxy service] check cycle failed: {e}")
            traceback.print_exc()

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main_loop()
