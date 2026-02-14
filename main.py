import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from bs4 import BeautifulSoup

TOKEN = "TU_WKLEJ_TOKEN"
CHECK_INTERVAL = 300  # 5 minut

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "data.json"

# =========================
# Pomocnicze
# =========================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

async def fetch_character(nick):
    url = f"https://cyleria.pl/?subtopic=characters&name={nick.replace(' ', '+')}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text()

    if "Name:" not in text:
        return None

    # Proste parsowanie (działa stabilnie na Cylerii)
    try:
        level_line = [line for line in text.split("\n") if "Level:" in line][0]
        level = int(level_line.split("Level:")[1].strip().split()[0])
    except:
        level = 0

    online = "Currently online" in text

    try:
        death_line = [line for line in text.split("\n") if "Died at Level" in line]
        last_death = death_line[0].strip() if death_line else "Brak"
    except:
        last_death = "Brak"

    return {
        "level": level,
        "online": online,
        "last_death": last_death,
        "url": url
    }

# =========================
# KOMENDY
# =========================

@bot.command()
async def char(ctx, *, nick):
    data = load_data()

    char_data = await fetch_character(nick)
    if not char_data:
        await ctx.send("❌ Postać nie istnieje.")
        return

    embed = discord.Embed(
        title=nick,
        url=char_data["url"],
        color=discord.Color.green() if char_data["online"] else discord.Color.red()
    )

    embed.add_field(name="Level", value=char_data["level"], inline=True)
    embed.add_field(name="Status", value="🟢 Online" if char_data["online"] else "🔴 Offline", inline=True)
    embed.add_field(name="Ostatni zgon", value=char_data["last_death"], inline=False)

    await ctx.send(embed=embed)

    # zapis do monitorowania
    guild_id = str(ctx.guild.id)

    if guild_id not in data:
        data[guild_id] = {}

    data[guild_id][nick] = {
        "last_level": char_data["level"],
        "channel_id": ctx.channel.id
    }

    save_data(data)

    await ctx.send(f"🔔 Monitoring włączony dla **{nick}**.")

# =========================
# ALERTY LVL
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_levels():
    await bot.wait_until_ready()
    data = load_data()

    for guild_id in data:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue

        for nick in data[guild_id]:
            info = data[guild_id][nick]

            char_data = await fetch_character(nick)
            if not char_data:
                continue

            old_lvl = info["last_level"]
            new_lvl = char_data["level"]

            if new_lvl // 10 > old_lvl // 10:
                channel = guild.get_channel(info["channel_id"])
                if channel:
                    embed = discord.Embed(
                        description=f"🎉 **[{nick}]({char_data['url']})** osiągnął **{new_lvl} lvl!**",
                        color=discord.Color.gold()
                    )
                    await channel.send(embed=embed)

            data[guild_id][nick]["last_level"] = new_lvl
            save_data(data)

            await asyncio.sleep(2)  # żeby nie floodować

# =========================
# START
# =========================

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    check_levels.start()

bot.run(TOKEN)
