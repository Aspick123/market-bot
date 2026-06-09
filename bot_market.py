"""
╔══════════════════════════════════════════════════════════════╗
║         BOT MARKETPLACE — JEUX VIDÉO                         ║
║              bot_market.py — Fichier principal               ║
╠══════════════════════════════════════════════════════════════╣
║  Fichiers requis :                                           ║
║  database_market.py, annonces.py, recherche.py,             ║
║  transactions.py, litiges.py, alertes.py,                   ║
║  reputation.py, parrainage.py, cgu.py,                      ║
║  gamification.py, admin_market.py                           ║
╠══════════════════════════════════════════════════════════════╣
║  Installation :                                              ║
║  pip install python-telegram-bot reportlab                   ║
║  python bot_market.py                                        ║
╚══════════════════════════════════════════════════════════════╝
"""
from threading import Thread
from flask import Flask

app = Flask("")

@app.route("/")
def home():
    return "Le bot Marketplace est en ligne !"

def run():
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()


import json, os, time, logging, datetime
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ChatMemberHandler
)

# ── Base de données (initialise tout au démarrage) ──
from database_market import (
    init_database, mdb_read, mdb_write, mdb_config,
    get_user, save_user, get_role, has_perm,
    ROLES_EQUIPE, add_log, format_date, DATA_DIR
)

# ── Modules ──
from annonces import (
    handle_annonces_callbacks, handle_annonces_input,
    handle_annonces_photos, start_creation_annonce, show_mes_annonces,
    afficher_annonce, booster_annonce
)
from recherche import handle_recherche_callbacks, handle_recherche_input
from transactions import handle_transactions_callbacks
from litiges import handle_litiges_callbacks, handle_litiges_input, handle_litiges_photos
from alertes import handle_alertes_callbacks, notifier_expiration_proche
from reputation import (
    handle_reputation_callbacks, handle_reputation_input,
    show_profil_public, show_leaderboard
)
from parrainage import (
    handle_parrainage_callbacks, handle_parrainage_start
)
from cgu import handle_cgu_callbacks, handle_cgu_input
from gamification import handle_gamification_callbacks, envoyer_rapports_periodiques
from admin_market import (
    handle_admin_market_callbacks, handle_admin_market_input,
    show_admin_panel, show_profil_complet_admin
)

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════

TOKEN = "8549692419:AAEf5EcX6TzgGsaT8KZWRiAEK42h4FJjc0k"
SUPER_ADMIN_ID = 5117004360

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, "market_bot.log")),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

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

    # Blacklist
    bl = mdb_read("blacklist.json")
    if any(b["user_id"] == uid for b in bl):
        await update.effective_message.reply_text("🚫 Ton compte est blacklisté.")
        return False

    # Suspension
    if user.get("suspendu"):
        fin = user.get("suspension_fin", "?")
        now = datetime.datetime.now()
        try:
            fin_dt = datetime.datetime.strptime(fin, "%d/%m/%Y")
            if now > fin_dt:
                user["suspendu"] = False
                save_user(uid, user)
            else:
                await update.effective_message.reply_text(
                    f"🔴 Compte suspendu jusqu'au *{fin}*.",
                    parse_mode="Markdown"
                )
                return False
        except: pass

    # Mode urgence
    config = mdb_config()
    if config.get("mode_urgence") and uid != SUPER_ADMIN_ID:
        await update.effective_message.reply_text(
            "🚨 Le marketplace est en mode urgence.\nToutes les transactions sont temporairement suspendues."
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
    args = ctx.args

    # Parrainage
    if args and args[0].startswith("parrain_"):
        await handle_parrainage_start(update, ctx, ctx.bot, SUPER_ADMIN_ID)

    # Afficher annonce directe
    if args and args[0].startswith("ann_"):
        ann_id = args[0].replace("ann_", "")
        await afficher_annonce(update.message, ann_id, user.id)
        return

    # Onboarding si nouveau
    user_data = get_user(user.id)
    role = get_role(user.id, SUPER_ADMIN_ID)
    role_label = ROLES_EQUIPE.get(role, "👤 Membre")

    kb = [
        [InlineKeyboardButton("🔍 Parcourir les annonces", callback_data="menu_recherche"),
         InlineKeyboardButton("➕ Publier une annonce", callback_data="menu_vendre")],
        [InlineKeyboardButton("📋 Mes annonces", callback_data="menu_mes_annonces"),
         InlineKeyboardButton("💰 Mes transactions", callback_data="menu_historique")],
        [InlineKeyboardButton("🔔 Mes alertes", callback_data="menu_alertes"),
         InlineKeyboardButton("🎯 Parrainage", callback_data="menu_parrainage")],
        [InlineKeyboardButton("🏆 Classement", callback_data="menu_leaderboard"),
         InlineKeyboardButton("🚫 Blacklist", callback_data="menu_blacklist_publique")],
        [InlineKeyboardButton("⚖️ Ouvrir un litige", callback_data="menu_litige"),
         InlineKeyboardButton("🎯 Mes défis", callback_data="menu_defis")],
        [InlineKeyboardButton("👤 Mon profil", callback_data=f"voir_profil_{user.id}"),
         InlineKeyboardButton("📋 CGU", callback_data="menu_cgu")],
    ]

    if has_perm(user.id, "valider_annonces", SUPER_ADMIN_ID):
        kb.append([InlineKeyboardButton("🔐 Panel Admin", callback_data="adm_market_panel")])

    await update.message.reply_text(
        f"🎮 *Marketplace Jeux Vidéo*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Bienvenue *{user.first_name}* !\n"
        f"Rôle : {role_label}\n\n"
        f"Achète, vends ou échange des comptes\n"
        f"et monnaies de jeux en toute sécurité.\n\n"
        f"👇 Choisis une option :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  COMMANDES
# ══════════════════════════════════════════════════════════════

async def cmd_vendre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    user = update.effective_user
    # Vérifier CGU vendeur
    from cgu import user_a_accepte_cgu_vendeur
    if not await user_a_accepte_cgu_vendeur(update.message, user.id, ctx):
        return
    await start_creation_annonce(update.message, user.id)

async def cmd_annonces(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from recherche import afficher_toutes
    await afficher_toutes(update.message, 0)

async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    if not ctx.args:
        ctx.user_data["rech_state"] = "texte_libre"
        await update.message.reply_text(
            "🔍 Tape ta recherche :\n_(ex: compte Fortnite, V-Bucks...)_",
            parse_mode="Markdown"
        )
        return
    texte = " ".join(ctx.args)
    from recherche import filter_annonces, afficher_resultats
    resultats = filter_annonces({"texte": texte})
    await afficher_resultats(update.message, resultats, 0, {"texte": texte}, "rech_texte_p")

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

async def cmd_cgu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from cgu import show_cgu
    await show_cgu(update.message)

async def cmd_parrainage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from parrainage import show_menu_parrainage
    await show_menu_parrainage(update.message, update.effective_user.id, ctx.bot)

async def cmd_defis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    from gamification import show_mes_defis
    await show_mes_defis(update.message, update.effective_user.id)

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
        "*/search [texte]* — Rechercher\n"
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
#  CALLBACK HANDLER PRINCIPAL
# ══════════════════════════════════════════════════════════════

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    # Déléguer aux modules dans l'ordre de priorité
    if await handle_cgu_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_annonces_callbacks(query, ctx, user, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_recherche_callbacks(query, ctx): return
    if await handle_transactions_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_litiges_callbacks(query, ctx, user, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_alertes_callbacks(query, ctx): return
    if await handle_reputation_callbacks(query, ctx, ctx.bot): return
    if await handle_parrainage_callbacks(query, ctx, ctx.bot): return
    if await handle_gamification_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_admin_market_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID): return

    # Callbacks restants
    data = query.data
    msg = query.message
    uid = user.id

    if data == "menu_vendre":
        from cgu import user_a_accepte_cgu_vendeur
        if not await user_a_accepte_cgu_vendeur(msg, uid, ctx):
            return
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

    elif data.startswith("adm_boost_"):
        ann_id = data.replace("adm_boost_", "")
        if has_perm(uid, "valider_annonces", SUPER_ADMIN_ID):
            success = await booster_annonce(ann_id, uid, ctx.bot)
            await msg.reply_text("🚀 Annonce boostée !" if success else "❌ Erreur.")

    elif data.startswith("voir_profil_admin_"):
        target_id = int(data.replace("voir_profil_admin_", ""))
        if has_perm(uid, "voir_telephone", SUPER_ADMIN_ID):
            await show_profil_complet_admin(msg, target_id)

# ══════════════════════════════════════════════════════════════
#  HANDLER MESSAGES TEXTE
# ══════════════════════════════════════════════════════════════

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return

    # Déléguer aux modules
    if await handle_cgu_input(update, ctx): return
    if await handle_annonces_input(update, ctx, update.effective_user, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_litiges_input(update, ctx, update.effective_user, ctx.bot, SUPER_ADMIN_ID): return
    if await handle_reputation_input(update, ctx, ctx.bot): return
    if await handle_recherche_input(update, ctx): return
    if await handle_admin_market_input(update, ctx, ctx.bot, SUPER_ADMIN_ID): return

# ══════════════════════════════════════════════════════════════
#  HANDLER PHOTOS
# ══════════════════════════════════════════════════════════════

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update): return
    if await handle_annonces_photos(update, ctx): return
    if await handle_litiges_photos(update, ctx): return

# ══════════════════════════════════════════════════════════════
#  TÂCHES PLANIFIÉES
# ══════════════════════════════════════════════════════════════

async def tache_hebdomadaire(ctx: ContextTypes.DEFAULT_TYPE):
    """Envoie les rapports hebdo et vérifie les expirations."""
    log.info("🔄 Tâche hebdomadaire lancée...")
    nb = await envoyer_rapports_periodiques(ctx.bot, "hebdo")
    await notifier_expiration_proche(ctx.bot)
    log.info(f"✅ Rapports hebdo envoyés à {nb} vendeurs.")

async def tache_mensuelle(ctx: ContextTypes.DEFAULT_TYPE):
    """Envoie les rapports mensuels."""
    log.info("🔄 Tâche mensuelle lancée...")
    nb = await envoyer_rapports_periodiques(ctx.bot, "mensuel")
    log.info(f"✅ Rapports mensuels envoyés à {nb} vendeurs.")

async def tache_quotidienne(ctx: ContextTypes.DEFAULT_TYPE):
    """Vérifie les expirations d'annonces et suspensions."""
    log.info("🔄 Tâche quotidienne lancée...")
    await notifier_expiration_proche(ctx.bot)

    # Lever les suspensions expirées
    users = mdb_read("users.json")
    now = datetime.datetime.now()
    for uid_str, u in users.items():
        if u.get("suspendu") and u.get("suspension_fin"):
            try:
                fin = datetime.datetime.strptime(u["suspension_fin"], "%d/%m/%Y")
                if now > fin:
                    u["suspendu"] = False
                    users[uid_str] = u
                    try:
                        await ctx.bot.send_message(
                            int(uid_str),
                            "✅ *Ta suspension a été levée !*\nTu peux à nouveau utiliser le marketplace.",
                            parse_mode="Markdown"
                        )
                    except: pass
            except: pass
    mdb_write("users.json", users)

# ══════════════════════════════════════════════════════════════
#  POST INIT
# ══════════════════════════════════════════════════════════════

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start",        "Menu principal"),
        BotCommand("aide",         "Liste des commandes"),
        BotCommand("vendre",       "Publier une annonce"),
        BotCommand("annonces",     "Parcourir les annonces"),
        BotCommand("search",       "Rechercher une annonce"),
        BotCommand("profil",       "Mon profil public"),
        BotCommand("mes_annonces", "Mes annonces"),
        BotCommand("historique",   "Mes transactions"),
        BotCommand("litige",       "Ouvrir un litige"),
        BotCommand("alertes",      "Mes alertes personnalisées"),
        BotCommand("classement",   "Leaderboard vendeurs"),
        BotCommand("parrainage",   "Mon parrainage"),
        BotCommand("defis",        "Mes défis"),
        BotCommand("cgu",          "Conditions d'utilisation"),
        BotCommand("admin",        "Panel administrateur"),
    ])

    # Planifier les tâches
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(tache_quotidienne, time=datetime.time(8, 0, 0))
        job_queue.run_repeating(tache_hebdomadaire, interval=604800, first=10)
        job_queue.run_repeating(tache_mensuelle, interval=2592000, first=20)

    log.info("✅ Bot Marketplace démarré !")

# ══════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # Commandes
    app.add_handler(CommandHandler("start",        start))
    app.add_handler(CommandHandler("aide",         cmd_aide))
    app.add_handler(CommandHandler("vendre",       cmd_vendre))
    app.add_handler(CommandHandler("annonces",     cmd_annonces))
    app.add_handler(CommandHandler("search",       cmd_search))
    app.add_handler(CommandHandler("profil",       cmd_profil))
    app.add_handler(CommandHandler("mes_annonces", cmd_mes_annonces))
    app.add_handler(CommandHandler("historique",   cmd_historique))
    app.add_handler(CommandHandler("litige",       cmd_litige))
    app.add_handler(CommandHandler("alertes",      cmd_alertes))
    app.add_handler(CommandHandler("classement",   cmd_classement))
    app.add_handler(CommandHandler("parrainage",   cmd_parrainage))
    app.add_handler(CommandHandler("defis",        cmd_defis))
    app.add_handler(CommandHandler("cgu",          cmd_cgu))
    app.add_handler(CommandHandler("admin",        cmd_admin))

    # Callbacks
    app.add_handler(CallbackQueryHandler(button_handler))

    # Messages texte
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Photos
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("🎮 Bot Marketplace démarré ! Ctrl+C pour arrêter.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
