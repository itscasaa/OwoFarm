import re
import asyncio
import time

from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded

won_pattern = r"and won <:cowoncy:\d+> ([\d,]+)"
lose_pattern = r"bet <:cowoncy:\d+> ([\d,]+)"


class Slots(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cmd = {
            "cmd_name": self.bot.alias["slots"]["normal"],
            "cmd_arguments": "20000",
            "prefix": True,
            "checks": False,
            "id": "slots",
        }
        self.turns_lost = 0
        self.exceeded_max_amount = False
        self.gamble_flags = {
            "goal_reached": False,
            "amount_exceeded": False,
            "no_balance": False,
        }
        self._last_roll = 0
        self._loop_task = None

    async def cog_load(self):
        if not self.bot.settings_dict["gamble"]["slots"]["enabled"]:
            try:
                asyncio.create_task(self.bot.unload_cog("cogs.slots"))
            except ExtensionNotLoaded:
                pass
        else:
            self._loop_task = asyncio.create_task(self._slots_worker())

    async def cog_unload(self):
        if self._loop_task:
            self._loop_task.cancel()
        await self.bot.remove_queue(id="slots")

    async def _slots_worker(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(2.0)
        while not self.bot.is_closed():
            try:
                while (
                    not self.bot.command_handler_status["state"]
                    or self.bot.command_handler_status["sleep"]
                    or self.bot.command_handler_status["captcha"]
                    or self.bot.command_handler_status.get("rate_limited", False)
                ):
                    await asyncio.sleep(2.0)

                cnf = self.bot.settings_dict["gamble"]["slots"]
                if not cnf.get("enabled", False):
                    break
                cd = cnf.get("cooldown", [22, 30])
                val = int(cnf.get("startValue", 20000))
                prefix = self.bot.settings_dict.get("setprefix", "owo ")
                silent = self.bot.global_settings_dict.get("silentTextMessages", False)

                await self.bot.send(f"{prefix}s {val}", silent=silent)

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
                await self.bot.log(f"Error in slots worker: {e}", "#c25560")
                await asyncio.sleep(10.0)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.id != 408785106942164992:
            return
        if "slots" not in after.content.lower():
            return

        if "and won nothing... :c" in after.content:
            match = int(re.search(lose_pattern, after.content).group(1).replace(",", ""))
            await self.bot.update_cash(match, reduce=True)
            self.bot.gain_or_lose -= match
            self.turns_lost += 1
            await self.bot.log(f"Lost {match} in slots. Net: {self.bot.gain_or_lose}", "#ffafaf")
            await self.bot.update_gamble_db("losses")

        elif "<:eggplant:417475705719226369>" in after.content.lower() and "and won" in after.content.lower():
            await self.bot.log("Slots: no win, no loss.", "#ffafaf")

        elif "and won" in after.content.lower():
            won = int(re.search(won_pattern, after.content).group(1).replace(",", ""))
            lost = int(re.search(lose_pattern, after.content).group(1).replace(",", ""))
            profit = won - lost
            await self.bot.update_cash(profit)
            self.bot.gain_or_lose += profit
            self.turns_lost = 0
            await self.bot.log(f"Won {won} in slots. Net: {self.bot.gain_or_lose}", "#51cf66")
            await self.bot.update_gamble_db("wins")


async def setup(bot):
    await bot.add_cog(Slots(bot))
