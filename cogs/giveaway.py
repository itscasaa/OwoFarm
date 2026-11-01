import asyncio
import json
import os
import time

import discord
from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded


def is_already_joined(message_id: int, joined_ids: set) -> bool:
    return message_id in joined_ids


class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._joined_ids: set = set()
        self._db_path: str = ""

    def _get_db_path(self) -> str:
        if self._db_path:
            return self._db_path
        username = getattr(self.bot, "user", None)
        uid = str(username.id) if username else "unknown"
        self._db_path = os.path.join("config", f"giveaway_ids_{uid}.json")
        return self._db_path

    def _load_ids(self):
        path = self._get_db_path()
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                    self._joined_ids = set(data.get("joined_ids", []))
        except Exception:
            self._joined_ids = set()

    def _save_ids(self):
        path = self._get_db_path()
        if len(self._joined_ids) > 200:
            self._joined_ids = set(list(self._joined_ids)[-200:])
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"joined_ids": list(self._joined_ids)}, f)
        except Exception as e:
            self.bot.loop.create_task(
                self.bot.log(f"Giveaway: failed to save IDs: {e}", "#c25560")
            )

    async def _try_join(self, message):
        cnf = self.bot.settings_dict.get("giveawayJoiner", {})
        if not cnf.get("enabled", False):
            return

        allowed_channels = [int(ch) for ch in cnf.get("channelsToJoin", [])]
        if message.channel.id not in allowed_channels:
            return

        # Find active giveaway button
        target_btn = None
        for row in getattr(message, "components", []):
            for child in getattr(row, "children", []):
                if getattr(child, "disabled", False):
                    continue
                cid = getattr(child, "custom_id", "") or ""
                lbl = (getattr(child, "label", "") or "").lower()
                if cid == "join_giveaway" or "giveaway" in lbl or "join" in lbl:
                    target_btn = child
                    break
            if target_btn:
                break

        if not target_btn:
            return

        if is_already_joined(message.id, self._joined_ids):
            return

        cooldown = cnf.get("cooldown", [2, 5])
        await self.bot.sleep_till(cooldown)
        try:
            await target_btn.click()
            self._joined_ids.add(message.id)
            self._save_ids()
            await self.bot.log(
                f"🎉 Successfully joined giveaway in #{message.channel.name} (Msg ID: {message.id})", "#00d7af"
            )
            if hasattr(self.bot, "add_dashboard_log"):
                self.bot.add_dashboard_log(
                    "giveaway",
                    f"Joined giveaway in #{message.channel.name} (ID: {message.id})",
                    "success",
                )
        except discord.errors.InvalidData:
            # Interaction request was sent and accepted by Discord HTTP API, but gateway interaction_finish was not received
            self._joined_ids.add(message.id)
            self._save_ids()
            await self.bot.log(
                f"🎉 Successfully sent interaction & joined giveaway in #{message.channel.name} (Msg ID: {message.id})", "#00d7af"
            )
            if hasattr(self.bot, "add_dashboard_log"):
                self.bot.add_dashboard_log(
                    "giveaway",
                    f"Joined giveaway in #{message.channel.name} (ID: {message.id})",
                    "success",
                )
        except Exception as e:
            await self.bot.log(
                f"⚠️ Error clicking giveaway in #{message.channel.name}: {e}", "#c25560"
            )

    async def _startup_scan(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(self.bot.random.uniform(2.0, 4.0))
        self._load_ids()
        cnf = self.bot.settings_dict.get("giveawayJoiner", {})
        if not cnf.get("enabled", False):
            return
        allowed_channels = [int(ch) for ch in cnf.get("channelsToJoin", [])]
        for channel_id in allowed_channels:
            try:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(channel_id)
                if not channel:
                    continue
                async for msg in channel.history(limit=cnf.get("messageRangeToCheck", 15)):
                    await self._try_join(msg)
            except Exception as e:
                await self.bot.log(f"Giveaway scan error ch {channel_id}: {e}", "#c25560")

    async def cog_load(self):
        cnf = self.bot.settings_dict.get("giveawayJoiner", {})
        if cnf.get("enabled", False):
            asyncio.create_task(self._startup_scan())
        else:
            try:
                asyncio.create_task(self.bot.unload_cog("cogs.giveaway"))
            except ExtensionNotLoaded:
                pass

    @commands.Cog.listener()
    async def on_message(self, message):
        await self._try_join(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        await self._try_join(after)


async def setup(bot):
    await bot.add_cog(Giveaway(bot))