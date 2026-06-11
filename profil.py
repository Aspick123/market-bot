import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database_market import db, get_user

SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

async def afficher_profil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    
    user_data = get_user(uid)
    # Détermination du rang
    if uid == SUPER_ADMIN_ID:
        rang = "👑 Fondateur"
    elif user_data.get("is_gerant", False):
        rang = "🛡️ Gérant (Staff)"
    else:
        rang = "👤 Membre"

    texte = (
        "👤 **VOTRE PROFIL MARKETPLACE**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🆔 **ID Utilisateur :** `{uid}`\n"
        f"🎖️ **Rang :** {rang}\n"
        f"📦 **Annonces actives :** `{db.annonces.count_documents({'vendeur_id': uid, 'statut': 'valide'})}`\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )

    kb = []
    # Si c'est un membre normal, on lui propose de postuler
    if uid != SUPER_ADMIN_ID and not user_data.get("is_gerant", False):
        kb.append([InlineKeyboardButton("💼 Postuler pour devenir Gérant", callback_data="staff:postuler")])
        
    kb.append([InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")])
    
    await query.message.edit_text(texte, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def gestion_candidature(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.first_name

    if query.data == "staff:postuler":
        await query.message.edit_text(
            "📩 **Candidature envoyée !**\n\n"
            "Le Fondateur a reçu votre demande pour rejoindre l'équipe des Gérants. "
            "Vous serez recontacté si votre profil est retenu.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]])
        )
        
        # Envoi au fondateur
        cand_text = (
            "💼 **NOUVELLE CANDIDATURE STAFF**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Utilisateur :** @{username}\n"
            f"🆔 **ID :** `{uid}`\n"
            "Souhaitez-vous le nommer Gérant du Marketplace ?"
        )
        kb = [[
            InlineKeyboardButton("🟢 Accepter", callback_data=f"staff:promouvoir:{uid}"),
            InlineKeyboardButton("🔴 Refuser", callback_data=f"staff:refuser:{uid}")
        ]]
        await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=cand_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif query.data.startswith("staff:promouvoir:"):
        target_uid = int(query.data.split(":")[2])
        db.users.update_one({"_id": target_uid}, {"$set": {"is_gerant": True}}, upsert=True)
        await query.message.edit_text(f"🟢 L'utilisateur `{target_uid}` est désormais **Gérant** !")
        try:
            await ctx.bot.send_message(chat_id=target_uid, text="🎉 **Félicitations !** Le Fondateur a accepté votre candidature. Vous êtes maintenant **Gérant** sur le Marketplace !")
        except Exception: pass

    elif query.data.startswith("staff:refuser:"):
        target_uid = int(query.data.split(":")[2])
        await query.message.edit_text(f"🔴 Candidature de `{target_uid}` refusée.")
