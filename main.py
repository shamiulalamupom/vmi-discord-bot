import discord
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID, LOG_LEVEL, LOG_FILE
from logging_setup import setup_logging
from commands.admin import setup_cmd, cancel_cmd
from commands.user import join_cmd, leave_cmd
from events.ready import on_ready as bootstrap_on_ready

log = setup_logging(level=LOG_LEVEL, json_console=False, logfile=LOG_FILE)

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# Register commands on the bot tree
bot.tree.add_command(setup_cmd)
bot.tree.add_command(cancel_cmd)
bot.tree.add_command(join_cmd)
bot.tree.add_command(leave_cmd)

@bot.event
async def on_ready_event():
    # discord.py reserves on_ready name; use different to avoid confusion in editor
    await bootstrap_on_ready(bot, GUILD_ID)

# Proper event hook name
@bot.event
async def on_ready():
    await on_ready_event()

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN in environment.")
    bot.run(DISCORD_TOKEN)
