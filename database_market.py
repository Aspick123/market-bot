import os
import time
import logging
from pymongo import MongoClient
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

# Configuration des logs
logger = logging.getLogger(__name__)

# --- CONFIGURATION MONGO DB ---
# Utilise la variable d'environnement MONGO_URI si elle existe, sinon utilise une base locale
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["marketplace_database"]

# --- GESTION ANTI-FLOOD & MAINTENANCE ---
# Dictionnaires temporaires en mémoire pour l'anti-flood
_USER_LAST_REQUEST_TIME = {}
FLOOD_LIMIT_SECONDS = 2  # Temps minimum entre deux requêtes

def is_mode_urgence() -> bool:
    """
    Vérifie si le mode maintenance/urgence est activé dans la base de données.
    """
    config = db.configuration.find_one({"key": "mode_urgence"})
    if config:
        return config.get("value", False)
    return False

def set_mode_urgence(status: bool):
    """
    Active ou désactive le mode maintenance/urgence.
    """
    db.configuration.update_one(
        {"key": "mode_urgence"},
        {"$set": {"value": status}},
        upsert=True
    )

def is_flooded(user_id: int) -> bool:
    """
    Vérifie si l'utilisateur envoie des requêtes trop rapidement (Anti-Flood).
    """
    current_time = time.time()
    last_time = _USER_LAST_REQUEST_TIME.get(user_id, 0)
    
    if current_time - last_time < FLOOD_LIMIT_SECONDS:
        return True
        
    _USER_LAST_REQUEST_TIME[user_id] = current_time
    return False


# --- GESTION DES UTILISATEURS ---

def get_user(user_id: int) -> dict:
    """
    Récupère un utilisateur depuis la base de données.
    S'il n'existe pas, il est automatiquement créé avec un profil par défaut.
    """
    user = db.users.find_one({"_id": user_id})
    if not user:
        user = {
            "_id": user_id,
            "username": None,
            "role": "vendeur",  # Rôles possibles : vendeur, staff, admin
            "banni": False,
            "date_inscription": time.time(),
            "score_fiabilite": 100,
            "annonces_publiees": 0
        }
        db.users.insert_one(user)
    return user

def save_user(user_id: int, user_data: dict):
    """
    Sauvegarde ou met à jour les données complètes d'un utilisateur.
    """
    db.users.update_one({"_id": user_id}, {"$set": user_data}, upsert=True)

def get_role_label(user_id: int, super_admin_id: int) -> str:
    """
    Retourne un label textuel et stylisé du rang de l'utilisateur.
    """
    if user_id == super_admin_id:
        return "👑 Fondateur / Super Admin"
        
    user = get_user(user_id)
    if user.get("banni", False):
        return "❌ Utilisateur Banni"
        
    role = user.get("role", "vendeur")
    if role == "admin":
        return "🛡️ Administrateur"
    elif role == "staff":
        return "👨‍✈️ Gérant / Staff"
    else:
        return "🛒 Vendeur Vérifié"


# --- 🔐 SYSTÈME DE VÉRIFICATION FORCE JOIN (ABONNEMENT REQUIS) ---

async def verifier_abonnement_canal(ctx: ContextTypes.DEFAULT_TYPE, user_id: int, canal_id: str) -> bool:
    """
    Interroge l'API Telegram en temps réel pour vérifier si l'utilisateur est présent
    dans le canal spécifié.
    
    Retourne :
      - True s'il est membre, administrateur ou créateur.
      - False s'il a quitté, s'il est exclu ou s'il y a une erreur de configuration.
    """
    # Toujours laisser passer les vérifications si l'ID est configuré vide ou invalide pendant les tests
    if not canal_id or canal_id == "@TonCanalDeVente":
        logger.warning("Le CANAL_VENTE_ID n'est pas encore configuré correctement. Accès autorisé par défaut.")
        return True

    try:
        # Requête directe auprès de l'infrastructure Telegram
        membre = await ctx.bot.get_chat_member(chat_id=canal_id, user_id=user_id)
        
        # Liste des statuts autorisés à utiliser les fonctionnalités du bot
        statuts_autorises = ["member", "administrator", "creator"]
        
        if membre.status in statuts_autorises:
            return True
            
        logger.info(f"Utilisateur {user_id} bloqué : Statut actuel dans le canal : {membre.status}")
        return False
        
    except TelegramError as e:
        # L'erreur survient généralement si le bot n'est pas Administrateur du canal
        logger.error(f"Erreur critique lors de la vérification du canal {canal_id} pour l'user {user_id} : {e}")
        return False
