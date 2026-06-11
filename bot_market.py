import os
import time
import logging
from threading import Thread
from flask import Flask
from bson.objectid import ObjectId

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
    db,
    get_user,
    save_user,
    get_role_label,
    is_flooded,
    is_mode_urgence
)
from menus import get_main_menu_keyboard, get_back_to_start_keyboard

# --- IMPORTS DE NOS AUTRES MODULES ---
from moderation import soumettre_a_la_moderation, traitement_moderation
from profil import afficher_profil, gestion_candidature

# États de la conversation pour le Tunnel de Vente
(
    CHOIX_CATEGORIE,
    ATTENTE_AUTRE_JEU,
    CHOIX_PLATEFORME,
    CHOIX_SPECIFICITES,
    ATTENTE_VALEURS_SPECS,
    ATTENTE_PHOTOS,
    ATTENTE_DESCRIPTION,
    CHOIX_DEVISE,
    ATTENTE_AUTRE_DEVISE,
    ATTENTE_PRIX,
    CHOIX_PAIEMENT,
    CHOIX_CRYPTO,
    ATTENTE_CONTACT,
    ATTENTE_DISPO,
    CONFIRMATION
) = range(15)

# État de la conversation pour la Recherche Flash (Oui/Non)
ATTENTE_RECHERCHE_JEU = 99

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

# ==================== LOGIQUE DU MODULE RECHERCHE FLASH (OUI / NON) ====================

async def debut_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔍 **Moteur de Recherche Flash**\n\n"
        "Entrez le nom exact du jeu que vous recherchez (ex: *Genshin Impact, eFootball, Brawl Stars...*) :",
        parse_mode="Markdown"
    )
    return ATTENTE_RECHERCHE_JEU

async def executer_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jeu_recherche = update.message.text.strip()
    
    # Recherche d'une annonce valide correspondante
    annonce = db.annonces.find_one({
        "categorie": {"$regex": f"^{jeu_recherche}$", "$options": "i"},
        "statut": "valide"
    })
    
    if annonce:
        vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
        username_vendeur = vendeur.get("username", "Inconnu") if vendeur else "Inconnu"
        paiements = ", ".join(annonce.get("paiements", []))
        
        reponse_oui = (
            "🟢 **OUI ! Une annonce est disponible !**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎮 **Jeu :** `{annonce['categorie']}`\n"
            f"💻 **Plateforme :** `{annonce.get('plateforme', 'Non spécifiée')}`\n"
            f"💰 **Prix :** `{annonce['prix']} {annonce['devise']}`\n"
            f"💳 **Paiements acceptés :** `{paiements}`\n"
            f"📝 **Description :**\n{annonce['description']}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Vendeur :** @{username_vendeur}\n\n"
            "💡 *Conseil : Utilisez le bouton bleu ci-dessous pour discuter directement avec le vendeur. Si vous vous mettez d'accord, demandez l'arbitrage pour sécuriser la transaction.*"
        )
        
        # Boutons d'interactions directes acheteur -> vendeur / gérant
        kb = [
            [InlineKeyboardButton("💬 Contacter le Vendeur", url=f"https://t.me/{username_vendeur}")],
            [InlineKeyboardButton("⚡ Sécuriser via un Gérant (Arbitrage)", callback_data=f"achat:arbitrage:{annonce['_id']}")],
            [InlineKeyboardButton("🔙 Retour au Menu Principal", callback_data="menu:retour_start")]
        ]
        
        await update.message.reply_text(reponse_oui, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        reponse_non = (
            "🔴 **NON. Aucune annonce disponible.**\n\n"
            f"Désolé, il n'y a actuellement aucun compte vérifié mis en vente pour le jeu *{jeu_recherche}*."
        )
        await update.message.reply_text(reponse_non, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        
    return ConversationHandler.END


# ==================== LOGIQUE DU MODULE VENTE (TUNNEL) ====================

async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    ctx.user_data.clear()
    ctx.user_data["specs_choisies"] = []
    ctx.user_data["specs_valeurs"] = {}
    ctx.user_data["photos"] = []
    ctx.user_data["vente_paiements"] = []
    
    await query.message.edit_text(
        "🎮 **Étape 1 : Quel est le jeu concerné ?**\n\n"
        "Veuillez écrire et envoyer le **nom exact** du jeu vidéo (ex: *Genshin Impact, eFootball...*).",
        parse_mode="Markdown"
    )
    return ATTENTE_AUTRE_JEU

async def autre_jeu_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_jeu"] = update.message.text.strip()
    
    kb = [
        [InlineKeyboardButton("📱 Android", callback_data="plat:Android")],
        [InlineKeyboardButton("🍏 iOS (Apple)", callback_data="plat:iOS")],
        [InlineKeyboardButton("💻 PC", callback_data="plat:PC")],
        [InlineKeyboardButton("🎮 Console (PS/Xbox)", callback_data="plat:Console")],
        [InlineKeyboardButton("🌐 Multiplateforme", callback_data="plat:Multi")]
    ]
    
    await update.message.reply_text(
        "🎮 **Sur quelle plateforme se trouve votre compte ?**\n\n"
        "Sélectionnez le support principal :",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_PLATEFORME

async def plateforme_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["vente_plateforme"] = query.data.replace("plat:", "")
    
    await query.message.edit_text(
        "📸 **Étape 2 : Preuves en images**\n\n"
        "Veuillez envoyer entre **1 et 5 photos** de votre compte (captures d'écran).\n\n"
        "👉 *Une fois fini, écrivez le mot* **'FIN'** *pour passer à la suite.*",
        parse_mode="Markdown"
    )
    return ATTENTE_PHOTOS

async def photos_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        if len(ctx.user_data["photos"]) < 5:
            ctx.user_data["photos"].append(photo_id)
            await update.message.reply_text(f"📸 Image reçue ({len(ctx.user_data['photos'])}/5). Continuez ou écrivez 'FIN'.")
        else:
            await update.message.reply_text("⚠️ Limite de 5 photos atteinte. Écrivez 'FIN' pour continuer.")
        return ATTENTE_PHOTOS
        
    if update.message.text and update.message.text.upper() == "FIN":
        await update.message.reply_text("📝 **Veuillez entrer une description détaillée pour votre compte :**")
        return ATTENTE_DESCRIPTION
    return ATTENTE_PHOTOS

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    
    kb = [
        [InlineKeyboardButton("💵 FCFA (XOF)", callback_data="devise:FCFA")],
        [InlineKeyboardButton("💵 Dollar ($)", callback_data="devise:USD")],
        [InlineKeyboardButton("💶 Euro (€)", callback_data="devise:EUR")]
    ]
    
    await update.message.reply_text(
        "💱 **Étape 3 : Choix de la devise**\n\nDans quelle devise fixez-vous le prix ?",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return ATTENTE_PRIX

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    if query and query.data.startswith("devise:"):
        await query.answer()
        choix_devise = query.data.split(":")[1]
        ctx.user_data["vente_devise"] = choix_devise
        
        await query.message.edit_text(
            f"💰 **Fixer le montant ({choix_devise})**\n\nEntrez le prix de vente souhaité (chiffres uniquement) :",
            parse_mode="Markdown"
        )
        return ATTENTE_PRIX

    if update.message:
        texte_prix = update.message.text.strip()
        if not texte_prix.isdigit():
            await update.message.reply_text("❌ Veuillez entrer un montant valide (uniquement des chiffres) :")
            return ATTENTE_PRIX
            
        ctx.user_data["vente_prix"] = int(texte_prix)
        return await afficher_choix_paiement(update.message.reply_text, ctx)

async def afficher_choix_paiement(reply_func, ctx):
    choix = ctx.user_data.get("vente_paiements", [])
    check = lambda m: "☑️" if m in choix else "⬜"
    
    kb = [
        [InlineKeyboardButton(f"{check('FCFA')} 💵 FCFA", callback_data="pay:FCFA")],
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    
    await reply_func(
        "💳 **Étape 4 : Moyens de paiement acceptés**\n\nSélectionnez vos méthodes préférées, puis validez :",
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
            await query.message.edit_text("⚠️ Sélectionnez au moins un moyen de paiement.", reply_markup=InlineKeyboardMarkup(kb))
            return CHOIX_PAIEMENT
            
        cat = ctx.user_data.get("vente_jeu", "Inconnu")
        desc = ctx.user_data.get("vente_description", "Aucune description")
        prix = ctx.user_data.get("vente_prix", 0)
        devise = ctx.user_data.get("vente_devise", "XOF")
        methodes = ", ".join(choix)
        
        recap = (
            "🧐 **VÉRIFICATION DE VOTRE ANNONCE**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"📦 **Jeu :** `{cat}`\n"
            f"💻 **Plateforme :** `{ctx.user_data.get('vente_plateforme')}`\n"
            f"📝 **Description :**\n{desc}\n\n"
            f"💰 **Prix demandé :** `{prix} {devise}`\n"
            f"💳 **Paiements acceptés :** `{methodes}`\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "Souhaitez-vous soumettre cette annonce à l'équipe de modération ?"
        )
        kb = [
            [InlineKeyboardButton("✅ Valider et Soumettre", callback_data="publier:oui")],
            [InlineKeyboardButton("❌ Tout annuler", callback_data="publier:non")]
        ]
        await query.message.edit_text(recap, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return CONFIRMATION

    methode = data.replace("pay:", "")
    if methode in choix: choix.remove(methode)
    else: choix.append(methode)
        
    ctx.user_data["vente_paiements"] = choix
    
    check = lambda m: "☑️" if m in choix else "⬜"
    kb = [
        [InlineKeyboardButton(f"{check('FCFA')} 💵 FCFA", callback_data="pay:FCFA")],
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return CHOIX_PAIEMENT

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "publier:oui":
        await soumettre_a_la_moderation(update, ctx)
    elif query.data == "publier:non":
        await query.message.edit_text("❌ **Création de l'annonce annulée.**", reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        
    return ConversationHandler.END


# ==================== AIGUILLAGE CENTRAL DES BOUTONS MENUS ====================

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    # 🔄 REDIRECTION ET RÈGLAGE DU BOUTON RETOUR MENU PRINCIPAL
    if data == "menu:retour_start":
        await query.answer()
        await start_command(update, ctx)
        return

    # ⚡ TRANSACTION SÉCURISÉE (DEMANDE D'ARBITRAGE EN DERNIER RECOURS)
    if data.startswith("achat:arbitrage:"):
        await query.answer()
        annonce_id = data.split(":")[2]
        
        annonce = db.annonces.find_one({"_id": ObjectId(annonce_id)})
        if not annonce:
            await query.message.reply_text("❌ Cette annonce n'est plus disponible ou a été retirée.")
            return
            
        vendeur_id = annonce["vendeur_id"]
        vendeur_data = db.users.find_one({"_id": vendeur_id})
        username_vendeur = vendeur_data.get("username", "Inconnu") if vendeur_data else "Inconnu"
        
        # 1. Message de confirmation immédiat à l'acheteur
        await query.message.reply_text(
            "⏳ **Demande d'arbitrage transmise !**\n\n"
            "Un Gérant Arbitre vient d'être mis au courant pour sécuriser votre transaction.\n"
            "Veuillez patienter le temps qu'il prenne contact avec vous et le vendeur pour créer le salon d'échange sécurisé.",
            parse_mode="Markdown"
        )
        
        # 2. Alerte envoyée au Super Admin (Gérant de la plateforme)
        ticket_arbitrage = (
            "🚨 **NOUVELLE DEMANDE D'ARBITRAGE (TRANSACTION)**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Acheteur :** @{update.effective_user.username or 'Sans_Pseudo'} (ID: `{uid}`)\n"
            f"📦 **Jeu ciblé :** `{annonce['categorie']}` (Prix: {annonce['prix']} {annonce['devise']})\n"
            f"👤 **Vendeur :** @{username_vendeur} (ID: `{vendeur_id}`)\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "ℹ️ *Action du Staff : Veuillez initier un groupe à 3 pour encadrer le paiement et la livraison des identifiants.*"
        )
        
        try:
            await ctx.bot.send_message(
                chat_id=SUPER_ADMIN_ID,
                text=ticket_arbitrage,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Impossible d'alerter l'admin pour arbitrage : {e}")
        return

    if data.startswith("mod:"):
        await traitement_moderation(update, ctx)
        return
    if data.startswith("staff:"):
        await gestion_candidature(update, ctx)
        return

    await query.answer()

    if is_mode_urgence() and uid != SUPER_ADMIN_ID:
        await query.message.edit_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return

    try:
        if "profil" in data:
            await afficher_profil(update, ctx)
            return

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
                await query.message.edit_text("⛔ Accès refusé.", reply_markup=get_back_to_start_keyboard())
                return
                
            total_users = db.users.count_documents({})
            total_annonces = db.annonces.count_documents({})
            statut_urgence = "🚨 ACTIF (Maintenance)" if is_mode_urgence() else "✅ INACTIF (En ligne)"

            admin_text = (
                "⚡ **PANNEAU D'ADMINISTRATION** ⚡\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"👤 Utilisateurs inscrits : `{total_users}`\n"
                f"📦 Annonces créées : `{total_annonces}`\n\n"
                f"⚙️ **Statut du Bot :** {statut_urgence}\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
            )
            kb = [
                [InlineKeyboardButton("🚨 Basculer Mode Urgence", callback_data="admin:toggle_urgence")],
                [InlineKeyboardButton("🔙 Retour au Menu", callback_data="menu:retour_start")]
            ]
            await query.message.edit_text(admin_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

        elif data == "admin:toggle_urgence":
            if uid != SUPER_ADMIN_ID: return
            config = db.config.find_one({"_id": "mode_urgence"})
            actuel = config.get("actif", False) if config else False
            nouveau_statut = not actuel
            db.config.update_one({"_id": "mode_urgence"}, {"$set": {"actif": nouveau_statut}}, upsert=True)
            
            kb = [[InlineKeyboardButton("🔄 Rafraîchir le Panel", callback_data="menu:admin_panel")]]
            await query.message.edit_text("⚙️ Statut de maintenance mis à jour !", reply_markup=InlineKeyboardMarkup(kb))

        elif data in ["menu:mes_annonces", "menu:historique", "menu:parrainage", "menu:historique_achats",
                      "menu:defis", "menu:leaderboard", "menu:litige", "menu:alertes", "menu:blacklist", "menu:recharger"]:
            feature_name = data.replace("menu:", "").replace("_", " ").title()
            await query.message.edit_text(
                f"🚧 **Module [{feature_name}]**\n\nCe module est en cours d'intégration.",
                reply_markup=get_back_to_start_keyboard(),
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"Erreur callback {data}: {str(e)}")


# ==================== ENTRÉE PRINCIPALE ====================

def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    # 1. Gestionnaire de Conversation : Vente
    vente_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_vente, pattern="^menu:vendre$")],
        states={
            ATTENTE_AUTRE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_jeu_recu)],
            CHOIX_PLATEFORME: [CallbackQueryHandler(plateforme_choisie_handler, pattern="^plat:")],
            ATTENTE_PHOTOS: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), photos_recues)],
            ATTENTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_recue)],
            ATTENTE_PRIX: [
                CallbackQueryHandler(prix_recu, pattern="^devise:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, prix_recu)
            ],
            CHOIX_PAIEMENT: [CallbackQueryHandler(paiement_choisi_handler, pattern="^pay:")],
            CONFIRMATION: [CallbackQueryHandler(confirmation_finale, pattern="^publier:")]
        },
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    # 2. Gestionnaire de Conversation : Recherche Flash
    recherche_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_recherche, pattern=".*recherche.*")],
        states={
            ATTENTE_RECHERCHE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, executer_recherche)]
        },
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    application.add_handler(vente_conv)
    application.add_handler(recherche_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🚀 Marketplace Bot entièrement configuré avec Tunnel d'Arbitrage !")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
