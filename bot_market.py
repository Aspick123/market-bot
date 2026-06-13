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
    is_mode_urgence,
    verifier_abonnement_canal,
    CANAL_VENTE_ID
)
from menus import get_main_menu_keyboard, get_back_to_start_keyboard

# États du tunnel de vente
(
    CHOIX_CATEGORIE, ATTENTE_AUTRE_JEU, CHOIX_PLATEFORME, 
    ATTENTE_PHOTOS, ATTENTE_DESCRIPTION, ATTENTE_PRIX, CONFIRMATION
) = range(7)

ATTENS_RECHERCHE_JEU = 99

app = Flask("")

@app.route("/")
def home():
    return "Marketplace opérationnel à 100% !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAEyKszXM8y_RNVz3XqW5LfV6UlKQtO3jzQ")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
MODERATION_CHAT_ID = os.environ.get("MODERATION_CHAT_ID", str(SUPER_ADMIN_ID))

# ==================== FONCTION /START SÉCURISÉE (FORMAT HTML) ====================

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id
        user = update.effective_user
        
        logger.info(f"🚀 Commande /start déclenchée par l'utilisateur : {uid}")
        
        # 1. Vérification de l'abonnement au canal
        est_abonne = await verifier_abonnement_canal(ctx, uid)
        if not est_abonne and uid != SUPER_ADMIN_ID:
            nom_canal_propre = CANAL_VENTE_ID.replace("@", "")
            texte_bloque = (
                f"🚀 <b>Bienvenue sur le Marketplace !</b>\n\n"
                f"Pour pouvoir utiliser ce bot et voir les annonces, vous devez obligatoirement rejoindre notre canal officiel.\n\n"
                f"👉 <b>Canal :</b> {CANAL_VENTE_ID}\n\n"
                f"Une fois installé dans le canal, revenez ici et cliquez sur /start pour débloquer l'accès."
            )
            kb_rejoin = [[InlineKeyboardButton("📢 Rejoindre le Canal officiel", url=f"https://t.me/{nom_canal_propre}")]]
            if update.callback_query:
                await update.callback_query.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="HTML")
            else:
                await update.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="HTML")
            return ConversationHandler.END

        # 2. Vérification des restrictions globales
        if is_mode_urgence() and uid != SUPER_ADMIN_ID:
            await update.effective_message.reply_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
            return ConversationHandler.END
            
        if is_flooded(uid):
            await update.effective_message.reply_text("⏳ Trop de requêtes simultanées. Veuillez patienter.")
            return ConversationHandler.END

        # 3. Synchronisation du profil en base de données
        user_data = get_user(uid)
        if not user_data.get("username") or user_data["username"] != user.username:
            user_data["username"] = user.username or user.first_name
            save_user(uid, user_data)

        role_label = get_role_label(uid, SUPER_ADMIN_ID)
        
        # Utilisation de balises HTML (⚡ Évite les plantages liés aux pseudos avec des symboles)
        welcome_text = (
            f"🎮 <b>Bienvenue sur le Marketplace, {user.first_name} !</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎖️ <b>Rang :</b> {role_label}\n\n"
            f"🤝 <i>Achetez et vendez vos comptes de jeux en toute sécurité.</i>\n\n"
            f"👇 <b>Sélectionnez une option ci-dessous :</b>"
        )
        
        reply_markup = get_main_menu_keyboard(uid, SUPER_ADMIN_ID)
        
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")
            except Exception:
                await update.callback_query.message.delete()
                await update.callback_query.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"❌ Erreur critique dans start_command : {e}", exc_info=True)


# ==================== LOGIQUE DE MODÉRATION SÉCURISÉE ====================

async def soumettre_a_la_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    annonce_data = {
        "vendeur_id": uid,
        "categorie": ctx.user_data.get("vente_jeu"),
        "plateforme": ctx.user_data.get("vente_plateforme"),
        "photos": ctx.user_data.get("photos", []),
        "description": ctx.user_data.get("vente_description"),
        "prix": ctx.user_data.get("vente_prix"),
        "devise": ctx.user_data.get("vente_devise"),
        "statut": "en_attente",
        "date_creation": time.time()
    }
    
    res = db.annonces.insert_one(annonce_data)
    annonce_id = str(res.inserted_id)
    
    txt_mod = (
        f"🚨 **NOUVELLE ANNONCE À MODÉRER**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🆔 **ID Annonce :** `{annonce_id}`\n"
        f"🎮 **Jeu :** `{annonce_data['categorie']}`\n"
        f"💻 **Plateforme :** `{annonce_data['plateforme']}`\n"
        f"💰 **Prix demandé :** `{annonce_data['prix']} {annonce_data['devise']}`\n"
        f"👤 **ID Vendeur :** `{uid}`\n"
        f"📝 **Description :**\n{annonce_data['description']}"
    )
    kb_mod = [
        [
            InlineKeyboardButton("✅ Approuver", callback_data=f"mod:approuver:{annonce_id}"),
            InlineKeyboardButton("❌ Rejeter", callback_data=f"mod:rejeter:{annonce_id}")
        ]
    ]
    
    if list(annonce_data["photos"]):
        await ctx.bot.send_photo(chat_id=MODERATION_CHAT_ID, photo=annonce_data["photos"][0], caption=txt_mod, reply_markup=InlineKeyboardMarkup(kb_mod), parse_mode="Markdown")
    else:
        await ctx.bot.send_message(chat_id=MODERATION_CHAT_ID, text=txt_mod, reply_markup=InlineKeyboardMarkup(kb_mod), parse_mode="Markdown")

    await update.callback_query.message.edit_text(
        "✅ **Votre offre a été envoyée avec succès à l'équipe !**\n\nElle sera analysée sous peu.",
        reply_markup=get_back_to_start_keyboard(),
        parse_mode="Markdown"
    )

async def traitement_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    
    _, action, annonce_id = data.split(":")
    annonce = db.annonces.find_one({"_id": ObjectId(annonce_id)})
    
    if not annonce:
        txt_err = "❌ Erreur : Cette annonce n'existe plus."
        if query.message.photo:
            await query.message.edit_caption(caption=txt_err)
        else:
            await query.message.edit_text(txt_err)
        return
        
    vendeur_id = annonce["vendeur_id"]
    
    if action == "approuver":
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"statut": "valide"}})
        db.users.update_one({"_id": vendeur_id}, {"$inc": {"annonces_publiees": 1}})
        
        txt_ok = f"🟢 **Annonce `{annonce_id}` approuvée et publiée !**"
        if query.message.photo:
            await query.message.edit_caption(caption=txt_ok, parse_mode="Markdown")
        else:
            await query.message.edit_text(txt_ok, parse_mode="Markdown")
        
        try:
            txt_canal = (
                f"📢 **COMPTE DISPONIBLE SUR LE MARKETPLACE**\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"🎮 **Jeu :** {annonce['categorie']}\n"
                f"💻 **Plateforme :** {annonce['plateforme']}\n"
                f"💰 **Prix :** {annonce['prix']} {annonce['devise']}\n"
                f"📝 **Description :**\n{annonce['description']}\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"🤖 *Pour acheter ce compte, utilisez notre bot officiel.*"
            )
            if list(annonce.get("photos", [])):
                await ctx.bot.send_photo(chat_id=CANAL_VENTE_ID, photo=annonce["photos"][0], caption=txt_canal, parse_mode="Markdown")
            else:
                await ctx.bot.send_message(chat_id=CANAL_VENTE_ID, text=txt_canal, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Échec publication canal : {e}")
            
        try:
            await ctx.bot.send_message(chat_id=vendeur_id, text="🎉 **Félicitations !** Votre annonce a été validée et est maintenant en ligne sur le canal officiel.")
        except Exception: pass

    elif action == "rejeter":
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"statut": "rejete"}})
        txt_refuse = f"🔴 **Annonce `{annonce_id}` refusée.**"
        if query.message.photo:
            await query.message.edit_caption(caption=txt_refuse, parse_mode="Markdown")
        else:
            await query.message.edit_text(txt_refuse, parse_mode="Markdown")
            
        try:
            await ctx.bot.send_message(chat_id=vendeur_id, text="❌ Votre annonce a été refusée par l'équipe car elle ne respecte pas nos règles de publication.")
        except Exception: pass


# ==================== TUNNEL DE VENTE ====================

async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.callback_query.answer("⚠️ Rejoignez d'abord le canal !", show_alert=True)
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    ctx.user_data["photos"] = []
    await query.message.edit_text("🎮 **Étape 1 : Nom du jeu vidéo ?**\n\nEnvoyez le nom complet par écrit (ex: Genshin Impact) :", parse_mode="Markdown")
    return ATTENTE_AUTRE_JEU

async def autre_jeu_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_jeu"] = update.message.text.strip()
    kb = [
        [InlineKeyboardButton("📱 Android", callback_data="plat:Android")], [InlineKeyboardButton("🍏 iOS", callback_data="plat:iOS")],
        [InlineKeyboardButton("💻 PC", callback_data="plat:PC")], [InlineKeyboardButton("🎮 Console", callback_data="plat:Console")]
    ]
    await update.message.reply_text("🎮 **Sélectionnez la plateforme :**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return CHOIX_PLATEFORME

async def plateforme_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["vente_plateforme"] = query.data.replace("plat:", "")
    await query.message.edit_text("📸 **Étape 2 : Captures d'écran**\n\nEnvoyez de 1 à 5 images de preuves, puis tapez le mot **'FIN'**.", parse_mode="Markdown")
    return ATTENTE_PHOTOS

async def photos_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        if len(ctx.user_data["photos"]) < 5:
            ctx.user_data["photos"].append(photo_id)
            await update.message.reply_text(f"📸 Screenshot enregistré ({len(ctx.user_data['photos'])}/5). Autre image ou écrivez 'FIN'.")
        else:
            await update.message.reply_text("⚠️ Maximum atteint. Écrivez 'FIN'.")
        return ATTENTE_PHOTOS
        
    if update.message.text and update.message.text.upper() == "FIN":
        if not ctx.user_data["photos"]:
            await update.message.reply_text("❌ Une image minimum requise.")
            return ATTENTE_PHOTOS
        await update.message.reply_text("📝 **Étape 3 : Saisissez la description de votre compte :**")
        return ATTENTE_DESCRIPTION
    return ATTENTE_PHOTOS

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    kb = [
        [InlineKeyboardButton("💵 FCFA", callback_data="devise:FCFA")], 
        [InlineKeyboardButton("🪙 USDT", callback_data="devise:USDT")], 
        [InlineKeyboardButton("💳 EUR / PayPal", callback_data="devise:EUR")]
    ]
    await update.message.reply_text("💱 **Étape 4 : Devise ?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ATTENTE_PRIX

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and query.data.startswith("devise:"):
        await query.answer()
        ctx.user_data["vente_devise"] = query.data.split(":")[1]
        await query.message.edit_text(f"💰 **Prix en {ctx.user_data['vente_devise']} ?** (Chiffres uniquement) :", parse_mode="Markdown")
        return ATTENTE_PRIX
        
    if update.message:
        texte_prix = update.message.text.strip()
        if not texte_prix.isdigit():
            await update.message.reply_text("❌ Format incorrect. Saisissez uniquement des chiffres :")
            return ATTENTE_PRIX
        ctx.user_data["vente_prix"] = int(texte_prix)
        
        recap = (
            f"🧐 **RÉCAPITULATIF DE VOTRE OFFRE**\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"📦 **Jeu :** `{ctx.user_data.get('vente_jeu')}`\n"
            f"💻 **Plateforme :** `{ctx.user_data.get('vente_plateforme')}`\n"
            f"💰 **Prix :** `{ctx.user_data.get('vente_prix')} {ctx.user_data.get('vente_devise')}`\n"
            f"📝 **Description :**\n{ctx.user_data.get('vente_description')}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"Souhaitez-vous envoyer cette annonce à la modération ?"
        )
        kb = [[InlineKeyboardButton("✅ Confirmer et Envoyer", callback_data="publier:oui")], [InlineKeyboardButton("❌ Annuler", callback_data="publier:non")]]
        await update.message.reply_text(recap, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return CONFIRMATION

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "publier:oui":
        await soumettre_a_la_moderation(update, ctx)
    else:
        await query.message.edit_text("❌ Annulée.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END


# ==================== GESTION DES BOUTONS DU MENU ====================

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    if data == "menu:retour_start":
        await query.answer()
        await start_command(update, ctx)
        return

    if data == "menu:liste_offres":
        await query.answer()
        annonces = list(db.annonces.find({"statut": "valide"}))
        if not annonces:
            await query.message.edit_text("📦 Aucune offre disponible dans la liste de vente actuellement.", reply_markup=get_back_to_start_keyboard())
            return
        kb = [[InlineKeyboardButton(f"🎮 {a['categorie']} — {a['prix']} {a['devise']}", callback_data=f"voir_offre:{a['_id']}")] for a in annonces]
        kb.append([InlineKeyboardButton("🔙 Retour Menu", callback_data="menu:retour_start")])
        await query.message.edit_text("🛍️ **LISTE DE VENTE ACTUELLE**", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("voir_offre:"):
        await query.answer()
        annonce_id = data.split(":")[1]
        annonce = db.annonces.find_one({"_id": ObjectId(annonce_id)})
        if not annonce:
            await query.message.edit_text("❌ Offre introuvable.", reply_markup=get_back_to_start_keyboard())
            return
            
        vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
        username = vendeur.get("username", "Inconnu") if vendeur else "Inconnu"
        
        txt_details = (
            f"🎮 **FICHE TECHNIQUE PRODUIT**\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"📦 **Jeu :** `{annonce.get('categorie')}`\n"
            f"💻 **Plateforme :** `{annonce.get('plateforme')}`\n"
            f"💰 **Prix :** `{annonce.get('prix')} {annonce.get('devise')}`\n"
            f"📝 **Description :**\n{annonce.get('description')}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Vendeur :** @{username}"
        )
        
        if list(annonce.get("photos", [])):
            await ctx.bot.send_photo(chat_id=query.message.chat_id, photo=annonce["photos"][0], caption=txt_details, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        else:
            await query.message.edit_text(txt_details, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        return

    if data == "menu:profil":
        await query.answer()
        user_data = get_user(uid)
        role = get_role_label(uid, SUPER_ADMIN_ID)
        txt = (
            f"👤 **PROFIL UTILISATEUR**\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎖️ **Rang :** {role}\n"
            f"📊 **Score Fiabilité :** `{user_data.get('score_fiabilite', 100)}/100` ⭐\n"
            f"📦 **Total ventes validées :** `{user_data.get('annonces_publiees', 0)}`"
        )
        await query.message.edit_text(txt, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        return

    if data == "menu:mes_annonces":
        await query.answer()
        mes_offres = list(db.annonces.find({"vendeur_id": uid}))
        if not mes_offres:
            await query.message.edit_text("📂 Vous n'avez aucune annonce enregistrée.", reply_markup=get_back_to_start_keyboard())
            return
        txt = "🗂️ **VOS ANNONCES DEPOSÉES :**\n\n"
        for idx, o in enumerate(mes_offres, 1):
            txt += f"{idx}. 🎮 `{o['categorie']}` — {o['prix']} {o['devise']} | [*{o['statut']}*]\n"
        await query.message.edit_text(txt, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        return

    if data == "menu:regles":
        await query.answer()
        regles = (
            "📜 **CHARTE DE SÉCURITÉ**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "• Les arnaques entraînent un bannissement définitif.\n"
            "• Ne donnez jamais vos identifiants avant d'avoir reçu le paiement complet."
        )
        await query.message.edit_text(regles, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        return

    if data == "menu:classement":
        await query.answer()
        top_users = list(db.users.find({"banni": False}).sort("score_fiabilite", -1).limit(5))
        txt = "🏆 **TOP 5 VENDEURS FIABLES**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        for i, u in enumerate(top_users, 1):
            name = u.get("username") or f"User_{u['_id']}"
            txt += f"{i}. @{name} — `{u.get('score_fiabilite', 100)}/100` ⭐\n"
        await query.message.edit_text(txt, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        return

    if data.startswith("mod:"):
        await traitement_moderation(update, ctx)
        return


# ==================== MOTEUR DE RECHERCHE ====================

async def debut_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🔍 **Recherche de compte**\n\nEntrez le nom complet du jeu recherché :")
    return ATTENS_RECHERCHE_JEU

async def executer_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jeu = update.message.text.strip()
    annonces = list(db.annonces.find({"categorie": {"$regex": f"^{jeu}$", "$options": "i"}, "statut": "valide"}))
    if annonces:
        a = annonces[0]
        txt = f"🛒 **OFFRE DISPONIBLE**\n🎮 Jeu : `{a['categorie']}`\n💰 Prix : `{a['prix']} {a['devise']}`"
        await update.message.reply_text(txt, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text("🔴 Aucun compte en vente pour ce jeu actuellement.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END


# ==================== GESTIONNAIRE D'ERREURS GLOBAL ====================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Intercepte et logue toutes les exceptions non gérées pour éviter le silence radio du bot."""
    logger.error(msg="⚠️ Une exception non gérée a été interceptée :", exc_info=context.error)


def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    vente_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_vente, pattern="^menu:vendre$")],
        states={
            ATTENTE_AUTRE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_jeu_recu)],
            CHOIX_PLATEFORME: [CallbackQueryHandler(plateforme_choisie_handler, pattern="^plat:")],
            ATTENTE_PHOTOS: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), photos_recues)],
            ATTENTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_recue)],
            ATTENTE_PRIX: [CallbackQueryHandler(prix_recu, pattern="^devise:"), MessageHandler(filters.TEXT & ~filters.COMMAND, prix_recu)],
            CONFIRMATION: [CallbackQueryHandler(confirmation_finale, pattern="^publier:")]
        },
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    recherche_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_recherche, pattern="^menu:recherche$")],
        states={ATTENS_RECHERCHE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, executer_recherche)]},
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")]
    )
    
    application.add_handler(vente_conv)
    application.add_handler(recherche_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Intégration du gestionnaire d'erreurs global
    application.add_error_handler(error_handler)
    
    application.run_polling()

if __name__ == "__main__":
    main()
