import requests
from bs4 import BeautifulSoup

URL = "https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=3&in_radius=10&price_cur=1&wo_dupl=1&sort=inspected_sort&firstIteraction=false&limit=20&market=3&type=list&client=searchV2&ch=212_f_2,212_t_4,246_244#map_state=22.29856_48.62319_0.0_12.2"

headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(URL, headers=headers)
soup = BeautifulSoup(resp.text, "html.parser")

cards = soup.select(".ticket-item")
print(f"Знайдено {len(cards)} оголошень")

for card in cards[:5]:  # показуємо перші 5
    title = card.select_one(".ticket-title").get_text(strip=True) if card.select_one(".ticket-title") else "Без назви"
    price = card.select_one(".price").get_text(strip=True) if card.select_one(".price") else "Ціну уточнюй"
    link = "https://dom.ria.com" + card.select_one("a")["href"]
    print(title, price, link)
