import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# =========================
# KONFIGURACJA
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "data.json"
PLAYERS_FILE = "players.txt"
CHECK_INTERVAL = 300  # 5 minut

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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
    return text[:limit-3] + "..." if len(text) > limit else text

async def fetch_character(nick):
    url = f"https://cyleria.pl/?subtopic=characters&name={quote_plus(nick)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                html = await resp.text()
    except:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # ====== ONLINE ======
    name_div = soup.find("h5", class_="js-player-name")
    if not name_div:
        return None
    online = "text-success" in name_div.get("class", [])

    # ====== LEVEL ======
    try:
        level_span = name_div.find_next_sibling("span")
        level = int(level_span.text.strip().replace("(", "").replace("lvl)", "").strip())
    except:
        level = 0

    # ====== HP / MP ======
    try:
        progress_bars = soup.select("div.progress-bar")
        hp = int(progress_bars[0].get_text(strip=True))
        mp = int(progress_bars[1].get_text(strip=True).split()[0])
    except:
        hp = mp = 0

    # ====== Outfit ======
    try:
        outfit_div = soup.select_one("div.outfit-sprite")
        outfit_url = outfit_div["data-url"] if outfit_div else None
    except:
        outfit_url = None

    # ====== Domek / Gildia / Build Points / Logowanie ======
    info_dict = {}
    for li in soup.select("li.list-group-item.d-flex.justify-content-between"):
        key_span = li.find("span")
        strong = li.find("strong")
        if key_span and strong:
            key = key_span.text.strip().lower()
            info_dict[key] = strong.get_text(strip=True)

    domek = info_dict.get("domek", "Brak")
    gildia = info_dict.get("gildia", "Brak")
    build_points = info_dict.get("build points", "Brak")
    logowanie = info_dict.get("logowanie", "Brak")

    # ====== OSTATNI ZGON ======
    last_death = "Brak"
    deaths_section = soup.select("div.list-group-item.d-flex.flex-column.align-items-left.text-left")
    if deaths_section:
        first_death = deaths_section[0]
        try:
            date = first_death.find("small", class_="text-muted").text.strip()
            desc = first_death.find("div").text.strip()
            last_death = f"{date} – {desc}"
        except:
            pass

    return {
        "nick": name_div.text.strip(),
        "level": level,
        "online": online,
        "hp": hp,
        "mp": mp,
        "domek": truncate(domek),
        "gildia": truncate(gildia),
        "build_points": truncate(build_points),
        "logowanie": truncate(logowanie),
        "last_death": truncate(last_death, 100),
        "outfit_url": outfit_url,
        "url": url
    }

# =========================
# KOMENDY
# =========================
@bot.command()
async def alert(ctx, *, token=None):
    """Ustaw token Discord runtime"""
    global TOKEN
    if token:
        TOKEN = token
        await ctx.send("✅ Token ustawiony.")
    else:
        await ctx.send("❌ Podaj token po komendzie !alert <token>.")

@bot.command()
async def char(ctx, *, nick):
    data = load_data()
    char_data = await fetch_character(nick)
    if not char_data:
        await ctx.send("❌ Postać nie istnieje.")
        return

    color = discord.Color.green() if char_data["online"] else discord.Color.red()
    embed = discord.Embed(title=char_data["nick"], url=char_data["url"], color=color)
    embed.add_field(name="Level", value=str(char_data["level"]), inline=True)
    embed.add_field(name="Status", value="🟢 Online" if char_data["online"] else "🔴 Offline", inline=True)
    embed.add_field(name="HP/MP", value=f"❤️ {char_data['hp']} / 💙 {char_data['mp']}", inline=True)
    embed.add_field(name="Domek", value=char_data["domek"], inline=True)
    embed.add_field(name="Gildia", value=char_data["gildia"], inline=True)
    embed.add_field(name="Build Points", value=char_data["build_points"], inline=True)
    embed.add_field(name="Logowanie", value=char_data["logowanie"], inline=True)
    embed.add_field(name="Ostatni zgon", value=char_data["last_death"], inline=False)
    if char_data["outfit_url"]:
        embed.set_thumbnail(url=char_data["outfit_url"])

    await ctx.send(embed=embed)

    # Zapis monitoringu
    guild_id = str(ctx.guild.id)
    if guild_id not in data:
        data[guild_id] = {}
    data[guild_id][char_data["nick"]] = {
        "last_level": char_data["level"],
        "last_death": char_data["last_death"],
        "channel_id": ctx.channel.id
    }
    save_data(data)
    await ctx.send(f"🔔 Monitoring włączony dla **{char_data['nick']}**.")

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
# ALERTY
# =========================
@tasks.loop(seconds=CHECK_INTERVAL)
async def check_levels():
    await bot.wait_until_ready()
    data = load_data()
    players = load_players()

    for guild_id in data:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        guild_nicks = set(players) | set(data[guild_id].keys())

        for nick in guild_nicks:
            info = data[guild_id].get(nick, {})
            char_data = await fetch_character(nick)
            if not char_data:
                continue

            old_lvl = info.get("last_level", 0)
            new_lvl = char_data["level"]
            if new_lvl // 100 > old_lvl // 100:
                channel = guild.get_channel(info.get("channel_id", 0))
                if channel:
                    embed = discord.Embed(
                        description=f"🎉 **[{char_data['nick']}]({char_data['url']})** osiągnął **{new_lvl} lvl!**",
                        color=discord.Color.gold()
                    )
                    await channel.send(embed=embed)

            old_death = info.get("last_death", "Brak")
            new_death = char_data["last_death"]
            if new_death != "Brak" and new_death != old_death:
                channel = guild.get_channel(info.get("channel_id", 0))
                if channel:
                    embed = discord.Embed(
                        description=f"⚰️ **[{char_data['nick']}]({char_data['url']})** zginął: {new_death}",
                        color=discord.Color.dark_red()
                    )
                    await channel.send(embed=embed)

            # Aktualizacja danych
            data[guild_id][nick] = {
                "last_level": new_lvl,
                "last_death": new_death,
                "channel_id": info.get("channel_id", 0)
            }
            await asyncio.sleep(1.5)

    save_data(data)

# =========================
# START
# =========================
@bot.event
async def on_ready():
    print(f"✅ Zalogowano jako {bot.user}")
    check_levels.start()

# =========================
# URUCHOMIENIE
# =========================
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Token nie ustawiony w ENV. Użyj komendy !alert <token> w Discordzie.")
