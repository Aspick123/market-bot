from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from database_market import get_user, save_user

async def user_a_accepte_cgu_vendeur(message, user_id, ctx):
    user = get_user(user_id)
    if user.get("cgu_vendeur") is True:
        return True
    
    text = "📜 *Règlement du Marketplace (CGU)*\n\nEn vendant ici, tu t'engages à fournir des informations réelles. Les arnaques entraînent un bannissement définitif."
    kb = [[InlineKeyboardButton("✅ Accepter et Continuer", callback_data="cgu_accepter")]]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return False

async def handle_cgu_callbacks(query, ctx, bot):
    data = query.data
    uid = query.from_user.id
    if data == "cgu_accepter":
        user = get_user(uid)
        user["cgu_vendeur"] = True
        save_user(uid, user)
        await query.message.edit_text("🎉 Tu as accepté les CGU ! Clique à nouveau sur 'Publier une annonce' au menu principal pour commencer.")
        return True
    return False

async def handle_cgu_input(update, ctx): return False
