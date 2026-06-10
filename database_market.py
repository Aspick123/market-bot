import os
import time
from pymongo import MongoClient
from collections import defaultdict

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(MONGO_URI)
db = client["market_bot_db"]

users_col = db["users"]
config_col = db["config"]
annonces_col = db["annonces"]

ROLES_EQUIPE = {
    "super_admin": "👑 Fondateur",
    "admin": "🛡️ Administrateur",
    "mod": "⚔️ Modérateur",
    "user": "👤 Membre"
}

_flood_store = defaultdict(list)

def is_flooded(uid: int) -> bool:
    now = time.time()
    _flood_store[uid] = [t for t in _flood_store[uid] if now - t < 60]
    _flood_store[uid].append(now)
    return len(_flood_store[uid]) > 6

def get_user(uid: int) -> dict:
    user = users_col.find_one({"_id": uid})
    if not user:
        user = {
            "_id": uid,
            "username": None,
            "role": "user",
            "accepte_cgu": False,
            "xp": 0,
            "niveau": 1,
            "parrains": 0,
            "blacklist": False,
            "date_inscription": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        users_col.insert_one(user)
    return user

def save_user(uid: int, data: dict):
    users_col.update_one({"_id": uid}, {"$set": data})

def get_role_label(uid: int, super_admin_id: int) -> str:
    if uid == super_admin_id:
        return ROLES_EQUIPE["super_admin"]
    user = get_user(uid)
    return ROLES_EQUIPE.get(user.get("role", "user"), ROLES_EQUIPE["user"])

def has_perm(uid: int, required_role: str, super_admin_id: int) -> bool:
    if uid == super_admin_id:
        return True
    user = get_user(uid)
    role_hierarchy = {"user": 0, "mod": 1, "admin": 2, "super_admin": 3}
    user_rank = role_hierarchy.get(user.get("role", "user"), 0)
    required_rank = role_hierarchy.get(required_role, 0)
    return user_rank >= required_rank

def is_mode_urgence() -> bool:
    cfg = config_col.find_one({"_id": "global_config"})
    if cfg:
        return cfg.get("mode_urgence", False)
    return False

def create_annonce(vendeur_id: int, categorie: str, description: str, prix: str) -> str:
    """Enregistre une nouvelle annonce dans la collection MongoDB."""
    import uuid
    annonce_id = str(uuid.uuid4())[:8] # Génère un ID unique court à 8 caractères
    
    annonce = {
        "_id": annonce_id,
        "vendeur_id": vendeur_id,
        "categorie": categorie,
        "description": description,
        "prix": prix,
        "statut": "disponible", # disponible / vendu / en_litige
        "date_publication": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    annonces_col.insert_one(annonce)
    return annonce_id

def get_user_annonces(vendeur_id: int) -> list:
    """Récupère toutes les annonces publiées par un utilisateur spécifique."""
    return list(annonces_col.find({"vendeur_id": vendeur_id}))

