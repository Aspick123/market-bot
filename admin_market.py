import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, mdb_config, get_user, save_user,
    add_to_blacklist, get_blacklist, add_log,
    set_role, get_role, has_perm, ROLES_EQUIPE
)

async def show_admin_panel(message, user_id: int, super_admin_id: int):
    role = get_role(user_id, super_admin_id)
    role_label = ROLES_EQUIPE.get(role, "?")
    kb = []
    if has_perm(user_id, "valider_annonces", super_admin_id):
        annonces = mdb_read("annonces.json")
        nb = sum(1 for a in annonces.values() if a.get("statut") == "en_attente")
        kb.append([InlineKeyboardButton(f"📋 Annonces ({nb})", callback_data="adm_annonces_attente")])
    if has_perm(user_id, "gerer_securite", super_admin_id):
        kb.append([InlineKeyboardButton("🔒 Sécurité & Blacklist", callback_data="adm_securite")])
    if has_perm(user_id, "nommer_moderateur", super_admin_id):
        kb.append([InlineKeyboardButton("👥 Gérer l'équipe", callback_data="adm_equipe")])
    if has_perm(user_id, "configurer", super_admin_id):
        kb.append([InlineKeyboardButton("⚙️ Configuration", callback_data="adm_config")])
    kb.append([InlineKeyboardButton("❌ Fermer", callback_data="adm_close")])
    await message.reply_text(f"🔐 *Panel Admin*\nRôle : {role_label}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def show_annonces_attente(message):
    await message.reply_text("📋 Mode modération des annonces actif.")

async def show_securite_menu(message):
    await message.reply_text("🔒 Menu Sécurité.")

async def show_equipe_menu(message, super_admin_id: int):
    await message.reply_text("👥 Menu Équipe.")

async def show_config_menu(message):
    await message.reply_text("⚙️ Configuration.")

async def handle_admin_market_callbacks(query, ctx, bot, super_admin_id: int) -> bool:
    data = query.data; msg = query.message; uid = query.from_user.id
    if data == "adm_market_panel": await show_admin_panel(msg, uid, super_admin_id); return True
    if data == "adm_close": await msg.delete(); return True
    return False

async def handle_admin_input(update, ctx, bot, super_admin_id: int) -> bool:
    state = ctx.user_data.get("adm_state")
    if not state: return False
    return False
