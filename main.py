import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import os
import json

TOKEN = os.getenv("DISCORD_TOKEN")
ALERT_CHANNEL_ID = 123456789012345678  # <- wpisz ID kanału dla alertów

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- poziomy do alertów ---
levels = {}
if os.path.exists("levels.json"):
    try:
        with open("levels.json", "r") as f:
            levels = json.load(f)
    except json.JSONDecodeError:
        levels = {}

# --- funkcja pobierająca pełne info postaci ---
def get_character_info(nick):
    url = f"https://cyleria.pl/?subtopic=characters&name={nick}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # nick i lvl
    try:
        div = soup.find("div", class_="d-flex align-items-baseline justify-content-center gap-1")
        player_name = div.find("h5", class_="js-player-name").text.strip()
        lvl = int(div.find("span").text.replace("(", "").replace(" lvl)", ""))
    except:
        player_name = nick
        lvl = None

    # opis / klasa
    try:
        desc = div.find_next("span", class_="d-block small text-muted").text.strip()
    except:
        desc = "Brak opisu"

    # obrazek outfit
    try:
        outfit_div = soup.find("div", class_="outfit-sprite")
        outfit_img = outfit_div.get("data-url")
    except:
        outfit_img = None

    # status online/offline
    online_status = False
    try:
        online_span = div.find("span", class_="text-success")
        if online_span:
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
            hp = None
        try:
            mp_text = progress_bars[1].span.text.strip()
            mp = int(mp_text.split()[0])
            if "bonusu" in mp_text:
                mp_bonus = int(''.join(filter(str.isdigit, mp_text.split('+')[1])))
        except:
            mp = None
            mp_bonus = None

    # dodatkowe informacje z karty
    card_info = soup.find("div", class_="card-body p-0")
    house = guild = build_points = last_login = "Brak"
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

    # ostatni zgon
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

# --- komendy Discord ---
@bot.event
async def on_ready():
    print("LVL Bot Online")
    check_levels.start()

@bot.command()
async def info(ctx):
    await ctx.send(
        "**Komendy:**\n"
        "`!char NICK` – sprawdza poziom i pełne info\n"
        "`!lista` – lista graczy\n"
        "`!info` – pokazuje pomoc"
    )

@bot.command()
async def lista(ctx):
    try:
        with open("players.txt", "r") as f:
            players = [p.strip() for p in f.readlines()]
        await ctx.send("**Lista graczy:**\n" + "\n".join(players))
    except:
        await ctx.send("Brak pliku players.txt")

@bot.command()
async def char(ctx, nick):
    info = get_character_info(nick)
    if not info:
        await ctx.send(f"Nie znaleziono postaci **{nick}**")
        return

    # HP / MP w jednej linijce
    hp_text = str(info["hp"]) if info["hp"] is not None else "Brak"
    if info["mp"] is not None:
        mp_text = str(info["mp"])
        if info.get("mp_bonus"):
            mp_text += f" (+{info['mp_bonus']})"
    else:
        mp_text = "Brak"

    # kolor embed w zależności od statusu
    color = discord.Color.green() if info.get("online") else discord.Color.red()

    # opis z pogrubieniami
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
        title=f"{info['nick']} (Lvl {info['lvl']})",
        description=description,
        color=color
    )

    # Outfit / obrazek
    if info["outfit_img"]:
        embed.set_thumbnail(url=info["outfit_img"])

    await ctx.send(embed=embed)

# --- alert co 10 lvl ---
@tasks.loop(minutes=10)
async def check_levels():
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if not channel:
        print("Nie znaleziono kanału alertów")
        return
    try:
        with open("players.txt", "r") as f:
            players = [p.strip() for p in f.readlines()]
    except:
        print("Brak pliku players.txt")
        return

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

    with open("levels.json", "w") as f:
        json.dump(levels, f)

bot.run(TOKEN)
