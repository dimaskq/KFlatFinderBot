import os
import asyncio
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DOMRIA_URL = os.getenv("DOMRIA_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

seen_ads = set()

def parse_domria():
    resp = requests.get(DOMRIA_URL, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")

    ads = []
    for card in soup.select(".ticket-item"):  # картка квартири
        ad_id = card.get("data-id")
        if not ad_id:
            continue

        title = card.select_one(".ticket-title").get_text(strip=True) if card.select_one(".ticket-title") else "Без назви"
        price = card.select_one(".price").get_text(strip=True) if card.select_one(".price") else "Ціну уточнюй"
        link = "https://dom.ria.com" + card.select_one("a")["href"]
        img = card.select_one("img")["src"] if card.select_one("img") else None

        ads.append({"id": ad_id, "title": title, "price": price, "link": link, "img": img})
    return ads

async def check_new_ads():
    ads = parse_domria()
    for ad in ads:
        if ad["id"] not in seen_ads:
            seen_ads.add(ad["id"])
            text = f"🏠 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['link']}"
            if ad["img"]:
                try:
                    await bot.send_photo(chat_id=CHAT_ID, photo=ad["img"], caption=text)
                except:
                    await bot.send_message(chat_id=CHAT_ID, text=text)
            else:
                await bot.send_message(chat_id=CHAT_ID, text=text)

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_new_ads, "interval", minutes=30)  # перевірка раз на 30 хв
    scheduler.start()

    print("✅ Бот запущений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
