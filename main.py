import json
import os
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView

from checker_core import (
    run_check_cycle, STATUS_FILE, get_install_code, is_first_run,
    open_url_on_device, proxy_link, BOT_USERNAME,
)

BG = (0.055, 0.063, 0.086, 1)
CARD = (0.11, 0.13, 0.17, 1)
ROW = (0.14, 0.16, 0.21, 1)
ROW_BEST = (0.11, 0.20, 0.16, 1)
ACCENT = (0.20, 0.55, 0.95, 1)
OK_COLOR = (0.20, 0.75, 0.45, 1)
ERR_COLOR = (0.90, 0.35, 0.35, 1)
TEXT = (0.93, 0.94, 0.97, 1)
SUBTEXT = (0.58, 0.62, 0.70, 1)


class RoundedBox(BoxLayout):
    def __init__(self, bg=CARD, radius=18, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*bg)
            self._rect = RoundedRectangle(radius=[radius], pos=self.pos, size=self.size)
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class FlatButton(Button):
    def __init__(self, bg=ACCENT, fg=(1, 1, 1, 1), **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = bg
        self.color = fg
        self.bold = True
        self.font_size = kwargs.get("font_size", "17sp")


class ProxyRow(RoundedBox):
    def __init__(self, rank, proxy, **kwargs):
        super().__init__(
            bg=ROW_BEST if rank == 1 else ROW, radius=14,
            orientation="horizontal", padding=[16, 10], spacing=12,
            size_hint=(1, None), height=68,
            **kwargs,
        )
        badge_bg = OK_COLOR if rank == 1 else (0.24, 0.27, 0.34, 1)
        badge = RoundedBox(bg=badge_bg, radius=16, size_hint=(None, None), size=(32, 32))
        badge.add_widget(Label(text=str(rank), bold=True, color=(1, 1, 1, 1), font_size="14sp"))
        self.add_widget(badge)

        info = BoxLayout(orientation="vertical")
        info.add_widget(Label(
            text=f"{proxy['server']}:{proxy['port']}", bold=True, color=TEXT,
            font_size="15sp", halign="left", valign="middle",
            size_hint=(1, None), height=22, text_size=(None, 22),
        ))
        info.add_widget(Label(
            text=f"пинг {proxy.get('latency_ms', '?')} мс", color=SUBTEXT,
            font_size="12sp", halign="left", valign="middle",
            size_hint=(1, None), height=18, text_size=(None, 18),
        ))
        self.add_widget(info)

        open_btn = FlatButton(
            text="Открыть", bg=OK_COLOR if rank == 1 else ACCENT,
            size_hint=(None, None), size=(96, 44), font_size="13sp",
        )
        open_btn.bind(on_press=lambda *_: open_url_on_device(proxy_link(proxy)))
        self.add_widget(open_btn)


class TgProxyApp(App):
    def build(self):
        from kivy.core.window import Window
        Window.clearcolor = BG

        root = BoxLayout(orientation="vertical", padding=[24, 56, 24, 24], spacing=14)

        header = BoxLayout(orientation="horizontal", size_hint=(1, None), height=48, spacing=14)
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            header.add_widget(Image(source=icon_path, size_hint=(None, None), size=(44, 44)))
        title_box = BoxLayout(orientation="vertical", spacing=2)
        title_box.add_widget(Label(
            text="TG Proxy Checker", font_size="20sp", bold=True, color=TEXT,
            halign="left", valign="bottom", size_hint=(1, None), height=26,
            text_size=(Window.width - 100, 26),
        ))
        title_box.add_widget(Label(
            text="Автоматический подбор рабочего прокси", font_size="11sp", color=SUBTEXT,
            halign="left", valign="top", size_hint=(1, None), height=16,
            text_size=(Window.width - 100, 16),
        ))
        header.add_widget(title_box)
        root.add_widget(header)

        status_row = BoxLayout(orientation="horizontal", size_hint=(1, None), height=20)
        self.summary_label = Label(
            text="Ещё не проверялось", font_size="13sp", color=SUBTEXT,
            halign="left", valign="middle", size_hint=(1, 1),
            text_size=(Window.width - 48, 20),
        )
        status_row.add_widget(self.summary_label)
        root.add_widget(status_row)

        self.list_box = BoxLayout(orientation="vertical", spacing=10, size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

        self.check_btn = FlatButton(text="Проверить сейчас", size_hint=(1, None), height=58)
        self.check_btn.bind(on_press=self.manual_check)
        root.add_widget(self.check_btn)

        footer = Label(
            text="Работает в фоне каждые 30 минут", font_size="11sp", color=SUBTEXT,
            size_hint=(1, None), height=18,
        )
        root.add_widget(footer)

        Clock.schedule_interval(lambda dt: self.refresh_status(), 5)
        self.refresh_status()
        self.start_background_service()
        Clock.schedule_once(lambda dt: self._maybe_link_telegram(), 1.5)
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
        self.summary_label.color = SUBTEXT
        self.summary_label.text = "Опрашиваю сервер и проверяю кандидатов..."
        threading.Thread(target=self._run_once, daemon=True).start()

    def _run_once(self):
        try:
            run_check_cycle()
        except Exception as e:
            print(f"manual check failed: {e}")
        Clock.schedule_once(lambda dt: self._on_check_done(), 0)

    def _on_check_done(self):
        self.check_btn.disabled = False
        self.check_btn.text = "Проверить сейчас"
        self.refresh_status()

    def _set_list(self, proxies):
        self.list_box.clear_widgets()
        for i, p in enumerate(proxies, start=1):
            self.list_box.add_widget(ProxyRow(i, p))

    def refresh_status(self):
        if not os.path.exists(STATUS_FILE):
            self.summary_label.text = "Ещё не проверялось"
            self._set_list([])
            return
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.summary_label.color = ERR_COLOR
            self.summary_label.text = "Ошибка чтения статуса"
            self._set_list([])
            return

        if data.get("error"):
            self.summary_label.color = ERR_COLOR
            self.summary_label.text = f"Ошибка проверки: {data['error'].splitlines()[0]}"
            self._set_list([])
            return

        age_min = int((time.time() - data.get("checked_at", 0)) / 60)
        working = data.get("working_list") or []

        if working:
            self.summary_label.color = OK_COLOR
            self.summary_label.text = f"✅ Найдено {len(working)} рабочих — проверено {age_min} мин назад"
        else:
            self.summary_label.color = ERR_COLOR
            self.summary_label.text = f"❌ Рабочих не найдено — проверено {age_min} мин назад"

        self._set_list(working)


if __name__ == "__main__":
    TgProxyApp().run()
