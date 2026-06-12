# -*- coding: utf-8 -*-
"""
Fichier : menus.py
Description : Centralisation complète de tous les menus et claviers (InlineKeyboards) 
              du Marketplace Telegram.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu_keyboard(user_id: int, super_admin_id: int) -> InlineKeyboardMarkup:
    """
    Génère le menu d'accueil principal du bot.
    La disposition respecte fidèlement la configuration de Screenshot_20260612-150250.jpg
    tout en ajoutant le bouton de liste de vente.
    """
    keyboard = [
        # Ligne 1 : Moteur de recherche et Lancement de vente
        [
            InlineKeyboardButton("🔍 Recherche", callback_data="menu:recherche"),
            InlineKeyboardButton("🎮 Vendre un compte", callback_data="menu:vendre")
        ],
        # Ligne 2 : Accès global au catalogue (Bouton Liste de vente demandé)
        [
            InlineKeyboardButton("🛍️ Liste de vente", callback_data="menu:liste_offres")
        ],
        # Ligne 3 : Gestion personnelle de l'utilisateur
        [
            InlineKeyboardButton("👤 Mon Profil", callback_data="menu:profil"),
            InlineKeyboardButton("📦 Mes Annonces", callback_data="menu:mes_annonces")
        ],
        # Ligne 4 : Informations communautaires et Fiabilité
        [
            InlineKeyboardButton("📜 Règles & CGU", callback_data="menu:regles"),
            InlineKeyboardButton("📈 Classement", callback_data="menu:classement")
        ]
    ]
    
    # Ligne 5 : Sécurité - Affiché uniquement si l'utilisateur est le Fondateur Principal
    if user_id == super_admin_id:
        keyboard.append([InlineKeyboardButton("⚡ Panneau Administration ⚡", callback_data="menu:admin")])
        
    return InlineKeyboardMarkup(keyboard)


def get_back_to_start_keyboard() -> InlineKeyboardMarkup:
    """
    Bouton universel de retour permettant de quitter une section 
    et de réafficher le menu principal.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Retour Menu Principal", callback_data="menu:retour_start")]
    ])


def get_platform_keyboard() -> InlineKeyboardMarkup:
    """
    Clavier de l'Étape 1 du tunnel de vente : Sélection du support de jeu.
    """
    keyboard = [
        [InlineKeyboardButton("📱 Android", callback_data="plat:Android")],
        [InlineKeyboardButton("🍏 iOS (Apple)", callback_data="plat:iOS")],
        [InlineKeyboardButton("💻 PC", callback_data="plat:PC")],
        [InlineKeyboardButton("🎮 Console (PS/Xbox)", callback_data="plat:Console")],
        [InlineKeyboardButton("🌐 Multiplateforme", callback_data="plat:Multi")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_currency_keyboard() -> InlineKeyboardMarkup:
    """
    Clavier de l'Étape 4 du tunnel de vente : Sélection de la devise de transaction.
    """
    keyboard = [
        [InlineKeyboardButton("💵 FCFA", callback_data="devise:FCFA")],
        [InlineKeyboardButton("🪙 USDT", callback_data="devise:USDT")],
        [InlineKeyboardButton("💳 EUR / PayPal", callback_data="devise:EUR")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Clavier de validation de l'annonce par l'auteur avant transmission au Staff.
    """
    keyboard = [
        [InlineKeyboardButton("✅ Valider et Soumettre", callback_data="publier:oui")],
        [InlineKeyboardButton("❌ Annuler l'annonce", callback_data="publier:non")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_moderation_keyboard(annonce_id: str) -> InlineKeyboardMarkup:
    """
    Clavier d'administration envoyé dans le canal privé de modération.
    Permet aux admins de statuer instantanément sur une offre reçue.
    """
    keyboard = [
        [
            InlineKeyboardButton("✅ Approuver", callback_data=f"mod:approuver:{annonce_id}"),
            InlineKeyboardButton("❌ Rejeter", callback_data=f"mod:rejeter:{annonce_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Clavier interne du Panneau d'administration pour la gestion des cas critiques.
    """
    keyboard = [
        [InlineKeyboardButton("🚨 Activer Mode Urgence", callback_data="admin:urgence_on")],
        [InlineKeyboardButton("✅ Désactiver Mode Urgence", callback_data="admin:urgence_off")],
        [InlineKeyboardButton("🔙 Retour Menu Principal", callback_data="menu:retour_start")]
    ]
    return InlineKeyboardMarkup(keyboard)
