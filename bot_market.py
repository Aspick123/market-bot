import json, os, time, logging, datetime
from collections import defaultdict
from threading import Thread
from flask import Flask

app = Flask("")
@app.route("/")
def home(): return "OK"
def run(): app.run(host="0.0.0.0", port=10000, threaded=True)
Thread(target=run, daemon=True).start()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from database_market import mdb_read, mdb_write, mdb_config, get_user, save_user, format_date, niveau_label, stars
from annonces import handle_annonces_callbacks, start_creation_annonce, show_mes_annonces, handle_annonces_input, handle_annonces_photos
from recherche import handle_recherche_callbacks, handle_recherche_input
from transactions import handle_transactions_callbacks
from litiges import handle_litiges_callbacks, handle_litiges_input, handle_litiges_photos
from alertes import handle_alertes_callbacks
from reputation import handle_reputation_callbacks, handle_reputation_input
from parrainage import handle_parrainage_callbacks
from cgu import handle_cgu_callbacks, handle_cgu_input
from gamification import handle_gamification_callbacks, show_leaderboard
from admin_market import handle_admin_market_callbacks, handle_admin_input

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.environ.get("TELEGRAM_TOKEN", "7900760431:AAFiNIsyPscuR-lX_2W4H8M_q6FwFOfw9I0")
SUPER_ADMIN_ID = 7132924157

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    user = get_user(user_id)
    if not user.get("username"):
        user["username"] = username
        save_user(user_id, user)
    
    welcome_text = f"🎮 *Bienvenue sur le Marketplace, {username} !* 🎮\n\nIci, tu peux acheter, vendre ou échanger tes comptes de jeux vidéo."
    kb = [
        [InlineKeyboardButton("🔍 Rechercher un article", callback_data="menu_recherche")],
        [InlineKeyboardButton("➕ Publier une annonce", callback_data="menu_vendre"), InlineKeyboardButton("📝 Mes Annonces", callback_data="menu_mes_annonces")],
        [InlineKeyboardButton("👤 Mon Profil", callback_data=f"voir_profil_{user_id}"), InlineKeyboardButton("🎁 Parrainage", callback_data="menu_parrainage")],
        [InlineKeyboardButton("🏆 Défis & Niveaux", callback_data="menu_defis"), InlineKeyboardButton("📊 Classement", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("🚨 Ouvrir un litige", callback_data="menu_litige"), InlineKeyboardButton("📋 CGU", callback_data="menu_cgu")]
    ]
    reply_markup = InlineKeyboardMarkup(kb)
    if update.callback_query: await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else: await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); msg = query.message; uid = query.from_user.id; data = query.data
    if await handle_annonces_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_recherche_callbacks(query, ctx): return
    if await handle_transactions_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_litiges_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_alertes_callbacks(query, ctx): return
    if await handle_reputation_callbacks(query, ctx, ctx.bot): return
    if await handle_parrainage_callbacks(query, ctx, ctx.bot): return
    if await handle_cgu_callbacks(query, ctx, ctx.bot): return
    if await handle_gamification_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_admin_market_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return

    if data == "menu_vendre":
        from cgu import user_a_accepte_cgu_vendeur
        if not await user_a_accepte_cgu_vendeur(msg, uid, ctx): return
        await start_creation_annonce(msg, uid)
    elif data == "retour_start": await start(update, ctx)

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if await handle_annonces_input(update, ctx, ctx.bot): return
    if await handle_recherche_input(update, ctx): return
    if await handle_litiges_input(update, ctx, ctx.bot): return
    if await handle_reputation_input(update, ctx, ctx.bot): return
    if await handle_cgu_input(update, ctx): return
    if await handle_admin_input(update, ctx, ctx.bot, SUPER_ADMIN_ID): return

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if await handle_annonces_photos(update, ctx): return
    if await handle_litiges_photos(update, ctx): return

def main():
    app_tg = ApplicationBuilder().token(TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CallbackQueryHandler(button_handler))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app_tg.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("🚀 Bot démarré avec succès !")
    app_tg.run_polling()

if __name__ == '__main__': main()
