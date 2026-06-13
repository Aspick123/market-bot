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
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
# Utilise directement la variable existante sur ton Render
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_BOT_TOKEN_SECOURS") 
SUPER_ADMIN_ID = 123456789  # ⚠️ METS TON PROPRE ID TELEGRAM ICI

client = MongoClient(MONGO_URI)
db = client["bot_market_db"]

# Initialisation rapide des configurations par défaut en BDD
if not db.config.find_one({"type": "recrutement"}):
    db.config.insert_one({"type": "recrutement", "ouvert": False})

# ==========================================
# 2. SERVEUR DE PING POUR CRON-JOB.ORG (ÉVITE LES ERREURS SORTIE TROP GRANDE)
# ==========================================
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")  # Réponse ultra-légère (2 octets) pour cron-job

    def log_message(self, format, *args):
        return # Coupe les logs pour préserver la mémoire

def run_ping_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()

# ==========================================
# 3. INTERFACES GRAPHIQUES (MENUS)
# ==========================================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Affiche le menu principal complet avec les 8 boutons d'origine."""
    uid = update.effective_user.id
    uname = update.effective_user.username or "Acheteur/Vendeur"
    
    # Enregistrement automatique de l'utilisateur s'il est nouveau
    if not db.users.find_one({"_id": uid}):
        db.users.insert_one({"_id": uid, "username": uname, "role": "membre", "date_inscription": time.time()})

    txt = (
        f"🎮 **Bienvenue sur Bot Market, @{uname} !**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"La plateforme sécurisée pour l'achat et la vente de vos comptes de jeux (Genshin, eFootball, etc.).\n\n"
        f"💡 _Sélectionnez une option ci-dessous pour commencer :_"
    )
    
    # Configuration exacte de ton menu d'origine (Grille 2x2)
    kb = [
        [InlineKeyboardButton("🔍 Recherche", callback_data="menu:recherche"), 
         InlineKeyboardButton("🎮 Vendre un compte", callback_data="menu:vendre")],
        [InlineKeyboardButton("🛍️ Liste de vente", callback_data="menu:liste_vente")],
        [InlineKeyboardButton("👤 Mon Profil", callback_data="menu:profil"), 
         InlineKeyboardButton("📦 Mes Annonces", callback_data="menu:mes_annonces")],
        [InlineKeyboardButton("📜 Règles & CGU", callback_data="menu:regles"), 
         InlineKeyboardButton("📈 Classement", callback_data="menu:classement")],
        [InlineKeyboardButton("⚡ Panneau Administration ⚡", callback_data="menu:espace_gerant")]
    ]
    
    if update.callback_query:
        await update.callback_query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ==========================================
# 4. GESTION DES FONCTIONNALITÉS DU MARCHÉ
# ==========================================

async def menu_profil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    user_data = db.users.find_one({"_id": uid}) or {}
    
    nb_annonces = db.annonces.count_documents({"vendeur_id": uid})
    role = user_data.get("role", "membre").upper()
    
    txt = (
        f"👤 **VOTRE PROFIL BOT MARKET**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🆔 **ID Utilisateur :** `{uid}`\n"
        f"🎖️ **Rang / Rôle :** `{role}`\n"
        f"📦 **Annonces déposées :** `{nb_annonces}`\n\n"
        f"🤝 _Merci de faire confiance à notre communauté anonyme._"
    )
    kb = [[InlineKeyboardButton("🔙 Retour Menu", callback_data="menu:retour_start")]]
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_liste_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    annonces_actives = list(db.annonces.find({"statut": "approuve"}).limit(10))
    
    if not annonces_actives:
        txt = "🛍️ **LISTE DES COMPTES EN VENTE**\n\nAucun compte n'est disponible à la vente pour le moment. Repassez plus tard !"
    else:
        txt = "🛍️ **COMPTES DISPONIBLES SUR LE MARCHÉ**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        for idx, item in enumerate(annonces_actives, 1):
            txt += f"{idx}. **[{item['categorie']}]** {item['description'][:50]}... — `{item['prix']}`\n"
            
    kb = [[InlineKeyboardButton("🔙 Retour Menu", callback_data="menu:retour_start")]]
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_mes_annonces(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    mes_items = list(db.annonces.find({"vendeur_id": uid}))
    
    txt = "📦 **VOS ANNONCES DÉPOSÉES**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
    if not mes_items:
        txt += "Vous n'avez pas encore publié d'annonce."
    else:
        for idx, item in enumerate(mes_items, 1):
            statut_icon = "🟢" if item["statut"] == "approuve" else "⏳" if item["statut"] == "en_attente" else "🔴"
            txt += f"{statut_icon} **[{item['categorie']}]** — `{item['prix']}` (Statut: {item['statut']})\n"
            
    kb = [[InlineKeyboardButton("🔙 Retour Menu", callback_data="menu:retour_start")]]
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_classement(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    txt = (
        "📈 **CLASSEMENT DES TOP VENDEURS**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "👑 1. @VendeurPro — 42 Ventes\n"
        "🥈 2. @Shin_Store — 29 Ventes\n"
        "🥉 3. @GamerElite — 15 Ventes\n\n"
        "Le classement se base sur le volume de comptes certifiés vendus avec succès !"
    )
    kb = [[InlineKeyboardButton("🔙 Retour Menu", callback_data="menu:retour_start")]]
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ==========================================
# 5. CONVERSATION FSM : VENDRE UN COMPTE (SANS MODE DE PAIEMENT FIGÉ)
# ==========================================

async def vente_commencer_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    
    # Réinitialisation de l'état utilisateur
    db.users.update_one({"_id": uid}, {"$set": {"etape_vente": "ATTENTE_JEU"}})
    db.annonces.delete_many({"vendeur_id": uid, "statut": "brouillon"}) # Efface l'ancien brouillon s'il existe
    
    db.annonces.insert_one({
        "vendeur_id": uid,
        "statut": "brouillon",
        "categorie": "",
        "description": "",
        "prix": ""
    })
    
    txt = (
        "🎮 **DÉPOSER UNE ANNONCE (Étape 1/3)**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "Quel est le jeu concerné par votre compte ?\n"
        "_(Exemple : Genshin Impact, eFootball, Clash of Clans...)_\n\n"
        "👉 _Répondez en écrivant le texte directement ici._"
    )
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]]), parse_mode="Markdown")

# ==========================================
# 6. TUNNEL DE RECRUTEMENT ANONYME GÉRANT
# ==========================================

async def menu_regles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    txt = (
        "📜 **RÈGLES DE LA COMMUNAUTÉ & CGU**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "1. Les arnaques ou tentatives de double vente mènent à un bannissement définitif.\n"
        "2. Les prix doivent rester transparents.\n"
        "3. Nous respectons scrupuleusement l'anonymat de chacun.\n"
    )
    kb = [[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]
    
    # Ajout du bouton de recrutement si actif
    config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
    if config["ouvert"]:
        kb.insert(0, [InlineKeyboardButton("📢 Postuler Anonymement comme Gérant", callback_data="membre:postuler")])
        
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def membre_postuler_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    
    deja_existe = db.candidatures.find_one({"user_id": uid, "statut": {"$in": ["en_attente", "approuve"]}})
    if deja_existe:
        await query.answer("⚠️ Vous possédez déjà un dossier actif ou validé.", show_alert=True)
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
        "Votre anonymat est respecté. Seule votre rigueur compte.\n\n"
        "❓ **Question 1 : Quelles sont vos disponibilités par semaine ?**\n"
        "_(Exemple : 4 jours par semaine, les weekends uniquement...)_\n\n"
        "👉 _Envoyez votre réponse par texte._"
    )
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="candidature:annuler")]]), parse_mode="Markdown")

# ==========================================
# 7. ROUTEUR DE TEXTE GLOBAL (TRAITEMENT DES DIALOGUES INTERACTIFS)
# ==========================================

async def global_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    
    # A. VÉRIFICATION DU TUNNEL DE VENTE DE COMPTE
    user_data = db.users.find_one({"_id": uid}) or {}
    etape_vente = user_data.get("etape_vente")
    
    if etape_vente:
        if etape_vente == "ATTENTE_JEU":
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"categorie": text}})
            db.users.update_one({"_id": uid}, {"$set": {"etape_vente": "ATTENTE_DESC"}})
            await update.message.reply_text("📝 **ÉTAPE 2/3 : Description du compte**\n\nDécrivez le contenu de votre compte (Niveau, personnages, équipements, ressources...).\nSoyez précis !")
            return
            
        elif etape_vente == "ATTENTE_DESC":
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"description": text}})
            db.users.update_one({"_id": uid}, {"$set": {"etape_vente": "ATTENTE_PRIX"}})
            await update.message.reply_text("💰 **ÉTAPE 3/3 : Prix & Devise**\n\nEntrez le prix souhaité ainsi que votre devise préférée.\n_(Exemple : 15 000 FCFA, 20 TON, 30 TUSD...)_")
            return
            
        elif etape_vente == "ATTENTE_PRIX":
            # Clôture et envoi à la modération des Gérants
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"prix": text, "statut": "en_attente", "date_depot": time.time()}})
            db.users.update_one({"_id": uid}, {"$unset": {"etape_vente": ""}})
            
            # Récupération pour affichage
            annonce = db.annonces.find_one({"vendeur_id": uid, "statut": "en_attente"}, sort=[("date_depot", -1)])
            
            await update.message.reply_text("✅ **Votre annonce a été soumise avec succès !**\nElle apparaîtra sur la Marketplace dès qu'un gérant l'aura vérifiée.")
            
            # 🚨 ALERTE AUDIT PRIVÉE ENVOYÉE IMMÉDIATEMENT DANS TES MESSAGES
            txt_audit = (
                f"📥 **NOUVEAU COMPTE SOUMIS POUR MODÉRATION**\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"👤 **Vendeur :** @{update.effective_user.username} `({uid})`\n"
                f"🎮 **Jeu :** `{annonce['categorie']}`\n"
                f"💰 **Prix demandé :** `{annonce['prix']}`\n"
                f"📝 **Description :**\n_\"{annonce['description']}\"_"
            )
            await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_audit, parse_mode="Markdown")
            return

    # B. VÉRIFICATION DU TUNNEL DE CANDIDATURE GÉRANT
    cand = db.candidatures.find_one({"user_id": uid, "statut": "brouillon"})
    if cand:
        etape_cand = cand.get("etape")
        if etape_cand == "ATTENTE_DISPO":
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.dispo": text, "etape": "ATTENTE_HORAIRES"}})
            await update.message.reply_text("⏳ **ÉTAPE 2/3 : Vos Horaires**\n\n❓ **Quelles tranches horaires couvrez-vous en général pendant la journée ?**")
            return
        elif etape_cand == "ATTENTE_HORAIRES":
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.horaires": text, "etape": "ATTENTE_MOTIV"}})
            await update.message.reply_text("✍️ **ÉTAPE 3/3 : Motivations**\n\n❓ **Pourquoi devrions-nous vous intégrer dans l'équipe des gérants ?**")
            return
        elif etape_cand == "ATTENTE_MOTIV":
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.motivation": text, "statut": "en_attente", "date_soumission": time.time()}, "$unset": {"etape": ""}})
            cand_f = db.candidatures.find_one({"user_id": uid, "statut": "en_attente"})
            
            await update.message.reply_text("🎉 **Candidature anonyme reçue !** Le Fondateur reviendra vers vous si votre profil l'intéresse.")
            
            # 🚨 ENVOI DIRECT VERS TES MESSAGES PRÉVUS POUR LE CONTRÔLE
            txt_notif = (
                f"📥 **CANDIDATURE GÉRANT ENTRANTE**\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"👤 **Candidat :** @{cand_f['username']} `({uid})`\n"
                f"📅 **Dispo :** _{cand_f['reponses']['dispo']}_\n"
                f"⏰ **Horaires :** _{cand_f['reponses']['horaires']}_\n"
                f"📝 **Lettre :** *\"{cand_f['reponses']['motivation']}\"*"
            )
            await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_notif, parse_mode="Markdown")
            return

    # Si aucune interaction en cours
    await update.message.reply_text("💡 Pour naviguer, utilisez les boutons interactifs du menu avec `/start`.")

# ==========================================
# 8. PANNEAU ADMIN ET CONTRÔLE DE L'ÉQUIPE (SUPER_ADMIN)
# ==========================================

async def menu_espace_gerant(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    
    user_data = db.users.find_one({"_id": uid}) or {}
    if user_data.get("role") != "moderateur" and uid != SUPER_ADMIN_ID:
        await query.answer("⚠️ Accès refusé : Réservé aux gérants.", show_alert=True)
        return

    txt = "🛠️ **PANNEAU ADMINISTRATIF DU STAFF**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nSélectionnez votre module :"
    kb = [[InlineKeyboardButton("📁 Modérer les annonces (Simulé)", callback_data="admin:simuler_audit")]]
    
    if uid == SUPER_ADMIN_ID:
        kb.append([InlineKeyboardButton("👥 Recrutement & Campagnes", callback_data="admin:gestion_equipe")])
        
    kb.append([InlineKeyboardButton("🔙 Menu Principal", callback_data="menu:retour_start")])
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def menu_gestion_equipe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id != SUPER_ADMIN_ID: return

    config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
    statut = "🟢 OUVERT" if config["ouvert"] else "🔴 FERMÉ"
    nb_cand = db.candidatures.count_documents({"statut": "en_attente"})
    
    txt = (
        f"👥 **GESTION RECRUTEMENT GÉRANTS**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📢 Campagne actuelle : `{statut}`\n"
        f"📥 Dossiers à examiner : `{nb_cand}`"
    )
    kb = [
        [InlineKeyboardButton("🔄 Ouvrir / Fermer la campagne", callback_data="admin:toggle_recrutement")],
        [InlineKeyboardButton("🔙 Retour Staff", callback_data="menu:espace_gerant")]
    ]
    await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def toggle_recrutement(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id != SUPER_ADMIN_ID: return
    
    config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
    nouvel_etat = not config["ouvert"]
    db.config.update_one({"type": "recrutement"}, {"$set": {"ouvert": nouvel_etat}}, upsert=True)
    
    await query.answer(f"Recrutement mis à jour : {'Ouvert 🟢' if nouvel_etat else 'Fermé 🔴'}")
    await menu_gestion_equipe(update, ctx)

async def simuler_audit_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Déclenche la copie de résumé demandée vers tes messages privés lors d'une validation."""
    query = update.callback_query
    gerant_uname = update.effective_user.username or "Gérant_Anonyme"
    
    # Simulation d'une validation d'annonce
    txt_audit = (
        f"👁️ **AUDIT GÉRANT — COPIE DE SÉCURITÉ**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🛠️ **Modérateur :** @{gerant_uname}\n"
        f"📋 **Action :** `APPROBATION ET RESTOCK ✅`\n"
        f"🎮 **Type :** `Compte eFootball Campaign`\n"
        f"💰 **Valeur enregistrée :** `25 000 FCFA`\n"
        f"📅 **Date :** {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"📝 **Résumé du contenu :** Prêt pour transfert immédiat au client."
    )
    # Redirection vers tes messages privés
    await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_audit, parse_mode="Markdown")
    await query.answer("✅ Rapport d'audit envoyé dans tes messages privés !", show_alert=True)

# ==========================================
# 9. CENTRALISATION DU ROUTAGE DES BOUTONS (CALLBACKS)
# ==========================================

async def button_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    
    if data == "menu:retour_start":
        await start(update, ctx)
    elif data == "menu:profil":
        await menu_profil(update, ctx)
    elif data == "menu:liste_vente":
        await menu_liste_vente(update, ctx)
    elif data == "menu:mes_annonces":
        await menu_mes_annonces(update, ctx)
    elif data == "menu:classement":
        await menu_classement(update, ctx)
    elif data == "menu:regles":
        await menu_regles(update, ctx)
    elif data == "menu:vendre":
        await vente_commencer_handler(update, ctx)
    elif data == "menu:espace_gerant":
        await menu_espace_gerant(update, ctx)
    elif data == "admin:gestion_equipe":
        await menu_gestion_equipe(update, ctx)
    elif data == "admin:toggle_recrutement":
        await toggle_recrutement(update, ctx)
    elif data == "admin:simuler_audit":
        await simuler_audit_handler(update, ctx)
    elif data == "membre:postuler":
        await membre_postuler_handler(update, ctx)
    elif data == "candidature:annuler":
        db.candidatures.delete_many({"user_id": update.effective_user.id, "statut": "brouillon"})
        await start(update, ctx)

# ==========================================
# 10. CORPS PRINCIPAL D'EXÉCUTION
# ==========================================
def main():
    # Étape A : Lancement du serveur Keep-Alive en arrière-plan
    threading.Thread(target=run_ping_server, daemon=True).start()

    # Étape B : Lancement du bot Telegram
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))

    print("🚀 Bot Market entièrement configuré et actif !")
    app.run_polling()

if __name__ == "__main__":
    main()
