from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database_market import db
from menus import get_back_to_start_keyboard

# État pour la conversation de recherche
ATTENTE_RECHERCHE_JEU = 99  # Un numéro unique pour ne pas croiser le tunnel de vente

async def debut_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.message.edit_text(
        "🔍 **Moteur de Recherche Flash**\n\n"
        "Entrez le nom exact du jeu que vous recherchez (ex: *Genshin Impact, eFootball...*) :",
        parse_mode="Markdown"
    )
    return ATTENTE_RECHERCHE_JEU

async def executer_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jeu_recherche = update.message.text.strip()
    uid = update.effective_user.id
    
    # On cherche une annonce validée pour ce jeu dans MongoDB
    annonce = db.annonces.find_one({
        "categorie": {"$regex": f"^{jeu_recherche}$", "$options": "i"},
        "statut": "valide"
    })
    
    if annonce:
        # Récupération du pseudo ou contact du vendeur
        vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
        username_vendeur = vendeur.get("username", "Inconnu") if vendeur else "Inconnu"
        
        paiements = ", ".join(annonce.get("paiements", []))
        
        reponse_oui = (
            "🟢 **OUI ! Une annonce est disponible !**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎮 **Jeu :** `{annonce['categorie']}`\n"
            f"💻 **Plateforme :** `{annonce.get('plateforme', 'Non spécifiée')}`\n"
            f"💰 **Prix :** `{annonce['prix']} {annonce['devise']}`\n"
            f"💳 **Paiements :** `{paiements}`\n"
            f"📝 **Description :**\n{annonce['description']}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Contact Vendeur :** @{username_vendeur}\n\n"
            "⚠️ *Pour votre sécurité, utilisez toujours notre système d'arbitrage lors du paiement.*"
        )
        await update.message.reply_text(reponse_oui, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
    else:
        reponse_non = (
            "🔴 **NON. Aucune annonce disponible.**\n\n"
            f"Désolé, il n'y a actuellement aucun compte vérifié et disponible pour le jeu *{jeu_recherche}*."
        )
        await update.message.reply_text(reponse_non, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
        
    from telegram.ext import ConversationHandler
    return ConversationHandler.END
