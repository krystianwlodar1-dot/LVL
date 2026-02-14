import discord
from discord.ext import commands
import requests
from bs4 import BeautifulSoup
import os

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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

    return span.text.replace("(", "").replace(")", "")

@bot.event
async def on_ready():
    print("LVL Bot Online")

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

    if not lvl:
        await ctx.send(f"Nie znaleziono postaci **{nick}**")
        return

    await ctx.send(f"**{nick}** ma **{lvl}**")

bot.run(TOKEN)
