import os

from typing import Dict

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_API_KEY = os.getenv("DISCORD_API_KEY")
if not DISCORD_API_KEY:
    raise RuntimeError("DISCORD_API_KEY is not set in environment variables")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned_or('$'), intents=intents)

# In-memory matchmaking storage to simulate a MongoDB collection for now.
matchmaking_pool: Dict[int, discord.Member] = {}


@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')


@bot.command(name='hello')
async def hello(ctx: commands.Context) -> None:
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass
    await ctx.send('Hello!')


@bot.command(name='join')
async def matchmake(ctx: commands.Context) -> None:
    user = ctx.author

    try: 
        await ctx.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    if user.id in matchmaking_pool:
        await ctx.author.send(f'You are already in the matchmaking queue.')

        return

    matchmaking_pool[user.id] = user
    current_count = len(matchmaking_pool)
    await ctx.author.send(f'{user.mention} added to matchmaking queue. Current players: {current_count}/2.')

    if current_count >= 2:
        mentions = ' '.join(member.mention for member in matchmaking_pool.values())
        await ctx.send(f'Matchmaking completed with {mentions}')
        for user in matchmaking_pool.values():
            await user.send(f'{user.mention} You have been matched! Check the server.')
        matchmaking_pool.clear()

@bot.command(name='leave')
async def leave_queue(ctx: commands.Context) -> None:
    user = ctx.author

    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    if user.id not in matchmaking_pool:
        await ctx.author.send(f'You are not in the matchmaking queue.')
        return

    del matchmaking_pool[user.id]
    await ctx.author.send(f'{user.mention} removed from matchmaking queue.')

@bot.command(name='disban')
@commands.has_permissions(administrator=True)
async def disban(ctx: commands.Context) -> None:
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    try:
        count = len(matchmaking_pool)
        for user in list(matchmaking_pool.values()):
            try:
                await user.send(f'{user.mention} The matchmaking queue has been cleared by an administrator.')
            except (discord.Forbidden, discord.HTTPException):
                pass
        matchmaking_pool.clear()
        await ctx.author.send(f'Matchmaking queue cleared. Removed {count} players.')
    except (discord.Forbidden, discord.HTTPException):
        await ctx.author.send('Failed to clear the matchmaking queue due to permission issues.')


@disban.error
async def disban_error(ctx: commands.Context, error: commands.CommandError) -> None:
    # Notify the command invoker if they lack the required permissions
    if isinstance(error, commands.MissingPermissions):
        try:
            await ctx.author.send("You do not have permission to run this command (administrator required).")
        except (discord.Forbidden, discord.HTTPException):
            # fallback to channel message if DMs are not possible
            try:
                await ctx.send(f"{ctx.author.mention} You do not have permission to run this command (administrator required).")
            except Exception:
                pass
    else:
        # Optionally notify about other errors
        try:
            await ctx.author.send(f"An error occurred while running the command: {error}")
        except Exception:
            pass

@bot.command(name='clear_channel')
@commands.has_permissions(manage_messages=True)
async def clear_channel(ctx: commands.Context) -> None:
    """Delete all recent (<=14 days) messages in the current channel."""
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    channel = ctx.channel
    try:
        deleted = await channel.purge(limit=None)
    except discord.Forbidden:
        await ctx.author.send(f'I do not have permission to manage messages in {channel.mention}.')
        return
    except discord.HTTPException as exc:
        await ctx.author.send(f'Failed to clear messages in {channel.mention}: {exc}')
        return

    await ctx.author.send(
        f'Removed {len(deleted)} messages from #{channel} (messages older than 14 days cannot be bulk deleted).'
    )


bot.run(DISCORD_API_KEY)
