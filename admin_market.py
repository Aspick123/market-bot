import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import mdb_read, mdb_write, mdb_config, get_user, save_user, add_to_blacklist, get_blacklist, add_log, set_role, get_role, has_perm

# Définition locale
ROLES_EQUIPE = {"admin": "Admin", "mod_annonces": "Modo Annonces", "support": "Support"}

async def show_admin_panel(message, user_id, super_admin_id):
    role = get_role(user_id, super_admin_id)
    role_label = ROLES_EQUIPE.get(role, "Admin")
    kb = []
    if has_perm(user_id, "valider_annonces", super_admin_id):
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
