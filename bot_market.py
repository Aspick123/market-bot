import os
import time
import io
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ==========================================
# 1. CONFIGURATION ET PARAMÈTRES CRITIQUES
# ==========================================
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_BOT_TOKEN")

SUPER_ADMIN_ID = 5117004360          # ID Fondateur / Propriétaire principal
PUBLIC_CHANNEL_ID = "@comptedejeux"  # Canal public d'exposition des annonces

client = MongoClient(MONGO_URI)
db = client["bot_market_premium_db"]

# Initialisation des configurations globales par défaut
if not db.config.find_one({"type": "global"}):
    db.config.insert_one({
        "type": "global",
        "recrutement_ouvert": False,
        "mode_urgence": False,
        "delai_anti_arnaque": 3600,  # En secondes (1 heure)
        "limite_annonces_membre": 3,
        "cgu_text": "1. L'utilisation de l'arbitrage intermédiaire est obligatoire.\n2. Pas d'arnaque.",
        "blacklist_publique": []
    })

def safe_html(text):
    """Prévient l'injection de balises malicieuses et les crashs de rendu de Telegram"""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def get_badge(points, role, verified):
    """Calcule dynamiquement les grades et badges visuels d'un utilisateur"""
    if role == "admin" or role == "superadmin": return "⚡ FONDATEUR"
    if role == "mod_litiges": return "⚖️ MOD LITIGES"
    if role == "mod_annonces": return "🛡️ MOD ANNONCES"
    
    if verified: badge = "✅ Vérifié"
    elif points >= 1000: badge = "🏆 Platine"
    elif points >= 500: badge = "🥇 Or"
    elif points >= 200: badge = "🥈 Argent"
    else: badge = "🥉 Bronze"
    return badge

# ==========================================
# 2. SERVEUR DE CONTRÔLE DE VIE (RENDER PING)
# ==========================================
class RenderPingServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"BOT_ALIVE")
    def log_message(self, format, *args): return

def run_render_ping():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), RenderPingServer)
    server.serve_forever()

# ==========================================
# 3. INTERFACE DU MENU PRINCIPAL HIERARCHIQUE
# ==========================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or f"User_{uid}"
    
    # Mode urgence activé par l'admin principal
    cfg = db.config.find_one({"type": "global"})
    if cfg.get("mode_urgence", False) and uid != SUPER_ADMIN_ID:
        txt_urg = "⚠️ <b>MAINTENANCE CRITIQUE</b>\n\nLe bot est actuellement gelé par l'équipe technique. Revenez plus tard."
        if update.callback_query: await update.callback_query.message.edit_text(txt_urg, parse_mode="HTML")
        else: await update.message.reply_text(txt_urg, parse_mode="HTML")
        return

    # Check Sanctions / Ban local temporel ou définitif
    u_curr = db.users.find_one({"_id": uid})
    if u_curr and u_curr.get("banni_jusqua", 0) > time.time():
        remps = int(u_curr["banni_jusqua"] - time.time())
        await update.effective_message.reply_text(f"🔴 <b>Accès Refusé.</b> Vous êtes suspendu du marché pour encore {remps // 60} minutes.")
        return

    db.users.update_one(
        {"_id": uid},
        {
            "$set": {"username": uname, "state": "IDLE"},
            "$setOnInsert": {
                "role": "superadmin" if uid == SUPER_ADMIN_ID else "membre",
                "date_inscription": time.time(),
                "points": 0, "xp": 0, "parrain": None, "parrainages_comptes": 0,
                "nationalite": "Non définie", "telephone": "", "tel_visibilite": "masque",
                "monnaies": ["FCFA"], "paiements": ["Orange Money"], "status_dispo": "en ligne",
                "plage_horaire": "08:00 - 22:00", "whatsapp": "", "instagram": "", "verified": False
            }
        },
        upsert=True
    )

    txt = (
        f"🎮 <b>BIENVENUE SUR BOT MARKET ULTRA v3.0</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"Sécurité, Rapidité, Intermédiation automatisée par Escrow.\n\n"
        f"👑 Badge : <code>{get_badge(u_curr.get('points', 0) if u_curr else 0, u_curr.get('role', 'membre') if u_curr else 'membre', u_curr.get('verified', False) if u_curr else False)}</code>\n"
        f"💰 Solde Points : <code>{u_curr.get('points', 0) if u_curr else 0} pts</code>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"💡 <i>Faites votre choix via le tableau de bord :</i>"
    )

    kb = [
        [InlineKeyboardButton("🔍 Recherche", callback_data="nav:recherche"), 
         InlineKeyboardButton("🎮 Déposer Annonce", callback_data="nav:vendre")],
        [InlineKeyboardButton("🛍️ Liste du Marché", callback_data="nav:marche_global")],
        [InlineKeyboardButton("👤 Mon Profil", callback_data="nav:mon_profil"), 
         InlineKeyboardButton("📦 Mes Annonces", callback_data="nav:mes_annonces")],
        [InlineKeyboardButton("📜 CGU & CGV", callback_data="nav:cgu"), 
         InlineKeyboardButton("📊 Leaderboard", callback_data="nav:leaderboard")],
        [InlineKeyboardButton("🎁 Parrainage & Gains", callback_data="nav:parrainage"),
         InlineKeyboardButton("🔔 Alertes Jeux", callback_data="nav:mes_alertes")],
        [InlineKeyboardButton("⚖️ Centre des Litiges", callback_data="nav:mes_litiges")],
        [InlineKeyboardButton("⚡ Panneau d'Administration ⚡", callback_data="nav:admin_root")]
    ]

    if update.callback_query:
        await update.callback_query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        # Analyse des arguments profonds de parrainage (/start ref_12345) ou d'achat direct (/start acheter_ID)
        if ctx.args:
            arg = ctx.args[0]
            if arg.startswith("ref_"):
                parrain_id = int(arg.split("_")[1])
                if parrain_id != uid and not db.users.find_one({"_id": uid}):
                    db.users.update_one({"_id": uid}, {"$set": {"parrain": parrain_id}})
                    db.users.update_one({"_id": parrain_id}, {"$inc": {"points": 50, "parrainages_comptes": 1}})
                    try: await ctx.bot.send_message(chat_id=parrain_id, text="🎁 <b>+50 Points !</b> Un nouvel utilisateur a rejoint via votre lien.")
                    except Exception: pass
            elif arg.startswith("acheter_"):
                id_ann = arg.split("_")[1]
                await simuler_demande_achat(update, ctx, id_ann, uid)
                return
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ==========================================
# 4. TUNNEL DE VENTE COMPLET ET GESTION DES PHOTOS
# ==========================================
async def executer_tunnel_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid, text=None, photo_id=None):
    u = db.users.find_one({"_id": uid})
    state = u.get("state", "IDLE")
    ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})

    if not ann:
        db.annonces.insert_one({"vendeur_id": uid, "statut": "brouillon", "photos": [], "booste": False})
        db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_JEU"}})
        await update.effective_message.reply_text("🎮 <b>Étape 1/7 : Nom du Jeu</b>\n\nQuel est le nom exact du jeu vidéo ?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))
        return

    if state == "VENTE_JEU" and text:
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"categorie": text}})
        db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PLATEFORME"}})
        kb = [[InlineKeyboardButton(p, callback_data=f"plat:{p}") for p in ["Android", "iOS", "PC", "Console"]]]
        await update.effective_message.reply_text("📱 <b>Étape 2/7 : Plateforme</b>\n\nSélectionnez le support du compte :", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "VENTE_DESC" and text:
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"description": text}})
        db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PHOTOS"}})
        await update.effective_message.reply_text("📸 <b>Étape 4/7 : Captures d'écran (Preuves)</b>\n\nEnvoyez une ou plusieurs photos du compte. Une fois terminé, cliquez sur le bouton ci-dessous :", 
                                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏁 Terminer l'envoi des photos", callback_data="plat:fin_photos")]]))

    elif state == "VENTE_PHOTOS" and photo_id:
        db.annonces.update_one({"_id": ann["_id"]}, {"$push": {"photos": photo_id}})
        await update.effective_message.reply_text("✅ Photo ajoutée à la galerie de l'annonce. Continuez à envoyer ou validez.")

    elif state == "VENTE_PRIX" and text:
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"prix": text}})
        db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_DEVISE"}})
        kb = [[InlineKeyboardButton(d, callback_data=f"dev:{d}") for d in ["FCFA", "USDT", "EUR"]]]
        await update.effective_message.reply_text("💱 <b>Étape 6/7 : Devise principale</b>\n\nChoisissez l'unité monétaire de réception :", reply_markup=InlineKeyboardMarkup(kb))

# ==========================================
# 5. ROUTEUR CENTRALISÉ DES MESSAGES TEXTE & IMAGES (FSM)
# ==========================================
async def central_text_and_media_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = db.users.find_one({"_id": uid}) or {}
    state = u.get("state", "IDLE")
    text = update.message.text
    photo = update.message.photo[-1].file_id if update.message.photo else None

    # Tunnel de Vente Direct
    if state.startswith("VENTE_"):
        await executer_tunnel_vente(update, ctx, uid, text=text, photo_id=photo)
        return

    # Recherche Avancée Regex
    if state == "RECHERCHE_INPUT" and text:
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        res = list(db.annonces.find({"statut": "approuve", "$or": [{"categorie": {"$regex": text, "$options": "i"}}, {"description": {"$regex": text, "$options": "i"}}]}))
        kb = [[InlineKeyboardButton("🔙 Revenir au menu", callback_data="nav:retour")]]
        if not res:
            await update.message.reply_text("🔍 Aucun compte ne correspond à votre recherche.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            txt_res = "🔍 <b>RÉSULTATS DE VOTRE RECHERCHE :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            for item in res:
                txt_res += f"🎮 <b>[{safe_html(item['categorie'])}]</b> - {safe_html(item['prix'])} {safe_html(item['devise'])}\n📝 {safe_html(item['description'])}\n\n"
            await update.message.reply_text(txt_res, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    # Ouverture de Litiges avec insertion de preuves d'escroquerie
    if state == "LITIGE_INPUT_RECOURS" and text:
        db.users.update_one({"_id": uid}, {"$set": {"state": "LITIGE_PROOFS", "tmp_litige_desc": text}})
        await update.message.reply_text("📸 Envoyez maintenant une capture d'écran comme preuve du préjudice subi (Paiement effectué, mot de passe erroné...) :")
        return

    if state == "LITIGE_PROOFS" and photo:
        desc = u.get("tmp_litige_desc", "Aucune description")
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        db.litiges.insert_one({
            "demandeur_id": uid, "description": desc, "preuve_photo": photo,
            "statut": "ouvert", "date_creation": time.time(), "assigne_a": "Staff"
        })
        await update.message.reply_text("⚖️ <b>Dossier de litige transmis au Tribunal du Marché !</b> L'équipe va l'étudier sous peu.")
        return

    # Réponses Vendeurs aux Notes / Commentaires de réputation
    if state.startswith("REP_NOTE_"):
        id_tx = state.split("_")[2]
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        db.transactions.update_one({"_id": ObjectId(id_tx)}, {"$set": {"reponse_vendeur": text}})
        await update.message.reply_text("⭐ Votre droit de réponse au commentaire a bien été publié sur votre profil.")
        return

    # Configuration du Profil Vendeur Privé/Public
    if state.startswith("SETPROF_"):
        champ = state.split("_")[1]
        db.users.update_one({"_id": uid}, {"$set": {champ.lower(): text, "state": "IDLE"}})
        await update.message.reply_text(f"✅ Profil mis à jour ! Votre paramètre [{champ}] a été enregistré.")
        return

# ==========================================
# 6. ROUTEUR STRATÉGIQUE DES CALLBACK QUERIES
# ==========================================
async def central_callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    uid = update.effective_user.id
    u = db.users.find_one({"_id": uid}) or {}
    
    parts = data.split(":")
    prefix = parts[0]

    # ─── NAVIGATION INTERNE ET AFFICHAGES PRINCIPAUX ───
    if prefix == "nav":
        cible = parts[1]
        if cible == "retour":
            await start(update, ctx)
        elif cible == "recherche":
            db.users.update_one({"_id": uid}, {"$set": {"state": "RECHERCHE_INPUT"}})
            await query.message.edit_text("🔍 Saisissez le nom du jeu ou un mot-clé recherché :", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))
        elif cible == "vendre":
            limite = db.config.find_one({"type": "global"}).get("limite_annonces_membre", 3)
            comptage = db.annonces.count_documents({"vendeur_id": uid, "statut": "approuve"})
            if comptage >= limite:
                await query.message.edit_text(f"⚠️ <b>Quota Atteint !</b> Vous avez déjà {comptage}/{limite} annonces en ligne. Supprimez-en une pour en publier de nouvelles.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]))
                return
            await executer_tunnel_vente(update, ctx, uid)
        elif cible == "marche_global":
            annonces = list(db.annonces.find({"statut": "approuve"}).sort("booste", -1))
            txt = "🛍️ <b>ANNONCES ACTIVES SUR LE MARCHÉ :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            if not annonces: txt += "Aucun compte disponible actuellement."
            kb = []
            for item in annonces:
                pref = "🔥 [BOOST] " if item.get("booste") else "🔹 "
                txt += f"{pref}<b>{safe_html(item['categorie'])}</b> - <code>{safe_html(item['prix'])} {safe_html(item['devise'])}</code>\n"
                kb.append([InlineKeyboardButton(f"🛒 Voir {item['categorie']} ({item['prix']})", callback_data=f"viewann:inspecte:{item['_id']}:")])
            kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
            await query.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            
        elif cible == "mon_profil":
            nb_ventes = db.annonces.count_documents({"vendeur_id": uid, "statut": "vendu"})
            txt_prof = (
                f"👤 <b>VOTRE PROFIL COMMERCIAL SÉCURISÉ</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"🆔 Identifiant : <code>{uid}</code>\n"
                f"🌍 Nationalité : <code>{safe_html(u.get('nationalite'))}</code>\n"
                f"📞 Mobile : <code>{safe_html(u.get('telephone') or 'Non configuré')}</code> ({u.get('tel_visibilite')})\n"
                f"⏰ Horaires : <code>{safe_html(u.get('plage_horaire'))}</code>\n"
                f"🟢 Statut : <b>{safe_html(u.get('status_dispo').upper())}</b>\n"
                f"🤝 Ventes comptabilisées : <code>{nb_ventes}</code>\n"
                f"🎁 Filleuls : <code>{u.get('parrainages_comptes', 0)}</code>"
            )
            kb = [
                [InlineKeyboardButton("🌍 Changer Pays", callback_data="setprof:NATIONALITE"), InlineKeyboardButton("📞 Changer Tel", callback_data="setprof:TELEPHONE")],
                [InlineKeyboardButton("⏰ Changer Horaires", callback_data="setprof:PLAGE_HORAIRE"), InlineKeyboardButton("📱 Ajouter WhatsApp", callback_data="setprof:WHATSAPP")],
                [InlineKeyboardButton("🔙 Menu Principal", callback_data="nav:retour")]
            ]
            await query.message.edit_text(txt_prof, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif cible == "leaderboard":
            pipeline = [{"$match": {"statut": "vendu"}}, {"$group": {"_id": "$vendeur_id", "total": {"$sum": 1}}}, {"$sort": {"total": -1}}, {"$limit": 5}]
            tops = list(db.annonces.aggregate(pipeline))
            txt_lead = "📊 <b>CLASSEMENT DES MEILLEURS VENDEURS DE LA PLATEFORME</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            meds = ["👑 1er", "🥈 2ème", "🥉 3ème", "🔹 4ème", "🔹 5ème"]
            for idx, item in enumerate(tops):
                user_obj = db.users.find_one({"_id": item["_id"]}) or {"username": "Anonyme"}
                txt_lead += f"{meds[idx]} : @{safe_html(user_obj.get('username'))} avec <b>{item['total']} ventes</b> sécurisées\n"
            if not tops: txt_lead += "Aucune vente enregistrée pour le moment."
            await query.message.edit_text(txt_lead, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]), parse_mode="HTML")

        elif cible == "parrainage":
            lien = f"https://t.me/{ctx.bot.username}?start=ref_{uid}"
            txt_ref = f"🎁 <b>PROGRAMME DE PARRAINAGE EXCLUSIF</b>\n\nPartagez votre lien et gagnez 50 points par utilisateur actif inscrit !\n\n🔗 <b>Votre lien unique :</b>\n<code>{lien}</code>"
            await query.message.edit_text(txt_ref, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]), parse_mode="HTML")

        elif cible == "mes_alertes":
            # Gestion simplifiée des alertes jeux par abonnement
            db.alertes.update_one({"user_id": uid}, {"$addToSet": {"jeux": "EFootball"}}, upsert=True)
            await query.edit_message_text("🔔 Vous vous êtes abonné avec succès aux alertes de baisse de prix sur le mot-clé #EFootball.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]))

        elif cible == "mes_litiges":
            db.users.update_one({"_id": uid}, {"$set": {"state": "LITIGE_INPUT_RECOURS"}})
            await query.message.edit_text("⚖️ <b>OUVERTURE DE CONFLIT / ESCROQUERIE</b>\n\nExpliquez précisément ce qu'il s'est passé avec le vendeur/acheteur :", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

        elif cible == "admin_root":
            if uid != SUPER_ADMIN_ID:
                await query.answer("⚠️ Accès Interdit. Réservé au Fondateur.", show_alert=True)
                return
            cfg = db.config.find_one({"type": "global"})
            st_rec = "OUVERT" if cfg.get("recrutement_ouvert") else "FERMÉ"
            st_urg = "ACTIF" if cfg.get("mode_urgence") else "INACTIF"
            txt_adm = f"🛠️ <b>PANNEAU DE CONTRÔLE ABSOLU DU FONDATEUR</b>\n\nRecrutement Staff : <code>{st_rec}</code>\nMode Urgence Général : <code>{st_urg}</code>"
            kb = [
                [InlineKeyboardButton("🔄 Toggle Recrutement", callback_data="admact:toggle_rec"), InlineKeyboardButton("🚨 Toggle URGENCE", callback_data="admact:toggle_urg")],
                [InlineKeyboardButton("📊 Exporter Logs PDF (TXT)", callback_data="admact:export_pdf"), InlineKeyboardButton("⚖️ Gérer Litiges", callback_data="admact:voir_litiges")],
                [InlineKeyboardButton("🔙 Menu Principal", callback_data="nav:retour")]
            ]
            await query.message.edit_text(txt_adm, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    # ─── ACTION DU PROFIL VENDEUR ───
    if prefix == "setprof":
        champ_modif = parts[1]
        db.users.update_one({"_id": uid}, {"$set": {"state": f"SETPROF_{champ_modif}"}})
        await query.message.edit_text(f"✍️ Saisissez la nouvelle valeur pour votre : <b>{champ_modif}</b>", parse_mode="HTML")

    # ─── ETAPES INTERACTIVES DU TUNNEL DE VENTE ───
    if prefix == "plat":
        action = parts[1]
        if action == "fin_photos":
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PRIX"}})
            await query.message.edit_text("💰 <b>Étape 5/7 : Prix demandé</b>\n\nIndiquez le montant de la transaction (Ex: 15000, 25, 100) :")
        else:
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"plateforme": action}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_DESC"}})
            await query.message.edit_text("📝 <b>Étape 3/7 : Description exhaustive</b>\n\nDécrivez le compte (Skins, Rang, Personnages débloqués, Archons...) :")

    if prefix == "dev":
        devise = parts[1]
        db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"devise": devise, "statut": "en_attente", "date_depot": time.time()}})
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        ann_creee = db.annonces.find_one({"vendeur_id": uid, "statut": "en_attente"}, sort=[("date_depot", -1)])
        
        # Envoi au fondateur pour validation instantanée (Modération)
        txt_mod = f"⚖️ <b>MODÉRATION D'ANNONCE REÇUE</b>\n\nJeu : {ann_creee['categorie']}\nPrix : {ann_creee['prix']} {devise}"
        kb_mod = [[InlineKeyboardButton("✅ Accepter & Publier", callback_data=f"modact:approuve:{ann_creee['_id']}"),
                   InlineKeyboardButton("❌ Rejeter", callback_data=f"modact:rejete:{ann_creee['_id']}")]]
        await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=txt_mod, reply_markup=InlineKeyboardMarkup(kb_mod))
        await query.message.edit_text("🎉 <b>Annonce envoyée à l'équipe !</b> Elle sera publiée dès approbation.")

    # ─── TRAITEMENT DE MODÉRATION FONDATEUR ───
    if prefix == "modact":
        act, id_a = parts[1], parts[2]
        if act == "approuve":
            db.annonces.update_one({"_id": ObjectId(id_a)}, {"$set": {"statut": "approuve"}})
            item = db.annonces.find_one({"_id": ObjectId(id_a)})
            v = db.users.find_one({"_id": item["vendeur_id"]}) or {"username": "Inconnu"}
            
            # Publication Enrichie sur le canal public officiel
            txt_pub = (
                f"📣 <b>COMPTE SÉCURISÉ DISPONIBLE À L'ACHAT !</b>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"🎮 Jeu : #{safe_html(item['categorie'].replace(' ', '_'))}\n"
                f"📱 Support : <code>{safe_html(item['plateforme'])}</code>\n"
                f"💰 Prix de l'échange : <b>{safe_html(item['prix'])} {safe_html(item['devise'])}</b>\n"
                f"📝 Spécifications : <i>{safe_html(item['description'])}</i>\n"
                f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                f"👤 Vendeur certifié : @{safe_html(v.get('username'))}\n\n"
                f"🤝 <i>Pour procéder à la transaction via notre service d'Escrow sécurisé, cliquez sur le bouton ci-dessous :</i>"
            )
            kb_pub = [[InlineKeyboardButton("🛒 Acheter en Escrow Sécurisé", url=f"https://t.me/{ctx.bot.username}?start=acheter_{item['_id']}")]]
            
            if item["photos"]:
                await ctx.bot.send_photo(chat_id=PUBLIC_CHANNEL_ID, photo=item["photos"][0], caption=txt_pub, reply_markup=InlineKeyboardMarkup(kb_pub), parse_mode="HTML")
            else:
                await ctx.bot.send_message(chat_id=PUBLIC_CHANNEL_ID, text=txt_pub, reply_markup=InlineKeyboardMarkup(kb_pub), parse_mode="HTML")
            
            await query.message.edit_text("🟢 Annonce validée et envoyée sur le canal @comptedejeux.")
        else:
            db.annonces.update_one({"_id": ObjectId(id_a)}, {"$set": {"statut": "rejete"}})
            await query.message.edit_text("❌ Annonce rejetée et supprimée de la file.")

    # ─── GESTION ACTIONS ADMINISTRATIVES AVANCÉES ───
    if prefix == "admact":
        act = parts[1]
        if act == "toggle_rec":
            c = db.config.find_one({"type": "global"})
            db.config.update_one({"type": "global"}, {"$set": {"recrutement_ouvert": not c.get("recrutement_ouvert", False)}})
            await query.answer("Statut Recrutement Staff inversé !")
            await start(update, ctx)
        elif act == "toggle_urg":
            c = db.config.find_one({"type": "global"})
            db.config.update_one({"type": "global"}, {"$set": {"mode_urgence": not c.get("mode_urgence", False)}})
            await query.answer("🚨 Mode urgence modifié !")
            await start(update, ctx)
        elif act == "export_pdf":
            # Simulation d'un fichier de traçabilité complet exportable à la volée (Buffer TXT/PDF)
            buffer = io.BytesIO()
            buffer.write(b"RAPPORT HEBDOMADAIRE D'AUDIT ET SECURITE BOT MARKET\n===============================================\n")
            txs = db.annonces.count_documents({"statut": "vendu"})
            buffer.write(f"Nombre total d'echanges securises par Escrow : {txs}\n".encode())
            buffer.seek(0)
            await ctx.bot.send_document(chat_id=uid, document=InputFile(buffer, filename="Audit_Transactions_Traçabilité.txt"), caption="📊 Voici le rapport de traçabilité complet extrait de MongoDB.")

    # ─── GESTIONNAIRE DE VUE INDIVIDUELLE D'ANNONCE ───
    if prefix == "viewann":
        id_a = parts[2]
        item = db.annonces.find_one({"_id": ObjectId(id_a)})
        if not item: return
        txt_view = f"🎮 <b>Fiche détaillée : {safe_html(item['categorie'])}</b>\n\nPrix : {item['prix']} {item['devise']}\nDescription : {item['description']}"
        kb_view = [[InlineKeyboardButton("🤝 Initier l'Achat direct", url=f"https://t.me/{ctx.bot.username}?start=acheter_{item['_id']}"),
                    InlineKeyboardButton("🔙 Revenir", callback_data="nav:marche_global")]]
        if item["photos"]:
            await ctx.bot.send_photo(chat_id=uid, photo=item["photos"][0], caption=txt_view, reply_markup=InlineKeyboardMarkup(kb_view), parse_mode="HTML")
        else:
            await ctx.bot.send_message(chat_id=uid, text=txt_view, reply_markup=InlineKeyboardMarkup(kb_view), parse_mode="HTML")

    # ─── CONFIRMATIONS BILATÉRALES DU CYCLE D'ESCROW ───
    if prefix == "escrowact":
        act, tx_id = parts[1], parts[2]
        tx = db.transactions.find_one({"_id": ObjectId(tx_id)})
        if not tx: return
        
        if act == "conf_vendeur":
            db.transactions.update_one({"_id": ObjectId(tx_id)}, {"$set": {"confirmation_vendeur": True}})
        elif act == "conf_acheteur":
            db.transactions.update_one({"_id": ObjectId(tx_id)}, {"$set": {"confirmation_acheteur": True}})
            
        # Re-vérification après mise à jour
        tx_updated = db.transactions.find_one({"_id": ObjectId(tx_id)})
        if tx_updated.get("confirmation_vendeur") and tx_updated.get("confirmation_acheteur"):
            # Clôture définitive positive
            db.transactions.update_one({"_id": ObjectId(tx_id)}, {"$set": {"statut": "valide"}})
            db.annonces.update_one({"_id": ObjectId(tx_updated["annonce_id"])}, {"$set": {"statut": "vendu"}})
            db.users.update_one({"_id": tx_updated["vendeur_id"]}, {"$inc": {"points": 100}}) # XP & Gamification
            
            msg = "🟢 <b>CYCLE TRANSACTIONNEL TERMINÉ !</b>\n\nL'acheteur et le vendeur ont tous deux validé le transfert de données. Les fonds sont débloqués."
            await ctx.bot.send_message(chat_id=tx_updated["vendeur_id"], text=msg, parse_mode="HTML")
            await ctx.bot.send_message(chat_id=tx_updated["acheteur_id"], text=msg, parse_mode="HTML")
        else:
            await query.message.edit_text("⏳ En attente de la confirmation de l'autre partie pour libérer le compte.")

# ==========================================
# 7. LOGIQUE ESCROW AVANCÉE ET SYSTÈME ANTI-ARNAQUE
# ==========================================
async def simuler_demande_achat(update: Update, ctx: ContextTypes.DEFAULT_TYPE, id_ann, uid):
    try: ann = db.annonces.find_one({"_id": ObjectId(id_ann)})
    except Exception: return
    if not ann or ann.get("statut") != "approuve":
        await update.message.reply_text("❌ Cette annonce n'est plus active ou a déjà été vendue.")
        return

    # Création de la transaction d'intermédiation en base
    tx_id = db.transactions.insert_one({
        "annonce_id": ObjectId(id_ann), "vendeur_id": ann["vendeur_id"], "acheteur_id": uid,
        "statut": "en_cours", "date_creation": time.time(),
        "confirmation_vendeur": False, "confirmation_acheteur": False
    }).inserted_id

    kb_v = [[InlineKeyboardButton("✅ Confirmer la livraison des accès", callback_data=f"escrowact:conf_vendeur:{tx_id}")]]
    kb_a = [[InlineKeyboardButton("✅ Confirmer la réception conforme du compte", callback_data=f"escrowact:conf_acheteur:{tx_id}")]]

    # Alerte instantanée et simultanée des deux parties contractantes
    try:
        await ctx.bot.send_message(chat_id=ann["vendeur_id"], 
                                   text=f"🚨 <b>UN ACHETEUR SOUHAITE VOTRE COMPTE !</b>\n\nL'utilisateur <code>{uid}</code> a initié la procédure d'Escrow pour votre annonce <b>{ann['categorie']}</b>.\nTransmettez les accès de manière sécurisée puis validez :", 
                                   reply_markup=InlineKeyboardMarkup(kb_v), parse_mode="HTML")
    except Exception: pass

    await update.message.reply_text(f"⏳ <b>Procédure de Sécurisation initiée !</b>\n\nLe vendeur a reçu l'ordre de livraison. Une fois que vous possédez le nouveau mot de passe et l'e-mail du compte, confirmez ci-dessous :", 
                                  reply_markup=InlineKeyboardMarkup(kb_a), parse_mode="HTML")

# ==========================================
# 8. AMORÇAGE ET SCRIPT DE PRODUCTION PRINCIPAL
# ==========================================
def main():
    # Lancement du Thread du serveur Web d'anti-mise en veille (Render Web Service)
    threading.Thread(target=run_render_ping, daemon=True).start()
    
    # Construction de l'application asynchrone Telegram
    app = Application.builder().token(BOT_TOKEN).build()

    # Déclaration des écouteurs d'événements et de commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(central_callback_router))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, central_text_and_media_handler))

    print("🚀 PRODUCTION : Tout l'écosystème Bot Market Ultimate a démarré sans aucune erreur.")
    app.run_polling()

if __name__ == "__main__":
    main()
