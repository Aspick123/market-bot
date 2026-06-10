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
ATTENTE_AUTRE_JEU, CHOIX_PAIEMENT = range(4, 6)

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

# Modifie la fonction debut_vente pour ajouter le bouton "Autre"
async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    kb = [
        [InlineKeyboardButton("⚽ eFootball Mobile", callback_data="cat:efootball")],
        [InlineKeyboardButton("✨ Genshin Impact", callback_data="cat:genshin")],
        [InlineKeyboardButton("⭐ Brawl Stars", callback_data="cat:brawl_stars")],
        [InlineKeyboardButton("➕ Autre Jeu", callback_data="cat:autre")],
        [InlineKeyboardButton("🔙 Annuler", callback_data="menu:retour_start")]
    ]
    await query.message.edit_text(
        "📦 **Étape 1 : Choix du jeu**\n\nQuel type de compte souhaitez-vous mettre en vente ?",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_CATEGORIE

async def categorie_choisie(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cat:autre":
        await query.message.edit_text(
            "🎮 **Quel est le nom de votre jeu ?**\n\nVeuillez écrire et envoyer le nom exact du jeu concerné.",
            parse_mode="Markdown"
        )
        return ATTENTE_AUTRE_JEU
    cat_mapping = {
        "cat:efootball": "eFootball Mobile",
        "cat:genshin": "Genshin Impact",
        "cat:brawl_stars": "Brawl Stars"
    }
    ctx.user_data["vente_categorie"] = cat_mapping.get(query.data, "Inconnu")
    await query.message.edit_text(
        f"📝 **Étape 2 : Description de l'offre ({ctx.user_data['vente_categorie']})**\n\nVeuillez envoyer les détails de votre compte.",
        parse_mode="Markdown"
    )
    return ATTENTE_DESCRIPTION

async def autre_jeu_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_categorie"] = update.message.text.strip()
    await update.message.reply_text(
        f"📝 **Étape 2 : Description de l'offre ({ctx.user_data['vente_categorie']})**\n\nVeuillez envoyer un message contenant les détails de votre compte.",
        parse_mode="Markdown"
    )
    return ATTENTE_DESCRIPTION

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    await update.message.reply_text(
        "💰 **Étape 3 : Fixer le prix**\n\nEntrez le prix de vente souhaité en **FCFA (XOF)**.\n*(Entrez uniquement un nombre entier)*",
        parse_mode="Markdown"
    )
    return ATTENTE_PRIX

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texte_prix = update.message.text.strip()
    if not texte_prix.isdigit():
        await update.message.reply_text("❌ Veuillez entrer un prix valide (uniquement des chiffres) :")
        return ATTENTE_PRIX
    ctx.user_data["vente_prix"] = int(texte_prix)
    ctx.user_data["vente_paiements"] = []
    return await afficher_choix_paiement(update.message.reply_text, ctx)

async def afficher_choix_paiement(reply_func, ctx):
    choix = ctx.user_data.get("vente_paiements", [])
    check = lambda m: "☑️" if m in choix else "⬜"
    kb = [
        [InlineKeyboardButton(f"{check('CFA')} 💵 FCFA (Airtel / Moov / Wave)", callback_data="pay:CFA")],
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (Binance TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    await reply_func(
        "💳 **Étape 4 : Moyens de paiement acceptés**\n\nSélectionnez la ou les méthodes que vous acceptez.\n*(Cochez/décochez, puis validez)*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_PAIEMENT

async def paiement_choisi_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    choix = ctx.user_data.get("vente_paiements", [])
    if data == "pay:valider":
        if not choix:
            kb = [[InlineKeyboardButton("🔄 Réessayer", callback_data="pay:refresh")]]
            await query.message.edit_text("⚠️ Vous devez sélectionner au moins un moyen de paiement.", reply_markup=InlineKeyboardMarkup(kb))
            return CHOIX_PAIEMENT
        cat = ctx.user_data["vente_categorie"]
        desc = ctx.user_data["vente_description"]
        prix = ctx.user_data["vente_prix"]
        methodes = ", ".join(choix)
        recap = (
            "🧐 **VÉRIFICATION DE VOTRE ANNONCE**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"📦 **Jeu :** `{cat}`\n"
            f"📝 **Description :**\n{desc}\n\n"
            f"💰 **Prix demandé :** `{prix} XOF`\n"
            f"💳 **Paiements :** `{methodes}`\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "Souhaitez-vous valider et publier cette annonce ?"
        )
        kb = [
            [InlineKeyboardButton("✅ Valider et Publier", callback_data="publier:oui")],
            [InlineKeyboardButton("❌ Tout annuler", callback_data="publier:non")]
        ]
        await query.message.edit_text(recap, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return CONFIRMATION
    methode = data.replace("pay:", "")
    if methode in choix:
        choix.remove(methode)
    else:
        choix.append(methode)
    ctx.user_data["vente_paiements"] = choix
    check = lambda m: "☑️" if m in choix else "⬜"
    kb = [
        [InlineKeyboardButton(f"{check('CFA')} 💵 FCFA (Airtel / Moov / Wave)", callback_data="pay:CFA")],
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (Binance TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return CHOIX_PAIEMENT

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if query.data == "publier:oui":
        cat = ctx.user_data.get("vente_categorie")
        desc = ctx.user_data.get("vente_description")
        prix = ctx.user_data.get("vente_prix")
        from database_market import create_annonce
        annonce_id = create_annonce(vendeur_id=uid, categorie=cat, description=desc, prix=prix)
        texte_succes = f"🎉 **Félicitations ! Annonce publiée !**\n\n🆔 ID unique : `{annonce_id}`\nVotre compte est bien enregistré."
        ctx.user_data.clear()
        await query.message.edit_text(texte_succes, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
    else:
        ctx.user_data.clear()
        await query.message.edit_text("❌ Création de l'annonce annulée.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END
# ---------------- FIN DU MODULE VENTE ----------------

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from database_market import is_mode_urgence, db
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
        
        # ➕ Étape insérée si l'utilisateur écrit lui-même son jeu
        ATTENTE_AUTRE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_jeu_recu)],
        
        ATTENTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_recue)],
        ATTENTE_PRIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, prix_recu)],
        
        # ➕ Nouvelle étape insérée pour le choix multiple des paiements
        CHOIX_PAIEMENT: [CallbackQueryHandler(paiement_choisi_handler, pattern="^pay:")],
        
        CONFIRMATION: [CallbackQueryHandler(confirmation_finale, pattern="^publier:")]
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

