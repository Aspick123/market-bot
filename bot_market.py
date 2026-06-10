import os
from threading import Thread
from flask import Flask

# ══════════════════════════════════════════════════════════════
# ✅ CONFIGURATION DU SERVEUR (Correcte pour Render)
# ══════════════════════════════════════════════════════════════
# --- Remplace ton bloc actuel par celui-ci ---
app = Flask("")
@app.route("/")
def home(): return "Le bot est en ligne !"

def run(): 
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

Thread(target=run, daemon=True).start()
# ---------------------------------------------

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from database_market import (
    mdb_read, mdb_write, mdb_config, get_user, save_user,
    get_role, has_perm, ROLES_EQUIPE, add_log, format_date
)
from annonces import (
    handle_annonces_callbacks, handle_annonces_input,
    handle_annonces_photos, start_creation_annonce, show_mes_annonces
)
from recherche import handle_recherche_callbacks, handle_recherche_input
from transactions import handle_transactions_callbacks
from litiges import handle_litiges_callbacks, handle_litiges_input, handle_litiges_photos
from alertes import handle_alertes_callbacks
from reputation import handle_reputation_callbacks, handle_reputation_input
from parrainage import handle_parrainage_callbacks
from cgu import handle_cgu_callbacks, handle_cgu_input
from gamification import handle_gamification_callbacks
from admin_market import handle_admin_market_callbacks, handle_admin_market_input, show_admin_panel

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAEf5EcX6TzgGsaT8KZWRiAEK42h4FJjc0k")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

# ══════════════════════════════════════════════════════════════
#  ANTIFLOOD
# ══════════════════════════════════════════════════════════════

_flood = defaultdict(list)

def is_flooded(uid: int) -> bool:
    now = time.time()
    _flood[uid] = [t for t in _flood[uid] if now - t < 60]
    _flood[uid].append(now)
    return len(_flood[uid]) > 8

async def check_access(update: Update) -> bool:
    uid = update.effective_user.id
    user = get_user(uid)
    bl = mdb_read("blacklist.json")
    if any(b["user_id"] == uid for b in bl):
        await update.effective_message.reply_text("🚫 Ton compte est blacklisté.")
        return False
    if user.get("suspendu"):
        fin = user.get("suspension_fin", "?")
        try:
            fin_dt = datetime.datetime.strptime(fin, "%d/%m/%Y")
            if datetime.datetime.now() > fin_dt:
                user["suspendu"] = False
                save_user(uid, user)
            else:
                await update.effective_message.reply_text(
                    f"🔴 Compte suspendu jusqu'au *{fin}*.", parse_mode="Markdown"
                )
                return False
        except: pass
    if mdb_config().get("mode_urgence") and uid != SUPER_ADMIN_ID:
        await update.effective_message.reply_text(
            "🚨 Le marketplace est temporairement suspendu."
        )
        return False
    if is_flooded(uid):
        await update.effective_message.reply_text("⏳ Trop de requêtes. Attends 1 minute.")
        return False
    return True

# ══════════════════════════════════════════════════════════════
#  MENU PRINCIPAL
# ══════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    user = update.effective_user
    args = ctx.args if hasattr(ctx, 'args') and ctx.args else []

    # Parrainage via lien
    if args and args[0].startswith("parrain_"):
        from parrainage import handle_parrainage_start
        await handle_parrainage_start(update, ctx, ctx.bot, SUPER_ADMIN_ID)

    # Affichage annonce directe
    if args and args[0].startswith("ann_"):
        from annonces import afficher_annonce
        ann_id = args[0].replace("ann_", "")
        await afficher_annonce(update.message, ann_id, user.id)
        return

    user_data = get_user(user.id)
    if not user_data.get("username"):
        user_data["username"] = user.username or user.first_name
        save_user(user.id, user_data)

    role = get_role(user.id, SUPER_ADMIN_ID)
    role_label = ROLES_EQUIPE.get(role, "👤 Membre")

    kb = [
        [
            InlineKeyboardButton("🔍 Rechercher un article", callback_data="menu_recherche"),
            InlineKeyboardButton("➕ Publier une annonce", callback_data="menu_vendre")
        ],
        [
            InlineKeyboardButton("📝 Mes Annonces", callback_data="menu_mes_annonces"),
            InlineKeyboardButton("💰 Mes Transactions", callback_data="menu_historique")
        ],
        [
            InlineKeyboardButton("👤 Mon Profil", callback_data=f"voir_profil_{user.id}"),
            InlineKeyboardButton("🎁 Parrainage", callback_data="menu_parrainage")
        ],
        [
            InlineKeyboardButton("🏆 Défis & Niveaux", callback_data="menu_defis"),
            InlineKeyboardButton("📊 Classement", callback_data="menu_leaderboard")
        ],
        [
            InlineKeyboardButton("🚨 Ouvrir un litige", callback_data="menu_litige"),
            InlineKeyboardButton("🔔 Mes alertes", callback_data="menu_alertes")
        ],
        [
            InlineKeyboardButton("🚫 Blacklist publique", callback_data="menu_blacklist_publique"),
            InlineKeyboardButton("📋 CGU", callback_data="menu_cgu")
        ],
    ]

    if has_perm(user.id, "valider_annonces", SUPER_ADMIN_ID):
        kb.append([InlineKeyboardButton("🔐 Panel Admin", callback_data="adm_market_panel")])

    welcome_text = (
        f"🎮 *Bienvenue sur le Marketplace, {user.first_name} !*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Rôle : {role_label}\n\n"
        f"Achète, vends ou échange tes comptes\n"
        f"et monnaies de jeux en toute sécurité.\n\n"
        f"👇 Choisis une option :"
    )

    reply_markup = InlineKeyboardMarkup(kb)
    if update.callback_query:
        await update.callback_query.message.edit_text(
            welcome_text, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            welcome_text, reply_markup=reply_markup, parse_mode="Markdown"
        )

# ══════════════════════════════════════════════════════════════
#  COMMANDES
# ══════════════════════════════════════════════════════════════

async def cmd_vendre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from cgu import user_a_accepte_cgu_vendeur
    if not await user_a_accepte_cgu_vendeur(update.message, update.effective_user.id, ctx):
        return
    await start_creation_annonce(update.message, update.effective_user.id)

async def cmd_annonces(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from recherche import afficher_toutes
    await afficher_toutes(update.message, 0)

async def cmd_profil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    await show_profil_public(update.message, update.effective_user.id, update.effective_user.id)

async def cmd_mes_annonces(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    await show_mes_annonces(update.message, update.effective_user.id)

async def cmd_historique(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from transactions import show_historique
    await show_historique(update.message, update.effective_user.id)

async def cmd_litige(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from litiges import start_litige
    await start_litige(update.message, update.effective_user.id, ctx)

async def cmd_alertes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from alertes import show_menu_alertes
    await show_menu_alertes(update.message, update.effective_user.id)

async def cmd_classement(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    await show_leaderboard(update.message, "vendeurs")

async def cmd_parrainage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from parrainage import show_menu_parrainage
    await show_menu_parrainage(update.message, update.effective_user.id, ctx.bot)

async def cmd_defis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from gamification import show_mes_defis
    await show_mes_defis(update.message, update.effective_user.id)

async def cmd_cgu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from cgu import show_cgu
    await show_cgu(update.message)

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    if not has_perm(update.effective_user.id, "valider_annonces", SUPER_ADMIN_ID):
        await update.message.reply_text("🚫 Accès refusé.")
        return
    await show_admin_panel(update.message, update.effective_user.id, SUPER_ADMIN_ID)

async def cmd_aide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    await update.message.reply_text(
        "📖 *Commandes disponibles*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "*/start* — Menu principal\n"
        "*/vendre* — Publier une annonce\n"
        "*/annonces* — Parcourir les annonces\n"
        "*/profil* — Mon profil public\n"
        "*/mes_annonces* — Mes annonces\n"
        "*/historique* — Mes transactions\n"
        "*/litige* — Ouvrir un litige\n"
        "*/alertes* — Mes alertes\n"
        "*/classement* — Leaderboard\n"
        "*/parrainage* — Mon parrainage\n"
        "*/defis* — Mes défis\n"
        "*/cgu* — Conditions d'utilisation\n"
        "*/admin* — Panel administrateur\n"
        "*/aide* — Cette liste",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    print(f"DEBUG_CLIC: {query.data}")
    print(f"DEBUG: Clic reçu avec data: {query.data}")
    await query.answer()
    msg = query.message
    uid = query.from_user.id
    data = query.data

    if await handle_cgu_callbacks(query, ctx, ctx.bot): return
    if await handle_annonces_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_recherche_callbacks(query, ctx): return
    if await handle_transactions_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_litiges_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_alertes_callbacks(query, ctx): return
    if await handle_reputation_callbacks(query, ctx, ctx.bot): return
    if await handle_parrainage_callbacks(query, ctx, ctx.bot): return
    if await handle_gamification_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_admin_market_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return

    # Callbacks restants
    if data == "menu_vendre":
        from cgu import user_a_accepte_cgu_vendeur
        if not await user_a_accepte_cgu_vendeur(msg, uid, ctx): return
        await start_creation_annonce(msg, uid)

    elif data == "menu_mes_annonces":
        await show_mes_annonces(msg, uid)

    elif data == "menu_historique":
        from transactions import show_historique
        await show_historique(msg, uid)

    elif data == "menu_leaderboard":
        await show_leaderboard(msg, "vendeurs")

    elif data == "menu_blacklist_publique":
        from admin_market import show_blacklist_publique
        await show_blacklist_publique(msg)

    elif data == "menu_alertes":
        from alertes import show_menu_alertes
        await show_menu_alertes(msg, uid)

    elif data == "menu_parrainage":
        from parrainage import show_menu_parrainage
        await show_menu_parrainage(msg, uid, ctx.bot)

    elif data == "menu_defis":
        from gamification import show_mes_defis
        await show_mes_defis(msg, uid)

    elif data == "menu_litige":
        from litiges import start_litige
        await start_litige(msg, uid, ctx)

    elif data == "menu_cgu":
        from cgu import show_cgu
        await show_cgu(msg)

    elif data == "menu_recherche":
        from recherche import show_menu_recherche
        await show_menu_recherche(msg)

    elif data == "retour_start":
        await start(update, ctx)

    elif data == "adm_market_panel":
        await show_admin_panel(msg, uid, SUPER_ADMIN_ID)

# ══════════════════════════════════════════════════════════════
#  HANDLERS MESSAGES ET PHOTOS
# ══════════════════════════════════════════════════════════════

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    if await handle_cgu_input(update, ctx): return
    if await handle_annonces_input(update, ctx, ctx.bot): return
    if await handle_litiges_input(update, ctx, ctx.bot): return
    if await handle_reputation_input(update, ctx, ctx.bot): return
    if await handle_recherche_input(update, ctx): return
    if await handle_admin_input(update, ctx, ctx.bot, SUPER_ADMIN_ID): return

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    if await handle_annonces_photos(update, ctx): return
    if await handle_litiges_photos(update, ctx): return

# ══════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════

def main():
    app_tg = ApplicationBuilder().token(TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("aide", cmd_aide))
    app_tg.add_handler(CommandHandler("vendre", cmd_vendre))
    app_tg.add_handler(CommandHandler("annonces", cmd_annonces))
    app_tg.add_handler(CommandHandler("profil", cmd_profil))
    app_tg.add_handler(CommandHandler("mes_annonces", cmd_mes_annonces))
    app_tg.add_handler(CommandHandler("historique", cmd_historique))
    app_tg.add_handler(CommandHandler("litige", cmd_litige))
    app_tg.add_handler(CommandHandler("alertes", cmd_alertes))
    app_tg.add_handler(CommandHandler("classement", cmd_classement))
    app_tg.add_handler(CommandHandler("parrainage", cmd_parrainage))
    app_tg.add_handler(CommandHandler("defis", cmd_defis))
    app_tg.add_handler(CommandHandler("cgu", cmd_cgu))
    app_tg.add_handler(CommandHandler("admin", cmd_admin))
    app_tg.add_handler(CallbackQueryHandler(button_handler))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app_tg.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("🚀 Bot Marketplace démarré !")
    app_tg.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
