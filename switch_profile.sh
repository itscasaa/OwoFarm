#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PROFILE="${1:-}"

if [[ "$PROFILE" == "mix" || "$PROFILE" == "mixed" ]]; then
    echo "🔄 Mengganti profil Mizu Bot ke: [MIX] (Hunt, Battle, Owo, Coinflip 5000, Pray)..."
    cp "$DIR/config/settings.mix.json" "$DIR/config/settings.json"
    pm2 restart owomizu
    echo "✅ Berhasil switch ke profil [MIX] dan restart PM2!"
elif [[ "$PROFILE" == "cf" || "$PROFILE" == "coinflip" || "$PROFILE" == "slots" || "$PROFILE" == "only_slots" || "$PROFILE" == "only-slots" || "$PROFILE" == "slot" ]]; then
    echo "🔄 Mengganti profil Mizu Bot ke: [ONLY OWO & COINFLIP 5000]..."
    cp "$DIR/config/settings.slots.json" "$DIR/config/settings.json"
    pm2 restart owomizu
    echo "✅ Berhasil switch ke profil [ONLY OWO & COINFLIP 5000] dan restart PM2!"
elif [[ "$PROFILE" == "giveaway" || "$PROFILE" == "ga" ]]; then
    echo "🎁 Mengganti profil Mizu Bot ke: [GIVEAWAY ONLY] (Semua command mati, hanya auto-join giveaway)..."
    cp "$DIR/config/settings.giveaway.json" "$DIR/config/settings.json"
    pm2 restart owomizu
    echo "✅ Berhasil switch ke profil [GIVEAWAY ONLY] dan restart PM2!"
elif [[ "$PROFILE" == "stop" || "$PROFILE" == "pause" ]]; then
    echo "⏸️ Mengganti profil Mizu Bot ke: [PAUSE / STOP] (Semua command dinonaktifkan, bot tetap online & standby)..."
    cp "$DIR/config/settings.pause.json" "$DIR/config/settings.json"
    pm2 restart owomizu
    echo "✅ Berhasil pause bot dan restart PM2!"
else
    echo "Penggunaan: ./switch_profile.sh <mix | cf | giveaway | stop>"
    echo "Contoh:"
    echo "  ./switch_profile.sh mix      -> Mengaktifkan profil campuran (Hunt, Battle, Owo, Coinflip 5000, Pray)"
    echo "  ./switch_profile.sh cf       -> Mengaktifkan profil khusus (Hanya Owo & Coinflip 5000)"
    echo "  ./switch_profile.sh giveaway -> Hanya auto-join giveaway (Tanpa command chat)"
    echo "  ./switch_profile.sh stop     -> Menghentikan pengiriman command (bot tetap standby & online)"
    exit 1
fi
