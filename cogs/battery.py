import asyncio
import random

from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded

from utils.battery import load_battery, get_battery_status, should_pause


class Battery(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._task = None
        self.cfg = load_battery()

    async def cog_load(self):
        if not self.cfg.get("enabled", False):
            try:
                asyncio.create_task(self.bot.unload_cog("cogs.battery"))
            except ExtensionNotLoaded:
                pass
        else:
            self._task = asyncio.create_task(self._loop())
            await self.bot.log("Battery guard active, will pause farming when low", "#f59e0b")

    async def cog_unload(self):
        if self._task:
            self._task.cancel()
        if self.bot.command_handler_status.get("battery", False):
            self.bot.command_handler_status["battery"] = False

    async def _loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            interval = self.cfg.get("checkInterval", [240, 360])
            await asyncio.sleep(random.uniform(interval[0], interval[1]))

            status = get_battery_status()
            if status is None:
                continue

            want = should_pause(status, self.cfg)
            current = self.bot.command_handler_status.get("battery", False)
            if want and not current:
                self.bot.command_handler_status["battery"] = True
                pct = status.get("percentage")
                self.bot.add_dashboard_log("system", f"Battery low ({pct}%), farming paused", "warn")
                await self.bot.log(f"Battery low at {pct}%, pausing farming until charged", "#f59e0b")
            elif not want and current:
                self.bot.command_handler_status["battery"] = False
                pct = status.get("percentage")
                self.bot.add_dashboard_log("system", f"Battery recovered ({pct}%), resuming", "info")
                await self.bot.log(f"Battery recovered ({pct}%), resuming farming", "#51cf66")


async def setup(bot):
    await bot.add_cog(Battery(bot))
