from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import has_perm

def get_main_menu_keyboard(uid: int, super_admin_id: int) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("🔍 Rechercher", callback_data="menu:recherche"),
            InlineKeyboardButton("➕ Vendre", callback_data="menu:vendre")
        ],
        [
            InlineKeyboardButton("📦 Mes Annonces", callback_data="menu:mes_annonces"),
            InlineKeyboardButton("💰 Historique", callback_data="menu:historique")
        ],
        [
            InlineKeyboardButton("👤 Mon Profil", callback_data="menu:profil"),
            InlineKeyboardButton("🎁 Parrainage", callback_data="menu:parrainage")
        ],
        [
            InlineKeyboardButton("🏆 Défis & Niveaux", callback_data="menu:defis"),
            InlineKeyboardButton("📊 Classement", callback_data="menu:leaderboard")
        ],
        [
            InlineKeyboardButton("⚖️ Ouvrir un litige", callback_data="menu:litige"),
            InlineKeyboardButton("🔔 Mes Alertes", callback_data="menu:alertes")
        ],
        [
            InlineKeyboardButton("🚫 Liste Noire", callback_data="menu:blacklist"),
            InlineKeyboardButton("📜 CGU", callback_data="menu:cgu")
        ]
    ]
    if has_perm(uid, "mod", super_admin_id):
        kb.append([InlineKeyboardButton("⚙️ Panel Admin", callback_data="menu:admin_panel")])
    return InlineKeyboardMarkup(kb)

def get_back_to_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour au Menu", callback_data="menu:retour_start")]])

