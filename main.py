import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from bs4 import BeautifulSoup

# =========================
# TOKEN z zmiennej środowiskowej
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Zmienna środowiskowa DISCORD_TOKEN nie jest ustawiona!")

CHECK_INTERVAL = 300  # 5 minut
DATA_FILE = "data.json"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# Funkcje pomocnicze
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                html = await resp.text()
    except Exception as e:
        print(f"⚠️ Błąd pobierania postaci {nick}: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    if "Name:" not in text:
        return None

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
        "last_death": char_data["last_death"],
        "channel_id": ctx.channel.id
    }
    save_data(data)
    await ctx.send(f"🔔 Monitoring włączony dla **{nick}**.")

@bot.command()
async def stopchar(ctx, *, nick):
    data = load_data()
    guild_id = str(ctx.guild.id)
    if guild_id in data and nick in data[guild_id]:
        del data[guild_id][nick]
        save_data(data)
        await ctx.send(f"🛑 Monitoring wyłączony dla **{nick}**.")
    else:
        await ctx.send("❌ Postać nie była monitorowana.")

# =========================
# ALERTY LVL i ZGONÓW
# =========================
@tasks.loop(seconds=CHECK_INTERVAL)
async def check_levels():
    await bot.wait_until_ready()
    data = load_data()
    changed = False

    for guild_id in data:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue

        for nick in data[guild_id]:
            info = data[guild_id][nick]
            char_data = await fetch_character(nick)
            if not char_data:
                continue

            # Alert lvl co 10
            old_lvl = info.get("last_level", 0)
            new_lvl = char_data["level"]
            if new_lvl // 10 > old_lvl // 10:
                channel = guild.get_channel(info["channel_id"])
                if channel:
                    embed = discord.Embed(
                        description=f"🎉 **[{nick}]({char_data['url']})** osiągnął **{new_lvl} lvl!**",
                        color=discord.Color.gold()
                    )
                    await channel.send(embed=embed)

            # Alert zgonu
            old_death = info.get("last_death", "Brak")
            new_death = char_data["last_death"]
            if new_death != "Brak" and new_death != old_death:
                channel = guild.get_channel(info["channel_id"])
                if channel:
                    embed = discord.Embed(
                        description=f"⚰️ **[{nick}]({char_data['url']})** zginął: {new_death}",
                        color=discord.Color.dark_red()
                    )
                    await channel.send(embed=embed)

            # aktualizacja danych
            data[guild_id][nick]["last_level"] = new_lvl
            data[guild_id][nick]["last_death"] = new_death

            await asyncio.sleep(1.5)  # małe opóźnienie żeby nie floodować

    save_data(data)

# =========================
# START
# =========================
@bot.event
async def on_ready():
    print(f"✅ Zalogowano jako {bot.user}")
    check_levels.start()

bot.run(TOKEN)
