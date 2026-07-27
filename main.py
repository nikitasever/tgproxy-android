import json
import os
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button

from checker_core import run_check_cycle, STATUS_FILE, load_config


class RootLayout(BoxLayout):
    pass


class TgProxyApp(App):
    def build(self):
        self.orientation = "vertical"
        layout = BoxLayout(orientation="vertical", padding=20, spacing=20)

        self.status_label = Label(text="Загрузка...", halign="center")
        layout.add_widget(self.status_label)

        check_btn = Button(text="Проверить сейчас", size_hint=(1, 0.2))
        check_btn.bind(on_press=self.manual_check)
        layout.add_widget(check_btn)

        Clock.schedule_interval(lambda dt: self.refresh_status(), 5)
        self.refresh_status()
        self.start_background_service()
        return layout

    def start_background_service(self):
        # python-for-android names the generated service class
        # "<package.domain>.<package.name>.Service<ServiceName title-cased>"
        # for a service declared in buildozer.spec as "check:service.py".
        try:
            from jnius import autoclass
            service = autoclass("org.nikitasever.tgproxycheck.ServiceCheck")
            mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
            service.start(mActivity, "")
        except Exception as e:
            print(f"start_background_service unavailable (running off-device?): {e}")

    def manual_check(self, instance):
        self.status_label.text = "Проверяю..."
        threading.Thread(target=self._run_once, daemon=True).start()

    def _run_once(self):
        try:
            run_check_cycle()
        except Exception as e:
            print(f"manual check failed: {e}")
        Clock.schedule_once(lambda dt: self.refresh_status(), 0)

    def refresh_status(self):
        if not os.path.exists(STATUS_FILE):
            self.status_label.text = "Ещё не проверялось"
            return
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self.status_label.text = "Ошибка чтения статуса"
            return

        age_min = int((time.time() - data.get("checked_at", 0)) / 60)
        if data.get("working"):
            p = data["working"]
            self.status_label.text = (
                f"Рабочий прокси: {p['server']}:{p['port']}\n"
                f"Проверено {age_min} мин назад"
            )
        else:
            self.status_label.text = f"Рабочих прокси не найдено (проверено {age_min} мин назад)"


if __name__ == "__main__":
    TgProxyApp().run()
