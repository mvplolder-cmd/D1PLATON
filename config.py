import os

# ─── Токены ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8994569220:AAHlH3vTSMiD3H6sT6htUnxUnqEjhIQwtgs")
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "594195:AA8t5lFCdyEHCPp3qr5riSRjYjcKbfe9sv4")

# ─── Твой Telegram ID (для уведомлений о заказах) ─────────────────────────────
ADMIN_ID = int(os.getenv("ADMIN_ID", "7098379286"))

# ─── Пакеты звёзд ─────────────────────────────────────────────────────────────
STARS_PACKAGES = [
    {"id": "50",   "stars": 50,   "ton": 0.5,  "usd": "1.0"},
    {"id": "100",  "stars": 100,  "ton": 0.9,  "usd": "1.8"},
    {"id": "250",  "stars": 250,  "ton": 2.1,  "usd": "4.2"},
    {"id": "500",  "stars": 500,  "ton": 4.0,  "usd": "8.0"},
    {"id": "1000", "stars": 1000, "ton": 7.5,  "usd": "15"},
    {"id": "2500", "stars": 2500, "ton": 17.5, "usd": "35"},
]
