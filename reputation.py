from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import get_user, save_user

async def handle_reputation_callbacks(query, ctx, bot):
    data = query.data
    uid = query.from_user.id
    
    if data.startswith("voir_profil_"):
        target_id = int(data.replace("voir_profil_", ""))
        user = get_user(target_id)
        profil = user.get("profil", {})
        
        nom = profil.get("nom", "Non renseigné")
        contact = profil.get("contact", "Non renseigné")
        desc = profil.get("description", "Aucune description.")
        
        text = f"👤 *Profil de {user.get('username', 'Utilisateur')}*\n\n📛 Nom : {nom}\n📞 Contact : {contact}\n📝 Bio : {desc}"
        kb = [[InlineKeyboardButton("📝 Modifier mes infos", callback_data="modif_profil")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return True
        
    elif data == "modif_profil":
        ctx.user_data["modif_state"] = "attente_nom"
        await query.message.reply_text("✍️ Envoie-moi ton nouveau nom ou pseudo public :")
        return True
    return False

async def handle_reputation_input(update, ctx, bot):
    uid = update.effective_user.id
    state = ctx.user_data.get("modif_state")
    if not state: return False
    
    user = get_user(uid)
    if "profil" not in user: user["profil"] = {}
    
    if state == "attente_nom":
        user["profil"]["nom"] = update.message.text
        save_user(uid, user)
        ctx.user_data["modif_state"] = "attente_contact"
        await update.message.reply_text("📞 Parfait ! Maintenant, envoie ton numéro (WhatsApp ou Téléphone) :")
        return True
    elif state == "attente_contact":
        user["profil"]["contact"] = update.message.text
        save_user(uid, user)
        ctx.user_data["modif_state"] = "attente_desc"
        await update.message.reply_text("📝 Écris une petite description pour ton profil (ex: Vendeur de comptes fiable) :")
        return True
    elif state == "attente_desc":
        user["profil"]["description"] = update.message.text
        save_user(uid, user)
        ctx.user_data.pop("modif_state", None)
        await update.message.reply_text("✅ Profil mis à jour avec succès ! Tape /start pour revenir au menu.")
        return True
    return False
