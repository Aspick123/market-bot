import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database_market import db

SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

async def afficher_profil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    user = update.effective_user

    # 1. Récupération ou initialisation des données utilisateur
    user_data = db.users.find_one({"_id": uid})
    if not user_data:
        user_data = {
            "_id": uid,
            "username": user.username or user.first_name,
            "role": "user",
            "solde": 0,
            "ventes_reussies": 0,
            "achats_reussis": 0,
            "note_totale": 0,
            "nombre_avis": 0
        }
        db.users.insert_one(user_data)

    # 2. Extraction des variables de statistiques personnelles
    solde = user_data.get("solde", 0)
    ventes = user_data.get("ventes_reussies", 0)
    achats = user_data.get("achats_reussis", 0)
    role = user_data.get("role", "user")
    
    # Calcul de la réputation (étoiles reçues par les autres utilisateurs)
    note_totale = user_data.get("note_totale", 0)
    nb_avis = user_data.get("nombre_avis", 0)
    if nb_avis > 0:
        moyenne = round(note_totale / nb_avis, 1)
        reputation = "⭐" * int(round(moyenne)) + f" ({moyenne}/5 - {nb_avis} avis)"
    else:
        reputation = "ℹ️ Aucun avis pour le moment"

    # Traduction claire du rang/rôle sur le marketplace
    if uid == SUPER_ADMIN_ID:
        role_label = "👑 Fondateur"
    elif role == "admin":
        role_label = "🛠️ Administrateur"
    elif role == "gerant":
        role_label = "⚡ Gérant Arbitre"
    elif role == "mod":
        role_label = "🛡️ Modérateur"
    else:
        role_label = "👤 Membre"

    # Compter ses annonces actuellement en ligne dans le canal
    annonces_actives = db.annonces.count_documents({"vendeur_id": uid, "statut": "valide"})

    # 3. Mise en page textuelle des informations de la personne
    profil_text = (
        f"👤 **VOS INFORMATIONS PERSONNELLES**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🆔 **Mon ID Unique :** `{uid}`\n"
        f"🏷️ **Nom d'utilisateur :** @{user_data.get('username', 'Inconnu')}\n"
        f"🎖️ **Mon Rang :** `{role_label}`\n\n"
        f"💰 **Mon Solde :** `{solde} FCFA`\n"
        f"📦 **Mes Annonces en ligne :** `{annonces_actives}`\n\n"
        f"📊 **MES STATISTIQUES DE CONFIANCE**\n"
        f"🤝 **Achats validés :** `{achats}`\n"
        f"💵 **Ventes clôturées :** `{ventes}`\n"
        f"📈 **Ma Réputation :** {reputation}\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    )

    # 4. Boutons d'actions liés exclusivement à la gestion de son compte
    kb = [
        [
            InlineKeyboardButton("🛒 Mes Achats", callback_data="menu:historique_achats"),
            InlineKeyboardButton("📦 Mes Ventes", callback_data="menu:mes_annonces")
        ],
        [
            InlineKeyboardButton("💳 Recharger mon solde", callback_data="menu:recharger")
        ],
        [
            InlineKeyboardButton("🔙 Retour au Menu Principal", callback_data="menu:retour_start")
        ]
    ]

    await query.message.edit_text(
        text=profil_text,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# Gardé uniquement pour éviter un plantage si l'ancien bouton est cliqué avant la mise à jour complète
async def gestion_candidature(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pass
