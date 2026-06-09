"""
╔══════════════════════════════════════════════════════════════╗
║         DATABASE_MARKET.PY — BASE DE DONNÉES                 ║
║         Bot Marketplace Jeux Vidéo                           ║
╚══════════════════════════════════════════════════════════════╝
"""

import json
import os
import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data_market")
os.makedirs(DATA_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION PAR DÉFAUT
# ══════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "max_annonces_par_user": 3,
    "duree_annonce_jours": 30,
    "boost_duree_jours": 7,
    "delai_anti_arnaque_minutes": 5,
    "signalements_avant_suspension": 3,
    "canal_id": "",
    "anciennete_vendeur_jours": 0,
    "rapport_hebdo_jour": "lundi",
    "rapport_mensuel_jour": 1,
    "version_cgu": "1.0",
    "recrutement_ouvert": True
}

# ── Jeux supportés avec monnaies associées ──
DEFAULT_JEUX = {
    "Fortnite":          {"monnaies": ["V-Bucks"], "type": ["compte", "monnaie"]},
    "FIFA 24":           {"monnaies": ["FIFA Points", "FIFA Coins"], "type": ["compte", "monnaie"]},
    "FC 25":             {"monnaies": ["FC Points", "FC Coins"], "type": ["compte", "monnaie"]},
    "Call of Duty":      {"monnaies": ["COD Points", "CP"], "type": ["compte", "monnaie"]},
    "PUBG Mobile":       {"monnaies": ["UC"], "type": ["compte", "monnaie"]},
    "Free Fire":         {"monnaies": ["Diamants"], "type": ["compte", "monnaie"]},
    "Clash of Clans":    {"monnaies": ["Gemmes"], "type": ["compte", "monnaie"]},
    "Clash Royale":      {"monnaies": ["Gemmes"], "type": ["compte", "monnaie"]},
    "Brawl Stars":       {"monnaies": ["Gemmes"], "type": ["compte", "monnaie"]},
    "Mobile Legends":    {"monnaies": ["Diamants"], "type": ["compte", "monnaie"]},
    "Genshin Impact":    {"monnaies": ["Primogyems", "Genesis Crystals"], "type": ["compte", "monnaie"]},
    "Valorant":          {"monnaies": ["VP"], "type": ["compte", "monnaie"]},
    "League of Legends": {"monnaies": ["RP", "Blue Essence"], "type": ["compte", "monnaie"]},
    "Minecraft":         {"monnaies": ["Minecoins"], "type": ["compte", "monnaie"]},
    "Roblox":            {"monnaies": ["Robux"], "type": ["compte", "monnaie"]},
    "Steam":             {"monnaies": ["Steam Wallet"], "type": ["compte", "monnaie"]},
    "PlayStation":       {"monnaies": ["PSN Credits"], "type": ["compte", "monnaie"]},
    "Xbox":              {"monnaies": ["Microsoft Points"], "type": ["compte", "monnaie"]},
    "Supercell ID":      {"monnaies": ["Gemmes"], "type": ["compte"]},
    "Autre":             {"monnaies": ["Autre"], "type": ["compte", "monnaie"]},
}

# ── Monnaies du monde + crypto ──
DEFAULT_MONNAIES_PAIEMENT = [
    # Afrique de l'Ouest
    "XOF (FCFA)", "GHS (Cedi)", "NGN (Naira)", "XAF (FCFA Central)",
    "MAD (Dirham)", "TND (Dinar)", "DZD (Dinar algérien)",
    "SEN (Sénégal)", "CIV (Côte d'Ivoire)", "CMR (Cameroun)",
    # International
    "EUR (Euro)", "USD (Dollar US)", "GBP (Livre sterling)",
    "CAD (Dollar canadien)", "CHF (Franc suisse)",
    "AED (Dirham EAU)", "SAR (Riyal saoudien)",
    # Crypto
    "USDT (Tether)", "Bitcoin (BTC)", "Ethereum (ETH)",
    "BNB (Binance)", "USDC", "Litecoin (LTC)", "Autre crypto"
]

# ── Méthodes de paiement ──
DEFAULT_METHODES_PAIEMENT = [
    "Wave", "Orange Money", "MTN Mobile Money", "Moov Money",
    "Airtel Money", "M-Pesa", "Free Money",
    "PayPal", "Western Union", "MoneyGram",
    "Virement bancaire", "CIH Bank", "Attijariwafa",
    "USDT (Crypto)", "Bitcoin", "Ethereum", "Autre crypto",
    "Carte cadeau (Gift Card)", "Autre"
]

# ── Pays / Nationalités ──
DEFAULT_PAYS = [
    "Côte d'Ivoire", "Sénégal", "Mali", "Burkina Faso", "Niger",
    "Guinée", "Togo", "Bénin", "Cameroun", "Gabon",
    "Congo", "RDC", "Madagascar", "Maroc", "Algérie",
    "Tunisie", "Mauritanie", "France", "Belgique", "Suisse",
    "Canada", "USA", "UK", "Autre"
]

# ── CGU par défaut ──
DEFAULT_CGU_COMMUNE = """📋 CONDITIONS GÉNÉRALES D'UTILISATION
Version 1.0 — {date}

🔹 ARTICLE 1 — OBJET
Ce bot est une plateforme de mise en relation entre vendeurs et acheteurs de comptes et monnaies virtuelles de jeux vidéo. Le bot n'intervient PAS dans les transactions financières.

🔹 ARTICLE 2 — RESPONSABILITÉ
Les transactions se font DIRECTEMENT entre vendeur et acheteur. Le bot et son administrateur ne peuvent être tenus responsables en cas de litige, arnaque ou perte financière.

🔹 ARTICLE 3 — OBLIGATIONS
• Fournir des informations exactes et véridiques
• Ne pas publier de fausses annonces
• Respecter les autres membres
• Ne pas tenter de frauder ou d'arnaquer

🔹 ARTICLE 4 — INTERDICTIONS
• Vente de comptes piratés ou volés
• Utilisation de faux profils
• Spam et publicité non autorisée
• Contournement du système de mise en relation

🔹 ARTICLE 5 — SANCTIONS
En cas de violation : avertissement → suspension → ban définitif

🔹 ARTICLE 6 — LITIGES
Tout litige doit être signalé via le bot. L'équipe de modération traitera les cas dans les meilleurs délais.

En acceptant ces CGU, vous reconnaissez avoir lu et compris l'ensemble des conditions."""

DEFAULT_CGU_VENDEUR = """

➕ CLAUSES SPÉCIFIQUES VENDEUR

🔹 ARTICLE V1 — IDENTITÉ
Le vendeur s'engage à fournir des informations d'identité exactes lors de sa première annonce.

🔹 ARTICLE V2 — ANNONCES
• Les annonces doivent être honnêtes et complètes
• Les photos doivent être réelles et récentes
• Toute modification après publication doit être signalée

🔹 ARTICLE V3 — TRANSACTIONS
• Le vendeur s'engage à honorer ses annonces
• Tout désistement abusif peut entraîner une sanction

🔹 ARTICLE V4 — RESPONSABILITÉ VENDEUR
Le vendeur est SEUL responsable de la transaction. Le bot n'est qu'un intermédiaire de mise en relation."""

# ── Données initiales vides ──
DEFAULT_USERS       = {}
DEFAULT_ANNONCES    = {}
DEFAULT_TRANSACTIONS= {}
DEFAULT_LITIGES     = {}
DEFAULT_ALERTES     = {}
DEFAULT_REPUTATION  = {}
DEFAULT_PARRAINAGE  = {}
DEFAULT_BLACKLIST   = []
DEFAULT_STATS       = {
    "total_annonces": 0, "total_transactions": 0,
    "total_litiges": 0, "total_users": 0,
    "annonces_par_jeu": {}, "transactions_par_jour": {}
}
DEFAULT_TEAM        = {}
DEFAULT_LOGS        = []
DEFAULT_CGU_ACCEPTATIONS = []
DEFAULT_GAMIFICATION = {}
DEFAULT_NOTIFICATIONS = {}

DEFAULTS = {
    "config.json":           DEFAULT_CONFIG,
    "jeux.json":             DEFAULT_JEUX,
    "monnaies_paiement.json":DEFAULT_MONNAIES_PAIEMENT,
    "methodes_paiement.json":DEFAULT_METHODES_PAIEMENT,
    "pays.json":             DEFAULT_PAYS,
    "users.json":            DEFAULT_USERS,
    "annonces.json":         DEFAULT_ANNONCES,
    "transactions.json":     DEFAULT_TRANSACTIONS,
    "litiges.json":          DEFAULT_LITIGES,
    "alertes.json":          DEFAULT_ALERTES,
    "reputation.json":       DEFAULT_REPUTATION,
    "parrainage.json":       DEFAULT_PARRAINAGE,
    "blacklist.json":        DEFAULT_BLACKLIST,
    "stats.json":            DEFAULT_STATS,
    "team.json":             DEFAULT_TEAM,
    "logs.json":             DEFAULT_LOGS,
    "cgu_acceptations.json": DEFAULT_CGU_ACCEPTATIONS,
    "gamification.json":     DEFAULT_GAMIFICATION,
    "notifications.json":    DEFAULT_NOTIFICATIONS,
    "cgu.json": {
        "version": "1.0",
        "date": datetime.datetime.now().strftime("%d/%m/%Y"),
        "commune": DEFAULT_CGU_COMMUNE.format(date=datetime.datetime.now().strftime("%d/%m/%Y")),
        "vendeur": DEFAULT_CGU_VENDEUR,
        "modifiee_le": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    }
}

# ══════════════════════════════════════════════════════════════
#  INITIALISATION
# ══════════════════════════════════════════════════════════════

def init_database():
    os.makedirs(DATA_DIR, exist_ok=True)
    for filename, default in DEFAULTS.items():
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            _write_file(path, default)
            print(f"✅ Créé : {filename}")
        else:
            print(f"✓  Existant : {filename}")
    print("✅ Base de données marketplace initialisée !")

# ══════════════════════════════════════════════════════════════
#  LECTURE / ÉCRITURE SÉCURISÉES
# ══════════════════════════════════════════════════════════════

def _write_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def mdb_read(filename: str):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        default = DEFAULTS.get(filename, {} if filename.endswith(".json") else [])
        mdb_write(filename, default)
        return default
    except json.JSONDecodeError:
        default = DEFAULTS.get(filename, {})
        mdb_write(filename, default)
        return default

def mdb_write(filename: str, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    _write_file(os.path.join(DATA_DIR, filename), data)

def mdb_config() -> dict:
    return mdb_read("config.json")

# ══════════════════════════════════════════════════════════════
#  GESTION UTILISATEURS
# ══════════════════════════════════════════════════════════════

def get_user(user_id: int) -> dict:
    users = mdb_read("users.json")
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "id": user_id,
            "joined": datetime.datetime.now().strftime("%d/%m/%Y"),
            "role": "membre",
            "est_vendeur": False,
            "vendeur_verifie": False,
            "profil": {
                "photo_id": None,
                "nom": "",
                "bio": "",
                "nationalite": "",
                "telephone": "",
                "telephone_public": False,
                "whatsapp": "",
                "instagram": "",
                "autres_reseaux": "",
                "monnaies_acceptees": [],
                "methodes_paiement": [],
                "statut": "hors_ligne",
                "heure_debut": "",
                "heure_fin": ""
            },
            "stats": {
                "annonces_publiees": 0,
                "ventes": 0,
                "achats": 0,
                "echanges": 0,
                "litiges_ouverts": 0,
                "litiges_resolus": 0,
                "signalements_recus": 0,
                "vues_total": 0,
                "contacts_recus": 0
            },
            "cgu_acceptee": False,
            "cgu_version_acceptee": "",
            "cgu_date_acceptation": "",
            "parrain_id": None,
            "filleuls": [],
            "points": 0,
            "niveau": "bronze",
            "badges": [],
            "abonne_alertes": [],
            "blackliste": False,
            "avertissements": 0,
            "suspendu": False,
            "rapport_hebdo": True,
            "rapport_mensuel": True
        }
        mdb_write("users.json", users)
    return users[uid]

def save_user(user_id: int, data: dict):
    users = mdb_read("users.json")
    users[str(user_id)] = data
    mdb_write("users.json", users)

def get_all_users() -> dict:
    return mdb_read("users.json")

# ══════════════════════════════════════════════════════════════
#  GESTION ANNONCES
# ══════════════════════════════════════════════════════════════

def next_annonce_id() -> str:
    annonces = mdb_read("annonces.json")
    num = len(annonces) + 1
    return f"ANN{num:04d}"

def get_annonce(annonce_id: str) -> dict:
    return mdb_read("annonces.json").get(annonce_id)

def save_annonce(annonce_id: str, data: dict):
    annonces = mdb_read("annonces.json")
    annonces[annonce_id] = data
    mdb_write("annonces.json", annonces)

def get_annonces_user(user_id: int) -> list:
    annonces = mdb_read("annonces.json")
    return [(aid, a) for aid, a in annonces.items() if a["vendeur_id"] == user_id]

def get_annonces_actives() -> list:
    annonces = mdb_read("annonces.json")
    now = datetime.datetime.now()
    actives = []
    for aid, a in annonces.items():
        if a.get("statut") == "active":
            try:
                exp = datetime.datetime.strptime(a["expiration"], "%d/%m/%Y")
                if exp > now:
                    actives.append((aid, a))
            except:
                actives.append((aid, a))
    return actives

def get_annonces_en_attente() -> list:
    annonces = mdb_read("annonces.json")
    return [(aid, a) for aid, a in annonces.items() if a.get("statut") == "en_attente"]

# ══════════════════════════════════════════════════════════════
#  GESTION TRANSACTIONS
# ══════════════════════════════════════════════════════════════

def next_transaction_id() -> str:
    transactions = mdb_read("transactions.json")
    num = len(transactions) + 1
    return f"TRX{num:04d}"

def get_transaction(trx_id: str) -> dict:
    return mdb_read("transactions.json").get(trx_id)

def save_transaction(trx_id: str, data: dict):
    transactions = mdb_read("transactions.json")
    transactions[trx_id] = data
    mdb_write("transactions.json", transactions)

def get_transactions_user(user_id: int) -> list:
    transactions = mdb_read("transactions.json")
    return [(tid, t) for tid, t in transactions.items()
            if t.get("vendeur_id") == user_id or t.get("acheteur_id") == user_id]

# ══════════════════════════════════════════════════════════════
#  GESTION LITIGES
# ══════════════════════════════════════════════════════════════

def next_litige_id() -> str:
    litiges = mdb_read("litiges.json")
    num = len(litiges) + 1
    return f"LIT{num:04d}"

def get_litige(litige_id: str) -> dict:
    return mdb_read("litiges.json").get(litige_id)

def save_litige(litige_id: str, data: dict):
    litiges = mdb_read("litiges.json")
    litiges[litige_id] = data
    mdb_write("litiges.json", litiges)

def get_litiges_en_cours() -> list:
    litiges = mdb_read("litiges.json")
    return [(lid, l) for lid, l in litiges.items() if l.get("statut") == "en_cours"]

# ══════════════════════════════════════════════════════════════
#  GESTION BLACKLIST
# ══════════════════════════════════════════════════════════════

def add_to_blacklist(user_id: int, raison: str, admin_id: int):
    bl = mdb_read("blacklist.json")
    entry = {
        "user_id": user_id,
        "raison": raison,
        "date": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "admin_id": admin_id
    }
    if not any(b["user_id"] == user_id for b in bl):
        bl.append(entry)
        mdb_write("blacklist.json", bl)
    user = get_user(user_id)
    user["blackliste"] = True
    save_user(user_id, user)

def is_blacklisted(user_id: int) -> bool:
    bl = mdb_read("blacklist.json")
    return any(b["user_id"] == user_id for b in bl)

def get_blacklist() -> list:
    return mdb_read("blacklist.json")

# ══════════════════════════════════════════════════════════════
#  GESTION ÉQUIPE
# ══════════════════════════════════════════════════════════════

ROLES_EQUIPE = {
    "super_admin":   "👑 Super Admin",
    "admin":         "🛡️ Admin",
    "mod_annonces":  "📋 Modérateur Annonces",
    "mod_litiges":   "⚖️ Modérateur Litiges",
    "support":       "🎧 Support Membres",
    "mod_securite":  "🔒 Modérateur Sécurité",
    "membre":        "👤 Membre"
}

PERMISSIONS = {
    "super_admin": [
        "valider_annonces", "refuser_annonces", "gerer_litiges",
        "gerer_securite", "blacklister", "avertir", "suspendre",
        "nommer_admin", "nommer_moderateur", "revoquer_role",
        "modifier_cgu", "exporter_donnees", "voir_stats",
        "voir_telephone", "boost_annonce", "mode_urgence",
        "configurer", "voir_tout", "aider_membres"
    ],
    "admin": [
        "valider_annonces", "refuser_annonces", "gerer_litiges",
        "gerer_securite", "blacklister", "avertir", "suspendre",
        "nommer_moderateur", "exporter_donnees", "voir_stats",
        "voir_telephone", "boost_annonce", "voir_tout", "aider_membres"
    ],
    "mod_annonces": [
        "valider_annonces", "refuser_annonces", "voir_tout"
    ],
    "mod_litiges": [
        "gerer_litiges", "avertir", "voir_tout"
    ],
    "support": [
        "aider_membres", "voir_tout"
    ],
    "mod_securite": [
        "gerer_securite", "blacklister", "avertir", "suspendre", "voir_telephone", "voir_tout"
    ],
    "membre": []
}

def get_role(user_id: int, super_admin_id: int) -> str:
    if user_id == super_admin_id:
        return "super_admin"
    team = mdb_read("team.json")
    return team.get(str(user_id), {}).get("role", "membre")

def has_perm(user_id: int, perm: str, super_admin_id: int) -> bool:
    role = get_role(user_id, super_admin_id)
    return perm in PERMISSIONS.get(role, [])

def get_team_ids_by_role(role: str) -> list:
    team = mdb_read("team.json")
    return [int(uid) for uid, data in team.items() if data.get("role") == role]

def get_all_team_ids() -> list:
    team = mdb_read("team.json")
    return [int(uid) for uid in team.keys()]

def set_role(user_id: int, role: str, assigned_by: int):
    team = mdb_read("team.json")
    team[str(user_id)] = {
        "role": role,
        "assigned_by": assigned_by,
        "date": datetime.datetime.now().strftime("%d/%m/%Y")
    }
    mdb_write("team.json", team)

# ══════════════════════════════════════════════════════════════
#  GESTION LOGS
# ══════════════════════════════════════════════════════════════

def add_log(action: str, details: str, user_id: int):
    logs = mdb_read("logs.json")
    logs.append({
        "date": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "action": action,
        "details": details,
        "user_id": user_id
    })
    mdb_write("logs.json", logs[-500:])

# ══════════════════════════════════════════════════════════════
#  GESTION STATS
# ══════════════════════════════════════════════════════════════

def update_stat(key: str, value: int = 1):
    stats = mdb_read("stats.json")
    if key in stats:
        stats[key] = stats.get(key, 0) + value
    mdb_write("stats.json", stats)

def update_stat_jeu(jeu: str):
    stats = mdb_read("stats.json")
    stats.setdefault("annonces_par_jeu", {})
    stats["annonces_par_jeu"][jeu] = stats["annonces_par_jeu"].get(jeu, 0) + 1
    mdb_write("stats.json", stats)

# ══════════════════════════════════════════════════════════════
#  GESTION CGU
# ══════════════════════════════════════════════════════════════

def get_cgu() -> dict:
    return mdb_read("cgu.json")

def save_cgu(data: dict):
    mdb_write("cgu.json", data)

def user_a_accepte_cgu(user_id: int) -> bool:
    user = get_user(user_id)
    cgu = get_cgu()
    return (user.get("cgu_acceptee") and
            user.get("cgu_version_acceptee") == cgu.get("version"))

def enregistrer_acceptation_cgu(user_id: int, type_cgu: str = "commune"):
    cgu = get_cgu()
    user = get_user(user_id)
    user["cgu_acceptee"] = True
    user["cgu_version_acceptee"] = cgu["version"]
    user["cgu_date_acceptation"] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    save_user(user_id, user)
    acceptations = mdb_read("cgu_acceptations.json")
    acceptations.append({
        "user_id": user_id,
        "type": type_cgu,
        "version": cgu["version"],
        "date": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "timestamp": datetime.datetime.now().isoformat()
    })
    mdb_write("cgu_acceptations.json", acceptations)

# ══════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════

def format_date(dt: datetime.datetime = None) -> str:
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime("%d/%m/%Y %H:%M")

def date_expiration(jours: int) -> str:
    exp = datetime.datetime.now() + datetime.timedelta(days=jours)
    return exp.strftime("%d/%m/%Y")

def is_expired(date_str: str) -> bool:
    try:
        exp = datetime.datetime.strptime(date_str, "%d/%m/%Y")
        return datetime.datetime.now() > exp
    except:
        return False

def stars(note: float) -> str:
    full = int(note)
    empty = 5 - full
    return "⭐" * full + "☆" * empty + f" ({note:.1f}/5)"

def niveau_label(niveau: str) -> str:
    return {
        "bronze": "🥉 Bronze",
        "argent": "🥈 Argent",
        "or":     "🥇 Or",
        "platine":"💎 Platine"
    }.get(niveau, "🥉 Bronze")

# Lancer l'initialisation à l'import
init_database()
