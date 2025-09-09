from dotenv import load_dotenv
import os
import asyncio
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.client.bot import DefaultBotProperties

# --- Завантаження токена з .env ---
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")  

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- Функція парсингу всіх сторінок ---
def parse_all(url):
    apartments = []
    page = 1

    while True:
        if page == 1:
            page_url = url
        else:
            if "/p-" in url:
                page_url = url.split("/p-")[0] + f"/p-{page}" + url.split("/p-")[1]
            else:
                page_url = url.replace("/obiavi/naemi/", f"/obiavi/naemi/p-{page}/")

        resp = requests.get(page_url)
        if resp.status_code != 200:
            break

        # Встановлюємо правильне кодування для imot.bg
        resp.encoding = 'windows-1251'

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("div.ads2023 > div.item")
        if not cards:
            break

        for card in cards:
            title_elem = card.select_one("a.title")
            price_elem = card.select_one("div.price div")
            link_elem = card.select_one("a.title")
            img_elem = card.select_one("div.big a img.pic")
            info_elem = card.select_one("div.info")
            seller_elem = card.select_one("div.sInfo div.name a")

            apartment = {
                "title": title_elem.text.strip() if title_elem else "No title",
                "price": price_elem.text.strip() if price_elem else "No price",
                "link": "https:" + link_elem['href'] if link_elem else "No link",
                "img": "https:" + img_elem['src'] if img_elem else None,
                "info": info_elem.text.strip() if info_elem else "",
                "seller": seller_elem.text.strip() if seller_elem else "",
            }
            apartments.append(apartment)

        page += 1

    return apartments

# --- Зберігання користувачів і їхніх URL ---
users_data = {}  # {chat_id: {"url": url, "last_links": set()}}

# --- Фоновий парсер ---
async def background_parser():
    await asyncio.sleep(5)  # невелика затримка перед стартом
    while True:
        for user_id, data in users_data.items():
            url = data["url"]
            last_links = data.get("last_links", set())

            try:
                apartments = parse_all(url)
                # Фільтруємо тільки оголошення з ціною
                apartments = [a for a in apartments if a['price'] != "No price"]

                new_apartments = [a for a in apartments if a['link'] not in last_links]

                # Відправляємо живе повідомлення про стан парсингу
                await bot.send_message(
                    chat_id=user_id,
                    text=f"Пропарсив {len(apartments)} квартир, нових: {len(new_apartments)}"
                )

                # Відправляємо нові оголошення
                for a in new_apartments:
                    text = (
                        f"<b>{a['title']}</b>\n"
                        f"<b>Ціна:</b> {a['price']}\n"
                        f"<b>Продавець:</b> {a['seller'] or 'Невідомо'}\n"
                        f"<b>Деталі:</b> <i>{a['info'][:300]}...</i>\n"
                        f"<a href='{a['link']}'>Перейти до оголошення</a>"
                    )
                    await bot.send_message(chat_id=user_id, text=text)

                # Оновлюємо останні посилання
                last_links.update([a['link'] for a in apartments])
                users_data[user_id]["last_links"] = last_links

            except Exception as e:
                await bot.send_message(chat_id=user_id, text=f"Сталася помилка фонового парсингу: {e}")

        await asyncio.sleep(3600)  # перевірка кожні 2 хвилини

# --- Обробник /start ---
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer("Привіт! Надішли мені посилання на сторінку з квартирами, і я буду повідомляти про нові.")

# --- Обробник посилання ---
@dp.message(F.text.startswith("http"))
async def handle_link(message: Message):
    url = message.text.strip()
    user_id = message.from_user.id

    if user_id not in users_data:
        users_data[user_id] = {"url": url, "last_links": set()}
    else:
        users_data[user_id]["url"] = url  # оновлюємо URL

    await message.answer("Працюю, збираю всі квартири і буду повідомляти про нові...")

# --- Старт бота і фонового парсера ---
if __name__ == "__main__":
    async def main():
        # Старт фонового парсера
        asyncio.create_task(background_parser())
        # Старт бота
        await dp.start_polling(bot)

    asyncio.run(main())
