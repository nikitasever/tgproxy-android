import json
import os
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView

from checker_core import run_check_cycle, STATUS_FILE

BG = (0.07, 0.08, 0.11, 1)
CARD = (0.13, 0.15, 0.19, 1)
ACCENT = (0.20, 0.55, 0.95, 1)
ACCENT_DARK = (0.15, 0.42, 0.75, 1)
OK_COLOR = (0.20, 0.75, 0.45, 1)
ERR_COLOR = (0.85, 0.30, 0.30, 1)
TEXT = (0.92, 0.93, 0.96, 1)
SUBTEXT = (0.60, 0.63, 0.70, 1)


class Card(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*CARD)
            self._rect = RoundedRectangle(radius=[18], pos=self.pos, size=self.size)
        self.bind(pos=self._update_rect, size=self._update_rect)

    def _update_rect(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class AccentButton(Button):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = ACCENT
        self.color = (1, 1, 1, 1)
        self.bold = True
        self.font_size = "18sp"


class TgProxyApp(App):
    def build(self):
        from kivy.core.window import Window
        Window.clearcolor = BG

        root = BoxLayout(orientation="vertical", padding=24, spacing=18)

        title = Label(
            text="TG Proxy Checker",
            font_size="24sp", bold=True, color=TEXT,
            size_hint=(1, None), height=44,
        )
        root.add_widget(title)

        subtitle = Label(
            text="Проверяет MTProto-прокси через текущую сеть телефона",
            font_size="13sp", color=SUBTEXT,
            size_hint=(1, None), height=24,
        )
        root.add_widget(subtitle)

        self.card = Card(orientation="vertical", padding=20, spacing=10, size_hint=(1, 0.55))
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

        self.check_btn = AccentButton(text="Проверить сейчас", size_hint=(1, None), height=64)
        self.check_btn.bind(on_press=self.manual_check)
        root.add_widget(self.check_btn)

        Clock.schedule_interval(lambda dt: self.refresh_status(), 5)
        self.refresh_status()
        self.start_background_service()
        return root

    def _resize_label(self, instance, size):
        instance.height = size[1]

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

    def refresh_status(self):
        if not os.path.exists(STATUS_FILE):
            self.status_label.color = TEXT
            self.status_label.text = "Ещё не проверялось"
            self.age_label.text = ""
            return
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.status_label.color = ERR_COLOR
            self.status_label.text = "Ошибка чтения статуса"
            return

        if data.get("error"):
            self.status_label.color = ERR_COLOR
            self.status_label.text = f"Ошибка проверки:\n{data['error']}"
            self.age_label.text = ""
            return

        age_min = int((time.time() - data.get("checked_at", 0)) / 60)
        self.age_label.text = f"Проверено {age_min} мин назад"

        if data.get("working"):
            p = data["working"]
            link = f"t.me/proxy?server={p['server']}&port={p['port']}&secret={p['secret']}"
            self.status_label.color = OK_COLOR
            self.status_label.text = (
                f"✅ Рабочий прокси\n\n"
                f"{p['server']}:{p['port']}\n"
                f"пинг {p.get('latency_ms', '?')} мс\n\n"
                f"{link}"
            )
        else:
            self.status_label.color = ERR_COLOR
            self.status_label.text = "❌ Ни один из проверенных прокси не работает через текущую сеть"


if __name__ == "__main__":
    TgProxyApp().run()
