from dotenv import load_dotenv
import os
import time
import asyncio
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.client.bot import DefaultBotProperties

# --- Завантаження токена ---
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- Функція парсингу ---
def parse_all(url):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)

    apartments = []

    driver.get(url)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h3.offer-title"))
        )
    except:
        print("[DEBUG] На першій сторінці не знайдено квартир")
        driver.quit()
        return apartments

    # --- Знаходимо кількість сторінок через пагінацію ---
    pagination = driver.find_elements(By.CSS_SELECTOR, "li.pagination-page-nav")
    total_pages = max(1, len(pagination))
    print(f"[DEBUG] Всього сторінок: {total_pages}")

    for page in range(1, total_pages + 1):
        page_url = url if page == 1 else f"{url}&page={page}"
        driver.get(page_url)

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.offer-card"))
            )
        except:
            print(f"[DEBUG] На сторінці {page} не знайдено карток")
            continue

        # Скролимо для lazy-load
        SCROLL_PAUSE_TIME = 1
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_PAUSE_TIME)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        html = driver.page_source
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.offer-card")

        for card in cards:
            title_elem = card.select_one("h3.offer-title")
            link_elem = card.select_one("a[href]")
            img_elem = card.select_one("div.img picture img")
            size_elem = card.select_one("div.right small.gray-d")
            type_elem = card.select_one("div.right small.gray-m")

            # --- Гнучкий парсинг ціни ---
            price_elem = card.select_one("div.left small.price span")
            if price_elem and price_elem.text.strip():
                price = price_elem.text.strip() + " €"
            else:
                price_small = card.select_one("div.left small.price")
                price = price_small.text.strip() + " €" if price_small else "No price"

            if img_elem:
                if img_elem.get("src"):
                    img = img_elem["src"]
                elif img_elem.get("data-src"):
                    img = img_elem["data-src"]
                elif img_elem.get("srcset"):
                    img = img_elem["srcset"].split()[0]
                else:
                    img = None
            else:
                img = None

            link = link_elem["href"] if link_elem else None
            if not link or not link.startswith("http"):
                continue  # пропускаємо некоректні лінки

            apartments.append({
                "title": title_elem.text.strip() if title_elem else "No title",
                "price": price,
                "link": link,
                "img": img,
                "size": size_elem.text.strip() if size_elem else "",
                "type": type_elem.text.strip() if type_elem else "",
            })

    driver.quit()
    return apartments

# --- Зберігання користувачів ---
users_data = {}  # {chat_id: {"url": url, "last_links": set()}}

# --- Фоновий парсер ---
async def background_parser():
    print("[DEBUG] Фоновий парсер стартував")
    while True:
        if not users_data:
            await asyncio.sleep(5)
            continue

        for user_id, data in users_data.items():
            url = data["url"]
            if "last_links" not in data:
                data["last_links"] = set()
            last_links = data["last_links"]

            try:
                apartments = await asyncio.to_thread(parse_all, url)

                # Відсіюємо лише валідні лінки
                valid_apartments = [a for a in apartments if a['link']]

                # Визначаємо нові квартири
                new_apartments = [a for a in valid_apartments if a['link'] not in last_links]

                total_found = len(valid_apartments)
                new_count = len(new_apartments)

                await bot.send_message(
                    chat_id=user_id,
                    text=f"Пропарсив всього квартир: {total_found}, нових: {new_count}"
                )

                for a in new_apartments:
                    img_url = a['img']
                    # Додаємо повний шлях до фото, якщо він відносний
                    if img_url and img_url.startswith("/"):
                        img_url = "https://address.bg" + img_url

                    caption = (
                        f"<b>{a['title']}</b>\n"
                        f"<b>Ціна:</b> {a['price']}\n"
                        f"<b>Тип:</b> {a['type']}\n"
                        f"<b>Розмір:</b> {a['size']}\n"
                        f"<a href='{a['link']}'>Перейти до оголошення</a>"
                    )

                    try:
                        if img_url:
                            await bot.send_photo(chat_id=user_id, photo=img_url, caption=caption)
                        else:
                            await bot.send_message(chat_id=user_id, text=caption)
                    except:
                        await bot.send_message(chat_id=user_id, text=caption)

                    last_links.add(a['link'])

                print(f"[DEBUG] Юзер {user_id} - всього збережених лінків: {len(last_links)}")

            except Exception as e:
                print(f"[ERROR] {e}")

        await asyncio.sleep(300)  # кожні 5 хвилин

# --- Обробники ---
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer("Привіт! Надішли мені посилання з address.bg, і я буду повідомляти про нові квартири.")

@dp.message(F.text.startswith("http"))
async def handle_link(message: Message):
    url = message.text.strip()
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"url": url, "last_links": set()}
    else:
        users_data[user_id]["url"] = url
    print(f"[DEBUG] Додано юзера {user_id} з URL: {url}")
    await message.answer("Прийняв, зараз збираю всі квартири і надалі слідкуватиму за новими 🚀")

# --- Старт бота ---
if __name__ == "__main__":
    async def main():
        asyncio.create_task(background_parser())
        await dp.start_polling(bot)

    asyncio.run(main())
