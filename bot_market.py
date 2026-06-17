import os
import time
import io
import datetime
import hashlib
import threading
import asyncio
import logging
import aiohttp
from http.server import BaseHTTPRequestHandler, HTTPServer
from pymongo import MongoClient
from bson.objectid import ObjectId

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Configuration du Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

# ==========================================
# 1. PARAMÈTRES ET CONNEXIONS CRITIQUES BDD
# ==========================================
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "TON_BOT_TOKEN")

# ⚠️ REMPLACE CET ID PAR LE TIEN POUR POUVOIR ACCÉDER AU PANEL ADMIN
SUPER_ADMIN_ID = 5117004360          
PUBLIC_CHANNEL_ID = "@comptedejeux"  

# Configuration Blockchain TON
TON_WALLET_ADDRESS = os.getenv("TON_WALLET_ADDRESS", "")
TON_PRIVATE_KEY    = os.getenv("TON_PRIVATE_KEY", "")
TONCENTER_API_KEY  = os.getenv("TONCENTER_API_KEY", "")
TONCENTER_URL      = "https://toncenter.com/api/v2"

TIMEOUT_PAIEMENT_MIN    = 30
SCAN_INTERVAL_SEC       = 10

# Connexion MongoDB
client = MongoClient(MONGO_URI)
db = client["bot_market_premium_db"]

# Initialisation des configurations globales
if not db.config.find_one({"type": "global"}):
    db.config.insert_one({
        "type": "global",
        "recrutement_ouvert": False,
        "mode_urgence": False,
        "delai_anti_arnaque": 3600,
        "limite_annonces_membre": 3,
        "ton_commission_pct": 5,
        "cgu_text": "1. L'utilisation de l'arbitrage intermédiaire par le bot est obligatoire.\n2. Tout contournement entraîne un ban permanent.",
        "blacklist_publique": []
    })

# ==========================================
# 2. FONCTIONS DE SÉCURITÉ ET GAMIFICATION
# ==========================================
def safe_html(text):
    if text is None: return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def get_badge(points, role, verified):
    if role in ["admin", "superadmin"]: return "⚡ FONDATEUR / STAFF"
    if verified: return "✅ Vendeur Vérifié"
    if points >= 1000: return "🏆 Niveau Platine"
    elif points >= 500: return "🥇 Niveau Or"
    elif points >= 200: return "🥈 Niveau Argent"
    else: return "🥉 Niveau Bronze"

def generer_memo(escrow_id: str) -> str:
    return f"TX-{hashlib.md5(escrow_id.encode()).hexdigest()[:6].upper()}"

# ==========================================
# 3. EXTRACTIONS BLOCKCHAIN TON
# ==========================================
async def scanner_transactions_ton() -> list:
    if not TON_WALLET_ADDRESS or not TONCENTER_API_KEY: return []
    headers = {"X-API-Key": TONCENTER_API_KEY}
    params = {"address": TON_WALLET_ADDRESS, "limit": 20, "to_lt": 0, "archival": False}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{TONCENTER_URL}/getTransactions", headers=headers, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", [])
    except Exception as e:
        log.error(f"Erreur API TON Center: {e}")
    return []

def extraire_memo(transaction: dict) -> str:
    try:
        msg = transaction.get("in_msg", {})
        if msg.get("message"): return msg["message"].strip()
        body = msg.get("msg_data", {})
        if body.get("text"):
            import base64
            return base64.b64decode(body["text"]).decode("utf-8", errors="ignore").strip()
    except: pass
    return ""

def extraire_montant(transaction: dict) -> float:
    try:
        return round(int(transaction.get("in_msg", {}).get("value", 0)) / 1_000_000_000, 4)
    except: return 0.0

# ==========================================
# 4. SERVEUR DE VITALITÉ (ANTI-CRASH)
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
    HTTPServer(("0.0.0.0", port), RenderPingServer).serve_forever()

# ==========================================
# 5. INTERFACE ET REQUÊTES DU MENU START
# ==========================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or f"User_{uid}"
    
    cfg = db.config.find_one({"type": "global"})
    if cfg.get("mode_urgence", False) and uid != SUPER_ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Maintenance critique active.", show_alert=True)
        else:
            await update.effective_message.reply_text("⚠️ <b>MAINTENANCE CRITIQUE ACTIVÉE.</b> Indisponible.")
        return

    db.users.update_one(
        {"_id": uid},
        {
            "$set": {"username": uname, "state": "IDLE"},
            "$setOnInsert": {
                "role": "superadmin" if uid == SUPER_ADMIN_ID else "membre",
                "date_inscription": time.time(), "points": 0, "parrainages_comptes": 0,
                "nationalite": "Non définie", "telephone": "", "tel_visibilite": "masque",
                "monnaies": ["FCFA", "USDT"], "paiements": ["Orange Money"], "status_dispo": "en ligne",
                "plage_horaire": "08:00 - 22:00", "whatsapp": "", "instagram": "", "verified": False
            }
        },
        upsert=True
    )
    
    u_curr = db.users.find_one({"_id": uid})

    if ctx.args:
        arg = ctx.args[0]
        if arg.startswith("ref_"):
            parrain_id = int(arg.split("_")[1])
            if parrain_id != uid and not db.users.find_one({"_id": uid}):
                db.users.update_one({"_id": uid}, {"$set": {"parrain": parrain_id}})
                db.users.update_one({"_id": parrain_id}, {"$inc": {"points": 50, "parrainages_comptes": 1}})
        elif arg.startswith("acheter_"):
            await initier_demande_achat_escrow(update, ctx, arg.split("_")[1], uid)
            return

    txt = (
        f"🎮 <b>BIENVENUE SUR BOT MARKET ULTIMATE v3.0</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"Sécurité et intermédiation automatisée par séquestre TON.\n\n"
        f"👑 Badge actuel : <code>{get_badge(u_curr.get('points', 0), u_curr.get('role'), u_curr.get('verified'))}</code>\n"
        f"💰 Score Fidélité : <code>{u_curr.get('points', 0)} pts</code>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"💡 <i>Utilisez les boutons ci-dessous pour naviguer :</i>"
    )

    kb = [
        [InlineKeyboardButton("🔍 Recherche Avancée", callback_data="nav:recherche"), 
         InlineKeyboardButton("🎮 Déposer une Annonce", callback_data="nav:vendre")],
        [InlineKeyboardButton("🛍️ Parcourir le Marché", callback_data="nav:marche_global")],
        [InlineKeyboardButton("👤 Mon Profil Vendeur", callback_data="nav:mon_profil"), 
         InlineKeyboardButton("📦 Mes Annonces", callback_data="nav:mes_annonces")],
        [InlineKeyboardButton("📜 Consulter CGU", callback_data="nav:cgu"), 
         InlineKeyboardButton("📊 Leaderboard Ventes", callback_data="nav:leaderboard")],
        [InlineKeyboardButton("🎁 Liens Parrainage", callback_data="nav:parrainage"),
         InlineKeyboardButton("💼 Recrutement Staff", callback_data="nav:recrutement_public")],
        [InlineKeyboardButton("⚖️ Ouvrir un Litige", callback_data="nav:mes_litiges")],
        [InlineKeyboardButton("⚙️ Administration Générale", callback_data="nav:admin_root")]
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(text=txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ==========================================
# 6. MACHINE D'ÉTATS (FSM)
# ==========================================
async def central_text_and_media_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = db.users.find_one({"_id": uid}) or {}
    state = u.get("state", "IDLE")
    text = update.message.text
    photo = update.message.photo[-1].file_id if update.message.photo else None

    if state.startswith("VENTE_"):
        ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})
        if not ann:
            db.annonces.insert_one({"vendeur_id": uid, "statut": "brouillon", "photos": [], "booste": False})
            ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})

        if state == "VENTE_JEU" and text:
            db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"categorie": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PLATEFORME"}})
            kb = [[InlineKeyboardButton(p, callback_data=f"plat:{p}") for p in ["Android", "iOS", "PC", "Console"]]]
            await update.message.reply_text("📱 <b>Étape 2/7 : Plateforme</b>\n\nSupport du compte :", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        
        elif state == "VENTE_DESC" and text:
            db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"description": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PHOTOS"}})
            await update.message.reply_text("📸 <b>Étape 4/7 : Galerie d'images</b>\n\nEnvoyez vos captures d'écran, puis cliquez sur :", 
                                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏁 Finir l'envoi", callback_data="plat:fin_photos")]]), parse_mode="HTML")
        
        elif state == "VENTE_PHOTOS" and photo:
            db.annonces.update_one({"_id": ann["_id"]}, {"$push": {"photos": photo}})
            await update.message.reply_text("✅ Image ajoutée. Continuez ou validez via le bouton.")
        
        elif state == "VENTE_PRIX" and text:
            db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"prix": text}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_DEVISE"}})
            kb = [[InlineKeyboardButton(d, callback_data=f"dev:{d}") for d in ["FCFA", "USDT", "EUR"]]]
            await update.message.reply_text("💱 <b>Étape 6/7 : Devise</b>\n\nSélectionnez l'unité :", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    if state == "RECHERCHE_INPUT" and text:
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        res = list(db.annonces.find({"statut": "approuve", "$or": [{"categorie": {"$regex": text, "$options": "i"}}, {"description": {"$regex": text, "$options": "i"}}]}))
        kb = [[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]
        if not res:
            await update.message.reply_text("🔍 Aucune annonce correspondante.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            txt_res = "🔍 <b>RÉSULTATS :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            for item in res:
                txt_res += f"🎮 <b>[{safe_html(item['categorie'])}]</b> - {safe_html(item['prix'])} {safe_html(item['devise'])}\n📝 {safe_html(item['description'])}\n\n"
            await update.message.reply_text(txt_res, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    if state == "LITIGE_INPUT_RECOURS" and text:
        db.users.update_one({"_id": uid}, {"$set": {"state": "LITIGE_PROOFS", "tmp_litige_desc": text}})
        await update.message.reply_text("📸 Joignez une capture d'écran pour preuve :")
        return

    if state == "LITIGE_PROOFS" and photo:
        desc = u.get("tmp_litige_desc", "Aucune description")
        db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
        db.litiges.insert_one({"demandeur_id": uid, "description": desc, "preuve_photo": photo, "statut": "ouvert", "date_creation": time.time()})
        await update.message.reply_text("⚖️ Dossier transmis à l'arbitrage.")
        return

    if state.startswith("SETPROF_"):
        champ = state.split("_")[1]
        db.users.update_one({"_id": uid}, {"$set": {champ.lower(): text, "state": "IDLE"}})
        await update.message.reply_text(f"✅ [<b>{champ}</b>] mis à jour !", parse_mode="HTML")
        return

    if state == "SET_WALLET_VENDEUR" and text:
        db.users.update_one({"_id": uid}, {"$set": {"wallet_ton_adresse": text, "state": "IDLE"}})
        await update.message.reply_text("🏦 Adresse TON mémorisée.")
        return

# ==========================================
# 7. ROUTEUR CENTRAL DES BOUTONS (CALLBACKS)
# ==========================================
async def central_callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id
    
    try:
        # Acquitter immédiatement le clic pour empêcher le bouton de freezer/charger
        await query.answer()
        
        u = db.users.find_one({"_id": uid}) or {}
        parts = data.split(":")
        prefix = parts[0]

        if prefix == "nav":
            cible = parts[1]
            if cible == "retour":
                await start(update, ctx)
            elif cible == "recherche":
                db.users.update_one({"_id": uid}, {"$set": {"state": "RECHERCHE_INPUT"}})
                await query.edit_message_text("🔍 Saisissez le nom du jeu recherché :", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))
            elif cible == "vendre":
                limite = db.config.find_one({"type": "global"}).get("limite_annonces_membre", 3)
                if db.annonces.count_documents({"vendeur_id": uid, "statut": "approuve"}) >= limite:
                    await query.edit_message_text(f"⚠️ Quota max de {limite} annonces atteint.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]))
                    return
                db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_JEU"}})
                await query.edit_message_text("🎮 <b>Étape 1/7 : Titre du jeu</b>\n\nQuel est le nom du jeu ?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]), parse_mode="HTML")
            elif cible == "marche_global":
                annonces = list(db.annonces.find({"statut": "approuve"}))
                txt = "🛍️ <b>OFFRES DISPONIBLES :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                kb = []
                for item in annonces:
                    txt += f"🔹 <b>{safe_html(item['categorie'])}</b> - <code>{safe_html(item['prix'])} {safe_html(item['devise'])}</code>\n"
                    kb.append([InlineKeyboardButton(f"👁️ {item['categorie']} ({item['prix']})", callback_data=f"viewann:inspecte:{item['_id']}")])
                kb.append([InlineKeyboardButton("🔙 Menu Principal", callback_data="nav:retour")])
                await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            elif cible == "mon_profil":
                txt_prof = f"👤 <b>PROFIL COMMERCIAL</b>\n🌍 Nationalité : {safe_html(u.get('nationalite'))}\n📞 Téléphone : {safe_html(u.get('telephone'))}"
                kb = [[InlineKeyboardButton("🌍 Pays", callback_data="setprof:NATIONALITE"), InlineKeyboardButton("📞 Mobile", callback_data="setprof:TELEPHONE")],
                      [InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]
                await query.edit_message_text(txt_prof, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            elif cible == "leaderboard":
                res = list(db.annonces.aggregate([{"$match": {"statut": "vendu"}}, {"$group": {"_id": "$vendeur_id", "total": {"$sum": 1}}}, {"$sort": {"total": -1}}]))
                txt_l = "📊 <b>MEILLEURS VENDEURS :</b>\n\n"
                for pos, r in enumerate(res): txt_l += f"{pos+1}. Utilisateur {r['_id']} — {r['total']} ventes\n"
                await query.edit_message_text(txt_l or "Aucune vente.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]))
            elif cible == "admin_root":
                if uid != SUPER_ADMIN_ID:
                    # Alerte contextuelle si l'ID ne correspond pas au SuperAdmin
                    await query.answer("⛔ Accès refusé : Tu n'es pas configuré comme SUPER_ADMIN_ID dans le code.", show_alert=True)
                    return
                cfg = db.config.find_one({"type": "global"})
                txt_adm = (
                    f"🛠️ <b>PANEL D'ADMINISTRATION SUPRÊME</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                    f"🚨 Mode Urgence : <code>{'ACTIF 🔴' if cfg.get('mode_urgence') else 'INACTIF 🟢'}</code>\n"
                    f"💼 Recrutements : <code>{'OUVERTS 🔓' if cfg.get('recrutement_ouvert') else 'FERMÉS 🔒'}</code>\n"
                )
                kb = [
                    [InlineKeyboardButton("🚨 Basculer Urgence", callback_data="admact:toggle_urg"), 
                     InlineKeyboardButton("💼 Basculer Recrutement", callback_data="admact:toggle_recrut")],
                    [InlineKeyboardButton("📊 Exporter Audit TXT", callback_data="admact:export")],
                    [InlineKeyboardButton("🔙 Menu Principal", callback_data="nav:retour")]
                ]
                await query.edit_message_text(txt_adm, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            elif cible == "mes_annonces":
                mes_ann = list(db.annonces.find({"vendeur_id": uid}))
                txt_ma = "📦 <b>VOS ANNONCES :</b>\n\n"
                for a in mes_ann: txt_ma += f"• {safe_html(a['categorie'])} — {safe_html(a['prix'])} {safe_html(a['devise'])} ({safe_html(a['statut'])})\n"
                if not mes_ann: txt_ma += "Aucune annonce."
                await query.edit_message_text(txt_ma, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]), parse_mode="HTML")
            elif cible == "cgu":
                cfg = db.config.find_one({"type": "global"})
                await query.edit_message_text(f"📜 <b>CGU & SÉCURITÉ</b>\n\n{safe_html(cfg.get('cgu_text'))}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]), parse_mode="HTML")
            elif cible == "parrainage":
                link = f"https://t.me/{ctx.bot.username}?start=ref_{uid}"
                await query.edit_message_text(f"🎁 <b>PARRAINAGE</b>\n\nGagnez 50 points par membre invité :\n\n<code>{link}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]), parse_mode="HTML")
            elif cible == "mes_litiges":
                db.users.update_one({"_id": uid}, {"$set": {"state": "LITIGE_INPUT_RECOURS"}})
                await query.edit_message_text("⚖️ <b>OUVERTURE DE LITIGE</b>\n\nExpliquez l'anomalie en un seul message :", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]), parse_mode="HTML")
            elif cible == "recrutement_public":
                cfg = db.config.find_one({"type": "global"})
                if cfg.get("recrutement_ouvert", False):
                    txt_recr = "💼 <b>CAMPAGNE DE RECRUTEMENT OUVERTE !</b>\n\nNous cherchons des modérateurs. Envoyez votre candidature au Fondateur."
                else:
                    txt_recr = "❌ <b>RECRUTEMENT FERMÉ</b>\n\nAucune session active pour le moment."
                await query.edit_message_text(txt_recr, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]), parse_mode="HTML")

        elif prefix == "setprof":
            db.users.update_one({"_id": uid}, {"$set": {"state": f"SETPROF_{parts[1]}"}})
            await query.edit_message_text(f"✍️ Saisissez la valeur pour {parts[1]} :")

        elif prefix == "plat":
            if parts[1] == "fin_photos":
                db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_PRIX"}})
                await query.edit_message_text("💰 <b>Étape 5/7 : Tarification</b>\n\nDéfinissez votre prix :", parse_mode="HTML")
            else:
                db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"plateforme": parts[1]}})
                db.users.update_one({"_id": uid}, {"$set": {"state": "VENTE_DESC"}})
                await query.edit_message_text("📝 <b>Étape 3/7 : Description</b>\n\nListez les détails du compte :", parse_mode="HTML")

        elif prefix == "dev":
            db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"devise": parts[1], "statut": "en_attente", "date_creation": time.time()}})
            db.users.update_one({"_id": uid}, {"$set": {"state": "IDLE"}})
            ann_creee = db.annonces.find_one({"vendeur_id": uid, "statut": "en_attente"}, sort=[("date_creation", -1)])
            
            await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=f"⚖️ <b>MODÉRATION</b>\nJeu : {ann_creee['categorie']}\nPrix : {ann_creee['prix']} {parts[1]}", 
                                       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Publier", callback_data=f"modact:ok:{ann_creee['_id']}"), InlineKeyboardButton("❌ Rejeter", callback_data=f"modact:ko:{ann_creee['_id']}")]]))
            await query.edit_message_text("🎉 Annonce envoyée à la modération !")

        elif prefix == "modact":
            act, id_a = parts[1], parts[2]
            if act == "ok":
                db.annonces.update_one({"_id": ObjectId(id_a)}, {"$set": {"statut": "approuve"}})
                item = db.annonces.find_one({"_id": ObjectId(id_a)})
                txt_pub = f"📣 <b>DISPONIBLE</b>\n🎮 Jeu : #{item['categorie']}\n💰 Prix : {item['prix']} {item['devise']}\n📝 Description : {item['description']}"
                kb_pub = [[InlineKeyboardButton("🛒 Acheter", url=f"https://t.me/{ctx.bot.username}?start=acheter_{item['_id']}")]]
                
                if item.get("photos"): await ctx.bot.send_photo(chat_id=PUBLIC_CHANNEL_ID, photo=item["photos"][0], caption=txt_pub, reply_markup=InlineKeyboardMarkup(kb_pub))
                else: await ctx.bot.send_message(chat_id=PUBLIC_CHANNEL_ID, text=txt_pub, reply_markup=InlineKeyboardMarkup(kb_pub))
                await query.edit_message_text("🟢 Annonce publiée.")
            else:
                db.annonces.update_one({"_id": ObjectId(id_a)}, {"$set": {"statut": "rejete"}})
                await query.edit_message_text("❌ Offre rejetée.")

        elif prefix == "viewann":
            item = db.annonces.find_one({"_id": ObjectId(parts[2])})
            txt_v = f"🎮 Fiche : {item['categorie']}\nTarif : {item['prix']} {item['devise']}\nDétails : {item['description']}"
            kb_v = [[InlineKeyboardButton("🤝 Acheter", url=f"https://t.me/{ctx.bot.username}?start=acheter_{item['_id']}")] ]
            if item.get("photos"): await ctx.bot.send_photo(chat_id=uid, photo=item["photos"][0], caption=txt_v, reply_markup=InlineKeyboardMarkup(kb_v))
            else: await ctx.bot.send_message(chat_id=uid, text=txt_v, reply_markup=InlineKeyboardMarkup(kb_v))

        elif prefix == "admact":
            if uid != SUPER_ADMIN_ID: return
            act = parts[1]
            
            if act == "toggle_urg":
                c = db.config.find_one({"type": "global"})
                db.config.update_one({"type": "global"}, {"$set": {"mode_urgence": not c.get("mode_urgence")}})
            elif act == "toggle_recrut":
                c = db.config.find_one({"type": "global"})
                db.config.update_one({"type": "global"}, {"$set": {"recrutement_ouvert": not c.get("recrutement_ouvert")}})
            elif act == "export":
                buf = io.BytesIO(b"RAPPORT D'AUDIT COMPLET")
                await ctx.bot.send_document(chat_id=uid, document=buf, filename="audit_market.txt")
                return
            
            cfg = db.config.find_one({"type": "global"})
            txt_adm = (
                f"🛠️ <b>PANEL D'ADMINISTRATION SUPRÊME</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"🚨 Mode Urgence : <code>{'ACTIF 🔴' if cfg.get('mode_urgence') else 'INACTIF 🟢'}</code>\n"
                f"💼 Recrutements : <code>{'OUVERTS 🔓' if cfg.get('recrutement_ouvert') else 'FERMÉS 🔒'}</code>\n"
            )
            kb = [
                [InlineKeyboardButton("🚨 Basculer Urgence", callback_data="admact:toggle_urg"), 
                 InlineKeyboardButton("💼 Basculer Recrutement", callback_data="admact:toggle_recrut")],
                [InlineKeyboardButton("📊 Exporter Audit TXT", callback_data="admact:export")],
                [InlineKeyboardButton("🔙 Menu Principal", callback_data="nav:retour")]
            ]
            await query.edit_message_text(txt_adm, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif prefix == "escrowact":
            act, tx_id = parts[1], parts[2]
            if act == "conf_vendeur":
                db.escrows.update_one({"_id": tx_id}, {"$set": {"confirmation_vendeur": True}})
                await query.edit_message_text("⏳ Livraison enregistrée. En attente de l'acheteur.")
            elif act == "conf_acheteur":
                db.escrows.update_one({"_id": tx_id}, {"$set": {"confirmation_acheteur": True}})
                await query.edit_message_text("⏳ Confirmation acheteur validée.")
            
            esc_up = db.escrows.find_one({"_id": tx_id})
            if esc_up.get("confirmation_vendeur") and esc_up.get("confirmation_acheteur"):
                await executer_deblocage_fonds_ton(ctx.bot, tx_id, esc_up)
                
    except Exception as e:
        log.error(f"Erreur d'exécution Callback : {e}", exc_info=True)
        try:
            # Renvoyer l'erreur exacte à l'écran Telegram au lieu de la cacher
            await query.answer(text=f"❌ Erreur Interne : {str(e)}", show_alert=True)
        except: pass

# ==========================================
# 8. SÉQUESTRE TON & ARBITRAGE
# ==========================================
async def initier_demande_achat_escrow(update: Update, ctx: ContextTypes.DEFAULT_TYPE, id_ann, uid):
    try: ann = db.annonces.find_one({"_id": ObjectId(id_ann)})
    except: return
    if not ann or ann.get("statut") != "approuve":
        await update.message.reply_text("❌ Offre indisponible.")
        return

    num = db.escrows.count_documents({}) + 1
    escrow_id = f"ESC{num:04d}"
    memo = generer_memo(escrow_id)
    
    db.escrows.insert_one({
        "_id": escrow_id, "ann_id": id_ann, "vendeur_id": ann["vendeur_id"],
        "acheteur_id": uid, "montant_ton": 5.0, "montant_vendeur": 4.75,
        "memo": memo, "statut": "attente_paiement",
        "deadline_paiement": (datetime.datetime.now() + datetime.timedelta(minutes=30)).isoformat(),
        "confirmation_vendeur": False, "confirmation_acheteur": False
    })
    db.annonces.update_one({"_id": ObjectId(id_ann)}, {"$set": {"statut": "en_cours"}})

    await update.message.reply_text(f"🛒 *SÉQUESTRE {escrow_id}*\n💰 Transférer : `5.0 TON`\n🏦 Vers : `{TON_WALLET_ADDRESS}`\n💬 Mémo strict : `{memo}`", parse_mode="Markdown")

async def executer_deblocage_fonds_ton(bot, escrow_id, escrow):
    vendeur = db.users.find_one({"_id": escrow["vendeur_id"]})
    wallet_dest = vendeur.get("wallet_ton_adresse")
    if not wallet_dest:
        db.users.update_one({"_id": escrow["vendeur_id"]}, {"$set": {"state": "SET_WALLET_VENDEUR"}})
        await bot.send_message(chat_id=escrow["vendeur_id"], text="💰 Spécifiez votre adresse TON pour recevoir l'argent :")
        db.escrows.update_one({"_id": escrow_id}, {"$set": {"statut": "attente_wallet_vendeur"}})
        return
    db.escrows.update_one({"_id": escrow_id}, {"$set": {"statut": "libere", "date_cloture": time.time()}})
    db.annonces.update_one({"_id": ObjectId(escrow["ann_id"])}, {"$set": {"statut": "vendu"}})
    await bot.send_message(chat_id=escrow["vendeur_id"], text=f"🟢 Séquestre {escrow_id} clôturé avec succès.")

# ==========================================
# 9. BOUCLE ASYNCHRONE DE RECHERCHE DE COMPTES
# ==========================================
async def matcher_paiement(bot, transactions: list):
    escrows_actifs = list(db.escrows.find({"statut": "attente_paiement"}))
    for tx in transactions:
        memo = extraire_memo(tx)
        if not memo: continue
        for escrow in escrows_actifs:
            if escrow.get("memo") == memo:
                db.escrows.update_one({"_id": escrow["_id"]}, {"$set": {"statut": "fonds_bloques"}})
                await bot.send_message(chat_id=escrow["acheteur_id"], text="🟡 Fonds reçus. Confirmez dès réception des accès.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Conforme", callback_data=f"escrowact:conf_acheteur:{escrow['_id']}")]]))
                await bot.send_message(chat_id=escrow["vendeur_id"], text="🟢 L'acheteur a payé. Fournissez les accès puis validez :", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 J'ai livré", callback_data=f"escrowact:conf_vendeur:{escrow['_id']}")]]))

async def post_init(application: Application) -> None:
    async def blockchain_background_loop():
        while True:
            try:
                txs = await scanner_transactions_ton()
                if txs: await matcher_paiement(application.bot, txs)
            except Exception as e: log.error(f"Incident blockchain loop : {e}")
            await asyncio.sleep(SCAN_INTERVAL_SEC)
    asyncio.create_task(blockchain_background_loop())

# ==========================================
# 10. POINT D'AMORÇAGE DE LA PRODUCTION
# ==========================================
def main():
    threading.Thread(target=run_render_ping, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(central_callback_router))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, central_text_and_media_handler))
    
    print("🚀 PRODUCTION : Tout l'écosystème Bot Market Ultimate unifié est actif.")
    app.run_polling()

if __name__ == "__main__":
    main()
