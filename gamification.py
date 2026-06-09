from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def handle_gamification_callbacks(query, ctx, bot, admin_id):
    data = query.data
    if data == "menu_defis":
        text = "🏆 *Défis & XP*\n\n➕ Publier une annonce : *+10 XP*\n✅ Transaction réussie : *+50 XP*"
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="retour_start")]]), parse_mode="Markdown")
        return True
    elif data == "menu_leaderboard":
        await show_leaderboard(query)
        return True
    return False

async def show_leaderboard(query):
    text = "📊 *Classement Général*\n\n1️⃣ Vendeur_Pro — *Level 5*\n2️⃣ GamerZone — *Level 3*"
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="retour_start")]]), parse_mode="Markdown")
  
