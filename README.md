<div align="center">

# 🌊 OwoFarm — Mizu OwO Suite 水

### *Next-Generation Multi-Account OwO Automation, Anti-Captcha Intelligence & Web Monitoring Suite*

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Discord](https://img.shields.io/badge/Discord.py--self-v2.0+-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://github.com/dolfies/discord.py-self)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS%20%7C%20Termux%20%7C%20Docker-2ea44f?style=for-the-badge)](https://github.com/itscasaa/OwoFarm)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge)]()

<br>

```
  ██████╗ ██╗    ██╗ ██████╗ ███████╗ █████╗ ██████╗ ███╗   ███╗
 ██╔═══██╗██║    ██║██╔═══██╗██╔════╝██╔══██╗██╔══██╗████╗ ████║
 ██║   ██║██║ █╗ ██║██║   ██║█████╗  ███████║██████╔╝██╔████╔██║
 ██║   ██║██║███╗██║██║   ██║██╔══╝  ██╔══██║██╔══██╗██║╚██╔╝██║
 ╚██████╔╝╚███╔███╔╝╚██████╔╝██║     ██║  ██║██║  ██║██║ ╚═╝ ██║
  ╚═════╝  ╚══╝╚══╝  ╚═════╝ ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
             M I Z U   A U T O M A T I O N   E N G I N E
```

<p align="center">
  <b>Multi-Token Architecture</b> • <b>Deep Learning OCR Captcha Solver</b> • <b>Real-time Web Dashboard</b><br>
  <b>Dynamic Jitter Anti-Ban Engine</b> • <b>One-Click Profile Switcher</b> • <b>Discord Webhook Dispatcher</b>
</p>

</div>

---

## 📑 Table of Contents

- [✨ Core Capabilities](#-core-capabilities)
- [🏗️ Architectural Overview](#️-architectural-overview)
- [🚀 Quickstart Guide](#-quickstart-guide)
  - [Prerequisites](#prerequisites)
  - [Linux / Debian / Ubuntu](#linux--debian--ubuntu)
  - [Windows](#windows)
  - [Android (Termux)](#android-termux)
  - [Docker & Docker Compose](#docker--docker-compose)
- [⚙️ Configuration & Profiles](#️-configuration--profiles)
  - [Environment Variables (.env)](#environment-variables-env)
  - [Live Profile Switcher](#live-profile-switcher)
  - [Configuration Files Matrix](#configuration-files-matrix)
- [🖥️ Web Dashboard](#️-web-dashboard)
- [🛡️ Anti-Ban & Stealth Engine](#️-anti-ban--stealth-engine)
- [📦 PM2 Production Deployment](#-pm2-production-deployment)
- [🔔 Unban Notifier & Watchdog](#-unban-notifier--watchdog)
- [⚠️ Safety & Disclaimer](#️-safety--disclaimer)
- [📄 License](#-license)

---

## ✨ Core Capabilities

### ⚡ Multi-Account Concurrency & Scheduling
- **Simultaneous Multi-Token Operation**: Run multiple Discord accounts concurrently with independent channel bindings and isolated state trackers.
- **Shift & Rotation Scheduler**: Automatically rotate accounts on timed shifts to prevent suspicion from continuous activity.

### 🧠 Dual-Engine AI Captcha Resolution
- **Offline ONNX Neural Network**: Fast local character recognition for standard image-based OwO captchas.
- **NopeCHA Cloud Solver & Fallback**: Automated solving pipeline for complex distorted captchas and web challenge links.
- **Instant Webhook Pings**: Urgent Discord mention notifications whenever a manual verification intervention is needed.

### 🎮 Automated Mini-Game & Economy Farming
- **Core Loop**: Automated `hunt`, `battle`, `owo`, `pray`, and `curse` executions with humanized Poisson delays.
- **Auto-Inventory & Consumables**: Automatically manage gems, crates, lootboxes, and item buffs.
- **Smart Sell & Sacrifice**: Auto-sell Common/Uncommon animals while protecting Legendaries and Mythicals.
- **Gambling Intelligence**: Configurable Coinflip, Slots, and Blackjack with configurable loss caps, progressive bet scalers, and stop-loss rules.
- **Automated Giveaway Claimer**: Silently monitors designated giveaway channels, parses Discord button interactions, and auto-joins with zero duplicate entries.

### 📊 Real-time Web Control Center
- **Live Flask Dashboard**: Responsive, dark-themed UI displaying real-time currency, XP trends, command logs, and bot health.
- **Remote Configuration**: Adjust cooldowns, toggle features, and inspect loot stats directly from your browser.

---

## 🏗️ Architectural Overview

```
                        ┌────────────────────────┐
                        │   Discord Gateway API  │
                        └───────────┬────────────┘
                                    │ WebSocket / REST
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          OwoFarm Core Engine                           │
│                                                                        │
│   ┌─────────────────────┐  ┌─────────────────────┐  ┌──────────────┐   │
│   │  Discord.py Client  │  │  Multi-Token Engine │  │ Profile Mgr  │   │
│   └──────────┬──────────┘  └──────────┬──────────┘  └──────┬───────┘   │
│              │                        │                    │           │
│              ▼                        ▼                    ▼           │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                      Anti-Ban Stealth Layer                    │   │
│   │   • Human Jitter Delay  • Typing Simulator  • Sleep System    │   │
│   └──────────┬────────────────────────┬────────────────────┬───────┘   │
│              │                        │                    │           │
│              ▼                        ▼                    ▼           │
│   ┌─────────────────────┐  ┌─────────────────────┐  ┌──────────────┐   │
│   │  AI Captcha Solver  │  │  Automated Cogs     │  │ Webhook Sync │   │
│   │  (ONNX / NopeCHA)   │  │  (Hunt/Battle/Etc)  │  │ (Alerts/Ban) │   │
│   └─────────────────────┘  └─────────────────────┘  └──────────────┘   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ IPC / Socket
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Flask Realtime Dashboard (Port 1200)                │
│             Live Analytics • Loot Log • Configuration Control          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart Guide

### Prerequisites
- **Python**: Version `3.10`, `3.11`, or `3.12`
- **Git**
- **Google Chrome / Chromium** *(optional, for interactive web captcha solver on desktop)*

---

### Linux / Debian / Ubuntu

```bash
# 1. Clone the repository
git clone https://github.com/itscasaa/OwoFarm.git
cd OwoFarm

# 2. Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create your environment configuration
cp .env.example .env
nano .env

# 5. Launch the wizard or start the bot
python setup.py    # Guided configuration setup
python mizu.py     # Launch automation bot
```

---

### Windows

```powershell
# 1. Clone repository
git clone https://github.com/itscasaa/OwoFarm.git
cd OwoFarm

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Copy .env.example to .env and configure
copy .env.example .env
notepad .env

# 5. Start bot
python mizu.py
```

---

### Android (Termux)

```bash
# Update packages & install git
pkg update && pkg upgrade -y
pkg install git python termux-api -y

# Clone and run automated setup
git clone https://github.com/itscasaa/OwoFarm.git
cd OwoFarm
chmod +x setup_termux.sh
./setup_termux.sh

# Run
python mizu.py
```

---

### Docker & Docker Compose

```bash
# Build and run containerized
docker-compose up -d --build

# View real-time logs
docker-compose logs -f
```

---

## ⚙️ Configuration & Profiles

### Environment Variables (`.env`)

Configure your Discord user token(s) and target farming channel IDs in `.env`:

```env
# Multi-token syntax: "TOKEN_1 CHANNEL_ID_1;TOKEN_2 CHANNEL_ID_2"
TOKENS="MTAwMDAwMDAwMDAwMDAwMDAw.xxxxxx.yyyyyy 123456789012345678;MTAxMDAwMDAwMDAwMDAwMDAw.aaaaaa.bbbbbb 987654321098765432"

# Web Dashboard Port (Default: 1200)
PORT=1200
```

---

### Live Profile Switcher

`OwoFarm` includes a preset switcher script (`switch_profile.sh`) allowing you to swap active strategies instantly without manually rewriting JSON configs:

```bash
chmod +x switch_profile.sh

# 1. Mixed Mode (Hunt, Battle, Owo, Coinflip 5k, Pray/Curse)
./switch_profile.sh mix

# 2. Gambling Mode (Only Owo & Coinflip 5000)
./switch_profile.sh cf

# 3. Stealth Giveaway Mode (Zero chat messages, auto-joins giveaways only)
./switch_profile.sh giveaway

# 4. Standby / Pause Mode (Safe quiet mode, stays online without executing commands)
./switch_profile.sh stop
```

---

### Configuration Files Matrix

| File | Purpose | Scope |
|---|---|---|
| `config/settings.json` | Active bot behavior, enabled commands, cooldown ranges, gamble settings | Current Active Profile |
| `config/global_settings.json` | Webhook endpoints, dashboard port, NopeCHA keys, captcha behaviors | Global / System-wide |
| `config/global_settings.local.json` | Optional uncommitted local override for private keys & webhooks | Local Environment |
| `config/danger.json` | Security gate for experimental features (Auto-Quests, Level Quotes) | Risk Containment |
| `config/webhookContent.json` | Discord embed templates, rich notification colors, and emoji styling | Notifications |

---

## 🖥️ Web Dashboard

Access the built-in management interface by pointing your browser to:

```
http://localhost:1200
```

- **Live Activity Feed**: Monitor real-time commands and OwO bot responses.
- **Inventory & Pet Radar**: Track caught animals, gems count, and currency growth.
- **Captcha Alert Panel**: Review recent captcha events and resolution statuses.
- **Hot-Reload Controls**: Toggle modules on the fly without stopping your background processes.

---

## 🛡️ Anti-Ban & Stealth Engine

To ensure maximum account longevity, `OwoFarm` incorporates several defensive layers:

1. **Human Delay Simulation**: Commands utilize variable randomized timers based on real human reaction distributions instead of fixed delays.
2. **Typing Indicators**: Emulates natural typing state before sending command messages.
3. **Typo Generator**: Intentionally misspells words periodically and edits them back, replicating human keyboard behavior.
4. **Circadian Sleep Scheduler**: Automatically enters hibernation during scheduled quiet hours (e.g., overnight).
5. **Rate-Limit Backoff**: Immediately throttles commands upon receiving Discord `429 Too Many Requests` or OwO slow-down warnings.

---

## 📦 PM2 Production Deployment

For 24/7 VPS hosting with automatic failure recovery and zero downtime:

```bash
# Install PM2 globally
npm install -g pm2

# Start OwoFarm under PM2 supervision
pm2 start run.sh --name "owomizu"

# Persist across server reboots
pm2 save
pm2 startup
```

Monitor status and logs:
```bash
pm2 status
pm2 logs owomizu
```

---

## 🔔 Unban Notifier & Watchdog

Includes an automated ban tracker utility (`scripts/unban_notifier.py`) that monitors ban expiration timers and delivers webhook alerts when an account is safe to farm again:

```bash
# Run tracker manually or configure via system cron
python3 scripts/unban_notifier.py --status
```

---

## ⚠️ Safety & Disclaimer

> [!CAUTION]
> **Use at your own discretion.** Automating user accounts (*selfbotting*) is against the Discord Terms of Service and OwO Bot Community Guidelines. This repository is intended strictly for educational, security research, and personal automation testing purposes. The authors assume no responsibility for account bans, suspensions, or penalties incurred.

---

## 📄 License

This project is licensed under the terms of the **GNU General Public License v3.0 (GPL-3.0)**.  
See the [LICENSE](LICENSE) file for complete licensing terms.

<div align="center">
  <sub>Crafted with passion for automation engineering. 🌊 Mizu OwO Suite.</sub>
</div>
