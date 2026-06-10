import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import mdb_read, mdb_write, mdb_config, get_user, save_user, add_to_blacklist, get_blacklist, add_log, has_perm

# Rôle simplifié
ROLES_EQUIPE = {"admin": "Admin"}

async def show_admin_panel(message, user_id, super_admin_id):
    # On définit le rôle localement sans appeler get_role
    role_label = "Admin"
    kb = []
    # On garde seulement les vérifications de base
    kb.append([InlineKeyboardButton("📋 Annonces", callback_data="adm_annonces_attente")])
    kb.append([InlineKeyboardButton("❌ Fermer", callback_data="adm_close")])
    await message.reply_text(f"🔐 *Panel Admin*\nRôle : {role_label}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def handle_admin_market_callbacks(query, ctx, bot, super_admin_id):
    data = query.data
    msg = query.message
    uid = query.from_user.id
    if data == "adm_market_panel": 
        await show_admin_panel(msg, uid, super_admin_id)
        return True
    if data == "adm_close": 
        await msg.delete()
        return True
    return False

async def handle_admin_input(update, ctx, bot, super_admin_id):
    return False
