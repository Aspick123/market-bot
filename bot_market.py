import os
import time
import logging
from threading import Thread
from flask import Flask

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from database_market import (
    get_user,
    save_user,
    get_role_label,
    is_flooded,
    is_mode_urgence
)
from menus import get_main_menu_keyboard, get_back_to_start_keyboard

app = Flask("")

@app.route("/")
def home():
    return "Le Marketplace Bot est opérationnel !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAEf5EcX6TzgGsaT8KZWRiAEK42h4FJjc0k")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "511704360"))

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    
    if is_mode_urgence() and uid != SUPER_ADMIN_ID:
        await update.effective_message.reply_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return
        
    if is_flooded(uid):
        await update.effective_message.reply_text("⏳ Trop de requêtes. Veuillez patienter.")
        return

    user_data = get_user(uid)
    if not user_data.get("username") or user_data["username"] != user.username:
        user_data["username"] = user.username or user.first_name
        save_user(uid, user_data)

    role_label = get_role_label(uid, SUPER_ADMIN_ID)
    
    welcome_text = (
        f"🎮 **Bienvenue sur le Marketplace, {user.first_name} !**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🎖️ **Rang :** {role_label}\n\n"
        f"🤝 *Achetez, vendez et échangez vos comptes de jeux et monnaies virtuelles en toute sécurité.*\n\n"
        f"👇 **Sélectionnez une option ci-dessous :**"
    )
    
    reply_markup = get_main_menu_keyboard(uid, SUPER_ADMIN_ID)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    data = query.data
    
    await query.answer()
    
    if is_mode_urgence() and uid != SUPER_ADMIN_ID:
        await query.message.edit_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return
        
    if is_flooded(uid):
        return

    logger.info(f"Bouton cliqué : {data} par {uid}")

    try:
        if data == "menu:retour_start":
            await start_command(update, ctx)
            
        elif data == "menu:profil":
            user_data = get_user(uid)
            profil_text = (
                f"👤 **Mon Profil Utilisateur**\n\n"
                f"🆔 **ID Telegram :** `{uid}`\n"
                f"🏷️ **Nom :** @{user_data.get('username')}\n"
                f"🎖️ **Statut :** {get_role_label(uid, SUPER_ADMIN_ID)}\n"
                f"📈 **Niveau :** {user_data.get('niveau', 1)} ({user_data.get('xp', 0)} XP)\n"
                f"🤝 **Filleuls parrainés :** {user_data.get('parrains', 0)}\n"
                f"📜 **Statut CGU :** {'✅ Acceptées' if user_data.get('accepte_cgu') else '❌ Non acceptées'}"
            )
            await query.message.edit_text(profil_text, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
            
        elif data == "menu:cgu":
            cgu_text = (
                "📜 **Conditions Générales d'Utilisation (CGU)**\n\n"
                "1. Tout acte de fraude entraînera un bannissement irrévocable.\n"
                "2. Les transactions doivent respecter le système d'arbitrage sécurisé du bot.\n"
                "3. La plateforme décline toute responsabilité hors du système d'arbitrage."
            )
            await query.message.edit_text(cgu_text, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
            
        elif data in ["menu:recherche", "menu:vendre", "menu:mes_annonces", "menu:historique", 
                      "menu:parrainage", "menu:defis", "menu:leaderboard", "menu:litige", 
                      "menu:alertes", "menu:blacklist", "menu:admin_panel"]:
            feature_name = data.replace("menu:", "").replace("_", " ").title()
            await query.message.edit_text(
                f"🚧 **Module [{feature_name}]**\n\nCe module est propre et prêt à recevoir sa logique métier.",
                reply_markup=get_back_to_start_keyboard(),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Erreur callback {data}: {str(e)}")
        await query.message.reply_text(f"❌ Erreur : {str(e)}")

def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🚀 Bot démarré !")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

