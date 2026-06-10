import os
import time
import logging
from threading import Thread
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

from database_market import (
    get_user,
    save_user,
    get_role_label,
    is_flooded,
    is_mode_urgence,
    create_annonce
)
from menus import get_main_menu_keyboard, get_back_to_start_keyboard

# États de la conversation pour la création d'une annonce
CHOIX_CATEGORIE, ATTENTE_DESCRIPTION, ATTENTE_PRIX, CONFIRMATION = range(4)

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

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAFxtyQig1cNZDvYF1PnTTbOlDOW1POlrx4")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    
    if is_mode_urgence() and uid != SUPER_ADMIN_ID:
        await update.effective_message.reply_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return ConversationHandler.END
        
    if is_flooded(uid):
        await update.effective_message.reply_text("⏳ Trop de requêtes. Veuillez patienter.")
        return ConversationHandler.END

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
    
    return ConversationHandler.END

# ---------------- LOGIQUE DU MODULE VENTE ----------------

async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Déclenchée quand l'utilisateur clique sur '➕ Vendre'."""
    query = update.callback_query
    await query.answer()
    
    kb = [
        [InlineKeyboardButton("🎮 Comptes de Jeu", callback_data="cat:Comptes")],
        [InlineKeyboardButton("💰 Monnaies Virtuelles / Items", callback_data="cat:Monnaies")],
        [InlineKeyboardButton("🔙 Annuler", callback_data="menu:retour_start")]
    ]
    
    await query.message.edit_text(
        "📁 **Étape 1 :** Choisissez la catégorie de votre produit :",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_CATEGORIE

async def categorie_choisie(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Enregistre la catégorie et demande la description."""
    query = update.callback_query
    await query.answer()
    
    ctx.user_data["v_categorie"] = query.data.replace("cat:", "")
    
    await query.message.edit_text(
        "📝 **Étape 2 :** Entrez la description de votre produit.\n"
        "*(Ex: Compte Genshin AR58, Raiden + Furina, Serveur EU)*.\n\n"
        "✍️ _Écrivez votre texte directement dans le chat puis envoyez._"
    )
    return ATTENTE_DESCRIPTION

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Enregistre la description et demande le prix."""
    ctx.user_data["v_description"] = update.message.text
    
    await update.message.reply_text(
        "💶 **Étape 3 :** Quel est le prix de votre article ?\n"
        "*(Ex: 250 USDT, 15 000 FCFA)*"
    )
    return ATTENTE_PRIX

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Enregistre le prix et demande la confirmation finale."""
    ctx.user_data["v_prix"] = update.message.text
    
    resume = (
        "📊 **Récapitulatif de votre annonce :**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📁 **Catégorie :** {ctx.user_data['v_categorie']}\n"
        f"📝 **Description :** {ctx.user_data['v_description']}\n"
        f"💰 **Prix demandé :** {ctx.user_data['v_prix']}\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "Souhaitez-vous publier cette annonce sur le marché ?"
    )
    
    kb = [
        [InlineKeyboardButton("✅ Publier l'annonce", callback_data="publier:oui")],
        [InlineKeyboardButton("❌ Annuler et tout effacer", callback_data="menu:retour_start")]
    ]
    
    await update.message.reply_text(resume, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return CONFIRMATION

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Enregistre définitivement l'annonce dans MongoDB."""
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    
    if query.data == "publier:oui":
        id_annonce = create_annonce(
            vendeur_id=uid,
            categorie=ctx.user_data["v_categorie"],
            description=ctx.user_data["v_description"],
            prix=ctx.user_data["v_prix"]
        )
        
        await query.message.edit_text(
            f"🎉 **Félicitations !** Votre annonce a été publiée avec succès.\n"
            f"🆔 **Référence de l'annonce :** `{id_annonce}`",
            reply_markup=get_back_to_start_keyboard(),
            parse_mode="Markdown"
        )
    ctx.user_data.clear()
    return ConversationHandler.END

# ---------------- FIN DU MODULE VENTE ----------------

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    data = query.data
    await query.answer()
    
    if is_mode_urgence() and uid != SUPER_ADMIN_ID:
        await query.message.edit_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return
        
    if is_flooded(uid): return

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
            
        elif data == "menu:admin_panel":
            if uid != SUPER_ADMIN_ID:
                await query.message.edit_text("⛔ Accès refusé. Vous n'êtes pas administrateur.", reply_markup=get_back_to_start_keyboard())
                return

            # Import dynamique ou appel direct de tes fonctions de database_market
            from database_market import db, is_mode_urgence
            
            # Récupération des statistiques réelles dans MongoDB
            total_users = db.users.count_documents({}) if hasattr(db, 'users') else 0
            total_annonces = db.annonces.count_documents({}) if hasattr(db, 'annonces') else 0
            statut_urgence = "🚨 ACTIF (Maintenance)" if is_mode_urgence() else "✅ INACTIF (En ligne)"

            admin_text = (
                "⚡ **PANNEAU D'ADMINISTRATION** ⚡\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"📊 **Statistiques du Marketplace :**\n"
                f"👤 Utilisateurs inscrits : `{total_users}`\n"
                f"📦 Annonces créées : `{total_annonces}`\n\n"
                f"⚙️ **Statut du Bot :** {statut_urgence}\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                "Utilisez les boutons ci-dessous pour piloter la plateforme :"
            )

            # Boutons de contrôle
            kb = [
                [InlineKeyboardButton("🚨 Basculer Mode Urgence", callback_data="admin:toggle_urgence")],
                [InlineKeyboardButton("🔙 Retour au Menu", callback_data="menu:retour_start")]
            ]
            await query.message.edit_text(admin_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

        elif data == "admin:toggle_urgence":
            if uid != SUPER_ADMIN_ID: return
            
            from database_market import db
            # On cherche ou crée la config du mode urgence
            config = db.config.find_one({"_id": "mode_urgence"})
            actuel = config.get("actif", False) if config else False
            nouveau_statut = not actuel
            
            db.config.update_one({"_id": "mode_urgence"}, {"$set": {"actif": nouveau_statut}}, upsert=True)
            
            texte_confirmation = f"🚨 **Mode Urgence modifié !**\nLe mode maintenance est maintenant : {'🔴 ACTIF' if nouveau_statut else '🟢 INACTIF'}."
            kb = [[InlineKeyboardButton("🔄 Rafraîchir le Panel", callback_data="menu:admin_panel")]]
            await query.message.edit_text(texte_confirmation, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

        # Reste des modules en chantier (sans admin_panel)
        elif data in ["menu:recherche", "menu:mes_annonces", "menu:historique", 
                      "menu:parrainage", "menu:defis", "menu:leaderboard", "menu:litige", 
                      "menu:alertes", "menu:blacklist"]:
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
    
    vente_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_vente, pattern="^menu:vendre$")],
        states={
            CHOIX_CATEGORIE: [CallbackQueryHandler(categorie_choisie, pattern="^cat:")],
            ATTENTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_recue)],
            ATTENTE_PRIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, prix_recu)],
            CONFIRMATION: [CallbackQueryHandler(confirmation_finale, pattern="^publier:oui")]
        },
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    application.add_handler(vente_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🚀 Bot démarré avec le module Vente actif !")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

