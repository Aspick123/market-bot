import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database_market import db

SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

# 📢 Identifiant public de ton canal Telegram
CANAL_MARKETPLACE_ID = "@comptedejeux" 

async def soumettre_a_la_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    
    cat = ctx.user_data.get("vente_jeu", "Inconnu")
    desc = ctx.user_data.get("vente_description", "Aucune description")
    prix = ctx.user_data.get("vente_prix", 0)
    devise = ctx.user_data.get("vente_devise", "XOF")
    plat = ctx.user_data.get("vente_plateforme", "Non spécifiée")
    paiements = ", ".join(ctx.user_data.get("vente_paiements", []))
    
    images = ctx.user_data.get("photos", [])
    
    annonce_id = db.annonces.insert_one({
        "vendeur_id": uid,
        "categorie": cat,
        "plateforme": plat,
        "description": desc,
        "prix": prix,
        "devise": devise,
        "paiements": ctx.user_data.get("vente_paiements", []),
        "photos": images,
        "statut": "en_attente"
    }).inserted_id

    await query.message.edit_text(
        "⏳ **Annonce soumise avec succès !**\n\n"
        "Votre annonce a été envoyée à l'équipe de modération.\n"
        "Elle sera automatiquement publiée sur le canal officiel dès sa validation.",
        parse_mode="Markdown"
    )

    # Ticket de modération reçu par le Fondateur (toi)
    ticket_text = (
        "🔔 **NOUVELLE ANNONCE À MODÉRER**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👤 **Vendeur ID :** `{uid}`\n"
        f"🎮 **Jeu :** `{cat}`\n"
        f"💻 **Plateforme :** `{plat}`\n"
        f"💰 **Prix :** `{prix} {devise}`\n"
        f"💳 **Paiements :** `{paiements}`\n"
        f"📝 **Description :**\n{desc}\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "Cliquez ci-dessous pour publier directement sur le canal :"
    )
    
    kb = [[
        InlineKeyboardButton("✅ Approuver & Publier", callback_data=f"mod:approuver:{annonce_id}"),
        InlineKeyboardButton("❌ Rejeter", callback_data=f"mod:rejeter:{annonce_id}")
    ]]
    
    try:
        await ctx.bot.send_message(
            chat_id=SUPER_ADMIN_ID,
            text=ticket_text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Erreur d'envoi du ticket admin: {e}")

async def traitement_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    action = data[1]       
    annonce_id = data[2]   
    
    from bson.objectid import ObjectId
    annonce = db.annonces.find_one({"_id": ObjectId(annonce_id)})
    
    if not annonce:
        await query.message.edit_text("❌ Erreur : Cette annonce n'existe plus.")
        return

    vendeur_id = annonce["vendeur_id"]
    vendeur_info = db.users.find_one({"_id": vendeur_id})
    username_vendeur = vendeur_info.get("username", "Inconnu") if vendeur_info else "Inconnu"

    if action == "approuver":
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"statut": "valide"}})
        await query.message.edit_text(f"✅ **Annonce approuvée ! Envoyée sur @comptedejeux**")
        
        # 📢 MESSAGE PROPRE ENVOYÉ AUTOMATIQUEMENT DANS TON CANAL
        texte_canal = (
            "🛒 **NOUVELLE OFFRE DISPONIBLE !**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎮 **Jeu :** #{annonce['categorie'].replace(' ', '_')}\n"
            f"💻 **Plateforme :** `{annonce.get('plateforme', 'Non spécifiée')}`\n"
            f"💰 **Prix :** `{annonce['prix']} {annonce['devise']}`\n"
            f"💳 **Paiements :** `{(', '.join(annonce.get('paiements', [])))}`\n"
            f"📝 **Description :**\n{annonce['description']}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Vendeur :** @{username_vendeur}\n\n"
            "⚠️ *Pour votre sécurité, contactez le fondateur pour l'arbitrage de la transaction.*"
        )
        
        try:
            # Si le vendeur a mis une photo dans le tunnel, on l'affiche dans le canal
            if annonce.get("photos") and len(annonce["photos"]) > 0:
                await ctx.bot.send_photo(
                    chat_id=CANAL_MARKETPLACE_ID,
                    photo=annonce["photos"][0],
                    caption=texte_canal,
                    parse_mode="Markdown"
                )
            else:
                await ctx.bot.send_message(
                    chat_id=CANAL_MARKETPLACE_ID,
                    text=texte_canal,
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"Erreur lors de la publication automatique : {e}")
        
        # Alerte le vendeur en MP
        try:
            await ctx.bot.send_message(
                chat_id=vendeur_id,
                text=f"🎉 **Félicitations !** Votre annonce pour *{annonce['categorie']}* a été validée et vient d'être publiée sur le canal officiel @comptedejeux !",
                parse_mode="Markdown"
            )
        except Exception: pass

    elif action == "rejeter":
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"statut": "rejete"}})
        await query.message.edit_text(f"❌ **Annonce refusée et supprimée.**")
        
        try:
            await ctx.bot.send_message(
                chat_id=vendeur_id,
                text=f"⚠️ **Votre annonce pour {annonce['categorie']} a été refusée** car elle ne remplit pas nos conditions de modération.",
                parse_mode="Markdown"
            )
        except Exception: pass
