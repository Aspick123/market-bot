import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ==========================================
# 1. CONFIGURATION ET CONNEXION BASE DE DONNÉES
# ==========================================
# Remplace ces valeurs par tes propres configurations
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
BOT_TOKEN = os.getenv("BOT_TOKEN", "TON_TELEGRAM_BOT_TOKEN")
SUPER_ADMIN_ID = 123456789  # ⚠️ REMPLACE PAR TON PROPRE ID TELEGRAM (FONDANTEUR)

client = MongoClient(MONGO_URI)
db = client["bot_market_db"]

# ==========================================
# 2. MINI-SERVEUR DE PING (CORRECTION CRON-JOB)
# ==========================================
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")  # Réponse ultra-légère pour éviter l'échec "sortie trop grande"

    def log_message(self, format, *args):
        return # Désactive les logs d'accès pour économiser la mémoire

def run_ping_server():
    # Écoute sur le port fourni par Render (par défaut 8080)
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    print(self_name := f"🚀 Serveur de Ping actif sur le port {port}")
    server.serve_forever()

# ==========================================
# 3. LOGIQUE DU PANNEAU DE CONTRÔLE & RECRUTEMENT
# ==========================================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Menu principal du bot."""
    txt = "🎮 **Bienvenue sur Bot Market !**\n\nSélectionnez une option ci-dessous :"
    kb = [
        [InlineKeyboardButton("🔍 Recherche", callback_data="menu:recherche"), 
         InlineKeyboardButton("🎮 Vendre un compte", callback_data="menu:vendre")],
        [InlineKeyboardButton("📜 Règles & CGU", callback_data="menu:regles")],
        [InlineKeyboardButton("⚡ Panneau Administration ⚡", callback_data="menu:espace_gerant")]
    ]
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_espace_gerant(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Espace accessible uniquement aux gérants et au Super Admin."""
    query = update.callback_query
    uid = update.effective_user.id
    
    user_data = db.users.find_one({"_id": uid}) or {}
    is_moderateur = user_data.get("role") == "moderateur"
    
    if not is_moderateur and uid != SUPER_ADMIN_ID:
        await query.answer("⚠️ Section réservée aux gérants de l'équipe.", show_alert=True)
        return

    txt = (
        f"🛠️ **PANNEAU DE CONTRÔLE GÉRANT**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"Bienvenue dans l'espace opérationnel.\n\n"
        f"Choisissez une action :"
    )
    kb = [[InlineKeyboardButton("💼 Mon Portefeuille Gérant", callback_data="gerant:portefeuille")]]
    
    # Menu exclusif pour toi (Le Fondateur)
    if uid == SUPER_ADMIN_ID:
        kb.append([InlineKeyboardButton("👥 Gestion Équipe & Candidatures", callback_data="admin:gestion_equipe")])
        
    kb.append([InlineKeyboardButton("🔙 Retour Menu Principal", callback_data="menu:retour_start")])
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_gestion_equipe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Gestion du statut de recrutement et vue globale (Super Admin uniquement)."""
    query = update.callback_query
    uid = update.effective_user.id
    
    if uid != SUPER_ADMIN_ID:
        await query.answer("Accès refusé.")
        return

    config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
    statut = "🟢 OUVERT" if config["ouvert"] else "🔴 FERMÉ"
    nb_candidatures = db.candidatures.count_documents({"statut": "en_attente"})
    
    txt = (
        f"👥 **CHEF D'ÉQUIPE — GESTION DES GÉRANTS**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📢 **Campagne de recrutement :** `{statut}`\n"
        f"📥 **Candidatures anonymes en attente :** `{nb_candidatures}`\n\n"
        f"Faites votre choix :"
    )
    kb = [
        [InlineKeyboardButton("🔄 Ouvrir/Fermer le Recrutement", callback_data="admin:toggle_recrutement")],
        [InlineKeyboardButton(f"📥 Consulter les dossiers ({nb_candidatures})", callback_data="admin:voir_candidatures")],
        [InlineKeyboardButton("🔙 Retour", callback_data="menu:espace_gerant")]
    ]
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def toggle_recrutement(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inverse l'état d'ouverture du recrutement."""
    query = update.callback_query
    if update.effective_user.id != SUPER_ADMIN_ID: return
    
    config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
    nouvel_etat = not config["ouvert"]
    db.config.update_one({"type": "recrutement"}, {"$set": {"ouvert": nouvel_etat}}, upsert=True)
    
    await query.answer(f"Le recrutement est désormais {'Ouvert 🟢' if nouvel_etat else 'Fermé 🔴'}", show_alert=True)
    await menu_gestion_equipe(update, ctx)

# ==========================================
# 4. TUNNEL DE RECRUTEMENT ANONYME (STATE MACHINE)
# ==========================================

async def menu_regles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Affiche les règles et le bouton de candidature si actif."""
    query = update.callback_query
    txt = "📜 **RÈGLES ET CONDITIONS GÉNÉRALES D'UTILISATION**\n\nRespectez les acheteurs et vendeurs..."
    
    kb = [[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]
    
    # Si le recrutement est ouvert, on insère dynamiquement le bouton postuler
    config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
    if config["ouvert"]:
        kb.insert(0, [InlineKeyboardButton("📢 Postuler anonymement comme Gérant", callback_data="membre:postuler")])
        
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def membre_postuler_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Initialise le formulaire de candidature."""
    query = update.callback_query
    uid = update.effective_user.id
    
    deja_existe = db.candidatures.find_one({"user_id": uid, "statut": {"$in": ["en_attente", "approuve"]}})
    if deja_existe:
        await query.answer("⚠️ Vous avez déjà une candidature en cours ou validée.", show_alert=True)
        return
        
    db.candidatures.delete_many({"user_id": uid, "statut": "brouillon"})
    db.candidatures.insert_one({
        "user_id": uid,
        "username": update.effective_user.username or f"ID_{uid}",
        "statut": "brouillon",
        "etape": "ATTENTE_DISPO",
        "reponses": {}
    })
    
    txt = (
        "📢 **RECRUTEMENT GÉRANT — ÉTAPE 1/3**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "L'anonymat de votre identité réelle est préservé. Seul votre parcours nous intéresse. 👍\n\n"
        "❓ **Question 1 : Quelles sont vos disponibilités hebdomadaires ?**\n"
        "_(Exemple : Tous les jours, uniquement les weekends, 4 jours par semaine...)_\n\n"
        "👉 _Envoyez votre réponse directement par texte._"
    )
    kb = [[InlineKeyboardButton("❌ Annuler", callback_data="candidature:annuler")]]
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def gestionnaire_texte_candidature(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Intercepte les textes de l'utilisateur s'il est dans le tunnel de recrutement."""
    uid = update.effective_user.id
    text_recu = update.message.text
    
    cand = db.candidatures.find_one({"user_id": uid, "statut": "brouillon"})
    if not cand:
        return False # Laisse le bot gérer le message normalement si aucun brouillon

    etape = cand.get("etape")
    
    if etape == "ATTENTE_DISPO":
        db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.dispo": text_recu, "etape": "ATTENTE_HORAIRES"}})
        await update.message.reply_text("⏳ **ÉTAPE 2/3 : Vos Horaires**\n\n❓ **Quelles sont vos tranches horaires de disponibilité au cours de la journée ?**\n_(Exemple : En soirée de 18h à 23h, l'après-midi, etc...)_")
        return True

    elif etape == "ATTENTE_HORAIRES":
        db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.horaires": text_recu, "etape": "ATTENTE_MOTIV"}})
        await update.message.reply_text("✍️ **ÉTAPE 3/3 : Vos Motivations**\n\n❓ **Donnez-nous vos motivations ou votre expérience (Même brève) sur Telegram ?**\n_(Pourquoi devrions-nous valider votre profil ?)_")
        return True

    elif etape == "ATTENTE_MOTIV":
        db.candidatures.update_one(
            {"user_id": uid, "statut": "brouillon"},
            {"$set": {"reponses.motivation": text_recu, "statut": "en_attente", "date_soumission": time.time()}, "$unset": {"etape": ""}}
        )
        
        cand_complete = db.candidatures.find_one({"user_id": uid, "statut": "en_attente"})
        reponses = cand_complete["reponses"]
        
        kb = [[InlineKeyboardButton("🔙 Menu Principal", callback_data="menu:retour_start")]]
        await update.message.reply_text("🎉 **Candidature enregistrée !**\n\nLe Fondateur examinera vos réponses. S'il valide votre profil, vous serez contacté. Merci !", reply_markup=InlineKeyboardMarkup(kb))
        
        # 🚨 TRANSFERT PRIVÉ IMMÉDIAT AU SUPER ADMIN
        txt_notif_admin = (
            f"📥 **NOUVELLE CANDIDATURE REÇUE**\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Candidat :** @{cand_complete['username']} `({uid})`\n"
            f"📅 **Date :** {time.strftime('%Y-%m-%d %H:%M')}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"📅 **Disponibilités :**\n_{reponses['dispo']}_\n\n"
            f"⏰ **Horaires :**\n_{reponses['horaires']}_\n\n"
            f"📝 **Motivations :**\n*\"{reponses['motivation']}\"*\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"⚡ _Rendez-vous dans le panneau équipe pour prendre votre décision._"
        )
        await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_notif_admin, parse_mode="Markdown")
        return True

    return False

async def candidature_annuler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    db.candidatures.delete_many({"user_id": update.effective_user.id, "statut": "brouillon"})
    await query.answer("Candidature annulée et effacée.", show_alert=True)
    await start(update, ctx)

# ==========================================
# 5. MODULE D'AUDIT EN DIRECT (TRANSACTIONS / MODÉRATION)
# ==========================================

async def traitement_moderation_exemple(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Exemple de fonction d'action d'un gérant.
    À intégrer à l'endroit exact où un gérant clique sur 'Approuver' ou 'Rejeter' une annonce.
    """
    query = update.callback_query
    gerant_id = update.effective_user.id
    username_gerant = update.effective_user.username or "Inconnu"
    
    # (Simulations de variables pour l'exemple)
    action = "approuver" # ou 'rejeter'
    annonce_id = "ABC123XYZ"
    vendeur_id = 987654321
    categorie_jeu = "Genshin Impact"
    prix_annonce = 150
    description_annonce = "Compte AR55 avec 5 personnages 5 étoiles, première main."
    
    # ─── Logique de modification de l'annonce en BDD ici ───
    # Exemple : db.annonces.update_one(...)
    
    # 🚨 NOTIFICATION D'AUDIT STRICTEMENT ENVOYÉE AU SUPER ADMIN (DMs)
    txt_audit = (
        f"👁️ **AUDIT GÉRANT — CONTRÔLE DE SÉCURITÉ**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🛠️ **Gérant en action :** @{username_gerant} `({gerant_id})`\n"
        f"📋 **Action exécutée :** `{'ÉLECTION / APPROBATION ✅' if action == 'approuver' else 'REJET ET SUPPRESSION ❌'}`\n"
        f"🆔 **ID de l'Annonce :** `{annonce_id}`\n"
        f"🎮 **Jeu concerné :** `{categorie_jeu}`\n"
        f"💰 **Valeur affichée :** `{prix_annonce} TON / FCFA`\n"
        f"👤 **Vendeur ID :** `{vendeur_id}`\n"
        f"📅 **Horodatage :** {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📝 **Contenu de la transaction :**\n*\"{description_annonce}\"*"
    )
    
    await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_audit, parse_mode="Markdown")
    await query.answer("Action enregistrée et auditée.", show_alert=True)

# ==========================================
# 6. ROUTAGE ET GESTION DES REQUÊTES GLOBAL
# ==========================================

async def global_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Routeur de texte global pour intercepter la machine d'état."""
    deja_traite = await gestionnaire_texte_candidature(update, ctx)
    if deja_traite:
        return
    
    # S'il n'est pas en train de postuler, le bot traite le texte normal ici
    await update.message.reply_text("Message reçu ! Utilisez les boutons du menu pour naviguer.")

async def button_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Routeur central des boutons Callback."""
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "menu:retour_start":
        # Recréer le message d'accueil
        txt = "🎮 **Bienvenue sur Bot Market !**\n\nSélectionnez une option ci-dessous :"
        kb = [
            [InlineKeyboardButton("🔍 Recherche", callback_data="menu:recherche"), InlineKeyboardButton("🎮 Vendre un compte", callback_data="menu:vendre")],
            [InlineKeyboardButton("📜 Règles & CGU", callback_data="menu:regles")],
            [InlineKeyboardButton("⚡ Panneau Administration ⚡", callback_data="menu:espace_gerant")]
        ]
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data == "menu:espace_gerant":
        await menu_espace_gerant(update, ctx)
    elif data == "admin:gestion_equipe":
        await menu_gestion_equipe(update, ctx)
    elif data == "admin:toggle_recrutement":
        await toggle_recrutement(update, ctx)
    elif data == "menu:regles":
        await menu_regles(update, ctx)
    elif data == "membre:postuler":
        await membre_postuler_handler(update, ctx)
    elif data == "candidature:annuler":
        await candidature_annuler(update, ctx)
    # Ajoute tes autres redirections de boutons ici...

# ==========================================
# 7. LANCEMENT DE L'APPLICATION
# ==========================================
def main():
    # A. Lancement du serveur Web de ping en arrière-plan (Thread séparé)
    ping_thread = threading.Thread(target=run_ping_server, daemon=True)
    ping_thread.start()

    # B. Initialisation et configuration du Bot Telegram
    app = Application.builder().token(BOT_TOKEN).build()

    # Enregistrement des commandes et handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))

    print("🤖 Le Bot Market est en cours d'exécution...")
    app.run_polling()

if __name__ == "__main__":
    main()
