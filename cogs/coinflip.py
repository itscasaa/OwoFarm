import re
import asyncio

from discord.ext import commands
from discord.ext.commands import ExtensionNotLoaded

won_pattern = re.compile(r"(?:you won|and won)\s+\**<:cowoncy:\d+>\s*([\d,]+)", re.I)
lose_pattern = re.compile(r"spent\s+\**<:cowoncy:\d+>\s*([\d,]+)", re.I)


class Coinflip(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.turns_lost = 0
        self.exceeded_max_amount = False
        self.gamble_flags = {
            "goal_reached": False,
            "amount_exceeded": False,
            "no_balance": False,
        }
        self._loop_task = None
        self._processed_msg_ids = set()

    async def cog_load(self):
        if not self.bot.settings_dict.get("gamble", {}).get("coinflip", {}).get("enabled", False):
            try:
                asyncio.create_task(self.bot.unload_cog("cogs.coinflip"))
            except ExtensionNotLoaded:
                pass
        else:
            self._loop_task = asyncio.create_task(self._cf_worker())

    async def cog_unload(self):
        if self._loop_task:
            self._loop_task.cancel()
        await self.bot.remove_queue(id="coinflip")

    async def _cf_worker(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(self.bot.random.uniform(2.0, 4.0))

        while not self.bot.is_closed():
            try:
                while (
                    not self.bot.command_handler_status["state"]
                    or self.bot.command_handler_status["sleep"]
                    or self.bot.command_handler_status["captcha"]
                    or self.bot.command_handler_status.get("rate_limited", False)
                ):
                    await asyncio.sleep(2.0)

                cnf = self.bot.settings_dict.get("gamble", {}).get("coinflip", {})
                if not cnf.get("enabled", False):
                    await asyncio.sleep(5.0)
                    continue

                cd = cnf.get("cooldown", [20, 28])
                val = int(cnf.get("startValue", 5000))
                strategy = cnf.get("strategy", "constant")
                goal_cfg = self.bot.settings_dict.get("gamble", {}).get("goalSystem", {})

                if strategy in ("constant", "safe"):
                    amount_to_gamble = val
                else:
                    mult = cnf.get("multiplierOnLose", 1)
                    amount_to_gamble = int(val * (mult ** self.turns_lost))

                # Safe mode streak check
                if strategy == "safe" and self.turns_lost >= cnf.get("maxStreakSafe", 3):
                    await self.bot.log(
                        f"Safe Mode: Lost {self.turns_lost} in a row. Stopping coinflip.", "#ff4444"
                    )
                    await asyncio.sleep(60.0)
                    continue

                # Goal system check
                if goal_cfg.get("enabled", False) and self.bot.gain_or_lose > goal_cfg.get("amount", 500000):
                    if not self.gamble_flags["goal_reached"]:
                        self.gamble_flags["goal_reached"] = True
                        await self.bot.log(
                            f"Goal reached {self.bot.gain_or_lose}/{goal_cfg['amount']} — stopping coinflip.",
                            "#4a270c",
                        )
                    await asyncio.sleep(30.0)
                    continue
                else:
                    self.gamble_flags["goal_reached"] = False

                # Balance check
                user_balance = self.bot.user_status.get("balance", 0)
                if self.bot.settings_dict.get("cashCheck", False) and amount_to_gamble > user_balance:
                    if not self.gamble_flags["no_balance"]:
                        self.gamble_flags["no_balance"] = True
                        await self.bot.log(
                            f"Next bet ({amount_to_gamble}) exceeds balance ({user_balance}) — pausing.",
                            "#4a270c",
                        )
                    await asyncio.sleep(30.0)
                    continue
                else:
                    self.gamble_flags["no_balance"] = False

                # Allotted amount check
                allotted = self.bot.settings_dict.get("gamble", {}).get("allottedAmount", 1000000)
                if self.bot.gain_or_lose + (allotted - amount_to_gamble) <= 0:
                    if not self.gamble_flags["amount_exceeded"]:
                        self.gamble_flags["amount_exceeded"] = True
                        await self.bot.log(
                            f"Allotted amount ({allotted}) exceeded — pausing coinflip.",
                            "#4a270c",
                        )
                    await asyncio.sleep(60.0)
                    continue
                else:
                    self.gamble_flags["amount_exceeded"] = False

                if amount_to_gamble > 250000:
                    self.exceeded_max_amount = True
                    await self.bot.log("Max coinflip amount (250,000) exceeded — pausing.", "#ff4444")
                    await asyncio.sleep(60.0)
                    continue

                # Construct and send command
                prefix = self.bot.settings_dict.get("setprefix", "owo ")
                silent = self.bot.global_settings_dict.get("silentTextMessages", False)
                options = cnf.get("options", [])
                opt_str = f" {self.bot.random.choice(options)}" if options else ""
                cmd_text = f"{prefix}cf {amount_to_gamble}{opt_str}".strip()

                color = self.bot.misc.get("command_info", {}).get("coinflip", {}).get("log_color", "#945322")
                await self.bot.send(cmd_text, color=color, silent=silent)
                self.bot.add_dashboard_log("coinflip", cmd_text)

                # Sleep until next coinflip cooldown
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
                await self.bot.log(f"Error in coinflip worker: {e}", "#c25560")
                await asyncio.sleep(10.0)

    async def _process_result(self, message):
        if message.id in self._processed_msg_ids:
            return

        content = message.content or ""
        content_lower = content.lower()

        if "chose" not in content_lower:
            return

        is_loss = "and you lost it all... :c" in content_lower
        is_win = "and you won" in content_lower or "and won" in content_lower

        if not (is_loss or is_win):
            return

        self._processed_msg_ids.add(message.id)
        if len(self._processed_msg_ids) > 200:
            self._processed_msg_ids.clear()

        try:
            spent_match = lose_pattern.search(content)
            spent_amount = int(spent_match.group(1).replace(",", "")) if spent_match else 0

            if is_loss:
                self.turns_lost += 1
                if spent_amount > 0:
                    await self.bot.update_cash(spent_amount, reduce=True)
                    self.bot.gain_or_lose -= spent_amount
                await self.bot.log(f"Lost {spent_amount} in coinflip. Net: {self.bot.gain_or_lose}", "#ffafaf")
                await self.bot.update_gamble_db("losses")
            elif is_win:
                won_match = won_pattern.search(content)
                won_amount = int(won_match.group(1).replace(",", "")) if won_match else (spent_amount * 2)
                profit = won_amount - spent_amount if spent_amount > 0 else won_amount
                self.turns_lost = 0
                await self.bot.update_cash(profit)
                self.bot.gain_or_lose += profit
                await self.bot.log(f"Won {won_amount} in coinflip. Net: {self.bot.gain_or_lose}", "#51cf66")
                await self.bot.update_gamble_db("wins")
        except Exception as e:
            await self.bot.log(f"Error - {e}, in coinflip _process_result()", "#c25560")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.author.id != 408785106942164992:
            return
        if after.channel.id not in (self.bot.channel_id, getattr(self.bot.cm, "id", None)):
            return
        await self._process_result(after)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.id != 408785106942164992:
            return
        if message.channel.id not in (self.bot.channel_id, getattr(self.bot.cm, "id", None)):
            return
        await self._process_result(message)


async def setup(bot):
    await bot.add_cog(Coinflip(bot))
