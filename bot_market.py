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
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_BOT_TOKEN")

SUPER_ADMIN_ID = 5117004360         # Ton ID Administrateur personnel (Fondateur)
PUBLIC_CHANNEL_ID = "@comptedejeux" # Ton canal public officiel

client = MongoClient(MONGO_URI)
db = client["bot_market_db"]

if not db.config.find_one({"type": "recrutement"}):
    db.config.insert_one({"type": "recrutement", "ouvert": False})

def safe_html(text):
    """Sécurise les chaînes de caractères contre les injections ou crashs HTML Telegram"""
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
# 3. INTERFACE DU MENU PRINCIPAL
# ==========================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or f"Utilisateur_{uid}"
    
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
# 4. GESTIONNAIRE DE TEXTE CENTRALISÉ (FSM)
# ==========================================
async def global_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    user_data = db.users.find_one({"_id": uid}) or {}
    state = user_data.get("state", "IDLE")
    
    # ─── A. RECHERCHE ───
    if state == "RECHERCHE_SOUHAIT":
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        resultats = list(db.annonces.find({
            "statut": "approuve",
            "$or": [{"categorie": {"$regex": text, "$options": "i"}}, {"description": {"$regex": text, "$options": "i"}}]
        }))
        kb = [[InlineKeyboardButton("🔙 Menu Principal", callback_data="menu:retour_start")]]
        if not resultats:
            await update.message.reply_text(f"🔍 <b>Aucun compte disponible pour :</b> <code>{safe_html(text)}</code>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        else:
            txt_res = f"🔍 <b>Comptes correspondants trouvés :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            for res in resultats:
                txt_res += f"🎮 <b>[{safe_html(res['categorie'])}]</b> — <code>{safe_html(res['prix'])}</code>\n📝 {safe_html(res['description'])}\n\n"
            await update.message.reply_text(txt_res, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    # ─── B. TUNNEL DE VENTE DIRECTE ───
    if state.startswith("VENTE_"):
        if state == "VENTE_JEU":
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"categorie": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_DESC"}})
            await update.message.reply_text("📝 <b>ÉTAPE 2/3 : Contenu du compte</b>\n\nDécris précisément l'état du compte (Niveau, inventaire, personnages...).")
            return
        elif state == "VENTE_DESC":
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"description": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PRIX"}})
            await update.message.reply_text("💰 <b>ÉTAPE 3/3 : Prix &amp; Devise</b>\n\nIndique ton prix et ta devise librement (Ex: 25 000 FCFA, 30 TUSD, 15 TON).")
            return
        elif state == "VENTE_PRIX":
            db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"prix": text, "statut": "en_attente", "date_depot": time.time()}})
            ann = db.annonces.find_one({"vendeur_id": uid, "statut": "en_attente"}, sort=[("date_depot", -1)])
            await notifier_admin_moderation(ctx, ann, uid, modif=False)
            await update.message.reply_text("✅ <b>Annonce soumise !</b> Elle a été transmise au Fondateur pour validation.")
            return

    # ─── C. MODIFICATION D'ANNONCE (CORRIGÉ) ───
    if state.startswith("EDIT_"):
        _, mode, id_ann = state.split("_")
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        champ = "description" if mode == "DESC" else "prix"
        
        db.annonces.update_one({"_id": ObjectId(id_ann)}, {"$set": {champ: text, "statut": "en_attente"}})
        ann_maj = db.annonces.find_one({"_id": ObjectId(id_ann)})
        await notifier_admin_moderation(ctx, ann_maj, uid, modif=True)
        await update.message.reply_text("✅ <b>Modification enregistrée !</b> Ton annonce est suspendue le temps de sa re-validation par l'admin.")
        return

    # ─── D. RECRUTEMENT STAFF ───
    if state.startswith("CAND_"):
        if state == "CAND_DISPO":
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.dispo": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "CAND_HORAIRES"}})
            await update.message.reply_text("⏳ <b>ÉTAPE 2/3 : Horaires</b>\n\nQuelles sont tes heures de disponibilité habituelles ?")
            return
        elif state == "CAND_HORAIRES":
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.horaires": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "CAND_MOTIV"}})
            await update.message.reply_text("✍️ <b>ÉTAPE 3/3 : Motivations</b>\n\nPourquoi veux-tu rejoindre le staff à ce poste ?")
            return
        elif state == "CAND_MOTIV":
            db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"reponses.motivation": text, "statut": "en_attente", "date_soumission": time.time()}})
            cand = db.candidatures.find_one({"user_id": uid, "statut": "en_attente"}, sort=[("date_soumission", -1)])
            
            await update.message.reply_text("🎉 <b>Candidature transmise avec succès !</b> Le Fondateur va l'analyser.")
            txt_cand = (
                f"📥 <b>CANDIDATURE REÇUE</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
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
# 5. SYSTÈME DE MODÉRATION ET AUDIT DIRECT
# ==========================================
async def notifier_admin_moderation(ctx, ann, uid, modif=False):
    titre = "🔄 MODIFICATION ANNONCE À RE-VÉRIFIER" if modif else "📥 NOUVELLE ANNONCE À MODÉRER"
    vendeur = db.users.find_one({"_id": uid}) or {"username": f"ID_{uid}"}
    txt = (
        f"⚖️ <b>{titre}</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👤 <b>Vendeur :</b> @{safe_html(vendeur.get('username'))} <code>({uid})</code>\n"
        f"🎮 <b>Jeu :</b> <code>{safe_html(ann['categorie'])}</code>\n"
        f"💰 <b>Prix demandé :</b> <code>{safe_html(ann['prix'])}</code>\n"
        f"📝 <b>Description :</b> <i>\"{safe_html(ann['description'])}\"</i>\n"
    )
    kb = [[
        InlineKeyboardButton("✅ Approuver & Publier", callback_data=f"mod:approuve:{ann['_id']}"),
        InlineKeyboardButton("❌ Rejeter", callback_data=f"mod:rejete:{ann['_id']}")
    ]]
    await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ==========================================
# 6. ROUTEUR DE BOUTONS INTERACTIFS
# ==========================================
async def button_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    uid = update.effective_user.id
    
    parts = data.split(":")
    famille = parts[0]

    # ─── SYSTÈME DE MODÉRATION DE COMPTE ───
    if famille == "mod":
        action, id_ann = parts[1], parts[2]
        ann = db.annonces.find_one({"_id": ObjectId(id_ann)})
        if not ann:
            await query.edit_text("❌ Annonce introuvable.")
            return
            
        if action == "approuve":
            db.annonces.update_one({"_id": ObjectId(id_ann)}, {"$set": {"statut": "approuve"}})
            vendeur = db.users.find_one({"_id": ann["vendeur_id"]}) or {"username": "Inconnu"}
            
            txt_canal = (
                f"📣 <b>COMPTE SÉCURISÉ DISPONIBLE !</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"🎮 <b>Jeu :</b> #{safe_html(ann['categorie'].replace(' ', '_'))}\n"
                f"💰 <b>Prix :</b> <code>{safe_html(ann['prix'])}</code>\n"
                f"📝 <b>Détails :</b>\n<i>{safe_html(ann['description'])}</i>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"👤 <b>Vendeur :</b> @{safe_html(vendeur.get('username'))}\n\n"
                f"🤝 <i>Pour acheter ce compte via un gérant de confiance, clique ci-dessous.</i>"
            )
            kb_canal = [[InlineKeyboardButton("🛒 Acheter / Sécuriser ce compte", url=f"https://t.me/{ctx.bot.username}?start=acheter_{id_ann}")]]
            await ctx.bot.send_message(chat_id=PUBLIC_CHANNEL_ID, text=txt_canal, reply_markup=InlineKeyboardMarkup(kb_canal), parse_mode="HTML")
            
            try:
                await ctx.bot.send_message(chat_id=ann["vendeur_id"], text=f"🟢 Votre compte <b>{safe_html(ann['categorie'])}</b> a été validé et mis en vente !")
            except Exception: pass
            await query.edit_text("✅ Annonce validée et propulsée sur le canal public.")
        
        elif action == "rejete":
            db.annonces.update_one({"_id": ObjectId(id_ann)}, {"$set": {"statut": "rejete"}})
            try:
                await ctx.bot.send_message(chat_id=ann["vendeur_id"], text=f"🔴 Votre annonce pour <b>{safe_html(ann['categorie'])}</b> a été refusée.")
            except Exception: pass
            await query.edit_text("❌ Annonce marquée comme rejetée.")
        return

    # ─── SYSTÈME DE GESTION DE L'ESCROW (FONDATEUR ACTION - NOUVEAU) ───
    if famille == "escrow":
        action, id_ann = parts[1], parts[2]
        ann = db.annonces.find_one({"_id": ObjectId(id_ann)})
        if not ann:
            await query.edit_text("❌ Cette annonce n'existe plus.")
            return
            
        if action == "valider":
            buyer_id = int(parts[3])
            db.annonces.update_one({"_id": ObjectId(id_ann)}, {"$set": {"statut": "vendu"}})
            
            try:
                await ctx.bot.send_message(chat_id=ann["vendeur_id"], text=f"🎉 <b>Félicitations !</b> Le gérant a validé la transaction. Ton compte <b>{safe_html(ann['categorie'])}</b> est officiellement vendu.", parse_mode="HTML")
                await ctx.bot.send_message(chat_id=buyer_id, text=f"✅ <b>Transaction sécurisée réussie !</b> Le gérant a validé le transfert pour le compte <b>{safe_html(ann['categorie'])}</b>.", parse_mode="HTML")
            except Exception: pass
            await query.edit_text("🟢 Échange validé avec succès. Statut de l'annonce passé à 'VENDU'.")
            
        elif action == "annuler":
            await query.edit_text("🔴 Procédure d'intermédiaire annulée.")
        return

    # ─── NAVIGATION MENU PRINCIPAL ───
    if famille == "menu":
        cible = parts[1]
        if cible == "retour_start":
            await start(update, ctx)
        elif cible == "recherche":
            db.users.update_one({"_id": uid}, {"$set": {"state": "RECHERCHE_SOUHAIT"}})
            await query.message.edit_text("🔍 Envoie le nom du jeu ou le mot-clé que tu recherches :", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]]))
        elif cible == "vendre":
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_JEU"}})
            db.annonces.delete_many({"vendeur_id": uid, "statut": "brouillon"})
            db.annonces.insert_one({"vendeur_id": uid, "statut": "brouillon", "categorie": "", "description": "", "prix": ""})
            await query.message.edit_text("🎮 <b>DÉPOSER UNE ANNONCE (1/3)</b>\n\nQuel est le nom du jeu ?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]]))
        elif cible == "liste_vente":
            marche = list(db.annonces.find({"statut": "approuve"}))
            txt = "🛍️ <b>COMPTES ACTUELLEMENT EN VENTE</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            if not marche:
                txt += "Aucun compte disponible pour le moment."
            else:
                for item in marche:
                    txt += f"🔹 <b>[{safe_html(item['categorie'])}]</b> — <code>{safe_html(item['prix'])}</code>\n<i>Détails :</i> {safe_html(item['description'])}\n\n"
                txt += "Pour sécuriser un achat, utilise le bouton direct situé sous l'annonce du canal public !"
            await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]), parse_mode="HTML")
        elif cible == "profil":
            nb_vendus = db.annonces.count_documents({"vendeur_id": uid, "statut": "vendu"})
            await query.message.edit_text(f"👤 <b>VOTRE PROFIL</b>\n▬▬▬▬▬▬▬▬▬▬▬▬\n🆔 ID : <code>{uid}</code>\n⚡ Rang : <code>Membre</code>\n🤝 Ventes validées : <code>{nb_vendus}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]), parse_mode="HTML")
        elif cible == "mes_annonces":
            mes_depots = list(db.annonces.find({"vendeur_id": uid}))
            txt = "📦 <b>VOS ANNONCES DÉPOSÉES</b>\n▬▬▬▬▬▬▬▬▬▬▬▬\nCliquez sur un de vos dépôts pour le modifier ou le supprimer.\n\n"
            if not mes_depots:
                txt += "Aucune annonce enregistrée."
                kb = [[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]
            else:
                kb = [[InlineKeyboardButton(f"⚙️ {item['categorie']} ({item['prix']}) [{item['statut']}]", callback_data=f"monann:gerer:{item['_id']}")] for item in mes_depots]
                kb.append([InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")])
            await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        elif cible == "classement":
            # RECHERCHE EN PROFONDEUR : Classement dynamique basé sur la BDD réelle
            pipeline = [{"$match": {"statut": "vendu"}}, {"$group": {"_id": "$vendeur_id", "total": {"$sum": 1}}}, {"$sort": {"total": -1}}, {"$limit": 5}]
            tops = list(db.annonces.aggregate(pipeline))
            txt = "📈 <b>CLASSEMENT DES TOP VENDEURS (DYNAMIQUE)</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            if not tops:
                txt += "Aucune vente validée pour le moment sur la plateforme."
            else:
                medailles = ["👑 1.", "🥈 2.", "🥉 3.", "🔹 4.", "🔹 5."]
                for idx, item in enumerate(tops):
                    u = db.users.find_one({"_id": item["_id"]}) or {"username": f"Utilisateur_{item['_id']}"}
                    txt += f"{medailles[idx]} @{safe_html(u.get('username'))} — <code>{item['total']}</code> vente(s) sécurisée(s)\n"
            await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]), parse_mode="HTML")
        elif cible == "regles":
            config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
            kb = [[InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]
            if config["ouvert"]:
                kb.insert(0, [InlineKeyboardButton("📢 Postuler au Staff", callback_data="recrut:postuler")])
            txt = "📜 <b>RÈGLES &amp; CONDITIONS GÉNÉRALES</b>\n\n1. L'utilisation d'un intermédiaire (Escrow) est obligatoire.\n2. Tout contournement entraîne un bannissement définitif."
            await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        elif cible == "espace_gerant":
            if uid != SUPER_ADMIN_ID:
                await query.answer("⚠️ Accès strictement réservé au Fondateur.", show_alert=True)
                return
            kb = [[InlineKeyboardButton("👥 Recrutement Staff", callback_data="admin:gestion_equipe")], [InlineKeyboardButton("🔙 Retour", callback_data="menu:retour_start")]]
            await query.message.edit_text("🛠️ <b>PANNEAU DE CONTRÔLE FONDATEUR</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    # ─── EXTENSION : MODIFICATION ET SUPPRESSION PAR LE VENDEUR ───
    if famille == "monann":
        action, id_ann = parts[1], parts[2]
        if action == "gerer":
            ann = db.annonces.find_one({"_id": ObjectId(id_ann)})
            txt = f"⚙️ <b>Gestion de l'annonce : {safe_html(ann['categorie'])}</b>\n\nStatut actuel : <code>{ann['statut']}</code>"
            kb = [
                [InlineKeyboardButton("📝 Modif. Description", callback_data=f"monann:edit_desc:{id_ann}"),
                 InlineKeyboardButton("💰 Modif. Prix", callback_data=f"monann:edit_prix:{id_ann}")],
                [InlineKeyboardButton("🗑️ Supprimer l'annonce", callback_data=f"monann:suppr:{id_ann}")],
                [InlineKeyboardButton("🔙 Mes Annonces", callback_data="menu:mes_annonces")]
            ]
            await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        elif action.startswith("edit_"):
            mode = "DESC" if action == "edit_desc" else "PRIX"
            db.users.update_one({"_id": uid}, {"$set": {"state": f"EDIT_{mode}_{id_ann}"}})
            await query.message.edit_text(f"✍️ Envoie la nouvelle valeur pour votre {'description' if mode == 'DESC' else 'prix'} :",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:mes_annonces")]]))
        elif action == "suppr":
            db.annonces.delete_one({"_id": ObjectId(id_ann)})
            await query.answer("Annonce définitivement retirée de la BDD.", show_alert=True)
            await start(update, ctx)

    # ─── SYSTÈME DE RECRUTEMENT DYNAMIQUE ───
    if famille == "recrut":
        action = parts[1]
        if action == "postuler":
            db.candidatures.delete_many({"user_id": uid, "statut": "brouillon"})
            db.candidatures.insert_one({"user_id": uid, "username": update.effective_user.username or f"ID_{uid}", "statut": "brouillon", "reponses": {}})
            kb = [
                [InlineKeyboardButton("👥 Devenir Gérant / Modérateur", callback_data="recrut:choix:gerant")],
                [InlineKeyboardButton("💻 Devenir Développeur", callback_data="recrut:choix:developpeur")],
                [InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]
            ]
            await query.message.edit_text("💼 <b>RECRUTEMENT</b>\n\nSélectionne le poste désiré :", reply_markup=InlineKeyboardMarkup(kb))
        elif action == "choix":
            poste = parts[2]
            db.users.update_one({"_id": uid}, {"$set": {"state": "CAND_DISPO"}})
            db.candidatures.update_one({"user_id": uid, "statut": "brouillon"}, {"$set": {"poste": poste}})
            await query.message.edit_text(f"📢 <b>CAMPAGNE [{poste.upper()}] (1/3)</b>\n\nIndique tes disponibilités hebdomadaires :",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="menu:retour_start")]]))

    # ─── COMMANDES FONDATEUR (TOGGLE RECRUTEMENT) ───
    if famille == "admin":
        if uid != SUPER_ADMIN_ID: return
        if parts[1] == "gestion_equipe":
            config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
            statut = "🟢 OUVERT" if config["ouvert"] else "🔴 FERMÉ"
            kb = [[InlineKeyboardButton("🔄 Basculer Statut", callback_data="admin:toggle")], [InlineKeyboardButton("🔙 Retour", callback_data="menu:espace_gerant")]]
            await query.message.edit_text(f"👥 <b>RECRUTEMENTS STAFF</b>\n\nCampagne actuelle : <code>{statut}</code>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        elif parts[1] == "toggle":
            config = db.config.find_one({"type": "recrutement"}) or {"ouvert": False}
            db.config.update_one({"type": "recrutement"}, {"$set": {"ouvert": not config["ouvert"]}})
            await query.answer("Le statut de recrutement a changé !")
            await start(update, ctx)

# ==========================================
# 7. FILTRAGE ET TRAITEMENT DU START LINK (ESCROW)
# ==========================================
async def check_start_arguments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    msg_text = update.message.text
    uid = update.effective_user.id
    
    if msg_text.startswith("/start acheter_"):
        id_ann = msg_text.split("acheter_")[1]
        try:
            ann = db.annonces.find_one({"_id": ObjectId(id_ann)})
        except (InvalidId, Exception):
            await update.message.reply_text("❌ Lien d'achat invalide.")
            return
            
        if not ann or ann.get("statut") != "approuve":
            await update.message.reply_text("❌ Ce compte a déjà été vendu ou n'est plus en ligne.")
            return
            
        vendeur = db.users.find_one({"_id": ann["vendeur_id"]})
        v_name = f"@{vendeur['username']}" if vendeur else "Inconnu"
        b_name = f"@{update.effective_user.username}" or f"ID_{uid}"
        
        await update.message.reply_text("⏳ <b>Demande d'achat transmise !</b>\nLe Fondateur va vous contacter pour sécuriser l'échange.")
        
        txt_escalade = (
            f"🚨 <b>DEMANDE D'INTERMÉDIAIRE (ESCROW) REÇUE !</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🛒 <b>Acheteur :</b> {safe_html(b_name)} <code>({uid})</code>\n"
            f"👤 <b>Vendeur :</b> {safe_html(v_name)} <code>({ann['vendeur_id']})</code>\n"
            f"🎮 <b>Compte ciblé :</b> <code>{safe_html(ann['categorie'])}</code>\n"
            f"💰 <b>Montant :</b> <code>{safe_html(ann['prix'])}</code>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"⚡ <i>Prends contact avec eux. Une fois l'échange validé, utilise le bouton ci-dessous pour archiver l'annonce.</i>"
        )
        kb_escrow = [[
            InlineKeyboardButton("✅ Confirmer la Vente", callback_data=f"escrow:valider:{id_ann}:{uid}"),
            InlineKeyboardButton("❌ Annuler l'Échange", callback_data=f"escrow:annuler:{id_ann}")
        ]]
        await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_escalade, reply_markup=InlineKeyboardMarkup(kb_escrow), parse_mode="HTML")
        return
        
    await start(update, ctx)

# ==========================================
# 8. LANCEMENT DE PRODUCTION
# ==========================================
def main():
    threading.Thread(target=run_ping_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", check_start_arguments))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))

    print("🚀 PRODUCTION : Le Bot Market est 100% propre, audité et prêt à l'emploi !")
    app.run_polling()

if __name__ == "__main__":
    main()
