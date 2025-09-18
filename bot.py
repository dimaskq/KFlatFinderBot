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
from aiogram.exceptions import TelegramRetryAfter
import requests
import chromedriver_autoinstaller

# --- Load API token ---
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- Selenium driver setup ---
def get_driver():
    chromedriver_autoinstaller.install()
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=options)
    return driver

# --- Parser for address.bg ---
def parse_address_bg(url):
    driver = get_driver()
    apartments = []

    driver.get(url)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "h3.offer-title"))
        )
    except:
        driver.quit()
        return apartments

    # Пагінація
    pagination = driver.find_elements(By.CSS_SELECTOR, "li.pagination-page-nav")
    total_pages = max(1, len(pagination))

    for page in range(1, total_pages + 1):
        page_url = url if page == 1 else f"{url}&page={page}"
        driver.get(page_url)

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.offer-card"))
            )
        except:
            continue

        SCROLL_PAUSE_TIME = 1
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_PAUSE_TIME)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        soup = BeautifulSoup(driver.page_source, "lxml")
        cards = soup.select("div.offer-card")

        for card in cards:
            title_elem = card.select_one("h3.offer-title")
            link_elem = card.select_one("a[href]")
            img_elem = card.select_one("div.img picture img")
            size_elem = card.select_one("div.right small.gray-d")
            type_elem = card.select_one("div.right small.gray-m")
            price_elem = card.select_one("div.left small.price span")

            if price_elem and price_elem.text.strip():
                price = price_elem.text.strip() + " €"
            else:
                price_small = card.select_one("div.left small.price")
                price = price_small.text.strip() + " €" if price_small else "No price"

            img = None
            if img_elem:
                if img_elem.get("src"):
                    img = img_elem["src"]
                elif img_elem.get("data-src"):
                    img = img_elem["data-src"]
                elif img_elem.get("srcset"):
                    img = img_elem.get("srcset").split()[0]

            link = link_elem["href"] if link_elem else None
            if not link or not link.startswith("http"):
                continue

            apartments.append({
                "title": title_elem.text.strip() if title_elem else "No title",
                "price": price,
                "link": link,
                "img": img,
                "size": size_elem.text.strip() if size_elem else "",
                "type": type_elem.text.strip() if type_elem else "",
                "source": "address.bg"
            })

    driver.quit()
    return apartments

# --- Parser for imot.bg ---
def parse_imot_bg(url):
    apartments = []
    page = 1
    while True:
        if page == 1:
            page_url = url
        else:
            if "/p-" in url:
                page_url = url.split("/p-")[0] + f"/p-{page}" + url.split("/p-")[1]
            else:
                if "prodazhbi" in url:
                    page_url = url.replace("/obiavi/prodazhbi/", f"/obiavi/prodazhbi/p-{page}/")
                else:
                    page_url = url.replace("/obiavi/naemi/", f"/obiavi/naemi/p-{page}/")

        resp = requests.get(page_url)
        if resp.status_code != 200:
            break

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

            if not price_elem or not price_elem.text.strip():
                continue

            apartments.append({
                "title": title_elem.text.strip() if title_elem else "No title",
                "price": price_elem.text.strip() if price_elem else "No price",
                "link": "https:" + link_elem['href'] if link_elem else "No link",
                "img": "https:" + img_elem['src'] if img_elem else None,
                "info": info_elem.text.strip() if info_elem else "",
                "seller": seller_elem.text.strip() if seller_elem else "",
                "source": "imot.bg"
            })

        page += 1

    return apartments

# --- Users data storage ---
users_data = {}  # {chat_id: {"urls": [], "last_links": set()}}
user_tasks = {}  # {chat_id: asyncio.Task}

# --- Individual user parser ---
async def user_parser(user_id: int):
    while user_id in users_data:
        data = users_data[user_id]
        all_apartments = []

        urls = data.get("urls", [])
        for url in urls:
            try:
                if "address.bg" in url:
                    apartments_address = await asyncio.to_thread(parse_address_bg, url)
                    all_apartments.extend(apartments_address)
                elif "imot.bg" in url:
                    apartments_imot = await asyncio.to_thread(parse_imot_bg, url)
                    all_apartments.extend(apartments_imot)
            except Exception as e:
                await bot.send_message(chat_id=user_id, text=f"[Error] {url}: {e}")

        last_links = data.get("last_links", set())
        new_apartments = [a for a in all_apartments if a["link"] not in last_links]

        total_found = len(all_apartments)
        new_count = len(new_apartments)
        await bot.send_message(chat_id=user_id, text=f"Знайдено: {total_found}, нових: {new_count}")

        for a in new_apartments:
            caption = f"<b>{a.get('title')}</b>\n<b>Price:</b> {a.get('price', 'No price')}\n"
            if a['source'] == "address.bg":
                caption += f"<b>Type:</b> {a.get('type', '')}\n<b>Size:</b> {a.get('size', '')}\n"
            else:
                caption += f"<b>Seller:</b> {a.get('seller', 'Unknown')}\n<b>Details:</b> <i>{a.get('info', '')[:300]}...</i>\n"
            caption += f"<a href='{a.get('link')}'>View listing</a>"

            try:
                if a.get("img"):
                    await bot.send_photo(chat_id=user_id, photo=a["img"], caption=caption)
                else:
                    await bot.send_message(chat_id=user_id, text=caption)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.timeout)
                if a.get("img"):
                    await bot.send_photo(chat_id=user_id, photo=a["img"], caption=caption)
                else:
                    await bot.send_message(chat_id=user_id, text=caption)
            except Exception as e:
                print(f"Failed to send message/photo: {e}")
                await bot.send_message(chat_id=user_id, text=caption)

            last_links.add(a["link"])
            data["last_links"] = last_links
            await asyncio.sleep(1)

        await asyncio.sleep(3600)

# --- Handlers ---
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer(
        "Привіт! 👋\n\n"
        "Щоб почати відслідковувати квартири, надішли будь-яку кількість посилань через пробіл:\n\n"
        "1️⃣ Посилання з address.bg (оренда чи продаж)\n"
        "2️⃣ Посилання з imot.bg (оренда чи продаж)\n\n"
        "Приклади:\n"
        "`https://www.address.bg/rent/varna https://www.address.bg/sale/varna`\n"
        "`https://www.imot.bg/obiavi/naemi/grad-varna https://www.address.bg/rent/varna`\n\n"
        "Можеш надсилати будь-яку комбінацію. Бот автоматично збере всі квартири та повідомлятиме про нові 🚀"
    )

@dp.message(F.text.startswith("http"))
async def handle_link(message: Message):
    urls = message.text.strip().split()
    user_id = message.from_user.id

    if not any("address.bg" in u or "imot.bg" in u for u in urls):
        await message.answer("Будь ласка, надішли посилання тільки з address.bg або imot.bg")
        return

    users_data[user_id] = {"urls": urls, "last_links": set()}

    # Cancel previous task if exists
    if user_id in user_tasks:
        user_tasks[user_id].cancel()

    user_tasks[user_id] = asyncio.create_task(user_parser(user_id))
    await message.answer(f"Прийнято {len(urls)} посилань ✅. Я буду відслідковувати нові квартири автоматично.")

# --- Start bot ---
if __name__ == "__main__":
    async def main():
        await dp.start_polling(bot)

    asyncio.run(main())
