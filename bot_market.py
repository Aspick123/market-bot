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

# États de la conversation pour la création d'une annonce (Tunnel Avancé - Strict)
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
    CHOIX_PAIEMENT,         # Placé correctement au bon endroit
    CHOIX_CRYPTO,
    ATTENTE_CONTACT,
    ATTENTE_DISPO,
    CONFIRMATION
) = range(15)              # Augmenté à 15 états réels

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
    query = update.callback_query
    await query.answer()
    
    ctx.user_data.clear()
    ctx.user_data["specs_choisies"] = []
    ctx.user_data["specs_valeurs"] = {}
    ctx.user_data["photos"] = []
    ctx.user_data["vente_paiements"] = []
    
    await query.message.edit_text(
        "🎮 **Étape 1 : Quel est le jeu concerné ?**\n\n"
        "Veuillez écrire et envoyer le **nom exact** du jeu vidéo (ex: *Genshin Impact, eFootball, Brawl Stars...*).",
        parse_mode="Markdown"
    )
    return ATTENTE_AUTRE_JEU

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    
    kb = [
        [InlineKeyboardButton("💵 FCFA (XOF)", callback_data="devise:FCFA")],
        [InlineKeyboardButton("💵 Dollar ($)", callback_data="devise:USD")],
        [InlineKeyboardButton("💶 Euro (€)", callback_data="devise:EUR")]
    ]
    
    await update.message.reply_text(
        "💱 **Étape 3 : Choix de la devise**\n\nDans quelle devise souhaitez-vous fixer le prix de votre compte ?",
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
            f"💰 **Étape 3.5 : Fixer le montant ({choix_devise})**\n\n"
            f"Entrez le prix de vente souhaité en **{choix_devise}**.\n"
            "*(Entrez uniquement un nombre entier, sans texte ni symboles)*",
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
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (Binance TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    
    await reply_func(
        "💳 **Étape 4 : Moyens de paiement acceptés**\n\n"
        "Sélectionnez les méthodes de paiement que vous acceptez pour cette vente.\n"
        "*(Cochez/décochez les options, puis validez)*",
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
            
        cat = ctx.user_data.get("vente_jeu", "Inconnu")
        desc = ctx.user_data.get("vente_description", "Aucune description")
        prix = ctx.user_data.get("vente_prix", 0)
        devise = ctx.user_data.get("vente_devise", "XOF")
        methodes = ", ".join(choix)
        
        recap = (
            "🧐 **VÉRIFICATION DE VOTRE ANNONCE**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"📦 **Jeu :** `{cat}`\n"
            f"📝 **Description :**\n{desc}\n\n"
            f"💰 **Prix demandé :** `{prix} {devise}`\n"
            f"💳 **Paiements acceptés :** `{methodes}`\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
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
        [InlineKeyboardButton(f"{check('FCFA')} 💵 FCFA", callback_data="pay:FCFA")],
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (Binance TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return CHOIX_PAIEMENT

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    if query.data == "publier:oui":
        cat = ctx.user_data.get("vente_jeu", "Inconnu")
        desc = ctx.user_data.get("vente_description", "Aucune description")
        prix = ctx.user_data.get("vente_prix", 0)
        
        create_annonce(vendeur_id=uid, categorie=cat, description=desc, prix=prix)
        
        texte_succes = (
            "🎉 **Félicitations ! Votre annonce a été publiée avec succès.**\n\n"
            "Elle est désormais en ligne. Vous recevrez une notification directe si un utilisateur est intéressé."
        )
        await query.message.edit_text(texte_succes, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
    
    elif query.data == "publier:non":
        await query.message.edit_text("❌ **Création de l'annonce annulée.**", reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        
    return ConversationHandler.END

# ---------------- GESTIONNAIRE GLOBAL DES BOUTONS MENUS ----------------

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = update.effective_user.id

    from database_market import db
    config = db.config.find_one({"_id": "mode_urgence"})
    
    if config and config.get("actif", False) and uid != SUPER_ADMIN_ID:
        await query.message.edit_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return

    try:
        if data == "menu:cgu":
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
            
            texte_confirmation = f"🚨 **Mode Urgence modifié !**\nLe mode maintenance est maintenant : {'🔴 ACTIF' if nouveau_statut else '🟢 INACTIF'}."
            kb = [[InlineKeyboardButton("🔄 Rafraîchir le Panel", callback_data="menu:admin_panel")]]
            await query.message.edit_text(texte_confirmation, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

        elif data in ["menu:recherche", "menu:mes_annonces", "menu:historique", 
                      "menu:parrainage", "menu:defis", "menu:leaderboard", "menu:litige", 
                      "menu:alertes", "menu:blacklist"]:
            feature_name = data.replace("menu:", "").replace("_", " ").title()
            await query.message.edit_text(
                f"🚧 **Module [{feature_name}]**\n\nCe module est prêt à recevoir sa logique métier.",
                reply_markup=get_back_to_start_keyboard(),
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"Erreur callback {data}: {str(e)}")

# ---------------- ETAPES DU TUNNEL AVANCE ----------------

async def autre_jeu_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_jeu"] = update.message.text.strip()
    
    kb = [
        [InlineKeyboardButton("📱 Android", callback_data="plat:Android")],
        [InlineKeyboardButton("🍏 iOS (Apple)", callback_data="plat:iOS")],
        [InlineKeyboardButton("💻 PC", callback_data="plat:PC")],
        [InlineKeyboardButton("🎮 Console (PS/Xbox/Switch)", callback_data="plat:Console")],
        [InlineKeyboardButton("🌐 Multiplateforme (Partout)", callback_data="plat:Multi")]
    ]
    
    await update.message.reply_text(
        "🎮 **Sur quelle plateforme se trouve votre compte ?**\n\n"
        "Sélectionnez le support principal de votre compte :",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_PLATEFORME

async def afficher_choix_specificites(reply_func, ctx):
    choix = ctx.user_data.get("specs_choisies", [])
    specs_disponibles = [
        ("👥 Personnages", "spec:Persos"),
        ("👕 Skins", "spec:Skins"),
        ("⚔️ Armes", "spec:Armes"),
        ("🔮 Objets Rares", "spec:Objets")
    ]
    
    kb = []
    for nom, callback in specs_disponibles:
        id_spec = callback.replace("spec:", "")
        check = "☑️" if id_spec in choix else "⬜"
        kb.append([InlineKeyboardButton(f"{check} {nom}", callback_data=callback)])
        
    kb.append([InlineKeyboardButton("✅ Valider la sélection", callback_data="spec:valider")])
    
    await reply_func(
        "📊 **Étape 2 : Spécificités du compte**\n\n"
        "Qu'est-ce qu'on collectionne principalement dans votre jeu ?\n"
        "*(Cochez ou décochez les options, puis cliquez sur Valider)*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_SPECIFICITES

async def specificite_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    choix = ctx.user_data.get("specs_choisies", [])
    
    if data == "spec:valider":
        if not choix:
            await query.message.edit_text(
                "📸 **Étape 3 : Preuves en images**\n\n"
                "Veuillez envoyer entre **1 et 5 photos** de votre compte (captures d'écran).\n\n"
                "👉 *Une fois que vous avez fini d'envoyer vos photos, écrivez le mot* **'FIN'** *pour passer à la suite.*",
                parse_mode="Markdown"
            )
            return ATTENTE_PHOTOS
            
        ctx.user_data["index_spec_actuelle"] = 0
        premiere_spec = choix[0]
        
        noms_affichage = {"Persos": "Personnages", "Skins": "Skins", "Armes": "Armes", "Objets": "Objets Rares"}
        nom_propre = noms_affichage.get(premiere_spec, premiere_spec)
        
        await query.message.edit_text(
            f"🔢 **Configuration des quantités**\n\n"
            f"Combien de **{nom_propre}** possédez-vous exactement sur votre compte ?\n"
            f"*(Entrez un nombre entier uniquement)*",
            parse_mode="Markdown"
        )
        return ATTENTE_VALEURS_SPECS

    id_spec = data.replace("spec:", "")
    if id_spec in choix:
        choix.remove(id_spec)
    else:
        choix.append(id_spec)
        
    ctx.user_data["specs_choisies"] = choix
    return await afficher_choix_specificites(query.message.edit_reply_markup, ctx)

async def valeurs_specs_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texte = update.message.text.strip()
    
    if not texte.isdigit():
        await update.message.reply_text("❌ Veuillez entrer un nombre valide (uniquement des chiffres) :")
        return ATTENTE_VALEURS_SPECS
        
    choix = ctx.user_data.get("specs_choisies", [])
    index = ctx.user_data.get("index_spec_actuelle", 0)
    
    spec_actuelle = choix[index]
    ctx.user_data["specs_valeurs"][spec_actuelle] = int(texte)
    
    index += 1
    ctx.user_data["index_spec_actuelle"] = index
    
    if index < len(choix):
        prochaine_spec = choix[index]
        noms_affichage = {"Persos": "Personnages", "Skins": "Skins", "Armes": "Armes", "Objets": "Objets Rares"}
        nom_propre = noms_affichage.get(prochaine_spec, prochaine_spec)
        
        await update.message.reply_text(
            f"🔢 **Prochaine quantité**\n\n"
            f"Combien de **{nom_propre}** possédez-vous au total ?",
            parse_mode="Markdown"
        )
        return ATTENTE_VALEURS_SPECS
    else:
        await update.message.reply_text(
            "📸 **Étape 3 : Preuves en images**\n\n"
            "Veuillez envoyer entre **1 et 5 photos** de votre compte (captures d'écran).\n\n"
            "👉 *Une fois que vous avez fini d'envoyer vos photos, écrivez le mot* **'FIN'** *pour passer à la suite.*",
            parse_mode="Markdown"
        )
        return ATTENTE_PHOTOS

async def plateforme_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    plateforme = query.data.replace("plat:", "")
    ctx.user_data["vente_plateforme"] = plateforme
    
    return await afficher_choix_specificites(query.message.edit_text, ctx)

# ---------------- TRANSITIONS OBLIGATOIRES ----------------

async def photos_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        if "photos" not in ctx.user_data:
            ctx.user_data["photos"] = []
        if len(ctx.user_data["photos"]) < 5:
            ctx.user_data["photos"].append(photo_id)
            await update.message.reply_text(f"📸 Image reçue ({len(ctx.user_data['photos'])}/5). Envoyez-en d'autres ou écrivez 'FIN'.")
        else:
            await update.message.reply_text("⚠️ Limite de 5 photos atteinte. Écrivez 'FIN' pour continuer.")
        return ATTENTE_PHOTOS
        
    if update.message.text and update.message.text.upper() == "FIN":
        await update.message.reply_text("📝 **Veuillez entrer une description détaillée pour votre compte :**")
        return ATTENTE_DESCRIPTION
    return ATTENTE_PHOTOS

async def devise_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["vente_devise"] = query.data.replace("devise:", "")
    await query.message.edit_text("💰 Entrez le prix en chiffres uniquement :")
    return ATTENTE_PRIX

async def autre_devise_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_devise"] = update.message.text.strip().upper()
    await update.message.reply_text("💰 Entrez le prix en chiffres uniquement :")
    return ATTENTE_PRIX

async def crypto_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return ATTENTE_CONTACT

async def contact_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return ATTENTE_DISPO

async def dispo_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return CONFIRMATION

# ---------------- ENTRÉE PRINCIPALE DU PROGRAMME ----------------

def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    vente_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_vente, pattern="^menu:vendre$")],
        states={
            ATTENTE_AUTRE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_jeu_recu)],
            CHOIX_PLATEFORME: [CallbackQueryHandler(plateforme_choisie_handler, pattern="^plat:")],
            CHOIX_SPECIFICITES: [CallbackQueryHandler(specificite_choisie_handler, pattern="^spec:")],
            ATTENTE_VALEURS_SPECS: [MessageHandler(filters.TEXT & ~filters.COMMAND, valeurs_specs_recues)],
            ATTENTE_PHOTOS: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), photos_recues)],
            ATTENTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_recue)],
            CHOIX_DEVISE: [CallbackQueryHandler(devise_choisie_handler, pattern="^devise:")],
            ATTENTE_AUTRE_DEVISE: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_devise_recue)],
            ATTENTE_PRIX: [
                CallbackQueryHandler(prix_recu, pattern="^devise:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, prix_recu)
            ],
            CHOIX_PAIEMENT: [CallbackQueryHandler(paiement_choisi_handler, pattern="^pay:")],
            CHOIX_CRYPTO: [CallbackQueryHandler(crypto_choisie_handler, pattern="^crypto:")],
            ATTENTE_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_recu)],
            ATTENTE_DISPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, dispo_recue)],
            CONFIRMATION: [CallbackQueryHandler(confirmation_finale, pattern="^publier:")]
        },
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    # TRÈS IMPORTANT : Le tunnel doit être ajouté AVANT le button_handler général
    application.add_handler(vente_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🚀 Bot démarré avec le module Vente actif !")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
