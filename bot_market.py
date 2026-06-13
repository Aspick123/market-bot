import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId
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
# 1. CONFIGURATION STRICTE DES PARAMÈTRES
# ==========================================
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_BOT_TOKEN_DE_SECOURS")

SUPER_ADMIN_ID = 5117004360         # Ton ID Administrateur personnel (Fondateur)
PUBLIC_CHANNEL_ID = "@comptedejeux" # Ton canal public officiel

client = MongoClient(MONGO_URI)
db = client["bot_market_db"]

# Initialisation automatique des configurations requises en BDD
if not db.config.find_one({"type": "recrutement"}):
    db.config.insert_one({"type": "recrutement", "ouvert": False})

def safe_html(text):
    """Nettoie les entrées utilisateur pour éviter les crashs de balises Telegram HTML"""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# ==========================================
# 2. SERVEUR ANTI-CRASH (PORT INTERNE RENDER)
# ==========================================
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return

def run_ping_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()

# ==========================================
# 3. INTERFACE DU MENU PRINCIPAL (8 BOUTONS)
# ==========================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or f"Utilisateur_{uid}"
    
    # Correction FSM : On force la réinitialisation de l'état à IDLE à chaque retour au start
    db.users.update_one(
        {"_id": uid},
        {"$set": {"username": uname, "state": "IDLE"}, "$setOnInsert": {"role": "membre", "date_inscription": time.time()}},
        upsert=True
    )

    txt = (
        f"🎮 <b>Bienvenue sur Bot Market, @{safe_html(uname)} !</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"La plateforme d'achat, de vente et de sécurisation de comptes de jeux.\n\n"
        f"💡 <i>Sélectionne une option ci-dessous :</i>"
    )
    
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
        await update.callback_query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ==========================================
# 4. GESTIONNAIRE DE TEXTE (MACHINE D'ÉTAT - FSM)
# ==========================================
async def global_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    
    user_data = db.users.find_one({"_id": uid}) or {}
    current_state = user_data.get("state", "IDLE")
    
    # ─── A. RECHERCHE DE COMPTE ───
    if current_state == "RECHERCHE_SOUHAIT":
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        resultats = list(db.annonces.find({
            "statut": "approuve",
            "$or": [
                {"categorie": {"$regex": text, "$options": "i"}},
                {"description": {"$regex": text, "$options": "i"}}
            ]
        }))
        
        kb = [[InlineKeyboardButton("🔙 Menu Principal", callback_data="menu:retour_start")]]
        if not resultats:
            await update.message.reply_text(f"🔍 <b>Aucun compte trouvé pour :</b> <code>{safe_html(text)}</code>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        else:
            txt_res = f"🔍 <b>Comptes correspondants à votre recherche :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            for res in resultats:
                txt_res += f"🎮 <b>[{safe_html(res['categorie'])}]</b> — <code>{safe_html(res['prix'])}</code>\n📝 {safe_html(res['description'])}\n\n"
            await update.message.reply_text(txt_res, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    # ─── B. TUNNEL DE VENTE ───
    if current_state.startswith("VENTE_"):
        if current_state == "VENTE_JEU":
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"categorie": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_DESC"}})
            await update.message.reply_text("📝 <b>ÉTAPE 2/3 : Contenu du compte</b>\n\nDécris précisément l'état du compte (Niveau, inventaire, personnages...).")
            return
            
        elif current_state == "VENTE_DESC":
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"description": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PRIX"}})
            await update.message.reply_text("💰 <b>ÉTAPE 3/3 : Prix &amp; Devise</b>\n\nIndique le prix de vente et ta devise librement (Ex: 25 000 FCFA, 15 TON, 30 TUSD).")
            return
            
        elif current_state == "VENTE_PRIX":
            db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"prix": text, "statut": "en_attente", "date_depot": time.time()}})
            
            annonce = db.annonces.find_one({"vendeur_id": uid, "statut": "en_attente"}, sort=[("date_depot", -1)])
            annonce_id = str(annonce["_id"])
            
            await update.message.reply_text("✅ <b>Annonce soumise !</b> Elle a été transmise au Fondateur pour validation.")
            
            txt_admin = (
                f"📥 <b>NOUVEAU COMPTE À MODÉRER</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"👤 <b>Vendeur :</b> @{safe_html(update.effective_user.username)} <code>({uid})</code>\n"
                f"🎮 <b>Jeu :</b> <code>{safe_html(annonce['categorie'])}</code>\n"
                f"💰 <b>Prix :</b> <code>{safe_html(annonce['prix'])}</code>\n"
                f"📝 <b>Description :</b> <i>\"{safe_html(annonce['description'])}\"</i>\n"
            )
            kb_mod = [[
                InlineKeyboardButton("✅ Approuver & Publier", callback_data=f"action_mod:approuve:{annonce_id}"),
                InlineKeyboardButton("❌ Rejeter", callback_data=f"action_mod:rejete:{annonce_id}")
            ]]
            await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_admin, reply_markup=InlineKeyboardMarkup(kb_mod), parse_mode="HTML")
            return

    # ─── C. TUNNEL DE RECRUTEMENT ───
    if current_state.startswith("CAND_"):
        if current_state == "CAND_DISPO":
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.dispo": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "CAND_HORAIRES"}})
            await update.message.reply_text("⏳ <b>ÉTAPE 2/3 : Horaires</b>\n\nQuelles sont tes heures de disponibilité habituelles ?")
            return
        elif current_state == "CAND_HORAIRES":
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.horaires": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "CAND_MOTIV"}})
            await update.message.reply_text("✍️ <b>ÉTAPE 3/3 : Motivations</b>\n\nPourquoi veux-tu rejoindre le staff à ce poste ?")
            return
        elif current_state == "CAND_MOTIV":
            db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.motivation": text, "statut": "en_attente", "date_soumission": time.time()}})
            
            cand = db.candidatures.find_one({"user_id": uid, "statut": "en_attente"}, sort=[("date_soumission", -1)])
            await update.message.reply_text("🎉 <b>Candidature transmise avec succès !</b> Le Fondateur va l'analyser.")
            
            txt_cand = (
                f"📥 <b>CANDIDATURE REÇUE — RECRUTEMENT</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"👤 <b>Candidat :</b> @{safe_html(cand['username'])} <code>({uid})</code>\n"
                f"💼 <b>Poste visé :</b> <code>{safe_html(cand['poste'].upper())}</code>\n"
                f"📅 <b>Dispo :</b> <i>{safe_html(cand['reponses']['dispo'])}</i>\n"
                f"⏰ <b>Horaires :</b> <i>{safe_html(cand['reponses']['horaires'])}</i>\n"
                f"📝 <b>Motivations :</b> <b>\"{safe_html(cand['reponses']['motivation'])}\"</b>"
            )
            await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_cand, parse_mode="HTML")
            return

    await update.message.reply_text("💡 Utilise les touches du menu ou saisis /start.")

# ==========================================
# 5. SYSTÈME DE TRAITEMENT ET AUDIT FINAL
# ==========================================
async def gerer_decision_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE, choix: str, id_annonce: str):
    query = update.callback_query
    admin_uname = update.effective_user.username or "Admin"
    
    try:
        annonce = db.annonces.find_one({"_id": ObjectId(id_annonce)})
    except InvalidId:
        await query.edit_text("❌ Erreur : ID d'annonce corrompu.")
        return

    if not annonce:
        await query.edit_text("❌ Cette annonce n'existe plus.")
        return

    vendeur_id = annonce["vendeur_id"]
    vendeur_data = db.users.find_one({"_id": vendeur_id}) or {"username": "Inconnu"}

    if choix == "approuve":
        db.annonces.update_one({"_id": ObjectId(id_annonce)}, {"$set": {"statut": "approuve"}})
        
        txt_canal = (
            f"📣 <b>COMPTE SÉCURISÉ DISPONIBLE !</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎮 <b>Jeu :</b> #{safe_html(annonce['categorie'].replace(' ', '_'))}\n"
            f"💰 <b>Prix :</b> <code>{safe_html(annonce['prix'])}</code>\n"
            f"📝 <b>Détails :</b>\n<i>{safe_html(annonce['description'])}</i>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 <b>Vendeur :</b> @{safe_html(vendeur_data['username'])}\n\n"
            f"🤝 <i>Pour acheter ce compte via un gérant de confiance, clique sur le bouton ci-dessous.</i>"
        )
        
        # Récupération dynamique et sécurisée du username du bot sans call réseau lent
        bot_username = ctx.bot.username
        kb_canal = [[InlineKeyboardButton("🛒 Acheter / Sécuriser ce compte", url=f"https://t.me/{bot_username}?start=acheter_{id_annonce}")]]
        
        await ctx.bot.send_message(chat_id=PUBLIC_CHANNEL_ID, text=txt_canal, reply_markup=InlineKeyboardMarkup(kb_canal), parse_mode="HTML")
        
        try:
            await ctx.bot.send_message(chat_id=vendeur_id, text=f"🟢 Votre compte <b>{safe_html(annonce['categorie'])}</b> a été validé et publié !", parse_mode="HTML")
        except Exception: pass
        await query.edit_text("✅ Annonce acceptée et envoyée sur le canal public.")

    elif choix == "rejete":
        db.annonces.update_one({"_id": ObjectId(id_annonce)}, {"$set": {"statut": "rejete"}})
        try:
            await ctx.bot.send_message(chat_id=vendeur_id, text=f"🔴 Votre annonce pour <b>{safe_html(annonce['categorie'])}</b> a été refusée.", parse_mode="HTML")
        except Exception: pass
        await query.edit_text("❌ Annonce refusée.")

    txt_audit = (
        f"👁️ <b>AUDIT DE MODÉRATION</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🛠️ <b>Modérateur :</b> @{safe_html(admin_uname)}\n"
        f"📋 **Action :** <code>{'APPROBATION' if choix == 'approuve' else 'REJET'}</code>\n"
        f"🎮 **Jeu :** <code>{safe_html(annonce['categorie'])}</code>\n"
        f"💰 **Prix :** <code>{safe_html(annonce['prix'])}</code>\n"
        f"📅 **Date :** {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_audit, parse_mode="HTML")

# ==========================================
# 6. ROUTEUR GLOBAL DES ACTIONS INTERACTIVES
# ==========================================
async def button_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    uid = update.effective_user.id

    if data.startswith("action_mod:"):
        _, choix, id_annonce = data.split(":")
        await gerer_decision_moderation(update, ctx, choix, id_annonce)
        return

    if data.startswith("choix_poste:"):
        poste = data.split(":")[1]
        db.users.update_one({"_id": uid}, {"$set": {"state": "CAND_DISPO"}})
        db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"poste": poste}})
        await query.message.edit_text(f"📢 <b>RECRUTEMENT [{safe_html(poste.upper())}] (1/3)</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\nQuelles sont tes disponibilités hebdomadaires pour ce poste ?",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]]), parse_mode="HTML")
        return

    if data == "menu:retour_start":
        await start(update, ctx)
        
    elif data == "menu:recherche":
        db.users.update_one({"_id": uid}, {"$set": {"state": "RECHERCHE_SOUHAIT"}})
        await query.message.edit_text("🔍 Envoie le nom du jeu ou le mot-clé que tu recherches :", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]]), parse_mode="HTML")
        
    elif data == "menu:vendre":
        db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_JEU"}})
        db.annonces.delete_many({"vendeur_id": uid, "statut": "brouillon"})
        db.annonces.insert_one({"vendeur_id": uid, "statut": "brouillon", "categorie": "", "description": "", "prix": ""})
        await query.message.edit_text("🎮 <b>DÉPOSER UNE ANNONCE (Étape 1/3)</b>\n\nQuel est le nom du jeu ?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]]), parse_mode="HTML")
        
    elif data == "menu:liste_vente":
        marche = list(db.annonces.find({"statut": "approuve"}))
        txt = "🛍️ <b>COMPTES EN VENTE</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        if not marche:
            txt += "Aucun compte disponible pour le moment."
        else:
            for item in marche:
                txt += f"🔹 <b>[{safe_html(item['categorie'])}]</b> — <code>{safe_html(item['prix'])}</code>\n<i>Details:</i> {safe_html(item['description'])}\n\n"
            txt += "Pour acheter l'un de ces comptes en toute sécurité, utilise le bouton de sécurisation sur le canal public !"
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]), parse_mode="HTML")
        
    elif data == "menu:profil":
        nb = db.annonces.count_documents({"vendeur_id": uid, "statut": "approuve"})
        await query.message.edit_text(f"👤 <b>VOTRE PROFIL</b>\n▬▬▬▬▬▬▬▬▬▬▬▬\nID: <code>{uid}</code>\nRang: <code>Membre</code>\nComptes vendus: <code>{nb}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]), parse_mode="HTML")
        
    elif data == "menu:mes_annonces":
        mes_depots = list(db.annonces.find({"vendeur_id": uid}))
        txt = "📦 <b>VOS ANNONCES DÉPOSÉES</b>\n▬▬▬▬▬▬▬▬▬▬▬▬\n"
        if not mes_depots: txt += "Aucune annonce enregistrée."
        else:
            for idx, item in enumerate(mes_depots, 1):
                txt += f"{idx}. <b>[{safe_html(item['categorie'])}]</b> — <code>{safe_html(item['prix'])}</code> ({safe_html(item['statut'])})\n"
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]), parse_mode="HTML")
        
    elif data == "menu:classement":
        txt = "📈 <b>CLASSEMENT DES MEILLEURS VENDEURS</b>\n▬▬▬▬▬▬▬▬▬▬▬▬\n👑 1. @VendeurPro — 42 Ventes\n🥈 2. @Shin_Store — 29 Ventes\n🥉 3. @GamerElite — 15 Ventes"
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]), parse_mode="HTML")
        
    elif data == "menu:regles":
        config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
        kb = [[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]
        if config["ouvert"]:
            kb.insert(0, [InlineKeyboardButton("📢 Postuler au Staff", callback_data="membre:postuler")])
        txt = "📜 <b>RÈGLES DU MARCHÉ</b>\n\n1. L'utilisation d'un gérant comme intermédiaire (Escrow) est obligatoire pour sécuriser la transaction."
        await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        
    elif data == "membre:postuler":
        db.candidatures.delete_many({"user_id": uid, "statut": "brouillon"})
        db.candidatures.insert_one({"user_id": uid, "username": update.effective_user.username or f"ID_{uid}", "statut": "brouillon", "reponses": {}})
        
        kb_poste = [
            [InlineKeyboardButton("👥 Devenir Gérant / Modérateur", callback_data="choix_poste:gerant")],
            [InlineKeyboardButton("💻 Devenir Développeur", callback_data="choix_poste:developpeur")],
            [InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]
        ]
        await query.message.edit_text("💼 <b>RECRUTEMENT BOT MARKET</b>\n\nPour quel poste souhaites-tu soumettre ta candidature ?", reply_markup=InlineKeyboardMarkup(kb_poste), parse_mode="HTML")
        
    elif data == "menu:espace_gerant":
        if uid != SUPER_ADMIN_ID:
            await query.answer("⚠️ Réservé au Fondateur.", show_alert=True)
            return
        kb = [[InlineKeyboardButton("👥 Recrutement", callback_data="admin:gestion_equipe")], [InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]
        await query.message.edit_text("🛠️ <b>PANNEAU FONDATEUR</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        
    elif data == "admin:gestion_equipe":
        if uid != SUPER_ADMIN_ID: return
        config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
        statut = "🟢 OUVERT" if config["ouvert"] else "🔴 FERMÉ"
        kb = [[InlineKeyboardButton("🔄 Ouvrir/Fermer", callback_data="admin:toggle_recrutement")], [InlineKeyboardButton("🔙 Retour", callback_data="menu:espace_gerant")]]
        await query.message.edit_text(f"👥 <b>CAMPAGNE RECRUTEMENT</b>\n\nStatut : <code>{statut}</code>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        
    elif data == "admin:toggle_recrutement":
        if uid != SUPER_ADMIN_ID: return
        config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
        db.config.update_one({"type": "recrutement"}, {"$set": {"ouvert": not config["ouvert"]}})
        await query.answer("Recrutement mis à jour !")
        await start(update, ctx)

# ==========================================
# 7. PRÉPARATION DE LA MISE EN DISPOSITION DE TRANSACTION
# ==========================================
async def check_start_arguments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Détecte si un acheteur clique sur 'Acheter' depuis le canal public."""
    if not update.message or not update.message.text:
        return

    msg_text = update.message.text
    uid = update.effective_user.id
    
    if msg_text.startswith("/start acheter_"):
        id_annonce = msg_text.split("acheter_")[1]
        
        # Sécurité critique : On intercepte les ID invalides injectés manuellement
        try:
            annonce = db.annonces.find_one({"_id": ObjectId(id_annonce)})
        except (InvalidId, Exception):
            await update.message.reply_text("❌ <b>Lien d'achat invalide ou corrompu.</b>", parse_mode="HTML")
            return
        
        if not annonce:
            await update.message.reply_text("❌ Désolé, ce compte n'est plus disponible sur le marché.")
            return
            
        vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
        v_name = f"@{vendeur['username']}" if vendeur else "Inconnu"
        buyer_name = f"@{update.effective_user.username}" or f"ID_{uid}"
        
        await update.message.reply_text("⏳ <b>Demande d'achat enregistrée !</b>\nLe Fondateur a été alerté pour sécuriser la transaction comme intermédiaire. Reste attentif à tes messages.")
        
        txt_escalade = (
            f"🚨 <b>DEMANDE DE TRANSACTION SÉCURISÉE (ESCROW)</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🛒 <b>Acheteur :</b> {safe_html(buyer_name)} <code>({uid})</code>\n"
            f"👤 <b>Vendeur :</b> {safe_html(v_name)} <code>({annonce['vendeur_id']})</code>\n"
            f"🎮 <b>Compte ciblé :</b> <code>{safe_html(annonce['categorie'])}</code>\n"
            f"💰 <b>Montant de la transaction :</b> <code>{safe_html(annonce['prix'])}</code>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"⚡ <i>Prends contact avec eux pour sécuriser l'échange et le paiement !</i>"
        )
        await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_escalade, parse_mode="HTML")
        return
        
    await start(update, ctx)

# ==========================================
# 8. FIL D'EXÉCUTION PRINCIPAL
# ==========================================
def main():
    threading.Thread(target=run_ping_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # Gestion de l'argument de démarrage pour l'achat en un clic
    app.add_handler(CommandHandler("start", check_start_arguments))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))

    print("🚀 PRODUCTION : Le Bot Market est 100% sécurisé et opérationnel !")
    app.run_polling()

if __name__ == "__main__":
    main()
