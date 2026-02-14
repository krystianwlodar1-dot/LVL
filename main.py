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

    # klasa / opis
    try:
        desc = div.find_next("span", class_="d-block small text-muted").text.strip()
    except:
        desc = "Brak opisu"

    # obrazek postaci (outfit)
    try:
        outfit_div = soup.find("div", class_="outfit-sprite")
        outfit_img = outfit_div.get("data-url")
    except:
        outfit_img = None

    # progress bars (HP i MP)
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

    # ekwipunek
    equipment = []
    table = soup.find("table")
    if table:
        for td in table.find_all("td"):
            img = td.find("img")
            if img:
                name = img.get("alt")
                src = img.get("src")
                # rarity wg class div
                parent_div = td.find("div")
                rarity_class = parent_div.get("class", [])
                if "unique-item" in rarity_class:
                    rarity = "Unique"
                elif "rare-item" in rarity_class:
                    rarity = "Rare"
                else:
                    rarity = "Normal"
                equipment.append({"name": name, "img": src, "rarity": rarity})

    return {
        "nick": player_name,
        "lvl": lvl,
        "desc": desc,
        "outfit_img": outfit_img,
        "hp": hp,
        "mp": mp,
        "mp_bonus": mp_bonus,
        "equipment": equipment
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

    embed = discord.Embed(
        title=f"{info['nick']} (Lvl {info['lvl']})",
        description=info['desc'],
        color=discord.Color.green()
    )

    # HP / MP
    if info["hp"]: embed.add_field(name="HP", value=info["hp"])
    if info["mp"]:
        mp_text = f"{info['mp']}"
        if info["mp_bonus"]:
            mp_text += f" (+{info['mp_bonus']} bonus)"
        embed.add_field(name="MP", value=mp_text)

    # Outfit / obrazek
    if info["outfit_img"]:
        embed.set_thumbnail(url=info["outfit_img"])

    # Ekwipunek
    if info["equipment"]:
        equip_text = ""
        for e in info["equipment"]:
            equip_text += f"[{e['name']}]({e['img']}) – {e['rarity']}\n"
        embed.add_field(name="Ekwipunek", value=equip_text, inline=False)

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
            await channel.send(f"🎉 **{nick}** osiągnął **{lvl} lvl**!")
        levels[nick] = lvl

    with open("levels.json", "w") as f:
        json.dump(levels, f)

bot.run(TOKEN)
