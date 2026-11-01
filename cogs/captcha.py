import threading
import time
import re
import os
import sys
import asyncio
import tempfile
import unicodedata

from discord.ext import commands, tasks
from discord import DMChannel

try:
    from utils.nopecha_monitor import (
        check_and_alert_nopecha,
        fetch_nopecha_status,
        sync_nopecha_manifests,
        get_configured_nopecha_keys,
        mask_key
    )
except ImportError:
    check_and_alert_nopecha = None
    fetch_nopecha_status = None
    sync_nopecha_manifests = None
    get_configured_nopecha_keys = None
    mask_key = lambda k: (k[:4] + "***" + k[-3:]) if k and len(k) > 6 else "***"

SOLVER_AVAILABLE = False
MAX_SOLVE_STRATEGIES = 0
try:
    from captcha_solver.solve import solve_captcha, get_strategy_count
    SOLVER_AVAILABLE = True
    MAX_SOLVE_STRATEGIES = get_strategy_count()
except ImportError:
    pass

SELENIUM_AVAILABLE = False
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service
    SELENIUM_AVAILABLE = True
except ImportError:
    pass

CLOAKBROWSER_AVAILABLE = False
try:
    import cloakbrowser
    CLOAKBROWSER_AVAILABLE = True
except ImportError:
    pass

list_captcha = ["human", "captcha", "link", "letterword"]

WRONG_ANSWER_PHRASES = [
    "wrong answer",
    "incorrect",
    "that is not right",
    "try again",
    "wrong! you have",
]

def get_path(path):
    cur_dir = os.getcwd()
    if os.path.isfile(path):

        return path
    audio_folder_path = os.path.join(cur_dir, "audio", path)
    if os.path.isfile(audio_folder_path):

        return audio_folder_path
    file_in_cwd = os.path.join(cur_dir, path)
    if os.path.isfile(file_in_cwd):

        return file_in_cwd

    return None

def normalize(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

def clean(msg):
    return re.sub(r"[^a-zA-Z0-9]", "", normalize(msg))

def is_termux():

    termux_prefix = os.environ.get("PREFIX")
    termux_home = os.environ.get("HOME")
    if termux_prefix and "com.termux" in termux_prefix:
        return True
    if termux_home and "com.termux" in termux_home:
        return True
    return os.path.isdir("/data/data/com.termux")

on_mobile = is_termux()

if not on_mobile:
    from plyer import notification
    from playsound3 import playsound

def run_system_command(command, timeout, retry=False, delay=5):
    def target():
        try:
            os.system(command)
        except Exception as e:
            print(f"Error executing command: {command} - {e}")

    thread = threading.Thread(target=target)
    thread.start()

    thread.join(timeout)

    if thread.is_alive():
        print(f"Error: {command} command failed! (captcha)")
        if retry:
            print(f"Retrying '{command}' after {delay}s")
            time.sleep(delay)
            run_system_command(command, timeout)

def get_channel_name(channel):
    if isinstance(channel, DMChannel):
        return "owo DMs"
    return channel.name

def console_handler(cnf, captcha=True):
    if cnf["runConsoleCommandOnCaptcha"] and captcha:
        run_system_command(cnf["commandToRunOnCaptcha"], timeout=5)
    elif cnf["runConsoleCommandOnBan"] and not captcha:
        run_system_command(cnf["commandToRunOnBan"], timeout=5)

class Captcha(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._solve_attempt: int = 0
        self._solve_max_retries: int = 3
        self._captcha_image_path: str | None = None
        self._captcha_channel = None
        self._solving_active: bool = False
        self._warning_pattern = re.compile(r"\((\d+)/(\d+)\)")
        self._kill_task: asyncio.Task | None = None

        self._driver = None
        self._last_verify_url: str | None = None
        self._wa_msg_id: str | None = None
        self._wa_msg_start_time: float | None = None

        self._is_web_solving: bool = False
        self._solve_requested_again: bool = False
        self._solve_lock: asyncio.Lock = asyncio.Lock()
        self._nopecha_credit: int | None = None
        self._nopecha_quota: int | None = None
        self._nopecha_status: str | None = None
        self._nopecha_ttl: int | None = None
        self._nopecha_active_count: int = 1
        self._nopecha_total_keys: int = 1
        self._nopecha_last_fetch: float = 0

        if check_and_alert_nopecha:
            self.nopecha_health_loop.start()

    async def _refresh_nopecha_status(self, force: bool = False):
        try:
            if not fetch_nopecha_status:
                return None
            now = time.time()
            if not force and (now - self._nopecha_last_fetch < 15) and self._nopecha_credit is not None:
                return {
                    "credit": self._nopecha_credit,
                    "quota": self._nopecha_quota,
                    "status": self._nopecha_status,
                    "ttl": self._nopecha_ttl,
                    "active_count": self._nopecha_active_count,
                    "keys_count": self._nopecha_total_keys
                }
            if check_and_alert_nopecha:
                data = await check_and_alert_nopecha(self.bot, force=force)
            else:
                key = self.bot.global_settings_dict.get("captcha", {}).get("nopecha", {}).get("key", "").strip() or os.environ.get("NOPECHA_KEY", "")
                data = await fetch_nopecha_status(key)
            if data and isinstance(data, dict):
                self._nopecha_credit = data.get("credit", 0)
                self._nopecha_quota = data.get("quota", 200)
                self._nopecha_status = data.get("status", "Active")
                self._nopecha_ttl = data.get("ttl", 0)
                self._nopecha_active_count = data.get("active_count", 1)
                self._nopecha_total_keys = data.get("keys_count", 1)
                self._nopecha_last_fetch = now
                return data
        except Exception as err:
            print(f"[NopeCHA Fetch Error]: {err}")
        return None

    async def update_wa_progress(self, status_title, status_badge, progress_bar, progress_pct, note, color="#f39c12"):
        if not self.bot.global_settings_dict.get("webhook", {}).get("enabled", False):
            return
        from datetime import datetime, timezone, timedelta
        now_str = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M:%S")
        if not self._wa_msg_start_time:
            self._wa_msg_start_time = time.time()
        elapsed_sec = int(time.time() - self._wa_msg_start_time)
        user_mention = f"<@{self.bot.user.id}>" if self.bot.user else "User"

        if self._nopecha_credit is None or (time.time() - self._nopecha_last_fetch > 60):
            await self._refresh_nopecha_status()

        nopecha_line = ""
        if self._nopecha_credit is not None:
            ttl_h = f" (~{round(self._nopecha_ttl / 3600, 1)} jam)" if self._nopecha_ttl else ""
            status_text = f" ({self._nopecha_status})" if self._nopecha_status and self._nopecha_status != "Active" else ""
            pool_info = f" (Pool: {self._nopecha_active_count}/{self._nopecha_total_keys} Keys)" if getattr(self, "_nopecha_total_keys", 1) > 1 else ""
            nopecha_line = f"🎟️ *Sisa Token NopeCHA*: *{self._nopecha_credit}* / {self._nopecha_quota}{pool_info}{status_text}{ttl_h}\n"

        content = (
            f"{status_title}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 *Bot*: `{self.bot.username}` ({user_mention})\n"
            f"📊 *Progress*: `{progress_bar}` *{progress_pct}*\n"
            f"⚙️ *Status*: {status_badge}\n"
            f"🎯 *Engine*: `Camofox Browser + NopeCHA AI`\n"
            f"{nopecha_line}"
            f"⏱️ *Durasi*: `{elapsed_sec}s` | 🕒 `{now_str} WIB`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{note}"
        )

        try:
            resp = await self.bot.webhookSender(
                msg=status_title,
                desc=content,
                colors=color,
                plain_text=content,
                message_id=self._wa_msg_id,
                clean=True,
                webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None)
            )
            if resp and isinstance(resp, dict) and resp.get("messageId") and not self._wa_msg_id:
                self._wa_msg_id = resp["messageId"]
        except Exception as w_err:
            print(f"[WA Progress Error]: {w_err}")


    def cog_unload(self):
        if check_and_alert_nopecha and self.nopecha_health_loop.is_running():
            self.nopecha_health_loop.cancel()
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass

    @tasks.loop(minutes=30)
    async def nopecha_health_loop(self):
        if check_and_alert_nopecha:
            try:
                await check_and_alert_nopecha(self.bot)
            except Exception as e:
                print(f"[NopeCHA Health Check Error]: {e}")

    @nopecha_health_loop.before_loop
    async def before_nopecha_health_loop(self):
        await self.bot.wait_until_ready()

    async def _kill_code(self):
        await asyncio.sleep(600)
        if self.bot.command_handler_status["captcha"]:
            await self.bot.log("Captcha not solved within 10 minutes. Exiting.", "#d70000")
            self.bot.add_dashboard_log("captcha", "Auto-exit: captcha timeout (10 min)", "error")
            os._exit(0)

    def _init_driver(self):

        if not SELENIUM_AVAILABLE or on_mobile:
            return None

        try:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1280,720")
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

            # Load NopeCHA extension if available
            ext_path = os.path.join(os.getcwd(), "extensions", "nopecha")
            if os.path.isdir(ext_path):
                try:
                    np_conf = self.bot.global_settings_dict.get("captcha", {}).get("nopecha", {})
                    if sync_nopecha_manifests and get_configured_nopecha_keys:
                        keys = get_configured_nopecha_keys(np_conf)
                        active_key = np_conf.get("key", "").strip() or (keys[0] if keys else "")
                        sync_nopecha_manifests(keys, active_key)
                except Exception as m_err:
                    print(f"[NopeCHA Manifest Sync Error]: {m_err}")

                options.add_argument(f"--disable-extensions-except={ext_path}")
                options.add_argument(f"--load-extension={ext_path}")
                print(f"🧩 [Web-Solver] NopeCHA extension loaded from: {ext_path}")

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            return driver
        except Exception as e:
            print(f"Failed to init Selenium: {e}")
            return None

    async def _poll_web_captcha_watchdog(self, token, session, max_duration=600):
        """Monitors owobot.com/api/auth in background to automatically resume farming as soon as captcha is solved."""
        start_time = time.time()
        while self.bot.command_handler_status["captcha"] and (time.time() - start_time < max_duration):
            await asyncio.sleep(5)
            try:
                def _check():
                    try:
                        resp = session.get('https://owobot.com/api/auth', timeout=5)
                        if resp.status_code == 200:
                            return resp.json()
                    except Exception:
                        pass
                    return None

                data = await asyncio.to_thread(_check)
                if data and isinstance(data, dict):
                    captcha_info = data.get('captcha', {})
                    if not captcha_info.get('active'):
                        await self._refresh_nopecha_status(force=True)
                        await self.bot.log("✅ [Web-Solver Watchdog] Captcha terverifikasi di server OwO!", "#51cf66")
                        self.bot.add_dashboard_log("captcha", "Web captcha verified via background watchdog", "success")
                        if self._wa_msg_id:
                            await self.update_wa_progress(
                                "✅ *[OWO BOT] CAPTCHA TELAH BERHASIL DISELESAIKAN!*",
                                "🟢 Terverifikasi Human (Success)",
                                "[▓▓▓▓▓▓▓▓▓▓]",
                                "100%",
                                "🎉 *Akun AMAN! Captcha terverifikasi di server OwO. Bot otomatis melanjutkan farming dalam 5 detik.*",
                                color="#51cf66"
                            )
                            self._wa_msg_id = None
                            self._wa_msg_start_time = None
                        elif self.bot.global_settings_dict["webhook"]["enabled"]:
                            nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                            await self.bot.webhookSender(
                                msg=f"✅ [{self.bot.username}] CAPTCHA TELAH BERHASIL DISELESAIKAN!",
                                desc=f"**Status**: Akun AMAN & Terverifikasi human!\n**User**: <@{self.bot.user.id}>{nopecha_token_desc}\nBot otomatis melanjutkan farming dalam 5 detik.",
                                colors="#51cf66",
                                webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                            )
                        self._is_web_solving = False
                        self._solve_requested_again = False
                        await asyncio.sleep(5)
                        self.bot.command_handler_status["captcha"] = False
                        await self.bot.log("🚀 Bot melanjutkan farming secara otomatis!", "#51cf66")
                        break
            except Exception as poll_err:
                print(f"[Captcha Watchdog Error]: {poll_err}")

    async def _handle_web_captcha(self, url="https://owobot.com/captcha"):
        if on_mobile:
            run_system_command(f"termux-open {url}", timeout=10)
            await self.bot.log(f"🔗 Opened captcha link in external browser (Termux)", "#3498db")
            return

        if self._is_web_solving:
            await self.bot.log("ℹ️ [Auto-Solver] Solver sedang aktif memproses captcha, mengantrekan solve ulang jika belum selesai...", "#f39c12")
            self._solve_requested_again = True
            return

        async with self._solve_lock:
            self._is_web_solving = True
            self._solve_requested_again = False
            self._wa_5m_warned = False
            try:
                # Refresh NopeCHA token balance at start of solving
                await self._refresh_nopecha_status(force=True)
                if check_and_alert_nopecha:
                    await check_and_alert_nopecha(self.bot)

                # Step 1: Inisialisasi & OAuth
                await self.update_wa_progress(
                    "🚨 *[OWO BOT] CAPTCHA TERDETEKSI!*",
                    "🔄 Otorisasi Discord OAuth & Sinkronisasi Sesi",
                    "[▓▓▓░░░░░░░]",
                    "30%",
                    "⚠️ *Bot di-pause sementara. Mempersiapkan browser Camofox & sesi login...*",
                    color="#f39c12"
                )

                await self.bot.log(f"🌐 [Auto-Solver] Memulai otorisasi OAuth & pemecahan Web Captcha...", "#3498db")
                self.bot.add_dashboard_log("captcha", "Web-Solver running...", "warning")

                token = self.bot.token
                if not token:
                    await self.bot.log("❌ [Auto-Solver] Token Discord tidak ditemukan", "#c25560")
                    await self.update_wa_progress(
                        "❌ *[OWO BOT] GAGAL MEMULAI SOLVER*",
                        "🔴 Token Discord Tidak Ditemukan",
                        "[▓▓▓▓▓▓▓▓▓▓]",
                        "GAGAL",
                        "🚨 *Token akun tidak valid / tidak ditemukan. Bot dihentikan.*",
                        color="#d70000"
                    )
                    return

                import requests
                headers = {
                    'Authorization': token,
                    'Content-Type': 'application/json',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://discord.com/api/v9/oauth2/authorize?client_id=408785106942164992&response_type=code&redirect_uri=https://owobot.com/api/auth/discord/redirect&scope=identify%20guilds'
                }
                s = requests.Session()
                r_oauth = await asyncio.to_thread(
                    s.post,
                    'https://discord.com/api/v9/oauth2/authorize?client_id=408785106942164992&response_type=code&redirect_uri=https://owobot.com/api/auth/discord/redirect&scope=identify%20guilds',
                    json={'authorize': True, 'integration_type': 0, 'permissions': '0', 'location_context': {'guild_id': '10000', 'channel_id': '10000', 'channel_type': 10000}},
                    headers=headers,
                    timeout=15
                )

                if r_oauth.status_code != 200:
                    await self.bot.log(f"❌ [Auto-Solver] Discord OAuth gagal (HTTP {r_oauth.status_code})", "#c25560")
                    await self.update_wa_progress(
                        "❌ *[OWO BOT] DISCORD OAUTH GAGAL*",
                        f"🔴 HTTP {r_oauth.status_code}",
                        "[▓▓▓▓▓▓▓▓▓▓]",
                        "GAGAL",
                        "🚨 *Gagal mengotorisasi sesi OAuth Discord. Silakan selesaikan manual:*\n🔗 https://owobot.com/captcha",
                        color="#d70000"
                    )
                    return

                loc = r_oauth.json().get('location')
                if not loc:
                    await self.bot.log("❌ [Auto-Solver] Location redirect OAuth tidak ditemukan", "#c25560")
                    return

                # Follow redirect to authenticate session
                await asyncio.to_thread(s.get, loc, timeout=15)
                cookies = s.cookies.get_dict()

                # Check if captcha is already inactive
                auth_chk = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=10).json() if s.get('https://owobot.com/api/auth', timeout=10).status_code == 200 else {})
                if not auth_chk.get('captcha', {}).get('active'):
                    await self._refresh_nopecha_status(force=True)
                    await self.bot.log("✅ [Auto-Solver] Captcha sudah tidak aktif / terverifikasi!", "#51cf66")
                    await self.update_wa_progress(
                        "✅ *[OWO BOT] CAPTCHA SUDAH TIDAK AKTIF!*",
                        "🟢 Sudah Terverifikasi",
                        "[▓▓▓▓▓▓▓▓▓▓]",
                        "100%",
                        "🎉 *Captcha sudah selesai sebelumnya! Bot melanjutkan farming secara otomatis.*",
                        color="#51cf66"
                    )
                    self._wa_msg_id = None
                    self._wa_msg_start_time = None
                    self.bot.command_handler_status["captcha"] = False
                    return

                # Launch background watchdog so any solve (via Camofox, Selenium, or user on mobile/PC) immediately unpauses farming
                asyncio.create_task(self._poll_web_captcha_watchdog(token, s))

                # Step 2: Meluncurkan Solver Camofox + Ekstensi NopeCHA
                await self.update_wa_progress(
                    "🦊 *[OWO BOT] MEMBUKA CAMOFOX BROWSER*",
                    "🌐 Menavigasi ke owobot.com/captcha",
                    "[▓▓▓▓▓░░░░░]",
                    "55%",
                    "🧩 *Sesi browser aktif. Menghubungkan ekstensi NopeCHA ke widget hCaptcha...*",
                    color="#3498db"
                )

                # --- Solver Engine 1: Camofox Browser Service (Port 9377) + NopeCHA Extension ---
                async def _try_camofox_solve(cookies_dict, attempt_num=1, active_key=None):
                    try:
                        chk = await asyncio.to_thread(requests.get, "http://localhost:9377/tabs", timeout=3)
                        if chk.status_code != 200:
                            return False, "Camofox service not responding"

                        masked_k = mask_key(active_key) if active_key else "default"
                        await self.bot.log(f"🦊 [Camofox] Membuka sesi captcha anti-detection di Camofox Browser (Attempt #{attempt_num} - Key: {masked_k})...", "#3498db")

                        camofox_user = f"user_{self.bot.user.id}" if self.bot.user else "default"

                        # 0. Reset any stale session for this bot to prevent account mix-ups
                        try:
                            await asyncio.to_thread(
                                requests.delete,
                                f"http://localhost:9377/sessions/{camofox_user}",
                                timeout=5
                            )
                        except Exception:
                            pass

                        # 1. Sync session cookies to Camofox for domain owobot.com
                        camo_cookies = []
                        for k, v in cookies_dict.items():
                            camo_cookies.append({"name": k, "value": v, "domain": "owobot.com", "path": "/"})
                            camo_cookies.append({"name": k, "value": v, "domain": ".owobot.com", "path": "/"})

                        try:
                            await asyncio.to_thread(
                                requests.post,
                                f"http://localhost:9377/sessions/{camofox_user}/cookies",
                                json={"cookies": camo_cookies},
                                timeout=5
                            )
                        except Exception as c_err:
                            print(f"[Camofox Cookie Sync Warning]: {c_err}")

                        # 2. Open owobot.com/captcha in Camofox
                        tab_res = await asyncio.to_thread(
                            requests.post,
                            "http://localhost:9377/tabs",
                            json={"userId": camofox_user, "sessionKey": camofox_user, "url": "https://owobot.com/captcha"},
                            timeout=20
                        )
                        tab_data = tab_res.json()
                        tab_id = tab_data.get("tabId")
                        if not tab_id:
                            return False, "Failed to create Camofox tab"

                        try:
                            # Wait for page to load
                            await asyncio.sleep(4)

                            # Poll for up to 50 seconds (25 iterations * 2s) while NopeCHA auto-solves
                            for _ in range(25):
                                await asyncio.sleep(2)
                                chk_auth = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=5).json() if s.get('https://owobot.com/api/auth', timeout=5).status_code == 200 else {})
                                if not chk_auth.get('captcha', {}).get('active'):
                                    return True, "Solved via Camofox + NopeCHA"

                                # Also verify via page content
                                try:
                                    eval_res = await asyncio.to_thread(
                                        requests.post,
                                        f"http://localhost:9377/tabs/{tab_id}/evaluate",
                                        json={
                                            "userId": camofox_user,
                                            "expression": "(() => { const b = document.body ? document.body.innerText.toLowerCase() : ''; return b.includes('verified') || b.includes('thank') || b.includes('success'); })()"
                                        },
                                        timeout=3
                                    )
                                    if eval_res.status_code == 200 and eval_res.json().get('result') is True:
                                        return True, "Solved via Camofox + NopeCHA (Page Verified)"
                                except Exception:
                                    pass

                            return False, "Camofox timed out waiting for NopeCHA solve"
                        finally:
                            try:
                                await asyncio.to_thread(requests.delete, f"http://localhost:9377/tabs/{tab_id}?userId={camofox_user}", timeout=5)
                            except Exception:
                                pass
                    except Exception as cf_err:
                        return False, f"Camofox error: {cf_err}"

                # --- Solver Engine 2: Stealth CloakBrowser (58 C++ Patches) + NopeCHA Extension ---
                async def _solve_via_cloakbrowser(cookies_dict, attempt_num=1, active_key=None):
                    if not CLOAKBROWSER_AVAILABLE:
                        return False, "CloakBrowser module not installed"

                    ext_path = os.path.join(os.getcwd(), 'extensions', 'nopecha')
                    masked_k = mask_key(active_key) if active_key else "default"
                    await self.bot.log(f"🛡️ [CloakBrowser] Membuka Stealth Chromium Engine (Attempt #{attempt_num} - Key: {masked_k})...", "#9b59b6")

                    temp_dir = None
                    context = None
                    try:
                        import tempfile, shutil
                        temp_dir = tempfile.mkdtemp(prefix='owomizu_cloak_')

                        args = [
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-gpu",
                            "--window-size=1280,800"
                        ]
                        if os.path.isdir(ext_path):
                            args.extend([
                                f"--disable-extensions-except={ext_path}",
                                f"--load-extension={ext_path}"
                            ])

                        context = await cloakbrowser.launch_persistent_context_async(
                            temp_dir,
                            headless=True,
                            args=args,
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        )

                        # Set cookies for owobot.com
                        pw_cookies = []
                        for c_name, c_val in cookies_dict.items():
                            pw_cookies.append({
                                "name": c_name,
                                "value": c_val,
                                "domain": ".owobot.com",
                                "path": "/"
                            })
                            pw_cookies.append({
                                "name": c_name,
                                "value": c_val,
                                "domain": "owobot.com",
                                "path": "/"
                            })
                        await context.add_cookies(pw_cookies)

                        page = context.pages[0] if context.pages else await context.new_page()

                        # Navigate to owobot.com/captcha
                        await page.goto("https://owobot.com/captcha", wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(3)

                        # 1. Click checkbox if present
                        for fr in page.frames:
                            u = fr.url or ""
                            if "frame=checkbox" in u:
                                for sel in ("#checkbox", "div[role=checkbox]", "label", "body"):
                                    try:
                                        await fr.click(sel, timeout=2000)
                                        break
                                    except Exception:
                                        pass
                                break

                        # 2. Polling loop with multi-challenge auto-refresh
                        session_start = time.time()
                        max_duration = 180
                        refresh_count = 0
                        consecutive_unsupported = 0

                        for iteration_idx in range(1, 35):
                            if time.time() - session_start >= max_duration:
                                break

                            # A. Check API auth
                            try:
                                auth_c = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=3).json() if s.get('https://owobot.com/api/auth', timeout=3).status_code == 200 else {})
                                if not auth_c.get('captcha', {}).get('active'):
                                    return True, f"Solved via CloakBrowser (Auth Verified in Iteration {iteration_idx})"
                            except Exception:
                                pass

                            # B. Check page text
                            try:
                                body_text = await page.inner_text('body', timeout=1000)
                                body_lower = body_text.lower()
                                if any(w in body_lower for w in ['verified', 'thank', 'success']):
                                    return True, "Solved via CloakBrowser (Page Verified)"
                            except Exception:
                                pass

                            # C. Find challenge frame
                            challenge_frame = None
                            for fr in page.frames:
                                u = fr.url or ""
                                if "frame=challenge" in u:
                                    challenge_frame = fr
                                    break

                            if not challenge_frame:
                                await asyncio.sleep(2)
                                for fr in page.frames:
                                    if "frame=checkbox" in (fr.url or ""):
                                        try:
                                            await fr.click("#checkbox", timeout=1500)
                                        except Exception:
                                            pass
                                continue

                            # D. Evaluate prompt
                            prompt_text = ""
                            try:
                                p_el = await challenge_frame.query_selector('.prompt-text, h2, .challenge-header')
                                if p_el:
                                    prompt_text = (await p_el.inner_text()).strip().replace('\n', ' ')
                            except Exception:
                                pass

                            has_grid = (await challenge_frame.query_selector('.task-image, .image, .task-cell')) is not None
                            has_canvas = (await challenge_frame.query_selector('canvas')) is not None
                            is_unsupported = has_canvas or any(kw in prompt_text.lower() for kw in [
                                'drag', 'fits', 'fit', 'inhabit', 'creatures that', 'places like this',
                                'tower', 'block', 'screw', 'joint', 'puzzle', 'slide', 'move'
                            ])

                            # Refresh if dynamic/unsupported challenge
                            if is_unsupported or not has_grid:
                                refresh_count += 1
                                consecutive_unsupported += 1
                                try:
                                    ref_btn = await challenge_frame.query_selector("div.refresh.button, [aria-label*='Refresh'], .button-reload")
                                    if ref_btn:
                                        await ref_btn.click(timeout=2000)
                                except Exception:
                                    pass

                                if consecutive_unsupported >= 6:
                                    consecutive_unsupported = 0
                                    await page.goto("https://owobot.com/captcha", wait_until="domcontentloaded", timeout=20000)
                                    await asyncio.sleep(2)
                                    for fr in page.frames:
                                        if "frame=checkbox" in (fr.url or ""):
                                            try:
                                                await fr.click("#checkbox", timeout=2000)
                                            except Exception:
                                                pass
                                else:
                                    await asyncio.sleep(2)
                                continue

                            # Grid challenge: tunggu NopeCHA memilih dan submit
                            consecutive_unsupported = 0
                            grid_solved = False
                            for _ in range(6):
                                await asyncio.sleep(2)
                                try:
                                    auth_c = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=3).json() if s.get('https://owobot.com/api/auth', timeout=3).status_code == 200 else {})
                                    if not auth_c.get('captcha', {}).get('active'):
                                        return True, "Solved via CloakBrowser + NopeCHA (Grid Verified)"
                                except Exception:
                                    pass

                                try:
                                    submit_btn = await challenge_frame.query_selector('.button-submit')
                                    if submit_btn:
                                        b_txt = (await submit_btn.inner_text()).strip().lower()
                                        if b_txt in ['next', 'verify']:
                                            await submit_btn.click(timeout=2000)
                                            grid_solved = True
                                            break
                                except Exception:
                                    pass

                            if grid_solved:
                                await asyncio.sleep(2.5)
                                try:
                                    auth_c = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=3).json() if s.get('https://owobot.com/api/auth', timeout=3).status_code == 200 else {})
                                    if not auth_c.get('captcha', {}).get('active'):
                                        return True, "Solved via CloakBrowser + NopeCHA (Grid Complete)"
                                except Exception:
                                    pass
                                continue
                            else:
                                refresh_count += 1
                                try:
                                    ref_btn = await challenge_frame.query_selector("div.refresh.button, [aria-label*='Refresh'], .button-reload")
                                    if ref_btn:
                                        await ref_btn.click(timeout=2000)
                                except Exception:
                                    pass
                                await asyncio.sleep(1.5)
                                continue

                        # Final verification check
                        try:
                            auth_c = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=4).json() if s.get('https://owobot.com/api/auth', timeout=4).status_code == 200 else {})
                            if not auth_c.get('captcha', {}).get('active'):
                                return True, "Solved via CloakBrowser (Final Check)"
                        except Exception:
                            pass

                        return False, f"CloakBrowser timed out after {refresh_count} refreshes"

                    except Exception as err:
                        return False, f"CloakBrowser error: {err}"
                    finally:
                        if context:
                            try:
                                await context.close()
                            except Exception:
                                pass
                        if temp_dir:
                            try:
                                import shutil
                                shutil.rmtree(temp_dir, ignore_errors=True)
                            except Exception:
                                pass

                # --- Solver Engine 3 (Legacy): Hardened Selenium with Visual & Auto-Refresh ---
                def _solve_via_selenium(active_key=None):
                    if not SELENIUM_AVAILABLE:
                        return False, "Selenium is not available"

                    ext_path = os.path.join(os.getcwd(), 'extensions', 'nopecha')
                    sel_key = active_key or self.bot.global_settings_dict.get("captcha", {}).get("nopecha", {}).get("key", "").strip() or os.environ.get("NOPECHA_KEY", "")

                    options = webdriver.ChromeOptions()
                    options.add_argument('--headless=new')
                    options.add_argument('--disable-gpu')
                    options.add_argument('--no-sandbox')
                    options.add_argument('--disable-dev-shm-usage')
                    options.add_argument('--disable-setuid-sandbox')
                    options.add_argument('--disable-software-rasterizer')
                    options.add_argument('--disable-site-isolation-trials')
                    options.add_argument('--disable-features=IsolateOrigins,site-per-process')
                    options.add_argument('--window-size=1280,800')
                    
                    temp_user_data = None
                    try:
                        import tempfile
                        temp_user_data = tempfile.mkdtemp(prefix='owomizu_sel_')
                        options.add_argument(f'--user-data-dir={temp_user_data}')
                    except Exception:
                        pass

                    if os.path.isdir(ext_path):
                        options.add_argument(f'--disable-extensions-except={ext_path}')
                        options.add_argument(f'--load-extension={ext_path}')
                    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

                    cft_bin = '/home/ndenn25/.local/browsers/chrome/linux-151.0.7922.71/chrome-linux64/chrome'
                    cft_driver = '/home/ndenn25/.wdm/drivers/chromedriver/linux64/151.0.7922.138/chromedriver-linux64/chromedriver'

                    driver = None
                    try:
                        if os.path.exists(cft_bin) and os.path.exists(cft_driver):
                            options.binary_location = cft_bin
                            service = Service(cft_driver)
                            driver = webdriver.Chrome(service=service, options=options)
                        else:
                            service = Service(ChromeDriverManager().install())
                            driver = webdriver.Chrome(service=service, options=options)

                        driver.get('https://owobot.com')
                        time.sleep(1)

                        for c_name, c_val in cookies.items():
                            driver.add_cookie({
                                'name': c_name,
                                'value': c_val,
                                'domain': 'owobot.com'
                            })

                        driver.get('https://owobot.com/captcha')
                        time.sleep(3)

                        # 1. Click checkbox
                        for iframe in driver.find_elements(By.TAG_NAME, 'iframe'):
                            src = iframe.get_attribute('src') or ''
                            if 'frame=checkbox' in src:
                                driver.switch_to.frame(iframe)
                                time.sleep(0.5)
                                try:
                                    driver.find_element(By.ID, 'checkbox').click()
                                except Exception:
                                    driver.find_element(By.TAG_NAME, 'body').click()
                                driver.switch_to.default_content()
                                break

                        time.sleep(3)

                        # Helper detection function for jump challenges
                        def _detect_jump_character(img_path, p_text):
                            try:
                                import cv2, numpy as np
                                img = cv2.imread(img_path)
                                if img is None:
                                    return None
                                columns = [
                                    ('Left', 100, 205),
                                    ('Center', 205, 295),
                                    ('Right', 295, 400)
                                ]
                                chars = []
                                for name, x1, x2 in columns:
                                    col_img = img[140:410, x1:x2]
                                    gray = cv2.cvtColor(col_img, cv2.COLOR_BGR2GRAY)
                                    edges = cv2.Canny(gray, 25, 100)
                                    ys, xs = np.where(edges > 0)
                                    if len(ys) > 30:
                                        center_x = int(np.median(xs) + x1)
                                        center_y = int(np.median(ys) + 140)
                                        chars.append({'col': name, 'x': center_x, 'y': center_y})
                                if not chars:
                                    return None
                                if 'highest' in p_text.lower():
                                    return min(chars, key=lambda c: c['y'])
                                else:
                                    return max(chars, key=lambda c: c['y'])
                            except Exception:
                                return None

                        from selenium.webdriver.common.action_chains import ActionChains

                        # 2. Persistent Multi-Challenge Solve & Auto-Refresh Engine
                        # Jika NopeCHA tidak bisa solve (unsupported / stuck), otomatis REFRESH dan coba solve lagi!
                        session_start = time.time()
                        max_session_duration = 280  # Maksimal ~4.5 menit per sesi browser
                        max_iterations = 45
                        refresh_count = 0
                        consecutive_unsupported = 0

                        for iteration_idx in range(1, max_iterations + 1):
                            if time.time() - session_start >= max_session_duration:
                                break

                            # A. Cek status API resmi OwO di setiap iterasi
                            try:
                                auth_c = s.get('https://owobot.com/api/auth', timeout=3).json()
                                if not auth_c.get('captcha', {}).get('active'):
                                    return True, f"Solved via API Auth (Verified in Iteration {iteration_idx})"
                            except Exception:
                                pass

                            # B. Cari frame challenge yang aktif
                            challenge_frame = None
                            for f in driver.find_elements(By.TAG_NAME, 'iframe'):
                                src = f.get_attribute('src') or ''
                                if 'frame=challenge' in src and f.is_displayed():
                                    challenge_frame = f
                                    break

                            if not challenge_frame:
                                time.sleep(1.5)
                                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                                if any(w in page_text for w in ['verified', 'thank', 'success']):
                                    return True, "Solved via Page Text (Verified)"

                                # Jika checkbox belum dicentang atau tertutup, klik kembali
                                for f in driver.find_elements(By.TAG_NAME, 'iframe'):
                                    src = f.get_attribute('src') or ''
                                    if 'frame=checkbox' in src:
                                        try:
                                            driver.switch_to.frame(f)
                                            driver.find_element(By.ID, 'checkbox').click()
                                            driver.switch_to.default_content()
                                            time.sleep(2)
                                        except Exception:
                                            driver.switch_to.default_content()
                                        break
                                continue

                            # C. Masuk ke dalam frame challenge untuk evaluasi soal
                            driver.switch_to.frame(challenge_frame)
                            time.sleep(0.8)

                            prompt_text = ""
                            try:
                                p_el = driver.find_element(By.CSS_SELECTOR, '.prompt-text, h2, .challenge-header')
                                prompt_text = p_el.text.strip().replace('\n', ' ')
                            except Exception:
                                pass

                            has_grid = len(driver.find_elements(By.CSS_SELECTOR, '.task-image, .image, .task-cell')) > 0
                            has_canvas = len(driver.find_elements(By.TAG_NAME, 'canvas')) > 0
                            is_jump = has_canvas and any(kw in prompt_text.lower() for kw in ['jump', 'highest', 'lowest'])
                            is_unsupported = (has_canvas and not is_jump) or any(kw in prompt_text.lower() for kw in [
                                'drag', 'fits', 'fit', 'inhabit', 'creatures that', 'places like this',
                                'tower', 'block', 'screw', 'joint', 'puzzle', 'slide', 'move'
                            ])

                            # KASUS 1: Soal Lompat Canvas -> Pecahkan dengan Computer Vision
                            if is_jump:
                                con_jump_solved = False
                                try:
                                    canvas = driver.find_element(By.TAG_NAME, 'canvas')
                                    c_w = canvas.size['width']
                                    c_h = canvas.size['height']
                                    shot_file = f'/tmp/hcap_jump_{iteration_idx}.png'
                                    canvas.screenshot(shot_file)
                                    target = _detect_jump_character(shot_file, prompt_text)
                                    if target:
                                        off_x = target['x'] - c_w // 2
                                        off_y = target['y'] - c_h // 2
                                        ActionChains(driver).move_to_element_with_offset(canvas, off_x, off_y).click().perform()
                                        time.sleep(1)
                                        submit_btn = driver.find_element(By.CSS_SELECTOR, '.button-submit')
                                        b_txt = submit_btn.text.strip().lower()
                                        if b_txt in ['next', 'verify']:
                                            driver.execute_script("arguments[0].click();", submit_btn)
                                            con_jump_solved = True
                                except Exception:
                                    pass

                                if con_jump_solved:
                                    driver.switch_to.default_content()
                                    time.sleep(2.5)
                                    continue
                                else:
                                    # Jika jump gagal/tidak terdeteksi, klik REFRESH untuk ganti soal!
                                    refresh_count += 1
                                    try:
                                        ref_btn = driver.find_element(By.CSS_SELECTOR, "div.refresh.button, [aria-label*='Refresh'], .button-reload")
                                        driver.execute_script("arguments[0].click();", ref_btn)
                                    except Exception:
                                        pass
                                    driver.switch_to.default_content()
                                    time.sleep(2)
                                    continue

                            # KASUS 2: Soal Dinamis / Drag-and-Drop (NopeCHA Tidak Bisa) -> OTOMATIS REFRESH!
                            if is_unsupported or not has_grid:
                                refresh_count += 1
                                consecutive_unsupported += 1
                                old_p = prompt_text
                                try:
                                    ref_btn = driver.find_element(By.CSS_SELECTOR, "div.refresh.button, [aria-label*='Refresh'], .button-reload")
                                    driver.execute_script("arguments[0].click();", ref_btn)
                                    # Tunggu pergantian teks prompt soal baru
                                    for _ in range(6):
                                        time.sleep(0.4)
                                        try:
                                            new_p = driver.find_element(By.CSS_SELECTOR, '.prompt-text, h2, .challenge-header').text.strip().replace('\n', ' ')
                                            if new_p and new_p != old_p:
                                                break
                                        except Exception:
                                            pass
                                except Exception:
                                    pass

                                driver.switch_to.default_content()

                                # Jika berturut-turut mendapat soal dinamis 6x, reload halaman penuh untuk reset sesi
                                if consecutive_unsupported >= 6:
                                    consecutive_unsupported = 0
                                    driver.get('https://owobot.com/captcha')
                                    time.sleep(2.5)
                                    # Centang ulang checkbox
                                    for f in driver.find_elements(By.TAG_NAME, 'iframe'):
                                        if 'frame=checkbox' in (f.get_attribute('src') or ''):
                                            try:
                                                driver.switch_to.frame(f)
                                                driver.find_element(By.ID, 'checkbox').click()
                                                driver.switch_to.default_content()
                                            except Exception:
                                                driver.switch_to.default_content()
                                            break
                                    time.sleep(2)
                                else:
                                    time.sleep(1.5)
                                continue

                            # KASUS 3: Grid 3x3 Standar -> Serahkan ke NopeCHA, Assist Submit, dan Refresh jika Stuck!
                            consecutive_unsupported = 0
                            grid_solved = False

                            # Beri waktu NopeCHA hingga 14 detik untuk menganalisis dan memilih gambar
                            for _ in range(7):
                                time.sleep(2)
                                try:
                                    auth_c = s.get('https://owobot.com/api/auth', timeout=3).json()
                                    if not auth_c.get('captcha', {}).get('active'):
                                        return True, "Solved via NopeCHA Extension (Grid API Verified)"
                                except Exception:
                                    pass

                                try:
                                    submit_btn = driver.find_element(By.CSS_SELECTOR, '.button-submit')
                                    b_txt = submit_btn.text.strip().lower()
                                    if b_txt in ['next', 'verify']:
                                        # NopeCHA berhasil memilih gambar! Klik submit langsung!
                                        time.sleep(0.4)
                                        driver.execute_script("arguments[0].click();", submit_btn)
                                        grid_solved = True
                                        break
                                except Exception:
                                    pass

                            if grid_solved:
                                driver.switch_to.default_content()
                                time.sleep(2.5)
                                # Cek apakah sudah terverifikasi selesai
                                try:
                                    auth_c = s.get('https://owobot.com/api/auth', timeout=3).json()
                                    if not auth_c.get('captcha', {}).get('active'):
                                        return True, "Solved via NopeCHA Extension (Grid Verified)"
                                except Exception:
                                    pass
                                continue
                            else:
                                # Jika setelah 14 detik NopeCHA gagal memilih (stuck pada 'Skip') -> KLIK REFRESH!
                                refresh_count += 1
                                try:
                                    ref_btn = driver.find_element(By.CSS_SELECTOR, "div.refresh.button, [aria-label*='Refresh'], .button-reload")
                                    driver.execute_script("arguments[0].click();", ref_btn)
                                    time.sleep(1.5)
                                except Exception:
                                    pass
                                driver.switch_to.default_content()
                                time.sleep(1.5)
                                continue

                        # Final verification check di akhir sesi
                        time.sleep(1)
                        try:
                            auth_c = s.get('https://owobot.com/api/auth', timeout=4).json()
                            if not auth_c.get('captcha', {}).get('active'):
                                return True, "Solved via API Auth (Final Session Check)"
                        except Exception:
                            pass
                        return False, f"Completed {iteration_idx} challenge cycles ({refresh_count} refreshes) without solve"
                    except Exception as err:
                        return False, f"Selenium execution error: {err}"
                    finally:
                        if driver:
                            try:
                                driver.quit()
                            except Exception:
                                pass
                        if temp_user_data:
                            try:
                                import shutil
                                shutil.rmtree(temp_user_data, ignore_errors=True)
                            except Exception:
                                pass

                # --- Solver Engine: Multi-Key Persistent Retry Loop ("Sampe Bisa") ---
                np_conf = self.bot.global_settings_dict.get("captcha", {}).get("nopecha", {})
                keys = get_configured_nopecha_keys(np_conf) if get_configured_nopecha_keys else []
                if not keys:
                    keys = [k for k in (self.bot.global_settings_dict.get("captcha", {}).get("nopecha", {}).get("keys", []) or [os.environ.get("NOPECHA_KEY", "")]) if k]

                start_solve_time = time.time()
                # 420 detik (7 menit): Batas aman KETAT sebelum 10 menit batas ban OwO!
                max_solve_duration = 420
                attempt_idx = 0
                solved = False
                solve_reason = "Belum berhasil"

                while self.bot.command_handler_status.get("captcha", False):
                    elapsed = time.time() - start_solve_time
                    if elapsed >= max_solve_duration:
                        await self.bot.log(f"⏰ [Auto-Solver] Batas waktu auto-solve tercapai ({int(elapsed)}s). Menghentikan percobaan loop.", "#d70000")
                        break

                    # Peringatan Darurat 5 Menit (Sisa 5 Menit sebelum batas Ban OwO 10 Menit)
                    if elapsed >= 300 and not getattr(self, '_wa_5m_warned', False):
                        self._wa_5m_warned = True
                        await self.bot.log(f"⚠️ [Auto-Solver] PERINGATAN: Auto-solve telah berjalan 5 menit! Sisa waktu 5 menit sebelum batas ban OwO.", "#f39c12")
                        await self.update_wa_progress(
                            "⚠️ *[OWO BOT] PERINGATAN 5 MENIT CAPTCHA!*",
                            "🟡 5 Menit Terlewati (Batas 10 Menit)",
                            "[▓▓▓▓▓▓▓░░░]",
                            "50%",
                            f"⚠️ *PERINGATAN:* Captcha telah berjalan 5 menit dan masih dalam proses auto-solve (Attempt #{attempt_idx + 1}).\n"
                            f"⏰ Batas waktu server OwO adalah *10 menit* (sisa ~5 menit) sebelum risiko ban 372H.\n"
                            f"👉 Selesaikan manual di: https://owobot.com/captcha jika ingin aman.",
                            color="#f39c12"
                        )
                        if self.bot.global_settings_dict.get("webhook", {}).get("enabled", True):
                            await self.bot.webhookSender(
                                msg=f"⚠️ [{self.bot.username}] PERINGATAN 5 MENIT CAPTCHA",
                                desc=f"Captcha telah berjalan 5 menit! Sisa waktu ~5 menit sebelum batas ban OwO.\n**Link**: https://owobot.com/captcha",
                                colors="#f39c12",
                                webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                            )

                    attempt_idx += 1
                    # Round-robin key selection from pool
                    key_idx = (attempt_idx - 1) % len(keys)
                    current_key = keys[key_idx]
                    key_num = key_idx + 1

                    # Update bot global settings & sync manifests
                    self.bot.global_settings_dict["captcha"]["nopecha"]["key"] = current_key
                    if sync_nopecha_manifests:
                        sync_nopecha_manifests(keys, current_key)

                    masked_k = mask_key(current_key) if mask_key else current_key[:4] + "***"

                    # 1. Quick pre-check if solved in background or via auth
                    try:
                        auth_chk = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=5).json() if s.get('https://owobot.com/api/auth', timeout=5).status_code == 200 else {})
                        if not auth_chk.get('captcha', {}).get('active'):
                            solved = True
                            solve_reason = "Solved via server verification"
                            break
                    except Exception:
                        pass

                    # 2. Engine: Coba Camofox Browser terlebih dahulu. Jika gagal/offline, fallback ke CloakBrowser Stealth Engine!
                    pct = min(95, 60 + ((attempt_idx - 1) % 7) * 5)
                    await self.update_wa_progress(
                        f"⚡ *[OWO BOT] MENYELESAIKAN HCAPTCHA (Attempt #{attempt_idx})*",
                        f"🔄 Camofox / CloakBrowser | Key {key_num} ({masked_k})",
                        "[▓▓▓▓▓▓▓▓░░]",
                        f"{pct}%",
                        f"🤖 *Percobaan #{attempt_idx} (Camofox & CloakBrowser Stealth). Sistem me-retry otomatis sampai berhasil...*",
                        color="#9b59b6"
                    )

                    # Tier 1: Coba Camofox Browser
                    await self.bot.log(f"🦊 [Auto-Solver] Menjalankan Camofox Browser (Attempt #{attempt_idx} - Key #{key_num}: {masked_k})...", "#3498db")
                    solved, solve_reason = await _try_camofox_solve(cookies, attempt_num=attempt_idx, active_key=current_key)

                    # Tier 2: Jika Camofox belum berhasil, fallback langsung ke CloakBrowser Stealth Engine
                    if not solved:
                        if CLOAKBROWSER_AVAILABLE:
                            await self.bot.log(f"🛡️ [Auto-Solver] Camofox belum berhasil ({solve_reason}). Beralih ke Fallback: CloakBrowser Stealth Engine...", "#9b59b6")
                            solved, solve_reason = await _solve_via_cloakbrowser(cookies, attempt_num=attempt_idx, active_key=current_key)
                        elif SELENIUM_AVAILABLE:
                            await self.bot.log(f"🌐 [Auto-Solver] CloakBrowser tidak tersedia, mencoba Selenium Fallback...", "#3498db")
                            solved, solve_reason = await asyncio.to_thread(_solve_via_selenium, current_key)

                    if solved:
                        break

                    # 3. Quick post-check if solved in background during solve attempt
                    try:
                        chk_mid = await asyncio.to_thread(lambda: s.get('https://owobot.com/api/auth', timeout=5).json() if s.get('https://owobot.com/api/auth', timeout=5).status_code == 200 else {})
                        if not chk_mid.get('captcha', {}).get('active'):
                            solved = True
                            solve_reason = "Solved via background verification"
                            break
                    except Exception:
                        pass

                    # 4. Jika belum berhasil dan captcha masih aktif, rotasi key dan retry
                    if self.bot.command_handler_status.get("captcha", False):
                        await self.bot.log(f"⚠️ [Auto-Solver] Attempt #{attempt_idx} belum berhasil ({solve_reason}). Merotasi key ke Key #{(key_idx + 1) % len(keys) + 1} & mencoba kembali...", "#f39c12")
                        await asyncio.sleep(4)

                if solved:
                    await self._refresh_nopecha_status(force=True)
                    await self.bot.log(f"✅ [Auto-Solver] Captcha berhasil dipecahkan pada Attempt #{attempt_idx}! ({solve_reason})", "#51cf66")
                    self.bot.add_dashboard_log("captcha", f"Solved hCaptcha on Attempt {attempt_idx} ({solve_reason})", "success")

                    # Step 4A: Sukses terpecahkan -> Edit pesan WhatsApp ke status SUKSES!
                    await self.update_wa_progress(
                        "✅ *[OWO BOT] CAPTCHA BERHASIL DISELESAIKAN!*",
                        "🟢 Terverifikasi Human (Success)",
                        "[▓▓▓▓▓▓▓▓▓▓]",
                        "100%",
                        f"🎉 *Akun AMAN! hCaptcha berhasil dipecahkan pada Attempt #{attempt_idx} ({solve_reason}). Bot otomatis melanjutkan farming dalam 5 detik.*",
                        color="#51cf66"
                    )
                    self._wa_msg_id = None
                    self._wa_msg_start_time = None

                    await asyncio.sleep(5)
                    self.bot.command_handler_status["captcha"] = False
                    await self.bot.log("🚀 Bot melanjutkan farming secara otomatis!", "#51cf66")
                    return
                else:
                    await self._refresh_nopecha_status(force=True)
                    await self.bot.log(f"🛑 [CRITICAL SAFETY LOCKOUT] Batas 7 menit tercapai! Auto-solve loop selesai setelah {attempt_idx} percobaan ({solve_reason}).", "#d70000")

                    # CRITICAL ANTI-BAN LOCKDOWN: Matikan bot total agar tidak mengirim command ke OwO setelah menit ke-10!
                    self.bot.command_handler_status["state"] = False
                    self.bot.command_handler_status["captcha"] = True
                    await self.bot.log("🛑 [SAFETY LOCKDOWN] Bot DIMATIKAN TOTAL (state = False)! Selesaikan manual di https://owobot.com/captcha sebelum batas 10 menit untuk mencegah ban 372H!", "#d70000")
                    self.bot.add_dashboard_log("captcha", "CRITICAL: Bot stopped to prevent 10-minute ban timeout", "critical")

                    await self.update_wa_progress(
                        "🚨 *[OWO BOT] EMERGENCY SAFETY LOCKOUT*",
                        "🔴 Mendekati Batas Waktu 10 Menit",
                        "[▓▓▓▓▓▓▓▓▓▓]",
                        "LOCKOUT",
                        f"🚨 *PERHATIAN DARURAT: Captcha belum solved setelah 7 menit ({solve_reason})!*\n"
                        f"🛑 *Bot TELAH DIMATIKAN TOTAL demi mencegah ban 10 menit (372H) dari OwO!*\n"
                        f"👉 Segera verifikasi manual di web: https://owobot.com/captcha\n"
                        f"⏰ *Waktu tersisa ~2.5 menit sebelum ban dijatuhkan oleh server OwO!*",
                        color="#d70000"
                    )
                    self._wa_msg_id = None
                    self._wa_msg_start_time = None
                    self._wa_msg_start_time = None

            except Exception as e:
                await self._refresh_nopecha_status(force=True)
                await self.bot.log(f"❌ [Auto-Solver] Error: {e}", "#c25560")
                await self.update_wa_progress(
                    "❌ *[OWO BOT] ERROR PADA AUTO-SOLVER*",
                    f"🔴 Error: {str(e)[:40]}",
                    "[▓▓▓▓▓▓▓▓▓▓]",
                    "ERROR",
                    f"🚨 *Terjadi kesalahan sistem saat mencoba memecahkan captcha.* `{str(e)[:60]}`\n"
                    f"👉 Segera verifikasi manual: https://owobot.com/captcha",
                    color="#d70000"
                )
                self._wa_msg_id = None
                self._wa_msg_start_time = None
            finally:
                self._is_web_solving = False
                if self._solve_requested_again and self.bot.command_handler_status.get("captcha"):
                    self._solve_requested_again = False
                    await self.bot.log("🔁 [Auto-Solver] Terdeteksi sinyal captcha baru/lanjutan! Menjalankan solver kembali...", "#f39c12")
                    asyncio.create_task(self._handle_web_captcha(self._last_verify_url or "https://owobot.com/captcha"))

    async def _download_image(self, url):

        try:
            async with self.bot.session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception as e:
            await self.bot.log(f"Failed to download captcha image: {e}", "#c25560")
        return None

    async def _attempt_solve(self, strategy_index=0):

        img_path = self._captcha_image_path
        if not img_path or not os.path.exists(img_path):
            await self.bot.log("🧩 Auto-Solver: No cached captcha image to solve", "#c25560")
            return False

        try:
            strategy_names = ["Standard", "Adaptive", "Heavy Distortion", "OTSU Auto"]
            name = strategy_names[strategy_index] if strategy_index < len(strategy_names) else f"Strategy {strategy_index}"

            await self.bot.log(f"🧩 Auto-Solver: Attempt {strategy_index + 1}/{self._solve_max_retries + 1} using [{name}]...", "#f39c12")
            self.bot.add_dashboard_log("captcha", f"Auto-Solver attempt {strategy_index + 1} [{name}]", "warning")

            loop = asyncio.get_running_loop()
            img_path = self._captcha_image_path
            answer = await loop.run_in_executor(None, solve_captcha, img_path, strategy_index)

            if answer and len(answer) > 0:
                await self.bot.log(f"🧩 Auto-Solver result: '{answer}' [{name}]", "#51cf66")
                self.bot.add_dashboard_log("captcha", f"Auto-Solver answer: {answer} [{name}]", "success")

                delay = self.bot.random_float([2.0, 5.0])
                await asyncio.sleep(delay)

                if self._captcha_channel:
                    await self._captcha_channel.send(answer)
                    await self.bot.log(f"🧩 Auto-Solver: Sent '{answer}' to {get_channel_name(self._captcha_channel)}", "#51cf66")
                    if self.bot.global_settings_dict["webhook"]["enabled"]:
                        await self.bot.webhookSender(
                            msg=f"🧩 [{self.bot.username}] Jawaban Captcha Otomatis Dikirim",
                            desc=f"**User**: <@{self.bot.user.id}>\n**Jawaban**: `{answer}`\n**Metode**: `{name}`\n**Channel**: {get_channel_name(self._captcha_channel)}",
                            colors="#f39c12",
                            webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                        )
                    return True
            else:
                await self.bot.log(f"🧩 Auto-Solver: Empty result from [{name}]", "#c25560")
        except Exception as e:
            await self.bot.log(f"🧩 Auto-Solver error (attempt {strategy_index + 1}): {e}", "#c25560")

        return False

    def _cleanup_captcha(self):

        img_path = self._captcha_image_path
        if img_path:
            try:
                os.remove(img_path)
            except Exception:
                pass
        self._captcha_image_path = None
        self._captcha_channel = None
        self._solve_attempt = 0
        self._solving_active = False

    async def _try_hcaptcha(self, message):
        if message.attachments:
            return False

        cfg = self.bot.global_settings_dict.get("captcha", {}).get("hcaptchaSolver", {})
        if not cfg.get("enabled") or self.bot.hcaptcha_client is None:
            return False

        await self.bot.log("🧩 hCaptcha-Solver: working on it...", "#f39c12")
        self.bot.add_dashboard_log("captcha", "hCaptcha solver started", "warning")

        try:
            solved = await self.bot.hcaptcha_client.solve(
                self.bot.local_headers,
                cfg.get("retries", 3),
            )
        except Exception as e:
            await self.bot.log(f"🧩 hCaptcha-Solver crashed: {e}", "#c25560")
            self.bot.add_dashboard_log("captcha", f"hCaptcha solver error: {e}", "error")
            return False

        if not solved:
            await self.bot.log("❌ hCaptcha-Solver couldn't finish it.", "#d70000")
            self.bot.add_dashboard_log("captcha", "hCaptcha solver failed", "error")
            return False

        balance = self.bot.hcaptcha_client.balance
        remaining = balance // 30
        await self.bot.log(
            f"✅ hCaptcha cleared! ~{remaining} solves left (balance {balance})",
            "#51cf66",
        )
        self.bot.add_dashboard_log(
            "captcha", f"hCaptcha solved, ~{remaining} solves left", "success"
        )
        return True

    def captcha_handler(self, channel, captcha_type):
        if self.bot.misc["hostMode"]:
            return
        cnf = self.bot.global_settings_dict["captcha"]
        channel_name = get_channel_name(channel)
        content = 'captchaContent' if not captcha_type=="Ban" else 'bannedContent'
        """Notifications"""
        if cnf["notifications"]["enabled"]:
            try:
                if on_mobile:
                    run_system_command(
                        f"termux-notification -t '{self.bot.username} captcha!' -c '{cnf['notifications'][content].format(username=self.bot.username,channelname=channel_name,captchatype=captcha_type)}' --led-color '#a575ff' --priority 'high'",
                        timeout=5, 
                        retry=True
                        )
                else:
                    notification.notify(
                        title=f'{self.bot.username} DETECTED CAPTCHA',
                        message=cnf['notifications'][content].format(username=self.bot.username,channelname=channel_name,captchatype=captcha_type),
                        app_icon=None,
                        timeout=15
                        )
            except Exception as e:
                print(f"{e} - at notifs")

        if cnf["playAudio"]["enabled"]:
            path = get_path(cnf['playAudio']['path'])
            try:
                if on_mobile:
                    run_system_command(f"termux-media-player play {path}", timeout=5, retry=True)
                else:
                    playsound(path, block=False)
            except Exception as e:
                print(f"{e} - at audio")

        if cnf["toastOrPopup"]["enabled"]:
            try:
                if on_mobile:
                    run_system_command(
                        f"termux-toast -c {cnf['toastOrPopup']['termuxToast']['textColour']} -b {cnf['toastOrPopup']['termuxToast']['backgroundColour']} -g {cnf['toastOrPopup']['termuxToast']['position']} '{cnf['toastOrPopup'][content].format(username=self.bot.username,channelname=channel_name,captchatype=captcha_type)}'",
                        timeout=5,
                        retry=True
                        )
                else:
                    self.bot.add_popup_queue(channel_name, captcha_type)
            except Exception as e:
                print(f"{e} - at Toast/Popup")

        if cnf["termux"]["vibrate"]["enabled"]:
            try:
                if on_mobile:
                    run_system_command(
                        f"termux-vibrate -f -d {cnf['termux']['vibrate']['time']*1000}",
                        timeout=5,
                        retry=True,
                    )
                else:
                    pass
            except Exception as e:
                print(f"{e} - at Toast/Popup")

        if cnf["termux"]["textToSpeech"]["enabled"]:
            try:
                if on_mobile:
                    run_system_command(
                            f"termux-tts-speak {cnf['termux']['textToSpeech'][content]}",
                            timeout=7,
                            retry=False
                        )
                else:
                    pass
            except Exception as e:
                print(f"{e} - at Toast/Popup")

        if cnf["termux"]["openCaptchaWebsite"] and on_mobile:
            run_system_command("termux-open https://owobot.com/captcha", timeout=5, retry=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        self.last_msg = time.time()

        if not self.bot.dm:
            if message.author.id == self.bot.owo_bot_id:
                self.bot.dm = await message.author.create_dm()
            else:
                return

        if message.channel.id in {self.bot.dm.id, self.bot.cm.id} and message.author.id == self.bot.owo_bot_id:
            if "I have verified that you are human! Thank you! :3" in message.content or "verified that you are human" in message.content.lower():
                await self._refresh_nopecha_status(force=True)
                if self._kill_task and not self._kill_task.done():
                    self._kill_task.cancel()
                    self._kill_task = None
                self._cleanup_captcha()
                self._is_web_solving = False
                self._solve_requested_again = False

                time_to_sleep = self.bot.random_float(self.bot.settings_dict['defaultCooldowns']['captchaRestart'])
                await self.bot.log(f"Captcha solved! - sleeping {time_to_sleep}s before restart.", "#5fd700")

                self.bot.add_dashboard_log("captcha", f"Captcha solved! Resuming in {time_to_sleep:.1f}s", "success")

                if self._wa_msg_id:
                    await self.update_wa_progress(
                        "✅ *[OWO BOT] CAPTCHA BERHASIL DISELESAIKAN!*",
                        "🟢 Akun Terverifikasi Human",
                        "[▓▓▓▓▓▓▓▓▓▓]",
                        "100%",
                        f"🎉 *Akun AMAN! OwO mengonfirmasi verifikasi sukses. Bot otomatis melanjutkan farming dalam `{time_to_sleep:.1f}s`.*",
                        color="#51cf66"
                    )
                    self._wa_msg_id = None
                    self._wa_msg_start_time = None
                elif self.bot.global_settings_dict["webhook"]["enabled"]:
                    nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                    await self.bot.webhookSender(
                        msg=f"✅ [{self.bot.username}] CAPTCHA BERHASIL DISELESAIKAN!",
                        desc=f"**Status**: Akun AMAN & Terverifikasi human!\n**User**: <@{self.bot.user.id}>{nopecha_token_desc}\nBot otomatis melanjutkan farming dalam `{time_to_sleep:.1f}s`.",
                        colors="#51cf66",
                        webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                    )

                await asyncio.sleep(time_to_sleep)
                self.bot.command_handler_status["captcha"] = False

                self.bot.add_dashboard_log("system", "Bot automatically resumed after captcha", "success")
                await self.bot.log(f"Bot automatically resumed after captcha!", "#51cf66")

                await self.bot.update_captcha_db()
                return

            content_lower = message.content.lower()
            if self._solving_active and any(phrase in content_lower for phrase in WRONG_ANSWER_PHRASES):
                self._solve_attempt += 1
                if self._solve_attempt <= self._solve_max_retries and self._solve_attempt < MAX_SOLVE_STRATEGIES:
                    await self.bot.log(f"🧩 Auto-Solver: Wrong answer! Retrying with strategy {self._solve_attempt + 1}...", "#f39c12")
                    self.bot.add_dashboard_log("captcha", f"Wrong answer - retrying (attempt {self._solve_attempt + 1})", "warning")

                    await asyncio.sleep(self.bot.random_float([1.5, 3.0]))
                    await self._attempt_solve(strategy_index=self._solve_attempt)
                else:
                    await self.bot.log(f"🧩 Auto-Solver: All {self._solve_attempt} attempts failed.", "#d70000")
                    self.bot.add_dashboard_log("captcha", "Auto-Solver exhausted all strategies", "error")

                    if hasattr(self, '_last_verify_url') and self._last_verify_url:
                        await self.bot.log("🌐 Auto-Solver: Falling back to web captcha handler...", "#f39c12")
                        asyncio.create_task(self._handle_web_captcha(self._last_verify_url))
                    else:
                        if self._wa_msg_id:
                            await self.update_wa_progress(
                                "❌ *[OWO BOT] AUTO-SOLVE GAGAL!*",
                                "🔴 Perlu Bantuan Manual",
                                "[▓▓▓▓▓▓▓▓▓▓]",
                                "GAGAL",
                                f"🚨 *Auto-solver belum berhasil menyelesaikan captcha.*\n"
                                f"⏰ *Anda memiliki waktu ~10 menit sebelum akun terblokir!*\n"
                                f"🔗 [Buka Pesan Captcha]({message.jump_url if hasattr(message, 'jump_url') else 'https://owobot.com/captcha'})",
                                color="#d70000"
                            )
                        elif self.bot.global_settings_dict["webhook"]["enabled"]:
                            await self.bot.webhookSender(
                                msg=f"🚨 [{self.bot.username}] PERINGATAN CAPTCHA: Perlu Bantuan Manual!",
                                desc=f"**PERHATIAN**: Auto-solver belum berhasil menyelesaikan captcha.\n**Sisa Waktu**: Anda memiliki waktu ~10 menit sebelum akun terblokir!\n**User**: <@{self.bot.user.id}>\n**Link**: [Buka Pesan Captcha]({message.jump_url if hasattr(message, 'jump_url') else 'https://owobot.com/captcha'})",
                                colors="#d70000",
                                webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                            )
                        self.captcha_handler(self._captcha_channel or message.channel, "Link")

                    self._cleanup_captcha()
                return

        if message.channel.id in {self.bot.dm.id, self.bot.cm.id} and message.author.id == self.bot.owo_bot_id:

            content_lower_raw = message.content.lower()

            warning_match = self._warning_pattern.search(message.content)
            if warning_match:
                current = int(warning_match.group(1))
                total = int(warning_match.group(2))
                is_dm = get_channel_name(message.channel) == "owo DMs"
                targets_me = (
                    is_dm
                    or self.bot.user.name.lower() in content_lower_raw
                    or f"<@{self.bot.user.id}>" in message.content
                    or (message.guild and any(str(self.bot.user.id) in str(m.id) for m in message.mentions))
                )
                if targets_me:
                    await self.bot.log(f"⚠️ OwO Warning detected ({current}/{total})! Pausing bot & triggering NopeCHA Auto-Solver...", "#f39c12")
                    self.bot.add_dashboard_log("captcha", f"OwO warning ({current}/{total}) - bot paused, solving via NopeCHA", "warning")
                    self.bot.command_handler_status["captcha"] = True
                    self.captcha_handler(message.channel, "Link")
                    if self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", True):
                        if not self._is_web_solving:
                            asyncio.create_task(self._handle_web_captcha("https://owobot.com/captcha"))
                        else:
                            await self.bot.log("ℹ️ [Auto-Solver] Solver sedang aktif, mengantrekan solve jika belum selesai...", "#f39c12")
                            self._solve_requested_again = True
                    elif self.bot.global_settings_dict["webhook"]["enabled"]:
                        await self._refresh_nopecha_status()
                        nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                        await self.bot.webhookSender(
                            msg=f"-{self.bot.username} [+] OwO Warning ({current}/{total})",
                            desc=f"**User** : <@{self.bot.user.id}>\n**Warning** : `({current}/{total})`{nopecha_token_desc}\n**Link** : [Message]({message.jump_url})",
                            colors="#f39c12",
                            webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                        )
                    return

            CAPTCHA_PLAIN_PHRASES = [
                "please complete your captcha",
                "verify that you are human",
                "complete captcha to continue",
            ]
            if any(phrase in content_lower_raw for phrase in CAPTCHA_PLAIN_PHRASES):
                is_dm = get_channel_name(message.channel) == "owo DMs"
                targets_me = (
                    is_dm
                    or self.bot.user.name.lower() in content_lower_raw
                    or f"<@{self.bot.user.id}>" in message.content
                    or (message.guild and any(str(self.bot.user.id) in str(m.id) for m in message.mentions))
                )
                if targets_me:
                    self.bot.command_handler_status["captcha"] = True
                    await self.bot.log("⛔ Captcha warning detected! Bot paused & triggering NopeCHA Auto-Solver...", "#d70000")
                    self.bot.add_dashboard_log("captcha", "Captcha prompt detected - solving via NopeCHA", "error")
                    self.captcha_handler(message.channel, "Link")
                    if self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", True):
                        if not self._is_web_solving:
                            asyncio.create_task(self._handle_web_captcha("https://owobot.com/captcha"))
                        else:
                            await self.bot.log("ℹ️ [Auto-Solver] Solver sedang aktif, mengantrekan solve jika belum selesai...", "#f39c12")
                            self._solve_requested_again = True
                    elif self.bot.global_settings_dict["webhook"]["enabled"]:
                        await self._refresh_nopecha_status()
                        nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                        await self.bot.webhookSender(
                            msg=f"-{self.bot.username} [+] CAPTCHA Detected",
                            desc=f"**User** : <@{self.bot.user.id}>{nopecha_token_desc}\n**Link** : [OwO Captcha]({message.jump_url})",
                            colors="#00FFAF",
                        )
                    return

            if (
                (
                    message.components
                    and len(message.components) > 0
                    and hasattr(message.components[0], "children")
                    and len(message.components[0].children) > 0
                    and (
                        (
                            hasattr(message.components[0].children[0], "label")
                            and message.components[0].children[0].label == "Verify"
                        )
                or (
                    hasattr(message.components[0].children[0], "url")
                    and "owobot.com" in message.components[0].children[0].url
                )
                    )
                )
            or ("⚠️" in message.content and message.attachments)
            or any(b in clean(message.content) for b in list_captcha)
            ):
                if not get_channel_name(message.channel) == "owo DMs":
                    display_name = message.guild.me.display_name
                    if not any(user in message.content for user in (self.bot.user.name, f"<@{self.bot.user.id}>", display_name)):
                        return
                self.bot.command_handler_status["captcha"] = True
                await self.bot.log(f"Captcha detected!", "#d70000")

                channel_name = get_channel_name(message.channel)
                self.bot.add_dashboard_log("captcha", f"Captcha detected in {channel_name}! Bot stopped automatically", "error")

                if self.bot.global_settings_dict.get("captcha", {}).get("stopCodeIfFailedToSolve", False):
                    if not self._kill_task or self._kill_task.done():
                        self._kill_task = asyncio.create_task(self._kill_code())

                auto_solved = False
                if SOLVER_AVAILABLE and message.attachments and self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", False):
                    try:
                        await self.bot.log("🧩 Auto-Solver: Captcha image detected, starting solve cycle...", "#f39c12")

                        img_url = message.attachments[0].url
                        img_data = await self._download_image(img_url)

                        if img_data:
                            try:
                                import io as _io
                                from PIL import Image as _Image
                                _Image.open(_io.BytesIO(img_data)).load()
                            except Exception:
                                await self.bot.log("🧩 Auto-Solver: Downloaded image is corrupt, skipping solve", "#c25560")
                                img_data = None

                        if img_data:
                            tmp_path = os.path.join(tempfile.gettempdir(), f"mizu_captcha_{self.bot.user.id}.png")
                            with open(tmp_path, "wb") as f:
                                f.write(img_data)

                            self._captcha_image_path = tmp_path
                            self._captcha_channel = message.channel
                            self._solve_attempt = 0
                            self._solving_active = True

                            auto_solved = await self._attempt_solve(strategy_index=0)
                        else:
                            await self.bot.log("🧩 Auto-Solver: Failed to download captcha image", "#c25560")
                    except Exception as e:
                        await self.bot.log(f"🧩 Auto-Solver error: {e}", "#c25560")
                        self.bot.add_dashboard_log("captcha", f"Auto-Solver error: {e}", "error")

                hcaptcha_solved = await self._try_hcaptcha(message)

                verify_url = None
                if message.components:
                    for comp in message.components:
                        if hasattr(comp, 'children'):
                            for child in comp.children:
                                if hasattr(child, 'url') and child.url and "owobot.com" in child.url:
                                    verify_url = child.url
                                    break

                target_solve_url = verify_url or "https://owobot.com/captcha"
                if not auto_solved and not hcaptcha_solved:
                    self._last_verify_url = target_solve_url
                    if self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", True):
                        if not self._is_web_solving:
                            asyncio.create_task(self._handle_web_captcha(target_solve_url))
                        else:
                            await self.bot.log("ℹ️ [Auto-Solver] Solver sedang aktif, mengantrekan solve jika belum selesai...", "#f39c12")
                            self._solve_requested_again = True
                else:
                    self._last_verify_url = None

                if not auto_solved and not self._solving_active and not hcaptcha_solved:
                    self.captcha_handler(message.channel, "Link")
                is_handled_by_web = bool(self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", True))
                if not is_handled_by_web and self.bot.global_settings_dict["webhook"]["enabled"]:
                    await self._refresh_nopecha_status()
                    nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                    await self.bot.webhookSender(
                        msg=f"-{self.bot.username} [+] CAPTCHA Detected",
                        desc=f"**User** : <@{self.bot.user.id}>{nopecha_token_desc}\n**Link** : [OwO Captcha]({message.jump_url})",
                        colors="#00FFAF",
                        img_url="https://cdn.discordapp.com/emojis/1171297031772438618.png",
                        author_img_url="https://imgur.com/a/xwALH1U",
                        plain_text=(
                            f"<@{self.bot.global_settings_dict['webhook']['webhookUserIdToPingOnCaptcha']}>"
                            if self.bot.global_settings_dict['webhook']['webhookUserIdToPingOnCaptcha']
                            else None
                        ),
                        webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                    )
                console_handler(self.bot.global_settings_dict["console"])

            elif "you have been banned" in message.content.lower() or "**☠" in message.content:
                self.bot.command_handler_status["captcha"] = True
                self.bot.command_handler_status["state"] = False
                self.captcha_handler(message.channel, "Ban")
                await self.bot.log(f"☠️ [OwO Ban Detected] Akun terkena ban! Menghentikan semua aktivitas bot: {message.content[:150]}", "#d70000")
                channel_name = get_channel_name(message.channel)
                self.bot.add_dashboard_log("captcha", f"Ban detected in {channel_name}! Bot stopped automatically", "error")

                self.captcha_handler(message.channel, "Ban")
                console_handler(self.bot.global_settings_dict["console"], captcha=False)
                if self.bot.global_settings_dict["webhook"]["enabled"]:
                    await self.bot.webhookSender(
                        msg=f"-{self.bot.username} [+] BAN Detected",
                        desc=f"**User** : <@{self.bot.user.id}>\n**Link** : [Ban Message]({message.jump_url})",
                        colors="#00FFAF",
                        img_url="https://cdn.discordapp.com/emojis/1213902052879503480.gif",
                        author_img_url="https://imgur.com/a/xwALH1U",
                        plain_text=(
                            f"<@{self.bot.global_settings_dict['webhook']['webhookUserIdToPingOnCaptcha']}>"
                            if self.bot.global_settings_dict["webhook"]["webhookUserIdToPingOnCaptcha"]
                            else None
                        ),
                        webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                    )
            elif message.embeds:
                for embed in message.embeds:
                    items = {
                        embed.title if embed.title else "",
                        embed.author.name if embed.author else "",
                        embed.footer.text if embed.footer else "",
                    }
                    for i in items:
                        if any(b in clean(i) for b in list_captcha):

                            self.bot.command_handler_status["captcha"] = True
                            await self.bot.log(f"Captcha detected in embed!", "#d70000")

                            channel_name = get_channel_name(message.channel)
                            self.bot.add_dashboard_log("captcha", f"Possible captcha detected in embed ({channel_name})! Bot stopped", "warning")
                            self.captcha_handler(message.channel, "Link")
                            if self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", True):
                                if not self._is_web_solving:
                                    asyncio.create_task(self._handle_web_captcha("https://owobot.com/captcha"))
                                else:
                                    await self.bot.log("ℹ️ [Auto-Solver] Solver sedang aktif, mengantrekan solve jika belum selesai...", "#f39c12")
                                    self._solve_requested_again = True
                            elif self.bot.global_settings_dict.get("webhook", {}).get("enabled", True):
                                await self._refresh_nopecha_status()
                                nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                                await self.bot.webhookSender(
                                    msg=f"🚨 [{self.bot.username}] CAPTCHA Terdeteksi (Embed)",
                                    desc=f"**User**: <@{self.bot.user.id}>{nopecha_token_desc}\n**Channel**: {channel_name}\n**Link**: [Lihat Pesan]({message.jump_url})\nBot otomatis berhenti untuk keamanan akun.",
                                    colors="#d70000",
                                    plain_text=(
                                        f"<@{self.bot.global_settings_dict['webhook']['webhookUserIdToPingOnCaptcha']}>"
                                        if self.bot.global_settings_dict.get("webhook", {}).get("webhookUserIdToPingOnCaptcha")
                                        else None
                                    ),
                                    webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                                )
                            break

                    if embed.fields:
                        for field in embed.fields:
                            if field.name and any(b in clean(field.name) for b in list_captcha):
                                self.bot.command_handler_status["captcha"] = True
                                await self.bot.log(f"Captcha detected in embed field!", "#d70000")

                                channel_name = get_channel_name(message.channel)
                                self.bot.add_dashboard_log("captcha", f"Possible captcha in embed field ({channel_name})! Bot stopped", "warning")
                                self.captcha_handler(message.channel, "Link")
                                if self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", True):
                                    if not self._is_web_solving:
                                        asyncio.create_task(self._handle_web_captcha("https://owobot.com/captcha"))
                                    else:
                                        await self.bot.log("ℹ️ [Auto-Solver] Solver sedang aktif, mengantrekan solve jika belum selesai...", "#f39c12")
                                        self._solve_requested_again = True
                                elif self.bot.global_settings_dict.get("webhook", {}).get("enabled", True):
                                    await self._refresh_nopecha_status()
                                    nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                                    await self.bot.webhookSender(
                                        msg=f"🚨 [{self.bot.username}] CAPTCHA Terdeteksi (Embed Field)",
                                        desc=f"**User**: <@{self.bot.user.id}>{nopecha_token_desc}\n**Channel**: {channel_name}\n**Link**: [Lihat Pesan]({message.jump_url})\nBot otomatis berhenti untuk keamanan akun.",
                                        colors="#d70000",
                                        plain_text=(
                                            f"<@{self.bot.global_settings_dict['webhook']['webhookUserIdToPingOnCaptcha']}>"
                                            if self.bot.global_settings_dict.get("webhook", {}).get("webhookUserIdToPingOnCaptcha")
                                            else None
                                        ),
                                        webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                                    )
                                break
                            if field.value and any(b in clean(field.value) for b in list_captcha):
                                self.bot.command_handler_status["captcha"] = True
                                await self.bot.log(f"Captcha detected in embed field value!", "#d70000")

                                channel_name = get_channel_name(message.channel)
                                self.bot.add_dashboard_log("captcha", f"Possible captcha in embed field value ({channel_name})! Bot stopped", "warning")
                                self.captcha_handler(message.channel, "Link")
                                if self.bot.global_settings_dict.get("captcha", {}).get("autoSolve", {}).get("enabled", True):
                                    if not self._is_web_solving:
                                        asyncio.create_task(self._handle_web_captcha("https://owobot.com/captcha"))
                                    else:
                                        await self.bot.log("ℹ️ [Auto-Solver] Solver sedang aktif, mengantrekan solve jika belum selesai...", "#f39c12")
                                        self._solve_requested_again = True
                                elif self.bot.global_settings_dict.get("webhook", {}).get("enabled", True):
                                    await self._refresh_nopecha_status()
                                    nopecha_token_desc = f"\n**Sisa Token NopeCHA**: `{self._nopecha_credit}/{self._nopecha_quota}`" if self._nopecha_credit is not None else ""
                                    await self.bot.webhookSender(
                                        msg=f"🚨 [{self.bot.username}] CAPTCHA Terdeteksi (Embed Field)",
                                        desc=f"**User**: <@{self.bot.user.id}>{nopecha_token_desc}\n**Channel**: {channel_name}\n**Link**: [Lihat Pesan]({message.jump_url})\nBot otomatis berhenti untuk keamanan akun.",
                                        colors="#d70000",
                                        plain_text=(
                                            f"<@{self.bot.global_settings_dict['webhook']['webhookUserIdToPingOnCaptcha']}>"
                                            if self.bot.global_settings_dict.get("webhook", {}).get("webhookUserIdToPingOnCaptcha")
                                            else None
                                        ),
                                        webhook_url=self.bot.global_settings_dict["webhook"].get("webhookCaptchaUrl", None),
                                    )
                                break

async def setup(bot):
    await bot.add_cog(Captcha(bot))