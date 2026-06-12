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
from moderation import soumettre_a_la_moderation, traitement_moderation
from profil import afficher_profil, gestion_candidature

# États du tunnel de vente (Sans l'étape redondante des modes de paiement)
(
    CHOIX_CATEGORIE, ATTENTE_AUTRE_JEU, CHOIX_PLATEFORME, 
    ATTENTE_PHOTOS, ATTENTE_DESCRIPTION, ATTENTE_PRIX, CONFIRMATION
) = range(7)

ATTENS_RECHERCHE_JEU = 99

app = Flask("")

@app.route("/")
def home():
    return "Le Marketplace Bot est entièrement corrigé et en ligne !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Récupération sécurisée du token (via Render ou valeur par défaut)
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAEyKszXM8y_RNVz3XqW5LfV6UlKQtO3jzQ")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    
    # 🔐 VÉRIFICATION STRICTE ET TRADUITE DU FORCE JOIN
    est_abonne = await verifier_abonnement_canal(ctx, uid)
    if not est_abonne and uid != SUPER_ADMIN_ID:
        nom_canal_propre = CANAL_VENTE_ID.replace("@", "")
        texte_bloque = (
            f"🚀 **Bienvenue sur le Marketplace !**\n\n"
            f"Pour pouvoir utiliser ce bot et voir les annonces, vous devez obligatoirement rejoindre notre canal officiel.\n\n"
            f"👉 **Canal :** {CANAL_VENTE_ID}\n\n"
            f"Une fois installé dans le canal, revenez ici et cliquez sur /start pour débloquer l'accès."
        )
        kb_rejoin = [[InlineKeyboardButton("📢 Rejoindre le Canal officiel", url=f"https://t.me/{nom_canal_propre}")]]
        
        if update.callback_query:
            await update.callback_query.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="Markdown")
        else:
            await update.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="Markdown")
        return ConversationHandler.END

    if is_mode_urgence() and uid != SUPER_ADMIN_ID:
        await update.effective_message.reply_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return ConversationHandler.END
        
    if is_flooded(uid):
        await update.effective_message.reply_text("⏳ Trop de requêtes simultanées. Veuillez patienter.")
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
        f"🤝 *Achetez et vendez vos comptes de jeux en toute sécurité.*\n\n"
        f"👇 **Sélectionnez une option ci-dessous :**"
    )
    
    reply_markup = get_main_menu_keyboard(uid, SUPER_ADMIN_ID)
    boutons_modifies = []
    for ligne in reply_markup.inline_keyboard:
        boutons_modifies.append(ligne)
        for bouton in ligne:
            if "recherche" in bouton.callback_data:
                boutons_modifies.append([InlineKeyboardButton("📋 Parcourir toutes les offres", callback_data="menu:liste_offres")])
                break

    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=InlineKeyboardMarkup(boutons_modifies), parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(boutons_modifies), parse_mode="Markdown")
    return ConversationHandler.END


# ==================== TUNNEL DE VENTE NETTOYÉ ====================

async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.callback_query.answer("⚠️ Vous devez avoir rejoint le canal pour déposer une annonce !", show_alert=True)
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    ctx.user_data["photos"] = []
    await query.message.edit_text("🎮 **Étape 1 : Quel est le jeu vidéo concerné ?**\n\nEnvoyez le nom exact du jeu (ex: Genshin Impact, EFD...).", parse_mode="Markdown")
    return ATTENTE_AUTRE_JEU

async def autre_jeu_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_jeu"] = update.message.text.strip()
    kb = [
        [InlineKeyboardButton("📱 Android", callback_data="plat:Android")], [InlineKeyboardButton("🍏 iOS (Apple)", callback_data="plat:iOS")],
        [InlineKeyboardButton("💻 PC", callback_data="plat:PC")], [InlineKeyboardButton("🎮 Console (PS/Xbox)", callback_data="plat:Console")],
        [InlineKeyboardButton("🌐 Multiplateforme", callback_data="plat:Multi")]
    ]
    await update.message.reply_text("🎮 **Sur quelle plateforme se trouve votre compte ?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return CHOIX_PLATEFORME

async def plateforme_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["vente_plateforme"] = query.data.replace("plat:", "")
    await query.message.edit_text("📸 **Étape 2 : Preuves visuelles**\n\nEnvoyez entre 1 et 5 captures d'écran de votre compte, puis tapez le mot **'FIN'**.", parse_mode="Markdown")
    return ATTENTE_PHOTOS

async def photos_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        if len(ctx.user_data["photos"]) < 5:
            ctx.user_data["photos"].append(photo_id)
            await update.message.reply_text(f"📸 Image enregistrée ({len(ctx.user_data['photos'])}/5). Ajoutez-en une autre ou écrivez 'FIN'.")
        else:
            await update.message.reply_text("⚠️ Limite maximale de 5 photos atteinte. Veuillez écrire 'FIN'.")
        return ATTENTE_PHOTOS
        
    if update.message.text and update.message.text.upper() == "FIN":
        if not ctx.user_data["photos"]:
            await update.message.reply_text("❌ Vous devez envoyer au moins une photo de preuve avant de taper FIN.")
            return ATTENTE_PHOTOS
        await update.message.reply_text("📝 **Étape 3 : Veuillez entrer la description détaillée de votre compte :**")
        return ATTENTE_DESCRIPTION
    return ATTENTE_PHOTOS

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    kb = [
        [InlineKeyboardButton("💵 FCFA", callback_data="devise:FCFA")], 
        [InlineKeyboardButton("🪙 USDT", callback_data="devise:USDT")], 
        [InlineKeyboardButton("💳 EUR / PayPal", callback_data="devise:EUR")]
    ]
    await update.message.reply_text("💱 **Étape 4 : Sélectionnez la devise de l'annonce :**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ATTENTE_PRIX

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and query.data.startswith("devise:"):
        await query.answer()
        ctx.user_data["vente_devise"] = query.data.split(":")[1]
        await query.message.edit_text(f"💰 **Fixer le montant en {ctx.user_data['vente_devise']}**\n\nEntrez uniquement le prix en chiffres :", parse_mode="Markdown")
        return ATTENTE_PRIX
        
    if update.message:
        texte_prix = update.message.text.strip()
        if not text_prix.isdigit():
            await update.message.reply_text("❌ Format invalide. Entrez un nombre entier (uniquement des chiffres) :")
            return ATTENTE_PRIX
        ctx.user_data["vente_prix"] = int(texte_prix)
        
        # SANS ÉTAPE INTERMÉDIAIRE : Génération directe du récapitulatif de validation
        recap = (
            f"🧐 **RÉCAPITULATIF DE VOTRE OFFRE**\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"📦 **Jeu :** `{ctx.user_data.get('vente_jeu')}`\n"
            f"💻 **Plateforme :** `{ctx.user_data.get('vente_plateforme')}`\n"
            f"💰 **Prix fixé :** `{ctx.user_data.get('vente_prix')} {ctx.user_data.get('vente_devise')}`\n"
            f"📝 **Description :**\n{ctx.user_data.get('vente_description')}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"Souhaitez-vous envoyer cette annonce à la modération ?"
        )
        kb = [
            [InlineKeyboardButton("✅ Valider et Soumettre", callback_data="publier:oui")], 
            [InlineKeyboardButton("❌ Annuler l'annonce", callback_data="publier:non")]
        ]
        await update.message.reply_text(recap, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return CONFIRMATION

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "publier:oui":
        await soumettre_a_la_moderation(update, ctx)
    else:
        await query.message.edit_text("❌ Création de l'annonce annulée avec succès.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END


# ==================== MOTEUR DE RECHERCHE ====================

async def debut_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.callback_query.answer("⚠️ Action refusée. Veuillez d'abord rejoindre le canal.", show_alert=True)
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🔍 **Moteur de Recherche**\n\nEntrez le nom du jeu que vous recherchez :")
    return ATTENS_RECHERCHE_JEU

async def executer_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jeu_recherche = update.message.text.strip()
    annonces_trouvees = list(db.annonces.find({"categorie": {"$regex": f"^{jeu_recherche}$", "$options": "i"}, "statut": "valide"}))
    
    if annonces_trouvees:
        annonce = annonces_trouvees[0]
        vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
        username = vendeur.get("username", "Inconnu") if vendeur else "Inconnu"
        txt = f"🛒 **OFFRE TROUVÉE**\n🎮 Jeu : `{annonce['categorie']}`\n💰 Prix : `{annonce['prix']} {annonce['devise']}`\n👤 Vendeur: @{username}"
        await update.message.reply_text(txt, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text("🔴 Désolé, aucune annonce active ne correspond à ce jeu pour le moment.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    if not await verifier_abonnement_canal(ctx, uid) and uid != SUPER_ADMIN_ID:
        await query.answer("🚨 Veuillez d'abord rejoindre le canal officiel pour débloquer les boutons.", show_alert=True)
        return

    if data == "menu:retour_start":
        await query.answer()
        await start_command(update, ctx)
        return

    if data == "menu:liste_offres":
        await query.answer()
        annonces_valides = list(db.annonces.find({"statut": "valide"}))
        if not annonces_valides:
            await query.message.edit_text("📦 Aucune offre n'est disponible pour le moment.", reply_markup=get_back_to_start_keyboard())
            return
        kb = [[InlineKeyboardButton(f"🎮 {a['categorie']} — {a['prix']} {a['devise']}", callback_data=f"voir_offre:{a['_id']}")] for a in annonces_valides]
        kb.append([InlineKeyboardButton("🔙 Retour Menu", callback_data="menu:retour_start")])
        await query.message.edit_text("📋 **OFFRES ACTUELLEMENT EN LIGNE**", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("mod:"): await traitement_moderation(update, ctx); return
    if data.startswith("staff:"): await gestion_candidature(update, ctx); return

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
        entry_points=[CallbackQueryHandler(debut_recherche, pattern=".*recherche.*")],
        states={ATTENS_RECHERCHE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, executer_recherche)]},
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")]
    )
    
    application.add_handler(vente_conv)
    application.add_handler(recherche_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.run_polling()

if __name__ == "__main__":
    main()
