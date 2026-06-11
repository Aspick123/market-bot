import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu_keyboard(uid, super_admin_id):
    # Boutons de base accessibles à tout le monde
    keyboard = [
        [
            InlineKeyboardButton("🔍 Rechercher", callback_data="menu:recherche"),
            InlineKeyboardButton("🎮 Vendre un compte", callback_data="menu:vendre")
        ],
        [
            InlineKeyboardButton("👤 Mon Profil", callback_data="menu:mon_profil"),
            InlineKeyboardButton("📦 Mes Annonces", callback_data="menu:mes_annonces")
        ],
        [
            InlineKeyboardButton("📜 Règles & CGU", callback_data="menu:cgu"),
            InlineKeyboardButton("📈 Classement", callback_data="menu:leaderboard")
        ]
    ]
    
    # Si l'utilisateur est le Fondateur, on lui ajoute le bouton d'accès au Panel Admin
    if uid == super_admin_id:
        keyboard.append([InlineKeyboardButton("⚡ Panneau Administration ⚡", callback_data="menu:admin_panel")])
        
    return InlineKeyboardMarkup(keyboard)

def get_back_to_start_keyboard():
    keyboard = [[InlineKeyboardButton("🔙 Retour au Menu Principal", callback_data="menu:retour_start")]]
    return InlineKeyboardMarkup(keyboard)
