from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)
from contextlib import asynccontextmanager
import asyncio
import aiohttp
import requests
import cv2
import pytesseract
from pyzbar.pyzbar import decode
from PIL import Image
import numpy as np
import io
import re
import logging

# === KONFIGURASI ===
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
BOT_TOKEN = "7792152468:AAHVnSc1fMMvK-1gIZ58vZZLMZTzQscEfb0"
CHAT_ID = "7559596766"
ESP32_IP = "http://192.168.43.145"
FASTAPI_URL = "http://192.168.43.8:8000"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
telegram_app = None  # akan diinisialisasi di lifespan

# === FASTAPI APP dengan lifespan ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    telegram_app = Application.builder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start_handler))
    telegram_app.add_handler(CommandHandler("open", open_handler))
    telegram_app.add_handler(CommandHandler("close", close_handler))

    # Inisialisasi & mulai polling
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    print("✅ Telegram bot started")
    try:
        yield
    finally:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        print("✅ Telegram bot stopped")

app = FastAPI(lifespan=lifespan)

# === UTILITAS ===
def preprocess_image(image: Image.Image) -> Image.Image:
    img_np = np.array(image)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(thresh)

def extract_resi_from_text(text: str):
    resi_list = []
    for line in text.splitlines():
        if "resi" in line.lower():
            tokens = line.split()
            for i, token in enumerate(tokens):
                if "resi" in token.lower() and i + 1 < len(tokens):
                    resi_list.append(tokens[i + 1].strip(":").strip())
    matches = re.findall(r'JP\d{9,}', text)
    resi_list.extend(matches)
    return list(set(resi_list))

def extract_resi_from_barcode(img_cv):
    decoded = decode(img_cv)
    return [obj.data.decode("utf-8") for obj in decoded]

def send_telegram_text(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    response = requests.post(url, data=data)
    print("Telegram text sent:", response.status_code, response.text)

async def call_fastapi(endpoint: str):
    url = f"{FASTAPI_URL}/{endpoint}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url) as resp:
            return await resp.json()

# === FASTAPI ENDPOINTS ===
@app.post("/upload")
async def upload_image(photo: UploadFile = File(...)):
    try:
        image_bytes = await photo.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Kirim gambar ke Telegram
        image_bytes_io = io.BytesIO()
        image.save(image_bytes_io, format='JPEG')
        image_bytes_io.seek(0)
        await bot.send_photo(chat_id=CHAT_ID, photo=image_bytes_io, caption="📷 Gambar diterima dari ESP32-CAM")

        # OCR
        processed_image = preprocess_image(image)
        ocr_text = pytesseract.image_to_string(processed_image)
        resi_ocr = extract_resi_from_text(ocr_text)

        # Barcode
        img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        resi_barcode = extract_resi_from_barcode(img_cv)

        all_resi = list(set(resi_ocr + resi_barcode))

        message = "📷 Gambar diterima.\n"
        if all_resi:
            message += "✅ Ditemukan nomor resi:\n" + "\n".join(f"📦 {resi}" for resi in all_resi)
        else:
            message += "⚠️ Tidak ditemukan nomor resi dari teks/barcode."

        send_telegram_text(message)

        return JSONResponse(status_code=200, content={"message": message})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/open-servo")
async def open_servo():
    try:
        response = requests.get(f"{ESP32_IP}/open", timeout=10)
        return {"status": response.text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
@app.post("/close-servo")
async def close_servo():
    try:
        response = requests.get(f"{ESP32_IP}/close", timeout=10)
        return {"status": response.text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# === TELEGRAM HANDLERS ===
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(">>> /start triggered!")
    await update.message.reply_text(
        "Selamat datang!\n\nPerintah:\n"
        "/start - Memulai bot\n"
        "/open - Membuka box\n"
        "/close - Menutup box"
    )

async def open_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(">>> /open triggered!")
    await update.message.reply_text("Membuka box...")
    result = await call_fastapi("open-servo")
    await update.message.reply_text(f"Status: {result.get('status', 'Error')}")

async def close_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(">>> /close triggered!")
    await update.message.reply_text("Menutup box...")
    result = await call_fastapi("close-servo")
    await update.message.reply_text(f"Status: {result.get('status', 'Error')}")

# === AKHIR ===
# Jalankan dengan: uvicorn final:app --host 0.0.0.0 --port 8000 --reload
