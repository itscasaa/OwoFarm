   

import asyncio

from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded

class Owo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._task = None

    async def cog_load(self):
        if not self.bot.settings_dict["commands"]["owo"]["enabled"]:
            try:
                asyncio.create_task(self.bot.unload_cog("cogs.owo"))
            except ExtensionNotLoaded:
                pass
        else:
            self._task = asyncio.create_task(self._owo_loop())

    async def cog_unload(self):
        if self._task:
            self._task.cancel()
        await self.bot.remove_queue(id="owo")

    async def _owo_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(self.bot.random.uniform(14.0, 18.0))

        while not self.bot.is_closed():
            try:
                while (
                    not self.bot.command_handler_status["state"]
                    or self.bot.command_handler_status["sleep"]
                    or self.bot.command_handler_status["captcha"]
                    or self.bot.command_handler_status.get("rate_limited", False)
                ):
                    await asyncio.sleep(1.5)

                silent = self.bot.global_settings_dict.get("silentTextMessages", False)
                await self.bot.send("owo", silent=silent)

                cd = self.bot.settings_dict["commands"]["owo"].get("cooldown", [24, 34])
                sleep_time = (
                    self.bot.random.uniform(cd[0], cd[1])
                    if isinstance(cd, list)
                    else float(cd)
                )
                deadline = asyncio.get_running_loop().time() + sleep_time
                while asyncio.get_running_loop().time() < deadline:
                    if (
                        self.bot.command_handler_status["captcha"]
                        or self.bot.command_handler_status["sleep"]
                        or not self.bot.command_handler_status["state"]
                    ):
                        break
                    await asyncio.sleep(min(1.0, deadline - asyncio.get_running_loop().time()))

            except asyncio.CancelledError:
                break
            except Exception as e:
                await self.bot.log(f"Error in owo loop: {e}", "#c25560")
                await asyncio.sleep(10.0)


async def setup(bot):
    await bot.add_cog(Owo(bot))