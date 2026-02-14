import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import os
import json

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CONFIG_FILE = "config.json"
LEVELS_FILE = "levels.json"

# ================= CONFIG =================

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

config = load_config()

# ================= LEVELS =================

if os.path.exists(LEVELS_FILE):
    try:
        with open(LEVELS_FILE, "r") as f:
            levels = json.load(f)
    except:
        levels = {}
else:
    levels = {}

# ================= SCRAPER =================

def get_character_info(nick):
    url = f"https://cyleria.pl/?subtopic=characters&name={nick}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Nick i lvl
    try:
        div = soup.find("div", class_="d-flex align-items-baseline justify-content-center gap-1")
        player_name = div.find("h5", class_="js-player-name").text.strip()
        lvl = int(div.find("span").text.replace("(", "").replace(" lvl)", ""))
    except:
        player_name = nick
        lvl = None

    # Klasa/opis
    try:
        desc = div.find_next("span", class_="d-block small text-muted").text.strip()
    except:
        desc = "Brak opisu"

    # Outfit
    try:
        outfit_div = soup.find("div", class_="outfit-sprite")
        outfit_img = outfit_div.get("data-url")
    except:
        outfit_img = None

    # Online status
    online_status = False
    try:
        if div.find("span", class_="text-success"):
            online_status = True
    except:
        online_status = False

    # HP / MP
    progress_bars = soup.find_all("div", class_="progress-bar")
    hp, mp, mp_bonus = None, None, None

    if progress_bars:
        try:
            hp = int(progress_bars[0].span.text.strip())
        except:
            pass

        try:
            mp_text = progress_bars[1].span.text.strip()
            mp = int(mp_text.split()[0])
            if "+" in mp_text:
                mp_bonus = int(''.join(filter(str.isdigit, mp_text.split('+')[1])))
        except:
            pass

    # Informacje dodatkowe
    house = guild = build_points = last_login = "Brak"
    card_info = soup.find("div", class_="card-body p-0")
    if card_info:
        for li in card_info.find_all("li", class_="list-group-item"):
            span = li.find("span")
            strong = li.find("strong")
            if not span or not strong:
                continue

            key = span.text.strip().lower()
            value = strong.get_text(separator=" ", strip=True)

            if "domek" in key:
                house = value
            elif "gildia" in key:
                guild = value
            elif "build points" in key:
                build_points = value
            elif "logowanie" in key:
                last_login = value

    # Ostatni zgon
    last_death = "Brak"
    death_div = soup.find("div", class_="list-group-item d-flex flex-column align-items-left text-left")
    if death_div:
        try:
            death_date = death_div.find("small").text.strip()
        except:
            death_date = ""
        try:
            death_info = death_div.find("div").get_text(separator=" ", strip=True)
        except:
            death_info = ""

        if death_date or death_info:
            last_death = f"{death_date} — {death_info}"

    return {
        "nick": player_name,
        "lvl": lvl,
        "desc": desc,
        "outfit_img": outfit_img,
        "hp": hp,
        "mp": mp,
        "mp_bonus": mp_bonus,
        "house": house,
        "guild": guild,
        "build_points": build_points,
        "last_login": last_login,
        "last_death": last_death,
        "online": online_status
    }

# ================= EVENTS =================

@bot.event
async def on_ready():
    print("Bot online")
    check_levels.start()

# ================= COMMANDS =================

@bot.command()
async def char(ctx, *, nick):
    nick = nick.strip('"')
    info = get_character_info(nick)

    if not info:
        await ctx.send(f"Nie znaleziono postaci **{nick}**")
        return

    hp_text = str(info["hp"]) if info["hp"] else "Brak"
    mp_text = "Brak"
    if info["mp"]:
        mp_text = str(info["mp"])
        if info["mp_bonus"]:
            mp_text += f" (+{info['mp_bonus']})"

    color = discord.Color.green() if info["online"] else discord.Color.red()
    status_icon = "🟢" if info["online"] else "🔴"

    description = (
        f"**{info['desc']}**\n\n"
        f"**HP:** {hp_text} / **MP:** {mp_text}\n"
        f"**Domek:** {info['house']}\n"
        f"**Gildia:** {info['guild']}\n"
        f"**Build Points:** {info['build_points']}\n"
        f"**Ostatnie logowanie:** {info['last_login']}\n"
        f"**Ostatni zgon:** {info['last_death']}"
    )

    embed = discord.Embed(
        title=f"{status_icon} {info['nick']} (Lvl {info['lvl']})",
        description=description,
        color=color
    )

    if info["outfit_img"]:
        embed.set_thumbnail(url=info["outfit_img"])

    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setalert(ctx):
    config["alert_channel_id"] = ctx.channel.id
    save_config(config)
    await ctx.send("✅ Ten kanał został ustawiony jako kanał alertów.")

# ================= LEVEL ALERT =================

@tasks.loop(minutes=10)
async def check_levels():
    alert_channel_id = config.get("alert_channel_id")

    if not alert_channel_id:
        return

    channel = bot.get_channel(alert_channel_id)
    if not channel:
        return

    if not os.path.exists("players.txt"):
        return

    with open("players.txt", "r") as f:
        players = [p.strip() for p in f.readlines()]

    for nick in players:
        info = get_character_info(nick)
        if not info or not info["lvl"]:
            continue

        lvl = info["lvl"]
        last_lvl = levels.get(nick, 0)

        if lvl // 10 > last_lvl // 10:
            url = f"https://cyleria.pl/?subtopic=characters&name={nick}"
            await channel.send(f"🎉 [{nick}]({url}) osiągnął **{lvl} lvl**!")

        levels[nick] = lvl

    with open(LEVELS_FILE, "w") as f:
        json.dump(levels, f)

# ================= RUN =================

bot.run(TOKEN)
