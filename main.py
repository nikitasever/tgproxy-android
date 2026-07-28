import json
import os
import threading
import time

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.effects.dampedscroll import DampedScrollEffect
from kivy.metrics import dp
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDIconButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField

from checker_core import (
    run_check_cycle, STATUS_FILE, get_install_code, is_first_run,
    open_url_on_device, proxy_tg_uri, bot_start_uri,
    request_runtime_permissions, request_ignore_battery_optimizations,
    load_live_log, load_config, parse_proxy_input, check_single_proxy,
    get_local_build_number, check_for_update, download_update,
    get_download_progress, open_downloaded_apk,
)

OK_COLOR = (0.20, 0.75, 0.45, 1)
ERR_COLOR = (0.90, 0.35, 0.35, 1)
WARN_COLOR = (0.95, 0.68, 0.20, 1)
SUBTEXT = (0.58, 0.62, 0.70, 1)
ROW_BEST_BG = (0.11, 0.20, 0.16, 1)
ROW_BG = (0.16, 0.18, 0.23, 1)
BADGE_BG = (0.26, 0.29, 0.36, 1)
TERMINAL_BG = (0.04, 0.05, 0.06, 1)
TERMINAL_TEXT = (0.35, 0.90, 0.45, 1)


class ProxyRow(MDCard):
    def __init__(self, rank, proxy, stagger=0.0, **kwargs):
        super().__init__(
            orientation="horizontal", padding=[16, 10], spacing=12,
            size_hint=(1, None), height="68dp",
            radius=[14], elevation=6 if rank == 1 else 2,
            md_bg_color=ROW_BEST_BG if rank == 1 else ROW_BG,
            opacity=0,
            **kwargs,
        )
        badge = MDCard(
            radius=[16], elevation=0, size_hint=(None, None), size=("32dp", "32dp"),
            md_bg_color=OK_COLOR if rank == 1 else BADGE_BG,
        )
        badge.add_widget(MDLabel(
            text=str(rank), bold=True, theme_text_color="Custom",
            text_color=(1, 1, 1, 1), font_style="Body1", halign="center",
        ))
        self.add_widget(badge)

        info = MDBoxLayout(orientation="vertical")
        info.add_widget(MDLabel(
            text=f"{proxy['server']}:{proxy['port']}", bold=True,
            theme_text_color="Primary", font_style="Subtitle1",
            halign="left", valign="middle", size_hint=(1, None), height="22dp",
        ))
        info.add_widget(MDLabel(
            text=f"пинг {proxy.get('latency_ms', '?')} мс", theme_text_color="Custom",
            text_color=SUBTEXT, font_style="Caption",
            halign="left", valign="middle", size_hint=(1, None), height="18dp",
        ))
        self.add_widget(info)

        open_btn = MDRaisedButton(
            text="Открыть",
            md_bg_color=OK_COLOR if rank == 1 else MDApp.get_running_app().theme_cls.primary_color,
            size_hint=(None, None), size=("96dp", "40dp"),
        )
        open_btn.bind(on_release=lambda *_: open_url_on_device(proxy_tg_uri(proxy)))
        self.add_widget(open_btn)

        anim = Animation(opacity=1, duration=0.35, t="out_quad")
        if rank == 1:
            anim.bind(on_complete=lambda *_: self._start_glow_pulse())
        Clock.schedule_once(lambda dt: anim.start(self), stagger)

    def _start_glow_pulse(self):
        pulse = (
            Animation(opacity=0.82, duration=1.1, t="in_out_sine")
            + Animation(opacity=1.0, duration=1.1, t="in_out_sine")
        )
        pulse.repeat = True
        pulse.start(self)


class TgProxyApp(MDApp):
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"

        root = MDBoxLayout(orientation="vertical", padding=[24, 56, 24, 24], spacing=12)

        header = MDBoxLayout(orientation="horizontal", size_hint=(1, None), height="48dp", spacing=14)
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            header.add_widget(Image(source=icon_path, size_hint=(None, None), size=("44dp", "44dp")))
        title_box = MDBoxLayout(orientation="vertical", spacing=2)
        title_box.add_widget(MDLabel(
            text="TG Proxy Checker", bold=True, font_style="H6",
            halign="left", valign="bottom", size_hint=(1, None), height="26dp",
        ))
        title_box.add_widget(MDLabel(
            text="Автоматический подбор рабочего прокси", theme_text_color="Custom",
            text_color=SUBTEXT, font_style="Caption",
            halign="left", valign="top", size_hint=(1, None), height="16dp",
        ))
        header.add_widget(title_box)
        header.add_widget(MDIconButton(icon="send", on_release=self._relink_telegram))
        header.add_widget(MDIconButton(icon="magnify", on_release=self.open_manual_check_dialog))
        root.add_widget(header)

        self.update_card = MDCard(
            orientation="horizontal", padding=[14, 8], spacing=10,
            size_hint=(1, None), height=0, opacity=0,
            radius=[12], md_bg_color=(0.18, 0.14, 0.05, 1),
        )
        self.update_label = MDLabel(
            text="", theme_text_color="Custom", text_color=WARN_COLOR, font_style="Caption",
            halign="left", valign="middle",
        )
        self.update_card.add_widget(self.update_label)
        self.update_btn = MDFlatButton(text="Скачать", theme_text_color="Custom", text_color=WARN_COLOR)
        self.update_btn.bind(on_release=self._download_update)
        self.update_card.add_widget(self.update_btn)
        root.add_widget(self.update_card)

        self.summary_label = MDLabel(
            text="Ещё не проверялось", theme_text_color="Custom", text_color=SUBTEXT,
            font_style="Body2", halign="left", valign="top",
            size_hint=(1, None), height="40dp",
        )
        root.add_widget(self.summary_label)

        self.list_box = MDBoxLayout(orientation="vertical", spacing=10, size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        self.scroll = ScrollView(
            size_hint=(1, 1), effect_cls=DampedScrollEffect,
            scroll_type=["bars", "content"], bar_width="4dp", smooth_scroll_end=10,
        )
        self.scroll.add_widget(self.list_box)
        root.add_widget(self.scroll)

        # "running command line" panel - visible only while a check is in
        # progress, showing exactly what's being contacted right now
        self.terminal_card = MDCard(
            orientation="vertical", padding=[12, 8], size_hint=(1, None),
            height=0, opacity=0, radius=[12], md_bg_color=TERMINAL_BG,
        )
        term_scroll = ScrollView(size_hint=(1, 1), effect_cls=DampedScrollEffect)
        self.terminal_label = MDLabel(
            text="", theme_text_color="Custom", text_color=TERMINAL_TEXT,
            font_style="Caption", halign="left", valign="top",
            size_hint_y=None,
        )
        self.terminal_label.bind(texture_size=lambda *_: setattr(
            self.terminal_label, "height", self.terminal_label.texture_size[1]
        ))
        term_scroll.add_widget(self.terminal_label)
        self.terminal_card.add_widget(term_scroll)
        self._terminal_scroll = term_scroll
        root.add_widget(self.terminal_card)

        self.check_btn = MDRaisedButton(
            text="Проверить сейчас", size_hint=(1, None), height="58dp",
            font_size="16sp",
        )
        self.check_btn.bind(on_release=self.manual_check)
        root.add_widget(self.check_btn)

        footer = MDLabel(
            text="Работает в фоне каждые 30 минут", theme_text_color="Custom",
            text_color=SUBTEXT, font_style="Caption",
            size_hint=(1, None), height="18dp", halign="left",
        )
        root.add_widget(footer)

        Clock.schedule_interval(lambda dt: self.refresh_status(), 5)
        Clock.schedule_interval(lambda dt: self._refresh_terminal(), 0.4)
        self.refresh_status()
        request_runtime_permissions()
        self.start_background_service()
        Clock.schedule_once(lambda dt: request_ignore_battery_optimizations(), 1.0)
        Clock.schedule_once(lambda dt: self._maybe_link_telegram(), 2.0)
        Clock.schedule_once(lambda dt: self._check_update_async(), 2.5)
        return root

    def _maybe_link_telegram(self):
        # auto-open only ever fires on the very first launch - if the user
        # never actually tapped Start in Telegram back then (closed it,
        # switched networks, etc.) there was previously no way to retry;
        # the header button below covers that
        if is_first_run():
            code = get_install_code()
            open_url_on_device(bot_start_uri(code))
        else:
            get_install_code()

    def _relink_telegram(self, *_):
        open_url_on_device(bot_start_uri(get_install_code()))

    def start_background_service(self):
        try:
            from jnius import autoclass
            service = autoclass("org.nikitasever.tgproxycheck.ServiceCheck")
            mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
            service.start(mActivity, "")
        except Exception as e:
            print(f"start_background_service unavailable (running off-device?): {e}")

    # -- manual single-proxy check dialog ----------------------------------

    def open_manual_check_dialog(self, *_):
        self._check_field = MDTextField(
            hint_text="Ссылка t.me/proxy или server:port:secret",
            mode="rectangle",
        )
        self._check_result_label = MDLabel(
            text="", theme_text_color="Custom", text_color=SUBTEXT,
            font_style="Caption", size_hint_y=None, height="20dp",
        )
        content = MDBoxLayout(
            orientation="vertical", spacing=10, size_hint_y=None, height="100dp",
        )
        content.add_widget(self._check_field)
        content.add_widget(self._check_result_label)
        self._check_dialog = MDDialog(
            title="Проверить прокси вручную",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="Закрыть", on_release=lambda *_: self._check_dialog.dismiss()),
                MDRaisedButton(text="Проверить", on_release=self._run_manual_single_check),
            ],
        )
        self._check_dialog.open()

    def _run_manual_single_check(self, *_):
        parsed = parse_proxy_input(self._check_field.text.strip())
        if not parsed:
            self._check_result_label.text_color = ERR_COLOR
            self._check_result_label.text = "Не разобрал формат"
            return
        self._check_result_label.text_color = SUBTEXT
        self._check_result_label.text = "Проверяю..."
        threading.Thread(target=self._manual_single_check_thread, args=(parsed,), daemon=True).start()

    def _manual_single_check_thread(self, parsed):
        server, port, secret = parsed
        try:
            cfg = load_config()
            ok, reason = check_single_proxy(cfg, server, port, secret)
        except Exception as e:
            ok, reason = None, str(e)
        Clock.schedule_once(lambda dt: self._on_manual_single_check_done(server, port, ok, reason), 0)

    def _on_manual_single_check_done(self, server, port, ok, reason):
        if ok is None:
            self._check_result_label.text_color = ERR_COLOR
            self._check_result_label.text = f"Ошибка: {reason}"
        elif ok:
            self._check_result_label.text_color = OK_COLOR
            self._check_result_label.text = f"✅ {server}:{port} работает"
        else:
            self._check_result_label.text_color = ERR_COLOR
            self._check_result_label.text = f"❌ {server}:{port} не отвечает ({reason})"

    # -- in-app update check -------------------------------------------------

    def _check_update_async(self):
        threading.Thread(target=self._check_update_thread, daemon=True).start()

    def _check_update_thread(self):
        remote_build, apk_url, err = check_for_update()
        if err:
            Clock.schedule_once(lambda dt: self._show_update_check_error(err), 0)
            return
        local_build = get_local_build_number()
        if remote_build > local_build:
            Clock.schedule_once(lambda dt: self._show_update_banner(remote_build, apk_url), 0)

    def _show_update_banner(self, remote_build, apk_url):
        self._update_apk_url = apk_url
        self.update_label.text = f"Доступно обновление (сборка #{remote_build})"
        self.update_btn.text = "Скачать"
        self.update_btn.disabled = False
        Animation(height=dp(44), opacity=1, duration=0.3, t="out_quad").start(self.update_card)

    def _show_update_check_error(self, err):
        # surfaced instead of silently failing - api.github.com being
        # unreachable without a VPN on this network is a real possibility,
        # and this makes that visible without needing adb
        self._update_apk_url = None
        self.update_label.text = f"Не удалось проверить обновления: {err}"
        self.update_btn.text = "Ок"
        self.update_btn.disabled = True
        Animation(height=dp(44), opacity=1, duration=0.3, t="out_quad").start(self.update_card)
        Clock.schedule_once(lambda dt: Animation(height=0, opacity=0, duration=0.3).start(self.update_card), 8.0)

    def _download_update(self, *_):
        if not self._update_apk_url:
            return
        if getattr(self, "_download_id", None) is not None:
            # already downloaded - this tap means "install now"
            open_downloaded_apk(self._download_id)
            return
        self.update_btn.disabled = True
        self.update_label.text = "Загрузка... 0%"
        threading.Thread(target=self._download_update_thread, daemon=True).start()

    def _download_update_thread(self):
        download_id, err = download_update(self._update_apk_url)
        if err:
            Clock.schedule_once(lambda dt: self._show_update_check_error(f"Не удалось начать загрузку: {err}"), 0)
            return
        self._download_id = download_id
        Clock.schedule_interval(self._poll_download_progress, 0.5)

    def _poll_download_progress(self, dt):
        status, downloaded, total, err = get_download_progress(self._download_id)
        if status == "running" or status == "pending":
            if total > 0:
                pct = int(downloaded * 100 / total)
                self.update_label.text = f"Загрузка... {pct}%"
            else:
                # GitHub's release CDN often serves the APK without a
                # Content-Length header (chunked transfer), so total stays
                # unknown/-1 the whole time - showing a permanently-stuck
                # "0%" looked like a hang even while bytes were arriving
                mb = downloaded / (1024 * 1024)
                self.update_label.text = f"Загрузка... {mb:.1f} МБ"
            return
        if status == "successful":
            self.update_label.text = "Загружено — жми, чтобы установить"
            self.update_btn.text = "Установить"
            self.update_btn.disabled = False
            return False
        if status == "failed":
            self._download_id = None
            self._show_update_check_error(f"Загрузка не удалась ({err})")
            return False

    # -- proxy check cycle ---------------------------------------------------

    def manual_check(self, instance):
        self.check_btn.disabled = True
        self.check_btn.text = "Проверяю..."
        self.summary_label.text_color = SUBTEXT
        self.summary_label.text = "Опрашиваю сервер и проверяю кандидатов..."
        pulse = (
            Animation(opacity=0.55, duration=0.6, t="in_out_sine")
            + Animation(opacity=1.0, duration=0.6, t="in_out_sine")
        )
        pulse.repeat = True
        pulse.start(self.check_btn)
        self._check_pulse = pulse
        threading.Thread(target=self._run_once, daemon=True).start()

    def _run_once(self):
        try:
            run_check_cycle()
        except Exception as e:
            print(f"manual check failed: {e}")
        Clock.schedule_once(lambda dt: self._on_check_done(), 0)

    def _on_check_done(self):
        if getattr(self, "_check_pulse", None):
            self._check_pulse.cancel(self.check_btn)
        self.check_btn.opacity = 1
        self.check_btn.disabled = False
        self.check_btn.text = "Проверить сейчас"
        self.refresh_status()
        # the device clearly has some network path working right now -
        # good moment to retry the update check if it failed on launch
        self._check_update_async()

    def _refresh_terminal(self):
        log = load_live_log()
        checking = log.get("checking")
        lines = log.get("lines") or []

        if checking:
            self.terminal_label.text = "\n".join(lines)
            if self.terminal_card.height < 10:
                Animation(height=dp(150), opacity=1, duration=0.25, t="out_quad").start(self.terminal_card)
            Clock.schedule_once(lambda dt: setattr(self._terminal_scroll, "scroll_y", 0), 0)
        elif self.terminal_card.height > 10 and lines:
            # leave the final lines up for a moment before collapsing
            self.terminal_label.text = "\n".join(lines)
            if not getattr(self, "_terminal_collapse_scheduled", False):
                self._terminal_collapse_scheduled = True

                def _collapse(dt):
                    Animation(height=0, opacity=0, duration=0.3, t="in_quad").start(self.terminal_card)
                    self._terminal_collapse_scheduled = False

                Clock.schedule_once(_collapse, 1.6)

    def _set_list(self, proxies):
        fingerprint = tuple((p["server"], p["port"], p.get("latency_ms")) for p in proxies)
        if fingerprint == getattr(self, "_last_fingerprint", None):
            return
        self._last_fingerprint = fingerprint
        self.list_box.clear_widgets()
        for i, p in enumerate(proxies, start=1):
            self.list_box.add_widget(ProxyRow(i, p, stagger=0.05 * (i - 1)))
        Animation(scroll_y=1, duration=0.4, t="out_quad").start(self.scroll)

    def refresh_status(self):
        if not os.path.exists(STATUS_FILE):
            self.summary_label.text = "Ещё не проверялось"
            self._set_list([])
            return
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.summary_label.text_color = ERR_COLOR
            self.summary_label.text = "Ошибка чтения статуса"
            self._set_list([])
            return

        if data.get("error"):
            self.summary_label.text_color = ERR_COLOR
            self.summary_label.text = f"Ошибка проверки: {data['error'].splitlines()[0]}"
            self._set_list([])
            return

        age_min = int((time.time() - data.get("checked_at", 0)) / 60)
        working = data.get("working_list") or []
        offline = data.get("offline")

        if working:
            self.summary_label.text_color = WARN_COLOR if offline else OK_COLOR
            self.summary_label.text = f"✅ Найдено {len(working)} рабочих — проверено {age_min} мин назад"
        else:
            self.summary_label.text_color = ERR_COLOR
            self.summary_label.text = f"❌ Рабочих не найдено — проверено {age_min} мин назад"

        if offline:
            cache_age = data.get("cache_age_min")
            age_note = f" ({cache_age} мин назад)" if cache_age is not None else ""
            self.summary_label.text += f"\n⚠️ Сервер недоступен — используются сохранённые кандидаты{age_note}"

        self._set_list(working)


if __name__ == "__main__":
    TgProxyApp().run()
