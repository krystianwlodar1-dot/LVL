import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# =========================
# TOKEN i konfiguracja
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
    """Przycinanie długich tekstów do limitu znaków"""
    if len(text) > limit:
        return text[:limit-3] + "..."
    return text

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

    # Szukamy nicka i statusu online/offline
    player_div = soup.find("h5", class_="js-player-name")
    if not player_div:
        return None
    online = "text-success" in player_div.get("class", [])
    name = player_div.text.strip()

    # Pobieramy level
    level_span = player_div.find_next_sibling("span")
    level = 0
    if level_span:
        try:
            level = int(level_span.text.strip().split()[0])
        except:
            pass

    # HP / MP
    card_body = soup.find("div", class_="card-body")
    hp, mp, outfit_url = 0, 0, None
    if card_body:
        bars = card_body.find_all("div", class_="progress-bar")
        if len(bars) >= 2:
            try:
                hp = int(bars[0].text.strip())
                mp = int(bars[1].text.strip().split()[0])
            except:
                pass
        outfit_div = card_body.find("div", class_="outfit-sprite")
        if outfit_div:
            style = outfit_div.get("style", "")
            if "background-image" in style:
                outfit_url = style.split("url('")[1].split("')")[0]

    # Domek, Gildia, Build Points, Logowanie
    domek, gildia, build_points, logowanie = "Brak", "Brak", "Brak", "Brak"
    list_items = soup.find_all("li", class_="list-group-item")
    for li in list_items:
        text = li.get_text(separator=" ", strip=True)
        if "Domek:" in text:
            domek = truncate(li.find("strong").text.strip())
        elif "Gildia:" in text:
            gildia = truncate(li.find("strong").text.strip())
        elif "Build Points:" in text:
            build_points = truncate(li.find("strong").text.strip())
        elif "Logowanie:" in text:
            logowanie = truncate(li.find("strong").text.strip())

    # Ostatni zgon
    deaths_div = soup.find("div", id="deathsList")
    last_death = "Brak"
    if deaths_div:
        death_items = deaths_div.find_all("div", class_="list-group-item")
        if death_items:
            last_death = truncate(death_items[0].get_text(separator=" ", strip=True))

    return {
        "nick": name,
        "level": level,
        "online": online,
        "hp": hp,
        "mp": mp,
        "outfit_url": outfit_url,
        "domek": domek,
        "gildia": gildia,
        "build_points": build_points,
        "logowanie": logowanie,
        "last_death": last_death,
        "url": url
    }

# =========================
# KOMENDY
# =========================
@bot.command()
async def alert(ctx, *, token=None):
    """Ustaw token Discord w runtime jeśli nie był w ENV"""
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

    # Tworzymy czytelny embed z HP/MP w jednej linijce i kolorami
    embed_color = discord.Color.green() if char_data["online"] else discord.Color.red()
    embed = discord.Embed(title=char_data["nick"], url=char_data["url"], color=embed_color)
    embed.add_field(name="Level", value=str(char_data["level"]), inline=True)
    status_text = "🟢 Online" if char_data["online"] else "🔴 Offline"
    embed.add_field(name="Status", value=status_text, inline=True)
    embed.add_field(name="HP/MP", value=f"❤️ {char_data['hp']} / 💙 {char_data['mp']}", inline=True)
    embed.add_field(name="Domek", value=char_data["domek"], inline=True)
    embed.add_field(name="Gildia", value=char_data["gildia"], inline=True)
    embed.add_field(name="Build Points", value=char_data["build_points"], inline=True)
    embed.add_field(name="Logowanie", value=char_data["logowanie"], inline=True)
    embed.add_field(name="Ostatni zgon", value=char_data["last_death"], inline=False)
    if char_data["outfit_url"]:
        embed.set_thumbnail(url=char_data["outfit_url"])

    await ctx.send(embed=embed)

    # Zapis do monitorowania
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
# ALERTY LVL I ZGONÓW
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

            # Alert lvl co 100
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

            # Alert zgonu
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
    print("❌ Token nie ustawiony w ENV. Użyj komendy !alert <token> w Discordzie, aby ustawić token runtime.")
