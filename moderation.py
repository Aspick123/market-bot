import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from database_market import db, create_annonce

SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

async def soumettre_a_la_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    
    # 1. Récupération des données du tunnel de vente
    cat = ctx.user_data.get("vente_jeu", "Inconnu")
    desc = ctx.user_data.get("vente_description", "Aucune description")
    prix = ctx.user_data.get("vente_prix", 0)
    devise = ctx.user_data.get("vente_devise", "XOF")
    plat = ctx.user_data.get("vente_plateforme", "Non spécifiée")
    paiements = ", ".join(ctx.user_data.get("vente_paiements", []))
    
    # 2. On crée l'annonce dans MongoDB avec le statut "en_attente"
    # Note : Ajuste ta fonction create_annonce si elle ne gère pas encore le statut ou la plateforme
    annonce_id = db.annonces.insert_one({
        "vendeur_id": uid,
        "categorie": cat,
        "plateforme": plat,
        "description": desc,
        "prix": prix,
        "devise": devise,
        "paiements": ctx.user_data.get("vente_paiements", []),
        "statut": "en_attente"
    }).inserted_id

    # 3. Notification à l'utilisateur
    await query.message.edit_text(
        "⏳ **Annonce soumise avec succès !**\n\n"
        "Votre annonce a été envoyée à l'équipe de modération. "
        "Vous recevrez une notification dès qu'un Gérant l'aura validée.",
        parse_mode="Markdown"
    )

    # 4. Envoi du ticket de modération à l'admin (Fondateur)
    ticket_text = (
        "🔔 **NOUVELLE ANNONCE À MODÉRER**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👤 **Vendeur ID :** `{uid}`\n"
        f"🎮 **Jeu :** `{cat}`\n"
        f"💻 **Plateforme :** `{plat}`\n"
        f"💰 **Prix :** `{prix} {devise}`\n"
        f"💳 **Paiements :** `{paiements}`\n"
        f"📝 **Description :**\n{desc}\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )
    
    kb = [
        [
            InlineKeyboardButton("✅ Approuver", callback_data=f"mod:approuver:{annonce_id}"),
            InlineKeyboardButton("❌ Rejeter", callback_data=f"mod:rejeter:{annonce_id}")
        ]
    ]
    
    # On envoie le ticket à l'admin principal
    try:
        await ctx.bot.send_message(
            chat_id=SUPER_ADMIN_ID,
            text=ticket_text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Erreur lors de l'envoi du ticket de modération : {e}")

async def traitement_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    action = data[1]       # "approuver" ou "rejeter"
    annonce_id = data[2]   # L'ID de l'annonce dans MongoDB
    
    from bson.objectid import ObjectId
    annonce = db.annonces.find_one({"_id": ObjectId(annonce_id)})
    
    if not annonce:
        await query.message.edit_text("❌ Erreur : Cette annonce n'existe plus.")
        return

    vendeur_id = annonce["vendeur_id"]

    if action == "approuver":
        # Mettre à jour le statut dans la bdd
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"statut": "valide"}})
        
        await query.message.edit_text(f"✅ **Annonce {annonce_id} approuvée et publiée !**")
        
        # Alerter le vendeur
        try:
            await ctx.bot.send_message(
                chat_id=vendeur_id,
                text=f"🎉 **Bonne nouvelle !** Votre annonce pour le jeu *{annonce['categorie']}* a été approuvée par l'administration et est désormais visible sur le Marketplace !",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif action == "rejeter":
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"statut": "rejete"}})
        
        await query.message.edit_text(f"❌ **Annonce {annonce_id} rejetée.**")
        
        # Alerter le vendeur
        try:
            await ctx.bot.send_message(
                chat_id=vendeur_id,
                text=f"⚠️ **Votre annonce pour le jeu {annonce['categorie']} a été refusée** car elle ne respecte pas nos critères de publication.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
