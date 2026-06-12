import os
import time
import logging
from pymongo import MongoClient
from telegram.ext import ContextTypes
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

# --- CONFIGURATION MONGO DB ---
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["marketplace_database"]

# Variable globale pour l'anti-flood
_USER_LAST_REQUEST_TIME = {}
FLOOD_LIMIT_SECONDS = 2

def is_mode_urgence() -> bool:
    config = db.configuration.find_one({"key": "mode_urgence"})
    return config.get("value", False) if config else False

def is_flooded(user_id: int) -> bool:
    current_time = time.time()
    last_time = _USER_LAST_REQUEST_TIME.get(user_id, 0)
    if current_time - last_time < FLOOD_LIMIT_SECONDS:
        return True
    _USER_LAST_REQUEST_TIME[user_id] = current_time
    return False

def get_user(user_id: int) -> dict:
    user = db.users.find_one({"_id": user_id})
    if not user:
        user = {
            "_id": user_id,
            "username": None,
            "role": "vendeur",
            "banni": False,
            "date_inscription": time.time(),
            "score_fiabilite": 100,
            "annonces_publiees": 0
        }
        db.users.insert_one(user)
    return user

def save_user(user_id: int, user_data: dict):
    db.users.update_one({"_id": user_id}, {"$set": user_data}, upsert=True)

def get_role_label(user_id: int, super_admin_id: int) -> str:
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
    return "🛒 Vendeur Vérifié"

# --- 🔐 VÉRIFICATION UNIQUE DU CANAL ---
async def verifier_abonnement_canal(ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """
    Vérifie en temps réel si l'utilisateur est dans le canal configuré.
    """
    canal_id = os.environ.get("CANAL_VENTE_ID", "@comptedejeux")
    try:
        membre = await ctx.bot.get_chat_member(chat_id=canal_id, user_id=user_id)
        if membre.status in ["member", "administrator", "creator"]:
            return True
        return False
    except TelegramError as e:
        logger.error(f"Erreur force join sur le canal {canal_id} pour l'user {user_id} : {e}")
        return False
