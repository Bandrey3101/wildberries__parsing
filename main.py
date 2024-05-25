import os
import json
import time
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.dispatcher.filters import Text
from google.oauth2.service_account import Credentials
import gspread
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logging
import config
import re

# Запись логов в файл
logging.basicConfig(filename='errors.log', level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s')


# Настройки для бота
API_TOKEN = config.token
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Настройки для Google Sheets
SERVICE_ACCOUNT_FILE = 'service_creds.json'
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

credentials = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
gc = gspread.authorize(credentials)

# id таблицы
SPREADSHEET_ID = 'your sheet id'
# ссылка на лист с базой данных
sheet_links = gc.open_by_key(SPREADSHEET_ID).worksheet("links")
# ссылка на лист с ценами
sheet_prices = gc.open_by_key(SPREADSHEET_ID).worksheet("prices")

# Настройки для Selenium
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
service = Service('path to chromedriver')


# Функция для получения информации о товаре
def get_product_details(url):
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.get(url)
    try:
        # Ожидаем, пока элемент с названием станет доступным
        title_tag = WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'h1.product-page__title'))
        )
        product_title = title_tag.text
        # Ожидаем, пока элемент с артикулом станет доступным
        article_tag = WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'span#productNmId'))
        )
        product_article = article_tag.text
        # Ожидаем, пока элемент с ценой станет доступным
        price_tag = WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'ins.price-block__final-price.wallet'))
        )
        price_text = price_tag.text.strip().split()[0]
        print(price_text)
        return {
            "title": product_title,
            "article": product_article,
            "price": price_text,
            "url": url
        }
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        logging.error("Ошибка: %s", str(e))
        return None
    finally:
        driver.quit()


# Функция для проверки и обновления цен
async def check_prices():
    links = sheet_links.col_values(1)  # Получаем все ссылки из первого столбца листа "links"
    url_pattern = re.compile(r'^https?://[^\s/$.?#].[^\s]*$')  # Регулярное выражение для проверки URL
    try:
        for link in links:
            if link and not url_pattern.match(link):  # Проверяем, заполненная ли ячейка и не содержит ли она ссылку
                continue  # Пропускаем заполненные ячейки без ссылки
            if link:  # Если ячейка заполнена и содержит ссылку
                product_details = get_product_details(link)  # Получаем детали товара по каждой ссылке
                if product_details:
                    cell = sheet_prices.find(product_details["article"])  # Ищем артикул товара в листе "prices"
                    if cell:
                        current_price = sheet_prices.cell(cell.row, 3).value  # Получаем текущую цену из таблицы. Цифра в скобках - это номер столба в таблице
                        if current_price != product_details["price"]:  # Проверяем, изменилась ли цена
                            old_price = current_price
                            new_price = product_details["price"]
                            sheet_prices.update_cell(cell.row, 3, new_price)  # Обновляем цену в таблице.
                            message = (f"Цена на <a href='{product_details['url']}'>{product_details['article']}</a> "
                                       f"была изменена с {old_price}р до {new_price}р.")
                            await bot.send_message(chat_id="your chat id", text=message, parse_mode='HTML')

                    else:
                        next_row = len(sheet_prices.col_values(1)) + 1  # Определяем следующую свободную строку
                        sheet_prices.update(
                            range_name=f'A{next_row}:D{next_row}',
                            values=[[
                                product_details["article"],
                                product_details["title"],
                                product_details["price"],
                                product_details["url"]
                            ]]
                        )  # Вставляем новую строку с информацией о товаре
        await bot.send_message(chat_id=415611078, text="Проверка цен завершена")  # Сообщаем о завершении проверки
    except Exception as e:
        print(f"Снова ошибка: {e}")
        logging.error("Ошибка: %s", str(e))


# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply("Привет! Я бот для отслеживания цен на товары.")


# Запуск проверки цен раз в сутки
async def scheduled(wait_for):
    while True:
        await check_prices()
        await asyncio.sleep(wait_for)


if __name__ == '__main__':
    import asyncio
    loop = asyncio.get_event_loop()
    loop.create_task(scheduled(86410))  # Проверка раз в сутки (в секундах)
    executor.start_polling(dp, skip_updates=True)
