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

ALERT_CHANNEL_ID = 123456789012345678  # <- wpisz ID kanału, gdzie mają iść alerty

# wczytanie poprzednich poziomów
if os.path.exists("levels.json"):
    with open("levels.json", "r") as f:
        levels = json.load(f)
else:
    levels = {}

def get_level(nick):
    url = f"https://cyleria.pl/?subtopic=characters&name={nick}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    div = soup.find("div", class_="d-flex align-items-baseline justify-content-center gap-1")
    if not div:
        return None
    span = div.find("span")
    if not span:
        return None
    try:
        lvl = int(span.text.replace("(", "").replace(" lvl)", ""))
        return lvl
    except:
        return None

@bot.event
async def on_ready():
    print("LVL Bot Online")
    check_levels.start()  # uruchamiamy cykliczne sprawdzanie

@bot.command()
async def info(ctx):
    await ctx.send(
        "**Komendy:**\n"
        "`!char NICK` – sprawdza poziom\n"
        "`!lista` – lista graczy\n"
        "`!info` – pokazuje pomoc"
    )

@bot.command()
async def lista(ctx):
    try:
        with open("players.txt", "r") as f:
            players = f.read()
        await ctx.send("**Lista graczy:**\n" + players)
    except:
        await ctx.send("Brak pliku players.txt")

@bot.command()
async def char(ctx, nick):
    lvl = get_level(nick)
    if lvl is None:
        await ctx.send(f"Nie znaleziono postaci **{nick}**")
        return
    await ctx.send(f"**{nick}** ma **{lvl}**")

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
        lvl = get_level(nick)
        if lvl is None:
            continue

        last_lvl = levels.get(nick, 0)
        # jeśli poziom przeszedł przez wielokrotność 10
        if lvl // 10 > last_lvl // 10:
            await channel.send(f"🎉 **{nick}** osiągnął **{lvl} lvl**!")
        
        # zapisujemy aktualny poziom
        levels[nick] = lvl

    # zapisujemy plik
    with open("levels.json", "w") as f:
        json.dump(levels, f)

bot.run(TOKEN)
