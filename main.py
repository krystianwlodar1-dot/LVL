import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# =========================
# TOKEN z environment
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ Zmienna środowiskowa DISCORD_TOKEN nie jest ustawiona!")

CHECK_INTERVAL = 300  # 5 minut
DATA_FILE = "data.json"
PLAYERS_FILE = "players.txt"

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

def load_players():
    if not os.path.exists(PLAYERS_FILE):
        return []
    with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

async def fetch_character(nick):
    url = f"https://cyleria.pl/?subtopic=characters&name={quote_plus(nick)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                html = await resp.text()
    except Exception as e:
        print(f"⚠️ Błąd pobierania postaci {nick}: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    # Szukamy nicka w tekście strony
    name_line = [line.strip() for line in text.split("\n") if nick.lower() in line.lower()]
    if not name_line:
        return None

    # Level
    try:
        level_line = [line for line in text.split("\n") if "Level:" in line][0]
        level = int(level_line.split("Level:")[1].strip().split()[0])
    except:
        level = 0

    online = "Currently online" in text

    # Ostatni zgon
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

    # zapis do monitorowania per guild
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

    # Lista nicków z pliku players.txt
    players = load_players()

    for guild_id in data:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue

        # Lista do monitorowania: z pliku + dodatkowo postacie dodane komendą !char
        guild_nicks = set(players) | set(data[guild_id].keys())

        for nick in guild_nicks:
            info = data[guild_id].get(nick, {})
            char_data = await fetch_character(nick)
            if not char_data:
                continue

            # Alert lvl co 10
            old_lvl = info.get("last_level", 0)
            new_lvl = char_data["level"]
            if new_lvl // 10 > old_lvl // 10:
                channel = guild.get_channel(info.get("channel_id", 0))
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
                channel = guild.get_channel(info.get("channel_id", 0))
                if channel:
                    embed = discord.Embed(
                        description=f"⚰️ **[{nick}]({char_data['url']})** zginął: {new_death}",
                        color=discord.Color.dark_red()
                    )
                    await channel.send(embed=embed)

            # Aktualizacja danych
            data[guild_id][nick] = {
                "last_level": new_lvl,
                "last_death": new_death,
                "channel_id": info.get("channel_id", 0)  # jeśli brak, nie wyśle alertu
            }

            await asyncio.sleep(1.5)  # małe opóźnienie, żeby nie floodować

    save_data(data)

# =========================
# START
# =========================
@bot.event
async def on_ready():
    print(f"✅ Zalogowano jako {bot.user}")
    check_levels.start()

bot.run(TOKEN)
