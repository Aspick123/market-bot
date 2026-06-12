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
    verifier_abonnement_canal
)
from menus import get_main_menu_keyboard, get_back_to_start_keyboard
from moderation import soumettre_a_la_moderation, traitement_moderation
from profil import afficher_profil, gestion_candidature

# États réajustés pour le tunnel de vente
(
    CHOIX_CATEGORIE, ATTENTE_AUTRE_JEU, CHOIX_PLATEFORME, 
    ATTENTE_PHOTOS, ATTENTE_DESCRIPTION, ATTENTE_PRIX, CONFIRMATION
) = range(7)

ATTENS_RECHERCHE_JEU = 99
ATTENTE_MODIF_PRIX = 100
ATTENTE_MODIF_DESC = 101

app = Flask("")

@app.route("/")
def home():
    return "Le Marketplace Bot est en ligne !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAFxtyQig1cNZDvYF1PnTTbOlDOW1POlrx4")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
CANAL_VENTE_ID = os.environ.get("CANAL_VENTE_ID", "@comptedejeux")

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    
    # 🔐 FORCE JOIN STRICT
    est_abonne = await verifier_abonnement_canal(ctx, uid)
    if not est_abonne and uid != SUPER_ADMIN_ID:
        texte_bloque = (
            f"🚀 **Pour utiliser ce bot, vous devez rejoindre notre canal officiel !**\n\n"
            f"👉 Canal : {CANAL_VENTE_ID}\n\n"
            f"Une fois que vous avez rejoint, relancez la commande /start pour débloquer le Marketplace."
        )
        kb_rejoin = [[InlineKeyboardButton("📢 Rejoindre le Canal", url=f"https://t.me/{CANAL_VENTE_ID.replace('@','')}")]]
        
        if update.callback_query:
            await update.callback_query.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="Markdown")
        else:
            await update.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="Markdown")
        return ConversationHandler.END

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
        f"🤝 *Achetez et vendez vos comptes en toute sécurité.*\n\n"
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


# ==================== TUNNEL DE VENTE RESTRUCTURÉ ====================

async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.callback_query.answer("⚠️ Vous devez rejoindre et rester dans le canal pour vendre !", show_alert=True)
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    ctx.user_data["photos"] = []
    await query.message.edit_text("🎮 **Étape 1 : Quel est le jeu concerné ?**\n\nEnvoyez le nom exact du jeu vidéo.", parse_mode="Markdown")
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
    await query.message.edit_text("📸 **Étape 2 : Preuves en images**\n\nEnvoyez de 1 à 5 captures d'écran, puis écrivez le mot **'FIN'**.", parse_mode="Markdown")
    return ATTENTE_PHOTOS

async def photos_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        if len(ctx.user_data["photos"]) < 5:
            ctx.user_data["photos"].append(photo_id)
            await update.message.reply_text(f"📸 Image reçue ({len(ctx.user_data['photos'])}/5). Continuez ou écrivez 'FIN'.")
        else:
            await update.message.reply_text("⚠️ Limite de 5 photos atteinte. Écrivez 'FIN'.")
        return ATTENTE_PHOTOS
        
    if update.message.text and update.message.text.upper() == "FIN":
        await update.message.reply_text("📝 **Étape 3 : Veuillez entrer une description détaillée pour votre compte :**")
        return ATTENTE_DESCRIPTION
    return ATTENTE_PHOTOS

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    kb = [
        [InlineKeyboardButton("💵 FCFA (XOF)", callback_data="devise:FCFA")], 
        [InlineKeyboardButton("🪙 USDT (TRC20)", callback_data="devise:USDT")], 
        [InlineKeyboardButton("💳 PayPal / Euro", callback_data="devise:EUR")]
    ]
    await update.message.reply_text("💱 **Étape 4 : Sélectionnez la devise de vente :**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ATTENTE_PRIX

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and query.data.startswith("devise:"):
        await query.answer()
        ctx.user_data["vente_devise"] = query.data.split(":")[1]
        await query.message.edit_text(f"💰 **Fixer le montant en ({ctx.user_data['vente_devise']})**\n\nEntrez le prix (chiffres uniquement) :", parse_mode="Markdown")
        return ATTENTE_PRIX
        
    if update.message:
        texte_prix = update.message.text.strip()
        if not texte_prix.isdigit():
            await update.message.reply_text("❌ Veuillez entrer des chiffres uniquement :")
            return ATTENTE_PRIX
        ctx.user_data["vente_prix"] = int(texte_prix)
        
        # TRANSITION DIRECTE : Génération immédiate du Récapitulatif final (Plus d'étape 4 intermédiaire)
        recap = (
            f"🧐 **VÉRIFICATION DE VOTRE ANNONCE**\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"📦 **Jeu :** `{ctx.user_data.get('vente_jeu')}`\n"
            f"💻 **Plateforme :** `{ctx.user_data.get('vente_plateforme')}`\n"
            f"💰 **Prix demandé :** `{ctx.user_data.get('vente_prix')} {ctx.user_data.get('vente_devise')}`\n"
            f"📝 **Description :**\n{ctx.user_data.get('vente_description')}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"Souhaitez-vous soumettre cette annonce à l'équipe de modération ?"
        )
        kb = [
            [InlineKeyboardButton("✅ Valider et Soumettre", callback_data="publier:oui")], 
            [InlineKeyboardButton("❌ Tout annuler", callback_data="publier:non")]
        ]
        await update.message.reply_text(recap, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return CONFIRMATION

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "publier:oui":
        await soumettre_a_la_moderation(update, ctx)
    else:
        await query.message.edit_text("❌ Création de l'annonce annulée.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END


# ==================== RECHERCHE & AUTRES FONCTIONS ====================

async def debut_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.callback_query.answer("⚠️ Action refusée. Rejoignez le canal.", show_alert=True)
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🔍 **Moteur de Recherche**\n\nEntrez le nom du jeu recherché :")
    return ATTENS_RECHERCHE_JEU

async def executer_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jeu_recherche = update.message.text.strip()
    annonce = db.annonces.find_one({"categorie": {"$regex": f"^{jeu_recherche}$", "$options": "i"}, "statut": "valide"})
    if list(db.annonces.find({"categorie": {"$regex": f"^{jeu_recherche}$", "$options": "i"}, "statut": "valide"})):
        vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
        username = vendeur.get("username", "Inconnu") if vendeur else "Inconnu"
        txt = f"🛒 **OFFRE TROUVÉE**\n🎮 Jeu : `{annonce['categorie']}`\n💰 Prix : `{annonce['prix']} {annonce['devise']}`\n👤 Vendeur: @{username}"
        await update.message.reply_text(txt, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text("🔴 Aucune annonce disponible pour ce jeu.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    # 🔒 SÉCURITÉ GLOBALE DES BOUTONS
    if not await verifier_abonnement_canal(ctx, uid) and uid != SUPER_ADMIN_ID:
        await query.answer("🚨 Action bloquée ! Vous devez rejoindre notre canal pour utiliser les fonctionnalités.", show_alert=True)
        return

    if data == "menu:retour_start":
        await query.answer()
        await start_command(update, ctx)
        return

    if data == "menu:liste_offres":
        await query.answer()
        annonces_valides = list(db.annonces.find({"statut": "valide"}))
        if not annonces_valides:
            await query.message.edit_text("📦 Aucune offre disponible.", reply_markup=get_back_to_start_keyboard())
            return
        kb = [[InlineKeyboardButton(f"🎮 {a['categorie']} — {a['prix']} {a['devise']}", callback_data=f"voir_offre:{a['_id']}")] for a in annonces_valides]
        kb.append([InlineKeyboardButton("🔙 Retour Menu", callback_data="menu:retour_start")])
        await query.message.edit_text("📋 **OFFRES EN LIGNE**", reply_markup=InlineKeyboardMarkup(kb))
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
