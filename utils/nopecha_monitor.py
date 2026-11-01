import time
import json
import asyncio
import aiohttp
import os
from typing import Optional, Dict, Any, List

_last_alert_time = 0
_ALERT_COOLDOWN = 1800  # Notify at most once every 30 minutes unless forced

def mask_key(key: str) -> str:
    if not key or len(key) <= 6:
        return "***"
    return f"{key[:4]}***{key[-3:]}"

def get_configured_nopecha_keys(nopecha_conf: Dict[str, Any]) -> List[str]:
    """
    Extract list of non-empty NopeCHA keys from config (keys array + fallback key).
    Deduplicates while preserving order.
    """
    keys = []
    # 1. Check keys array
    raw_keys = nopecha_conf.get("keys", [])
    if isinstance(raw_keys, list):
        for k in raw_keys:
            if isinstance(k, str) and k.strip() and k.strip() not in keys:
                keys.append(k.strip())
    elif isinstance(raw_keys, str) and raw_keys.strip():
        keys.append(raw_keys.strip())

    # 2. Check single key fallback
    single_k = nopecha_conf.get("key", "")
    if isinstance(single_k, str) and single_k.strip() and single_k.strip() not in keys:
        keys.append(single_k.strip())

    return keys

async def fetch_nopecha_status(key: str, session: Optional[aiohttp.ClientSession] = None) -> Optional[Dict[str, Any]]:
    """
    Query NopeCHA API for current key status, credit balance, and TTL.
    """
    if not key:
        return None

    url = f"https://api.nopecha.com/status?key={key}"
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"key": key, **data}
            elif resp.status in (400, 404):
                return {"key": key, "status": "Invalid", "error": "Invalid API Key", "credit": 0, "quota": 200, "ttl": 0}
            elif resp.status == 402:
                return {"key": key, "status": "Exhausted", "error": "Quota Exhausted", "credit": 0, "quota": 200, "ttl": 0}
            else:
                return {"key": key, "status": f"HTTP {resp.status}", "credit": 0, "quota": 200, "ttl": 0}
    except Exception as e:
        print(f"[NopeCHA Monitor Error] Failed to fetch status for {mask_key(key)}: {e}")
        return {"key": key, "status": "Error", "error": str(e), "credit": 0, "quota": 200, "ttl": 0}
    finally:
        if close_session:
            await session.close()

async def fetch_all_nopecha_status(keys: List[str]) -> List[Dict[str, Any]]:
    """
    Query status for all keys concurrently.
    """
    if not keys:
        return []

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_nopecha_status(k, session=session) for k in keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    cleaned = []
    for idx, r in enumerate(results):
        if isinstance(r, dict):
            cleaned.append(r)
        else:
            k = keys[idx]
            cleaned.append({"key": k, "status": "Error", "error": str(r), "credit": 0, "quota": 200, "ttl": 0})
    return cleaned

def sync_nopecha_manifests(keys: List[str], active_key: Optional[str] = None):
    """
    Synchronize the active key and full keys pool across extension manifests
    in owomizu and camofox-browser.
    """
    if not keys:
        return

    primary = active_key if active_key else keys[0]
    manifest_paths = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "extensions", "nopecha", "manifest.json"),
        "/home/ndenn25/camofox-browser/extensions/nopecha/manifest.json"
    ]

    for p in manifest_paths:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "nopecha" not in data or not isinstance(data["nopecha"], dict):
                data["nopecha"] = {}
            
            needs_save = False
            if data["nopecha"].get("key") != primary:
                data["nopecha"]["key"] = primary
                needs_save = True
            if data["nopecha"].get("keys") != keys:
                data["nopecha"]["keys"] = keys
                needs_save = True

            if needs_save:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                print(f"🔄 [NopeCHA Sync] Manifest updated at {p} with active key {mask_key(primary)} and {len(keys)} keys.")
        except Exception as err:
            print(f"[NopeCHA Manifest Sync Error] Failed updating {p}: {err}")

async def check_and_alert_nopecha(bot, force: bool = False) -> Optional[Dict[str, Any]]:
    """
    Check NopeCHA multi-key pool health, auto-rotate/promote the best key,
    sync manifests, and dispatch webhook alert if credits are critically low or exhausted.
    """
    global _last_alert_time

    captcha_conf = bot.global_settings_dict.get("captcha", {})
    nopecha_conf = captcha_conf.get("nopecha", {})
    
    if not nopecha_conf.get("enabled", True):
        return None

    keys = get_configured_nopecha_keys(nopecha_conf)
    if not keys:
        return None

    threshold = nopecha_conf.get("lowCreditThreshold", 25)
    notify_enabled = nopecha_conf.get("notifyOnLowCredit", True)

    # 1. Fetch status for all keys
    status_list = await fetch_all_nopecha_status(keys)
    if not status_list:
        return None

    # 2. Aggregate pool metrics
    total_credit = sum(k.get("credit", 0) for k in status_list)
    total_quota = sum(k.get("quota", 200) for k in status_list)
    max_ttl = max((k.get("ttl", 0) for k in status_list), default=0)

    # Find healthy / active keys
    active_keys = [k for k in status_list if k.get("status") == "Active" and k.get("credit", 0) > 0]
    healthy_keys = [k for k in status_list if k.get("status") == "Active" and k.get("credit", 0) > threshold]

    # Select best active key: highest remaining credit
    best_item = None
    if active_keys:
        best_item = max(active_keys, key=lambda x: x.get("credit", 0))
    elif status_list:
        best_item = status_list[0]

    best_key = best_item.get("key", keys[0]) if best_item else keys[0]

    # If best key changed from current single key, update bot config & sync manifests
    current_primary = nopecha_conf.get("key", "")
    if best_key != current_primary:
        bot.global_settings_dict["captcha"]["nopecha"]["key"] = best_key
        sync_nopecha_manifests(keys, best_key)
        print(f"🔀 [NopeCHA Rotation] Active solver key rotated to: {mask_key(best_key)} ({best_item.get('credit', 0)} credits remaining)")

    # 3. Determine Alert Conditions
    now = time.time()
    needs_alert = False
    alert_type = "warning"
    alert_title = "⚠️ [NOPECHA KEY PERLU DI-GENERATE ULANG]"

    if len(active_keys) == 0 or total_credit <= 0:
        needs_alert = True
        alert_title = "🚨 [SEMUA NOPECHA KEY HABIS / KEDALUWARSA]"
        alert_type = "danger"
    elif len(healthy_keys) < len(keys):
        # One or more keys are low/exhausted, but backup keys are still active
        needs_alert = True
        exhausted_count = len(keys) - len(healthy_keys)
        alert_title = f"⚠️ [PERINGATAN KUOTA NOPECHA: {exhausted_count} KEY MENIPIS/HABIS]"
        alert_type = "warning"

    # 4. Dispatch Alert if triggered
    if (needs_alert or force) and notify_enabled:
        if force or (now - _last_alert_time) >= _ALERT_COOLDOWN:
            _last_alert_time = now
            
            # Format breakdown per key
            key_lines = []
            for idx, item in enumerate(status_list, start=1):
                k_masked = mask_key(item.get("key", ""))
                k_cred = item.get("credit", 0)
                k_quota = item.get("quota", 200)
                k_stat = item.get("status", "Unknown")
                k_ttl = round(item.get("ttl", 0) / 3600, 1)
                is_active = "🎯 *Aktif*" if item.get("key") == best_key else "📦 Backup"
                key_lines.append(
                    f"• *Key {idx}* (`{k_masked}`) [{is_active}]: *{k_cred}* / {k_quota} ({k_stat}) | ~{k_ttl}h"
                )
            
            breakdown_text = "\n".join(key_lines)
            max_ttl_hours = round(max_ttl / 3600, 1) if max_ttl else 0

            msg_content = (
                f"🚨 *STATUS POOL CAPTCHA NOPECHA*\n\n"
                f"{alert_title}\n"
                f"📊 *Total Kredit Pool*: *{total_credit}* / {total_quota} ({len(active_keys)}/{len(keys)} Key Aktif)\n"
                f"🎯 *Key Utama Digunakan*: `{mask_key(best_key)}`\n"
                f"⏳ *Masa Reset Pool*: ~{max_ttl_hours} jam lagi\n\n"
                f"📋 *Rincian Status Key Pool*:\n"
                f"{breakdown_text}\n\n"
                f"⚡ *Info Sistem*: Sistem rotasi otomatis (round-robin / fallback) aktif. Jika Key 1 habis, sistem secara otomatis mengalihkan beban ke Key berikutnya tanpa memutus bot!"
            )

            # Send via Webhook (Routes to WhatsApp)
            try:
                if bot.global_settings_dict.get("webhook", {}).get("enabled", False):
                    webhook_url = (
                        bot.global_settings_dict["webhook"].get("webhookCaptchaUrl")
                        or bot.global_settings_dict["webhook"].get("webhookUrl")
                    )
                    if webhook_url:
                        await bot.webhookSender(
                            msg=alert_title,
                            desc=msg_content,
                            colors="#e74c3c" if alert_type == "danger" else "#f39c12",
                            webhook_url=webhook_url
                        )
                        print(f"📲 [NopeCHA Alert] Peringatan status pool ({total_credit}/{total_quota}) terkirim ke WhatsApp Webhook!")
            except Exception as ex:
                print(f"[NopeCHA Alert Error] Failed sending webhook alert: {ex}")

    return {
        "credit": total_credit,
        "quota": total_quota,
        "status": "Active" if active_keys else "Exhausted",
        "ttl": max_ttl,
        "active_key": best_key,
        "active_count": len(active_keys),
        "keys_count": len(keys),
        "keys": status_list
    }
