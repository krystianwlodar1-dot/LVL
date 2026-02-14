import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

# =========================
# KONFIGURACJA
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
CHECK_INTERVAL = 300  # 5 minut

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "data.json"
PLAYERS_FILE = "players.txt"

# =========================
# FUNKCJE POMOCNICZE
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

def truncate(text, limit=70):
    return text if len(text) <= limit else text[:limit] + "..."

async def fetch_character(nick):
    url = f"https://cyleria.pl/?subtopic=characters&name={quote_plus(nick)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                html = await resp.text()
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")
    
    # Sprawdzenie czy postać istnieje
    name_tag = soup.select_one(".js-player-name")
    if not name_tag:
        return None
    
    # Level
    lvl_tag = soup.find("span", text=lambda t: t and "lvl" in t)
    try:
        level = int(lvl_tag.text.strip().replace("(", "").replace(")", "").replace("lvl","").strip())
    except:
        level = 0

    # Online/offline po kolorze nicku
    online = "text-success" in name_tag.get("class", [])

    # HP i MP
    hp_tag = soup.select_one(".progress-bar.bg-danger span")
    mp_tag = soup.select_one(".progress-bar.bg-primary span")
    try:
        hp = hp_tag.text.strip()
        mp = mp_tag.text.strip()
    except:
        hp = mp = "Brak"

    # Outfit
    outfit_tag = soup.select_one(".outfit-sprite")
    outfit_url = outfit_tag["data-url"] if outfit_tag else None

    # Domek
    domek_tag = soup.find("li", string=lambda t: t and "Domek:" in t)
    try:
        domek = domek_tag.strong.text.strip()
    except:
        domek = "Brak"

    # Gildia
    gildia_tag = soup.find("li", string=lambda t: t and "Gildia:" in t)
    try:
        gildia = gildia_tag.strong.text.strip()
    except:
        gildia = "Brak"

    # Build Points
    build_tag = soup.find("li", string=lambda t: t and "Build Points:" in t)
    try:
        build_points = build_tag.strong.get_text(" / ", strip=True)
    except:
        build_points = "Brak"

    # Logowanie
    login_tag = soup.find("li", string=lambda t: t and "Logowanie:" in t)
    try:
        last_login = login_tag.strong.text.strip()
    except:
        last_login = "Brak"

    # Ostatni zgon
    deaths = soup.select("div.list-group-item.d-flex.flex-column.align-items-left.text-left")
    if deaths:
        last_death_date = deaths[0].select_one("small").text.strip()
        last_death_desc = deaths[0].select_one("div").text.strip()
        last_death = f"{last_death_date} - {truncate(last_death_desc)}"
    else:
        last_death = "Brak"

    return {
        "level": level,
        "online": online,
        "hp": hp,
        "mp": mp,
        "outfit": outfit_url,
        "domek": domek,
        "gildia": gildia,
        "build_points": build_points,
        "last_login": last_login,
        "last_death": last_death,
        "url": url
    }

# =========================
# KOMENDY
# =========================

@bot.command()
async def alert(ctx, *, token=None):
    global TOKEN
    if token:
        TOKEN = token
        await ctx.send("✅ Token ustawiony.")
    else:
        await ctx.send("❌ Brak tokena.")

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

    embed.add_field(name="Status", value="🟢 Online" if char_data["online"] else "🔴 Offline", inline=True)
    embed.add_field(name="Level", value=char_data["level"], inline=True)
    embed.add_field(name="HP / MP", value=f"❤️ {char_data['hp']} / 💙 {char_data['mp']}", inline=True)
    if char_data["outfit"]:
        embed.set_thumbnail(url=char_data["outfit"])
    embed.add_field(name="Domek", value=char_data["domek"], inline=True)
    embed.add_field(name="Gildia", value=char_data["gildia"], inline=True)
    embed.add_field(name="Build Points", value=char_data["build_points"], inline=True)
    embed.add_field(name="Ostatnie logowanie", value=char_data["last_login"], inline=True)
    embed.add_field(name="Ostatni zgon", value=char_data["last_death"], inline=False)

    await ctx.send(embed=embed)

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
        await ctx.send("❌ Postać nie jest monitorowana.")

# =========================
# ALERTY
# =========================

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_levels():
    await bot.wait_until_ready()
    data = load_data()
    updated = False

    for guild_id in data:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        for nick in list(data[guild_id].keys()):
            info = data[guild_id][nick]
            char_data = await fetch_character(nick)
            if not char_data:
                continue

            # Alert lvl co 100 lvl
            old_lvl = info["last_level"]
            new_lvl = char_data["level"]
            if new_lvl // 100 > old_lvl // 100:
                channel = guild.get_channel(info["channel_id"])
                if channel:
                    embed = discord.Embed(
                        description=f"🎉 **[{nick}]({char_data['url']})** osiągnął **{new_lvl} lvl!**",
                        color=discord.Color.gold()
                    )
                    await channel.send(embed=embed)

            # Alert zgonu
            if char_data["last_death"] != info.get("last_death"):
                channel = guild.get_channel(info["channel_id"])
                if channel:
                    embed = discord.Embed(
                        description=f"💀 **[{nick}]({char_data['url']})** zginął!\n{char_data['last_death']}",
                        color=discord.Color.dark_red()
                    )
                    await channel.send(embed=embed)

            data[guild_id][nick]["last_level"] = new_lvl
            data[guild_id][nick]["last_death"] = char_data["last_death"]
            updated = True
            await asyncio.sleep(1.5)  # unikamy floodowania

    if updated:
        save_data(data)

# =========================
# START
# =========================

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    # Monitorowanie graczy z players.txt
    players = load_players()
    guilds = bot.guilds
    for guild in guilds:
        guild_id = str(guild.id)
        data = load_data()
        if guild_id not in data:
            data[guild_id] = {}
        for nick in players:
            if nick not in data[guild_id]:
                data[guild_id][nick] = {
                    "last_level": 0,
                    "last_death": "Brak",
                    "channel_id": None
                }
        save_data(data)
    check_levels.start()

bot.run(TOKEN)
