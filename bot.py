import os
import logging
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Server is Running!"
@app.route('/')
def home():
    return "Bot is alive and running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# 2. የቴሌግራም ቦት ማስተካከያ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    
    welcome_message = (
        f"ሰላም {user_name}!\n\n"
        "📖 መጽሐፍ፡ «እልፍ በል!» (የተስፋ እና የዕድገት ጉዞ)\n"
        "✍️ ደራሲ፡ ብርሃኑ ወልደጊዮርጊስ\n"
        "💰 ዋጋ፡ 490 ብር (ETB)\n\n"
        "ይህን መጽሐፍ ማዘዝ ከፈለጉ ከታች ያለውን አዝራር ይጫኑ!"
    )
    
    keyboard = [
        [InlineKeyboardButton("📚 መጽሐፉን አሁን ይዘዙ (490 ብር)", callback_data="buy_book")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

if __name__ == '__main__':
    # Flask ን በጀርባ (Background) ማስኬድ
    t = threading.Thread(target=run_flask)
    t.start()

    # የሰጡት ትክክለኛ የቦት ቶከን እዚህ ገብቷል
    TOKEN = "8631290638:AAFeaCddTXKXvLr07DCYg9kXxPoiJXfx8T8"
    
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    print("ቦቱ በመሥራት ላይ ይገኛል (24/7)...")
    application.run_polling()
