#!/usr/bin/env python3
"""
OwO Bot Unban Notifier & Webhook Dispatcher
Tracks ban expiration and alerts user via Webhook when bot is safe to use again.
"""

import sys
import os
import time
import json
import argparse
import datetime
import urllib.request

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
GLOBAL_SETTINGS = os.path.join(CONFIG_DIR, "global_settings.json")
FLAG_FILE = os.path.join(CONFIG_DIR, "unban_notified.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "unban_notifier.log")

# Ban Details
USER_ID = os.environ.get("UNBAN_USER_ID", "123456789012345678")
USERNAME = os.environ.get("UNBAN_USERNAME", "owo_user")
BAN_HOURS = 756
BAN_START_EPOCH = 1790671380  # 2026-09-29 08:43:00 UTC
UNBAN_EPOCH = BAN_START_EPOCH + (BAN_HOURS * 3600)  # 1793392980 -> 2026-10-30 20:43:00 UTC / 2026-10-31 03:43:00 WIB
DEFAULT_WEBHOOK = os.environ.get("UNBAN_WEBHOOK", "")


def get_webhook_url():
    try:
        if os.path.exists(GLOBAL_SETTINGS):
            with open(GLOBAL_SETTINGS, "r") as f:
                data = json.load(f)
                return data.get("webhook", {}).get("webhookUrl") or DEFAULT_WEBHOOK
    except Exception:
        pass
    return DEFAULT_WEBHOOK


def log_message(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def send_webhook(content, embeds=None):
    url = get_webhook_url()
    payload = {"content": content}
    if embeds:
        payload["embeds"] = embeds

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "MizuOwO-UnbanNotifier/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in [200, 204]:
                log_message(f"✅ Webhook sent successfully (Status {resp.status})")
                return True
            else:
                log_message(f"⚠️ Webhook warning (Status {resp.status})")
                return False
    except Exception as e:
        log_message(f"❌ Webhook error: {e}")
        return False


def get_remaining_str(target_epoch):
    now = time.time()
    diff = int(target_epoch - now)
    if diff <= 0:
        return "0 detik (MASA BAN TELAH BERAKHIR)"

    days = diff // 86400
    hours = (diff % 86400) // 3600
    minutes = (diff % 3600) // 60
    seconds = diff % 60

    parts = []
    if days > 0:
        parts.append(f"{days} hari")
    if hours > 0:
        parts.append(f"{hours} jam")
    if minutes > 0:
        parts.append(f"{minutes} menit")
    parts.append(f"{seconds} detik")
    return " ".join(parts)


def check_and_notify():
    now = time.time()

    if os.path.exists(FLAG_FILE):
        return False

    if now < UNBAN_EPOCH:
        return False

    # Masa ban berakhir, kirim notifikasi!
    content = (
        f"🎉 **[OWO BOT UNBAN ALERT]** 🎉\n\n"
        f"Halo <@{USER_ID}>! Masa hukuman ban OwO Bot kamu telah **SELESAI**!\n\n"
        f"📋 **Detail Akun & Ban**:\n"
        f"• Username: **{USERNAME}** (`{USER_ID}`)\n"
        f"• Durasi Hukuman: **{BAN_HOURS} Jam (31.5 Hari)**\n"
        f"• Waktu Selesai: **31 Oktober 2026, 03:43:00 WIB**\n"
        f"• Status: **Bebas dari Ban (Ready to Use)**\n\n"
        f"⚙️ **Status Bot Saat Ini**: Standby `giveaway_only`.\n\n"
        f"🚀 **Cara Mengaktifkan Kembali Mode Farming / Coinflip**:\n"
        f"Gunakan terminal VPS di `/home/ndenn25/owomizu`:\n"
        f"• `./switch_profile.sh mix` → Farming lengkap (Hunt, Battle, Pray, Coinflip)\n"
        f"• `./switch_profile.sh cf` → Khusus Coinflip / Slots 5000\n"
        f"• `./switch_profile.sh giveaway` → Tetap Giveaway Only"
    )

    embed = {
        "title": "🎉 OwO Bot Unbanned! Masa Hukuman 756H Selesai",
        "description": f"Akun **{USERNAME}** kini sudah bebas dari ban OwO Bot dan dapat digunakan kembali secara normal.",
        "color": 0x00FF66,
        "fields": [
            {"name": "👤 Akun", "value": f"{USERNAME} (`{USER_ID}`)", "inline": True},
            {"name": "⏱️ Total Ban", "value": f"{BAN_HOURS} Jam (31.5 Hari)", "inline": True},
            {"name": "📅 Waktu Selesai", "value": "31 Okt 2026, 03:43 WIB", "inline": False},
            {"name": "🔄 Rekomendasi", "value": "Jalankan `./switch_profile.sh mix` untuk mengaktifkan kembali bot.", "inline": False}
        ],
        "footer": {"text": "OwO Mizu Auto-Unban Notifier"}
    }

    success = send_webhook(content=content, embeds=[embed])
    if success:
        with open(FLAG_FILE, "w") as f:
            json.dump({
                "notified_at": time.time(),
                "notified_at_str": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": USER_ID,
                "username": USERNAME,
                "unban_epoch": UNBAN_EPOCH
            }, f, indent=4)
        log_message("🎉 Notifikasi unban berhasil dikirim dan flag file disimpan.")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="OwO Bot Unban Notifier")
    parser.add_argument("--check", action="store_true", help="Check if ban expired and send webhook if ready")
    parser.add_argument("--status", action="store_true", help="Print remaining time until unban")
    parser.add_argument("--test", action="store_true", help="Send a test notification to verify webhook")
    parser.add_argument("--init", action="store_true", help="Send initialization notification confirming registration")

    args = parser.parse_args()

    if args.status:
        remaining = get_remaining_str(UNBAN_EPOCH)
        print(f"Target Unban (UTC): 2026-10-30 20:43:00 UTC")
        print(f"Target Unban (WIB): 2026-10-31 03:43:00 WIB")
        print(f"Sisa Waktu: {remaining}")
        print(f"Flag Notifikasi: {'Sudah Dikirim' if os.path.exists(FLAG_FILE) else 'Belum Dikirim (Menunggu Waktu)'}")
        return

    if args.test:
        content = (
            f"🧪 **[TEST] OwO Unban Notifier Webhook Check**\n"
            f"Tes pengiriman webhook dari server VPS berhasil!\n"
            f"Target unban akun **{USERNAME}**: **31 Oktober 2026, 03:43:00 WIB**"
        )
        send_webhook(content)
        return

    if args.init:
        remaining = get_remaining_str(UNBAN_EPOCH)
        content = (
            f"🛡️ **[OWO BOT - JADWAL NOTIFIKASI UNBAN TERDAFTAR]**\n\n"
            f"Sistem notifikasi otomatis untuk akun **{USERNAME}** (`{USER_ID}`) telah diaktifkan di VPS.\n\n"
            f"📊 **Informasi Status Saat Ini**:\n"
            f"• Mode Bot: **Giveaway Only** (Semua command chat dinonaktifkan, hanya standby reaction giveaway)\n"
            f"• Status PM2: **Online & Standby**\n"
            f"• Durasi Ban: **{BAN_HOURS} Jam (31 Hari 12 Jam)**\n"
            f"• Target Unban: **Sabtu, 31 Oktober 2026, 03:43:00 WIB**\n"
            f"• Sisa Waktu: **{remaining}**\n\n"
            f"🔔 Notifikasi otomatis akan dikirim ke webhook ini saat masa ban telah berakhir."
        )
        send_webhook(content)
        return

    if args.check:
        check_and_notify()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
