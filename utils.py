"""
╔══════════════════════════════════════════════════════════════╗
║               UTILS.PY — Connexion et fonctions partagées    ║
║  MongoDB unique + helpers utilisés par bot_market + escrow   ║
╚══════════════════════════════════════════════════════════════╝

Ce fichier contient :
- La connexion unique à MongoDB Atlas (client + db)
- Les fonctions utilitaires partagées
- IMPORTANT : NE PAS dupliquer ces fonctions dans les autres fichiers
"""

import os
import time
import datetime
import logging
from pymongo import MongoClient
from bson.objectid import ObjectId

log = logging.getLogger("BotMarket")

# ══════════════════════════════════════════════════════════════
#  CONNEXION MONGODB UNIQUE
# ══════════════════════════════════════════════════════════════

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")

client = MongoClient(MONGO_URI)
db = client["bot_market_premium_db"]

# ══════════════════════════════════════════════════════════════
#  FONCTIONS UTILITAIRES PARTAGÉES
# ══════════════════════════════════════════════════════════════

def safe_html(text) -> str:
    """Échappe les caractères HTML pour affichage Telegram."""
    if text is None:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def fmt_date(ts=None) -> str:
    """Formate un timestamp en date lisible (JJ/MM/AAAA HH:MM)."""
    if ts is None:
        ts = time.time()
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")

def try_objectid(val):
    """Convertit une chaîne en ObjectId MongoDB, ou retourne None si invalide."""
    try:
        return ObjectId(val)
    except Exception:
        return None

def log_audit(action: str, details: str, acted_by: int):
    """Enregistre une action dans le journal d'audit."""
    db.audit_logs.insert_one({
        "action": action,
        "details": details,
        "acted_by": acted_by,
        "date": fmt_date(),
        "timestamp": time.time()
    })
