import json
import os
import threading
import time

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel

from checker_core import (
    run_check_cycle, STATUS_FILE, get_install_code, is_first_run,
    open_url_on_device, proxy_link, BOT_USERNAME,
    request_runtime_permissions, request_ignore_battery_optimizations,
)

OK_COLOR = (0.20, 0.75, 0.45, 1)
ERR_COLOR = (0.90, 0.35, 0.35, 1)
WARN_COLOR = (0.95, 0.68, 0.20, 1)
SUBTEXT = (0.58, 0.62, 0.70, 1)
ROW_BEST_BG = (0.11, 0.20, 0.16, 1)
ROW_BG = (0.16, 0.18, 0.23, 1)
BADGE_BG = (0.26, 0.29, 0.36, 1)


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
        open_btn.bind(on_release=lambda *_: open_url_on_device(proxy_link(proxy)))
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

        root = MDBoxLayout(orientation="vertical", padding=[24, 56, 24, 24], spacing=14)

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
        root.add_widget(header)

        self.summary_label = MDLabel(
            text="Ещё не проверялось", theme_text_color="Custom", text_color=SUBTEXT,
            font_style="Body2", halign="left", valign="top",
            size_hint=(1, None), height="40dp",
        )
        root.add_widget(self.summary_label)

        self.list_box = MDBoxLayout(orientation="vertical", spacing=10, size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

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
        self.refresh_status()
        request_runtime_permissions()
        self.start_background_service()
        Clock.schedule_once(lambda dt: request_ignore_battery_optimizations(), 1.0)
        Clock.schedule_once(lambda dt: self._maybe_link_telegram(), 2.0)
        return root

    def _maybe_link_telegram(self):
        if is_first_run():
            code = get_install_code()
            open_url_on_device(f"https://t.me/{BOT_USERNAME}?start={code}")
        else:
            get_install_code()

    def start_background_service(self):
        try:
            from jnius import autoclass
            service = autoclass("org.nikitasever.tgproxycheck.ServiceCheck")
            mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
            service.start(mActivity, "")
        except Exception as e:
            print(f"start_background_service unavailable (running off-device?): {e}")

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

    def _set_list(self, proxies):
        fingerprint = tuple((p["server"], p["port"], p.get("latency_ms")) for p in proxies)
        if fingerprint == getattr(self, "_last_fingerprint", None):
            return
        self._last_fingerprint = fingerprint
        self.list_box.clear_widgets()
        for i, p in enumerate(proxies, start=1):
            self.list_box.add_widget(ProxyRow(i, p, stagger=0.05 * (i - 1)))

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
