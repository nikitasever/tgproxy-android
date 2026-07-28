[app]
title = TG Proxy Checker
package.name = tgproxycheck
package.domain = org.nikitasever

source.dir = .
source.include_exts = py,json,png,jpg,kv,atlas

icon.filename = %(source.dir)s/icon.png

version = 0.3
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.2.1,kivymd==1.2.0,materialyoucolor,asynckivy,asyncgui,telethon,pyaes,rsa,pyasn1,pysocks,plyer,certifi

# Android 14 (API 34) throws MissingForegroundServiceTypeException and
# crashes the app on every launch if a foreground service doesn't declare
# its type - dataSync fits what this service actually does (periodic
# network fetch/check of proxy candidates)
services = check:service.py:foreground:foregroundServiceType=dataSync

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,FOREGROUND_SERVICE,FOREGROUND_SERVICE_DATA_SYNC,POST_NOTIFICATIONS,WAKE_LOCK,RECEIVE_BOOT_COMPLETED,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,REQUEST_INSTALL_PACKAGES
# targeting an old SDK is one of the signals Play Protect uses to flag a
# sideloaded APK as "suspicious" / "not optimized for newer Android"
android.api = 34
android.minapi = 24
android.ndk_api = 24
# buildozer's release build defaults to producing an .aab (Play Store
# bundle format), which isn't directly installable by sideloading/adb -
# we distribute a plain APK via GitHub Releases, not the Play Store
android.release_artifact = apk
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 0
