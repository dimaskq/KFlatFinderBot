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
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException

# --- Load API token ---
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- Centralized driver setup ---
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
                    img = img_elem["srcset"].split()[0]

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
users_data = {}  # {chat_id: {"address_url": "", "imot_url": "", "last_links": set()}}

# --- Background parser ---
async def background_parser():
    print("[DEBUG] Background parser started")
    while True:
        if not users_data:
            await asyncio.sleep(5)
            continue

        for user_id, data in users_data.items():
            all_apartments = []

            address_url = data.get("address_url")
            if address_url:
                try:
                    apartments_address = await asyncio.to_thread(parse_address_bg, address_url)
                    all_apartments.extend(apartments_address)
                except Exception as e:
                    await bot.send_message(chat_id=user_id, text=f"[address.bg] Error: {e}")

            imot_url = data.get("imot_url")
            if imot_url:
                try:
                    apartments_imot = await asyncio.to_thread(parse_imot_bg, imot_url)
                    all_apartments.extend(apartments_imot)
                except Exception as e:
                    await bot.send_message(chat_id=user_id, text=f"[imot.bg] Error: {e}")

            last_links = data.get("last_links", set())
            new_apartments = [a for a in all_apartments if a["link"] not in last_links]

            total_found = len(all_apartments)
            new_count = len(new_apartments)
            await bot.send_message(chat_id=user_id, text=f"Total apartments found: {total_found}, new: {new_count}")

            for a in new_apartments:
                caption = f"<b>{a.get('title')}</b>\n"
                caption += f"<b>Price:</b> {a.get('price', 'No price')}\n"

                if a['source'] == "address.bg":
                    caption += f"<b>Type:</b> {a.get('type', '')}\n"
                    caption += f"<b>Size:</b> {a.get('size', '')}\n"
                else:
                    caption += f"<b>Seller:</b> {a.get('seller', 'Unknown')}\n"
                    caption += f"<b>Details:</b> <i>{a.get('info', '')[:300]}...</i>\n"

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
        "Hello! To start tracking new apartments, please send me two links in one message:\n"
        "1️⃣ First link: a search page from address.bg\n"
        "2️⃣ Second link: a search page from imot.bg\n\n"
        "Send both links separated by a space. For example:\n"
        "`https://www.address.bg/flats?search=sofia https://www.imot.bg/naemi/flats?city=sofia`\n"
        "I will collect all apartments and notify you about new ones automatically 🚀"
    )

@dp.message(F.text.startswith("http"))
async def handle_link(message: Message):
    urls = message.text.strip().split()
    if len(urls) != 2:
        await message.answer("Please send exactly two links separated by a space: first from address.bg, second from imot.bg.")
        return

    address_url, imot_url = urls
    user_id = message.from_user.id

    if user_id not in users_data:
        users_data[user_id] = {"address_url": address_url, "imot_url": imot_url, "last_links": set()}
    else:
        users_data[user_id]["address_url"] = address_url
        users_data[user_id]["imot_url"] = imot_url

    await message.answer("Links accepted ✅. I will now collect all apartments and notify you about new ones automatically.")

# --- Start bot ---
if __name__ == "__main__":
    async def main():
        asyncio.create_task(background_parser())
        await dp.start_polling(bot)

    asyncio.run(main())