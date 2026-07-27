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
    open_url_on_device, BOT_USERNAME,
)

BG = (0.055, 0.063, 0.086, 1)
CARD = (0.11, 0.13, 0.17, 1)
ACCENT = (0.20, 0.55, 0.95, 1)
ACCENT_DARK = (0.15, 0.42, 0.75, 1)
OK_COLOR = (0.20, 0.75, 0.45, 1)
OK_DARK = (0.14, 0.55, 0.35, 1)
ERR_COLOR = (0.90, 0.35, 0.35, 1)
TEXT = (0.93, 0.94, 0.97, 1)
SUBTEXT = (0.58, 0.62, 0.70, 1)


class Card(BoxLayout):
    def __init__(self, bg=CARD, **kwargs):
        super().__init__(**kwargs)
        self._bg = bg
        with self.canvas.before:
            Color(*bg)
            self._rect = RoundedRectangle(radius=[20], pos=self.pos, size=self.size)
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
        self.font_size = "17sp"


class TgProxyApp(App):
    def build(self):
        from kivy.core.window import Window
        Window.clearcolor = BG

        root = BoxLayout(orientation="vertical", padding=24, spacing=16)

        header = BoxLayout(orientation="horizontal", size_hint=(1, None), height=56, spacing=14)
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            header.add_widget(Image(source=icon_path, size_hint=(None, None), size=(48, 48)))
        title_box = BoxLayout(orientation="vertical")
        title_box.add_widget(Label(
            text="TG Proxy Checker", font_size="22sp", bold=True, color=TEXT,
            halign="left", valign="middle", size_hint=(1, None), height=28,
            text_size=(Window.width - 130, 28),
        ))
        title_box.add_widget(Label(
            text="Автоматический подбор рабочего прокси", font_size="12sp", color=SUBTEXT,
            halign="left", valign="middle", size_hint=(1, None), height=18,
            text_size=(Window.width - 130, 18),
        ))
        header.add_widget(title_box)
        root.add_widget(header)

        self.card = Card(orientation="vertical", padding=20, spacing=10, size_hint=(1, 0.5))
        scroll = ScrollView(size_hint=(1, 1))
        self.status_label = Label(
            text="Ещё не проверялось", font_size="16sp", color=TEXT,
            halign="left", valign="top", size_hint_y=None,
            text_size=(Window.width - 100, None),
        )
        self.status_label.bind(texture_size=self._resize_label)
        scroll.add_widget(self.status_label)
        self.card.add_widget(scroll)
        root.add_widget(self.card)

        self.age_label = Label(
            text="", font_size="12sp", color=SUBTEXT,
            size_hint=(1, None), height=20,
        )
        root.add_widget(self.age_label)

        self.open_tg_btn = FlatButton(
            text="Открыть в Telegram", bg=OK_COLOR, size_hint=(1, None), height=60,
        )
        self.open_tg_btn.bind(on_press=self._open_in_telegram)
        self.open_tg_btn.opacity = 0
        self.open_tg_btn.disabled = True
        self.open_tg_btn.size_hint_y = None
        self.open_tg_btn.height = 0
        root.add_widget(self.open_tg_btn)

        self.check_btn = FlatButton(text="Проверить сейчас", size_hint=(1, None), height=60)
        self.check_btn.bind(on_press=self.manual_check)
        root.add_widget(self.check_btn)

        footer = Label(
            text="Работает в фоне каждые 30 минут", font_size="11sp", color=SUBTEXT,
            size_hint=(1, None), height=18,
        )
        root.add_widget(footer)

        self._current_link = None
        Clock.schedule_interval(lambda dt: self.refresh_status(), 5)
        self.refresh_status()
        self.start_background_service()
        Clock.schedule_once(lambda dt: self._maybe_link_telegram(), 1.5)
        return root

    def _resize_label(self, instance, size):
        instance.height = size[1]

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
        self.status_label.color = TEXT
        self.status_label.text = "Опрашиваю сервер и проверяю кандидатов..."
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

    def _open_in_telegram(self, instance):
        if self._current_link:
            open_url_on_device(self._current_link)

    def _show_open_button(self, show):
        self.open_tg_btn.disabled = not show
        self.open_tg_btn.opacity = 1 if show else 0
        self.open_tg_btn.height = 60 if show else 0

    def refresh_status(self):
        if not os.path.exists(STATUS_FILE):
            self.status_label.color = TEXT
            self.status_label.text = "Ещё не проверялось"
            self.age_label.text = ""
            self._show_open_button(False)
            return
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.status_label.color = ERR_COLOR
            self.status_label.text = "Ошибка чтения статуса"
            self._show_open_button(False)
            return

        if data.get("error"):
            self.status_label.color = ERR_COLOR
            self.status_label.text = f"Ошибка проверки:\n{data['error']}"
            self.age_label.text = ""
            self._show_open_button(False)
            return

        age_min = int((time.time() - data.get("checked_at", 0)) / 60)
        self.age_label.text = f"Проверено {age_min} мин назад"

        if data.get("working"):
            p = data["working"]
            self._current_link = f"https://t.me/proxy?server={p['server']}&port={p['port']}&secret={p['secret']}"
            self.status_label.color = OK_COLOR
            self.status_label.text = (
                f"✅ Рабочий прокси найден\n\n"
                f"{p['server']}:{p['port']}\n"
                f"пинг {p.get('latency_ms', '?')} мс"
            )
            self._show_open_button(True)
        else:
            self._current_link = None
            self.status_label.color = ERR_COLOR
            self.status_label.text = "❌ Ни один из проверенных прокси не работает через текущую сеть"
            self._show_open_button(False)


if __name__ == "__main__":
    TgProxyApp().run()
