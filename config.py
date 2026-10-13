import os

# ───────────── BOT CONFIG ─────────────
# Sirf yahi file edit karni hai (ya environment variables use karo).

# @BotFather se NAYA token yahan daalo (purana /revoke kar do).
BOT_TOKEN = os.getenv("BOT_TOKEN", "8495990131:AAGsljIQDOQhKkGH4efQknhtURkaa6MCuVg")

ADMIN_IDS = [8603893462]          # Admin numeric Telegram ID(s)
LOG_CHANNEL = -1004175542309      # Naye user ka alert channel (-100...), nahi chahiye to 0
DB_PATH = "bot.db"                # Isko delete mat karna, saara data isi me hai

# UI mode:
#   "auto"    -> Rich Message + buttons card ke ANDAR; agar Telegram reject kare to khud neeche wale mode me gir jaata hai
#   "classic" -> Rich Message + colored buttons niche (inline keyboard)
#   "plain"   -> normal HTML message + colored buttons
RICH_MODE = "auto"

# Start card ka font (optional). Khali chhodo to system font auto milega.
# FONT_PATH = "fonts/Roboto-Regular.ttf"
# FONT_BOLD_PATH = "fonts/Roboto-Bold.ttf"
