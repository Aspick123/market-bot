import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database_market import db

SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

async def afficher_profil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    user = update.effective_user

    # 1. Récupération ou initialisation complète des données dans MongoDB
    user_data = db.users.find_one({"_id": uid})
    if not user_data:
        user_data = {
            "_id": uid,
            "username": user.username or user.first_name,
            "role": "user",
            "solde": 0,
            "ventes_reussies": 0,
            "note_totale": 0,
            "nombre_avis": 0
        }
        db.users.insert_one(user_data)

    # 2. Sécurité pour s'assurer que les nouveaux champs existent
    solde = user_data.get("solde", 0)
    ventes = user_data.get("ventes_reussies", 0)
    role = user_data.get("role", "user")
    
    # Calcul de la moyenne des notes (Reputation)
    note_totale = user_data.get("note_totale", 0)
    nb_avis = user_data.get("nombre_avis", 0)
    if nb_avis > 0:
        moyenne = round(note_totale / nb_avis, 1)
        etoiles = "⭐" * int(round(moyenne)) + f" ({moyenne}/5, {nb_avis} avis)"
    else:
        etoiles = " Pas encore d'avis"

    # 3. Traduction propre des rôles
    if uid == SUPER_ADMIN_ID:
        role_label = "👑 Fondateur / Super Admin"
    elif role == "admin":
        role_label = "🛠️ Administrateur"
    elif role == "gerant":
        role_label = "⚡ Gérant Arbitre"
    elif role == "mod":
        role_label = "🛡️ Modérateur"
    else:
        role_label = "👤 Membre Marketplace"

    # Compter ses annonces actives
    annonces_actives = db.annonces.count_documents({"vendeur_id": uid, "statut": "valide"})

    # 4. Rédaction du texte du profil
    profil_text = (
        f"👤 **ESPACE MEMBRE - VOTRE PROFIL**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🆔 **ID Utilisateur :** `{uid}`\n"
        f"🏷️ **Nom d'utilisateur :** @{user_data.get('username', 'Inconnu')}\n"
        f"🎖️ **Rang sur la plateforme :** `{role_label}`\n"
        f"💳 **Solde Portefeuille :** `{solde} FCFA`\n"
        f"🤝 **Ventes clôturées :** `{ventes}`\n"
        f"📦 **Annonces en ligne :** `{annonces_actives}`\n"
        f"📈 **Réputation vendeur :** {etoiles}\n\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"💡 *Plus votre réputation est haute, plus les acheteurs auront confiance en vous !*"
    )

    # 5. Boutons du profil (Dynamiques selon le rôle)
    kb = []
    
    # Si c'est un utilisateur simple, il peut postuler dans le staff
    if role == "user" and uid != SUPER_ADMIN_ID:
        kb.append([InlineKeyboardButton("🚀 Postuler pour devenir Staff/Gérant", callback_data="staff:postuler")])
    else:
        kb.append([InlineKeyboardButton("⚙️ Accéder aux fonctions Staff", callback_data="staff:infos_reglement")])

    kb.append([InlineKeyboardButton("💳 Recharger mon solde", callback_data="menu:recharger")])
    kb.append([InlineKeyboardButton("🔙 Retour au Menu", callback_data="menu:retour_start")])

    await query.message.edit_text(
        text=profil_text,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ==================== SYSTÈME DE CANDIDATURE AUTOMATIQUE ====================

async def gestion_candidature(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = update.effective_user.id
    user = update.effective_user

    if data == "staff:postuler":
        text_candidature = (
            "📝 **RECRUTEMENT STAFF & GÉRANT ARBITRE**\n\n"
            "Vous souhaitez rejoindre l'équipe pour valider des annonces ou sécuriser des transactions (Arbitre) ?\n\n"
            "⚠️ **Conditions requises :**\n"
            "• Être honnête et actif quotidiennement.\n"
            "• Connaître les prix des comptes de jeux.\n"
            "• Ne jamais avoir triché ou fraudé.\n\n"
            "Souhaitez-vous envoyer instantanément votre profil au Fondateur pour étude ?"
        )
        kb = [
            [InlineKeyboardButton("✅ Envoyer ma candidature", callback_data="staff:envoyer_demande")],
            [InlineKeyboardButton("❌ Annuler", callback_data="menu:mon_profil")]
        ]
        await query.message.edit_text(text_candidature, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data == "staff:envoyer_demande":
        # Alerte le Fondateur directement
        ticket_staff = (
            "📥 **NOUVELLE CANDIDATURE STAFF RECUE**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Candidat :** {user.first_name}\n"
            f"🆔 **ID :** `{uid}`\n"
            f"🏷️ **Username :** @{user.username or 'Aucun'}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            "Attribuez un rôle directement à ce membre :"
        )
        kb_admin = [
            [InlineKeyboardButton("Promouvoir Gérant ⚡", callback_data=f"staff:promouvoir:{uid}:gerant")],
            [InlineKeyboardButton("Promouvoir Modérateur 🛡️", callback_data=f"staff:promouvoir:{uid}:mod")],
            [InlineKeyboardButton("Refuser la demande ❌", callback_data=f"staff:refuser:{uid}")]
        ]
        
        try:
            await ctx.bot.send_message(
                chat_id=SUPER_ADMIN_ID,
                text=ticket_staff,
                reply_markup=InlineKeyboardMarkup(kb_admin),
                parse_mode="Markdown"
            )
            await query.message.edit_text("✅ **Votre candidature a été transmise au Fondateur.** Vous recevrez une notification en cas de validation.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Mon Profil", callback_data="menu:mon_profil")]]))
        except Exception:
            await query.message.edit_text("❌ Erreur lors de l'envoi de la demande. Réessayez plus tard.")

    elif data.startswith("staff:promouvoir:"):
        # Seul le super admin peut promouvoir
        if uid != SUPER_ADMIN_ID:
            return
            
        params = data.split(":")
        target_uid = int(params[2])
        nouveau_role = params[3]

        db.users.update_one({"_id": target_uid}, {"$set": {"role": nouveau_role}}, upsert=True)
        await query.message.edit_text(f"✅ L'utilisateur `{target_uid}` a été promu au rang de : `{nouveau_role}`.")

        # Notifier l'utilisateur en privé
        try:
            await ctx.bot.send_message(
                chat_id=target_uid,
                text=f"🎉 **Félicitations !** Votre candidature a été acceptée par le Fondateur. Vous êtes maintenant **{nouveau_role.upper()}** sur la plateforme !",
                parse_mode="Markdown"
            )
        except Exception: pass

    elif data.startswith("staff:refuser:"):
        if uid != SUPER_ADMIN_ID: return
        target_uid = int(data.split(":")[2])
        await query.message.edit_text("❌ Candidature refusée.")
        
        try:
            await ctx.bot.send_message(
                chat_id=target_uid,
                text="⚠️ Votre demande pour intégrer l'équipe du staff n'a pas été retenue pour le moment.",
                parse_mode="Markdown"
            )
        except Exception: pass

    elif data == "staff:infos_reglement":
        text_regles = (
            "🛡️ **PANNEAU ET RÈGLEMENT DU STAFF**\n\n"
            "En tant que membre de l'équipe, vous devez :\n"
            "1. Rester poli et neutre lors des litiges.\n"
            "2. Vérifier scrupuleusement les preuves d'achat avant de valider une transaction.\n"
            "3. Signaler tout comportement suspect au Fondateur."
        )
        await query.message.edit_text(text_regles, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour Profil", callback_data="menu:mon_profil")]]))
