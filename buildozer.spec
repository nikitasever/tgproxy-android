[app]
title = TG Proxy Checker
package.name = tgproxycheck
package.domain = org.nikitasever

source.dir = .
source.include_exts = py,json,png,jpg,kv,atlas

icon.filename = %(source.dir)s/icon.png

version = 0.3
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.2.1,kivymd==1.2.0,materialyoucolor,asynckivy,asyncgui,telethon,pyaes,rsa,pyasn1,pysocks,plyer,certifi

services = check:service.py:foreground

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,WAKE_LOCK,RECEIVE_BOOT_COMPLETED,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 0
