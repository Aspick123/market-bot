"""
╔══════════════════════════════════════════════════════════════╗
║         BOT MARKET ULTRA v3.1 — VERSION ROBUSTE              ║
║         Fichier unique — tous boutons opérationnels          ║
╠══════════════════════════════════════════════════════════════╣
║  Corrections apportées :                                      ║
║  • Plus aucun crash sur champ manquant (.get avec défauts)   ║
║  • Webhook supprimé au démarrage (anti-conflit polling)      ║
║  • Gestionnaire d'erreurs global (logs clairs sur Render)    ║
║  • Serveur de ping Flask robuste (anti-veille Render)        ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import time
import io
import logging
import traceback
import threading
import datetime
from flask import Flask
from pymongo import MongoClient
from bson.objectid import ObjectId
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ══════════════════════════════════════════════════════════════
# ⚠️ BLOC FLASK — NE PAS MODIFIER (anti-veille Render)
# ══════════════════════════════════════════════════════════════
app_flask = Flask("")

@app_flask.route("/")
def home():
    return "BOT_ALIVE"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port, threaded=True)

threading.Thread(target=run_flask, daemon=True).start()
# ══════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger("BotMarket")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAEf5EcX6TzgGsaT8KZWRiAEK42h4FJjc0k")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
PUBLIC_CHANNEL_ID = os.environ.get("PUBLIC_CHANNEL_ID", "@comptedejeux")

client = MongoClient(MONGO_URI)
db = client["bot_market_premium_db"]

DEFAULTS_USER = {
    "username": "Inconnu", "role": "membre", "state": "IDLE",
    "date_inscription": 0, "points": 0, "xp": 0, "parrain": None,
    "parrainages_comptes": 0, "nationalite": "Non définie",
    "telephone": "", "tel_visibilite": "masque",
    "monnaies": ["FCFA"], "paiements": ["Orange Money"],
    "status_dispo": "en ligne", "plage_horaire": "08:00 - 22:00",
    "whatsapp": "", "instagram": "", "verified": False,
    "banni_jusqua": 0, "tmp_litige_desc": "",
}

DEFAULTS_CONFIG = {
    "type": "global", "recrutement_ouvert": False, "mode_urgence": False,
    "delai_anti_arnaque": 3600, "limite_annonces_membre": 3, "commission_pct": 5,
    "cgu_text": (
        "📋 CONDITIONS GÉNÉRALES D'UTILISATION\n\n"
        "1. L'utilisation de l'arbitrage intermédiaire (Escrow) est obligatoire.\n"
        "2. Toute tentative d'arnaque entraîne un bannissement immédiat.\n"
        "3. Les annonces doivent être honnêtes et vérifiables.\n"
        "4. Le bot et son équipe ne sont pas responsables hors du cadre prévu.\n"
        "5. Tout litige doit être signalé via le Centre des Litiges."
    ),
    "blacklist_publique": []
}

if not db.config.find_one({"type": "global"}):
    db.config.insert_one(DEFAULTS_CONFIG)

# ══════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════

def safe_html(text) -> str:
    if text is None:
        return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def get_config() -> dict:
    cfg = db.config.find_one({"type": "global"}) or {}
    return {**DEFAULTS_CONFIG, **cfg}

def get_user(uid: int) -> dict:
    u = db.users.find_one({"_id": uid})
    if not u:
        u = {"_id": uid, **DEFAULTS_USER,
             "role": "superadmin" if uid == SUPER_ADMIN_ID else "membre",
             "date_inscription": time.time()}
        db.users.insert_one(u)
        return u
    missing = {k: v for k, v in DEFAULTS_USER.items() if k not in u or u.get(k) is None}
    if missing:
        db.users.update_one({"_id": uid}, {"$set": missing})
        u.update(missing)
    return u

def save_user(uid: int, data: dict):
    db.users.update_one({"_id": uid}, {"$set": data}, upsert=True)

def get_badge(points: int, role: str, verified: bool) -> str:
    if role in ("admin", "superadmin"): return "⚡ FONDATEUR"
    if role == "mod_litiges": return "⚖️ MOD LITIGES"
    if role == "mod_annonces": return "🛡️ MOD ANNONCES"
    if verified: return "✅ Vérifié"
    if points >= 1000: return "🏆 Platine"
    if points >= 500: return "🥇 Or"
    if points >= 200: return "🥈 Argent"
    return "🥉 Bronze"

def fmt_date(ts=None) -> str:
    if ts is None: ts = time.time()
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")

def try_objectid(val):
    try: return ObjectId(val)
    except Exception: return None

async def safe_edit(query, text, reply_markup=None, parse_mode="HTML"):
    try:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "not modified" not in str(e).lower():
            log.warning(f"safe_edit fallback : {e}")
            try:
                await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception as e2:
                log.error(f"safe_edit a échoué : {e2}")

# ══════════════════════════════════════════════════════════════
#  MENU PRINCIPAL
# ══════════════════════════════════════════════════════════════

def build_main_menu() -> list:
    return [
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

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or f"User_{uid}"
    cfg = get_config()

    if cfg.get("mode_urgence") and uid != SUPER_ADMIN_ID:
        txt = "⚠️ <b>MAINTENANCE CRITIQUE</b>\n\nLe bot est gelé temporairement. Revenez plus tard."
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text(txt, parse_mode="HTML")
        return

    u = get_user(uid)
    if u.get("banni_jusqua", 0) > time.time():
        rem = int(u["banni_jusqua"] - time.time())
        await update.effective_message.reply_text(
            f"🔴 <b>Accès refusé.</b> Suspendu encore {rem // 60} minutes.", parse_mode="HTML")
        return

    save_user(uid, {"username": uname, "state": "IDLE"})

    txt = (
        f"🎮 <b>BIENVENUE SUR BOT MARKET ULTRA v3.1</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"Sécurité, Rapidité, Intermédiation automatisée.\n\n"
        f"👑 Badge : <code>{get_badge(u.get('points',0), u.get('role','membre'), u.get('verified',False))}</code>\n"
        f"💰 Solde Points : <code>{u.get('points',0)} pts</code>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"💡 <i>Faites votre choix via le tableau de bord :</i>"
    )
    kb = InlineKeyboardMarkup(build_main_menu())

    if update.callback_query:
        await safe_edit(update.callback_query, txt, kb)
    else:
        if ctx.args:
            arg = ctx.args[0]
            if arg.startswith("ref_"):
                try:
                    parrain_id = int(arg.split("_")[1])
                    if parrain_id != uid and not db.users.find_one({"_id": uid}):
                        save_user(uid, {"parrain": parrain_id})
                        db.users.update_one({"_id": parrain_id}, {"$inc": {"points": 50, "parrainages_comptes": 1}})
                        try:
                            await ctx.bot.send_message(parrain_id, "🎁 <b>+50 Points !</b> Un nouvel utilisateur a rejoint via votre lien.", parse_mode="HTML")
                        except Exception: pass
                except Exception: pass
            elif arg.startswith("acheter_"):
                id_ann = arg.split("_", 1)[1]
                await simuler_demande_achat(update, ctx, id_ann, uid)
                return
        await update.message.reply_text(txt, reply_markup=kb, parse_mode="HTML")

# ══════════════════════════════════════════════════════════════
#  TUNNEL DE VENTE
# ══════════════════════════════════════════════════════════════

async def executer_tunnel_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE, uid, text=None, photo_id=None):
    u = get_user(uid)
    state = u.get("state", "IDLE")
    ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})

    if not ann:
        db.annonces.insert_one({"vendeur_id": uid, "statut": "brouillon", "photos": [], "booste": False, "date_creation": time.time()})
        save_user(uid, {"state": "VENTE_JEU"})
        await update.effective_message.reply_text(
            "🎮 <b>Étape 1/7 : Nom du Jeu</b>\n\nQuel est le nom exact du jeu vidéo ?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:annuler_vente")]]))
        return

    if state == "VENTE_JEU" and text:
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"categorie": text}})
        save_user(uid, {"state": "VENTE_PLATEFORME"})
        kb = [[InlineKeyboardButton(p, callback_data=f"plat:{p}") for p in ["Android", "iOS", "PC", "Console"]]]
        await update.effective_message.reply_text(
            "📱 <b>Étape 2/7 : Plateforme</b>\n\nSélectionnez le support du compte :",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "VENTE_DESC" and text:
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"description": text}})
        save_user(uid, {"state": "VENTE_PHOTOS"})
        await update.effective_message.reply_text(
            "📸 <b>Étape 4/7 : Captures d'écran</b>\n\nEnvoyez photos puis cliquez Terminer :",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏁 Terminer l'envoi des photos", callback_data="plat:fin_photos")]]))

    elif state == "VENTE_PHOTOS" and photo_id:
        db.annonces.update_one({"_id": ann["_id"]}, {"$push": {"photos": photo_id}})
        await update.effective_message.reply_text("✅ Photo ajoutée. Continuez ou cliquez sur Terminer.")

    elif state == "VENTE_PRIX" and text:
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"prix": text}})
        save_user(uid, {"state": "VENTE_DEVISE"})
        kb = [[InlineKeyboardButton(d, callback_data=f"dev:{d}") for d in ["FCFA", "USDT", "EUR"]]]
        await update.effective_message.reply_text(
            "💱 <b>Étape 6/7 : Devise</b>\n\nChoisissez l'unité monétaire :",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        save_user(uid, {"state": "IDLE"})
        await update.effective_message.reply_text("⚠️ Étape incohérente. Relance /vendre ou Déposer Annonce.")

# ══════════════════════════════════════════════════════════════
#  ROUTEUR MESSAGES TEXTE & PHOTOS
# ══════════════════════════════════════════════════════════════

async def central_text_and_media_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    state = u.get("state", "IDLE")
    text = update.message.text if update.message else None
    photo = update.message.photo[-1].file_id if (update.message and update.message.photo) else None

    if state.startswith("VENTE_"):
        await executer_tunnel_vente(update, ctx, uid, text=text, photo_id=photo)
        return

    if state == "RECHERCHE_INPUT" and text:
        save_user(uid, {"state": "IDLE"})
        res = list(db.annonces.find({
            "statut": "approuve",
            "$or": [{"categorie": {"$regex": text, "$options": "i"}},
                    {"description": {"$regex": text, "$options": "i"}}]
        }))
        kb = [[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]
        if not res:
            await update.message.reply_text("🔍 Aucun résultat.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            txt = "🔍 <b>RÉSULTATS :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            for item in res[:15]:
                txt += f"🎮 <b>[{safe_html(item.get('categorie'))}]</b> - {safe_html(item.get('prix'))} {safe_html(item.get('devise'))}\n📝 {safe_html(item.get('description',''))[:80]}\n\n"
            await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    if state == "LITIGE_INPUT_RECOURS" and text:
        save_user(uid, {"state": "LITIGE_PROOFS", "tmp_litige_desc": text})
        await update.message.reply_text("📸 Envoyez une capture d'écran comme preuve :")
        return

    if state == "LITIGE_PROOFS" and photo:
        desc = u.get("tmp_litige_desc", "Aucune description")
        save_user(uid, {"state": "IDLE"})
        lit_id = db.litiges.insert_one({
            "demandeur_id": uid, "description": desc, "preuve_photo": photo,
            "statut": "ouvert", "date_creation": time.time()
        }).inserted_id
        await update.message.reply_text("⚖️ <b>Dossier transmis !</b> L'équipe va l'étudier.", parse_mode="HTML")
        try:
            await ctx.bot.send_message(
                SUPER_ADMIN_ID,
                f"🚨 <b>Nouveau litige</b> #{lit_id}\nDe : <code>{uid}</code>\n📝 {safe_html(desc)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Résolu", callback_data=f"litact:resolu:{lit_id}"),
                    InlineKeyboardButton("🚫 Sanctionner", callback_data=f"litact:sanction:{lit_id}")
                ]]))
        except Exception: pass
        return

    if state.startswith("REP_NOTE_") and text:
        id_tx = state.split("_")[2]
        save_user(uid, {"state": "IDLE"})
        tx_oid = try_objectid(id_tx)
        if tx_oid:
            db.transactions.update_one({"_id": tx_oid}, {"$set": {"reponse_vendeur": text}})
        await update.message.reply_text("⭐ Réponse publiée.")
        return

    if state.startswith("SETPROF_") and text:
        champ = state.split("_", 1)[1].lower()
        save_user(uid, {champ: text, "state": "IDLE"})
        await update.message.reply_text(f"✅ Profil mis à jour ! [{champ}] enregistré.")
        return

# ══════════════════════════════════════════════════════════════
#  ROUTEUR CALLBACKS
# ══════════════════════════════════════════════════════════════

async def central_callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    uid = update.effective_user.id
    u = get_user(uid)

    try:
        parts = data.split(":")
        prefix = parts[0]

        if prefix == "nav":
            await handle_nav(query, ctx, uid, u, parts)
        elif prefix == "setprof":
            champ = parts[1]
            save_user(uid, {"state": f"SETPROF_{champ}"})
            await safe_edit(query, f"✍️ Saisissez la nouvelle valeur pour : <b>{champ}</b>")
        elif prefix == "plat":
            await handle_plat(query, ctx, uid, parts)
        elif prefix == "dev":
            await handle_devise(query, ctx, uid, parts)
        elif prefix == "modact":
            await handle_moderation(query, ctx, parts)
        elif prefix == "admact":
            await handle_admin_action(query, ctx, uid, parts)
        elif prefix == "viewann":
            await handle_view_annonce(query, ctx, parts)
        elif prefix == "escrowact":
            await handle_escrow_action(query, ctx, parts)
        elif prefix == "litact":
            await handle_litige_action(query, ctx, uid, parts)
    except Exception as e:
        log.error(f"Erreur callback '{data}' : {e}\n{traceback.format_exc()}")
        try:
            await query.message.reply_text("⚠️ Erreur survenue. L'équipe a été notifiée.\nTape /start pour revenir au menu.")
        except Exception: pass

# ──────────────── NAVIGATION ────────────────

async def handle_nav(query, ctx, uid, u, parts):
    cible = parts[1]

    if cible == "retour":
        class FakeUpdate: pass
        fu = FakeUpdate()
        fu.callback_query = query
        fu.effective_user = query.from_user
        fu.effective_message = query.message
        await start(fu, ctx)

    elif cible == "annuler_vente":
        db.annonces.delete_one({"vendeur_id": uid, "statut": "brouillon"})
        save_user(uid, {"state": "IDLE"})
        await safe_edit(query, "❌ Création d'annonce annulée.",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "recherche":
        save_user(uid, {"state": "RECHERCHE_INPUT"})
        await safe_edit(query, "🔍 Saisissez le nom du jeu ou un mot-clé :",
                         InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif cible == "vendre":
        cfg = get_config()
        limite = cfg.get("limite_annonces_membre", 3)
        compte = db.annonces.count_documents({"vendeur_id": uid, "statut": "approuve"})
        if compte >= limite:
            await safe_edit(query, f"⚠️ <b>Quota atteint !</b> {compte}/{limite} annonces en ligne.",
                             InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]))
            return
        class FakeUpdate: pass
        fu = FakeUpdate()
        fu.effective_message = query.message
        await executer_tunnel_vente(fu, ctx, uid)

    elif cible == "marche_global":
        annonces = list(db.annonces.find({"statut": "approuve"}).sort("booste", -1).limit(20))
        txt = "🛍️ <b>ANNONCES ACTIVES :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        if not annonces: txt += "Aucun compte disponible actuellement."
        kb = []
        for item in annonces:
            pref = "🔥 " if item.get("booste") else "🔹 "
            txt += f"{pref}<b>{safe_html(item.get('categorie'))}</b> - <code>{safe_html(item.get('prix'))} {safe_html(item.get('devise'))}</code>\n"
            kb.append([InlineKeyboardButton(f"🛒 {item.get('categorie','?')} ({item.get('prix','?')})",
                       callback_data=f"viewann:inspecte:{item['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif cible == "mon_profil":
        nb_ventes = db.annonces.count_documents({"vendeur_id": uid, "statut": "vendu"})
        txt = (
            f"👤 <b>VOTRE PROFIL</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🆔 ID : <code>{uid}</code>\n"
            f"🌍 Nationalité : <code>{safe_html(u.get('nationalite'))}</code>\n"
            f"📞 Mobile : <code>{safe_html(u.get('telephone') or 'Non configuré')}</code> ({safe_html(u.get('tel_visibilite'))})\n"
            f"⏰ Horaires : <code>{safe_html(u.get('plage_horaire'))}</code>\n"
            f"🟢 Statut : <b>{safe_html(u.get('status_dispo','en ligne')).upper()}</b>\n"
            f"🤝 Ventes : <code>{nb_ventes}</code>\n"
            f"🎁 Filleuls : <code>{u.get('parrainages_comptes',0)}</code>\n"
            f"⚡ Points : <code>{u.get('points',0)}</code>"
        )
        kb = [
            [InlineKeyboardButton("🌍 Pays", callback_data="setprof:NATIONALITE"),
             InlineKeyboardButton("📞 Téléphone", callback_data="setprof:TELEPHONE")],
            [InlineKeyboardButton("⏰ Horaires", callback_data="setprof:PLAGE_HORAIRE"),
             InlineKeyboardButton("📱 WhatsApp", callback_data="setprof:WHATSAPP")],
            [InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]
        ]
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif cible == "mes_annonces":
        mine = list(db.annonces.find({"vendeur_id": uid, "statut": {"$ne": "brouillon"}}).limit(15))
        if not mine:
            await safe_edit(query, "📦 Vous n'avez encore aucune annonce.",
                             InlineKeyboardMarkup([[InlineKeyboardButton("➕ Créer", callback_data="nav:vendre")],
                                                   [InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))
            return
        txt = "📦 <b>VOS ANNONCES :</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        kb = []
        statut_label = {"en_attente": "🟡 En attente", "approuve": "✅ En ligne", "vendu": "🏷️ Vendu", "rejete": "❌ Rejeté"}
        for item in mine:
            st = statut_label.get(item.get("statut"), item.get("statut", "?"))
            txt += f"{st} — <b>{safe_html(item.get('categorie','?'))}</b> ({safe_html(item.get('prix','?'))})\n"
            if item.get("statut") in ("en_attente", "approuve"):
                kb.append([InlineKeyboardButton(f"🗑️ Supprimer {item.get('categorie','?')}", callback_data=f"viewann:suppr:{item['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif cible == "cgu":
        cfg = get_config()
        txt = f"📜 <b>CGU & CGV</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n{safe_html(cfg.get('cgu_text',''))}"
        await safe_edit(query, txt, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "leaderboard":
        pipeline = [{"$match": {"statut": "vendu"}}, {"$group": {"_id": "$vendeur_id", "total": {"$sum": 1}}},
                    {"$sort": {"total": -1}}, {"$limit": 5}]
        tops = list(db.annonces.aggregate(pipeline))
        txt = "📊 <b>TOP VENDEURS</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        meds = ["👑 1er", "🥈 2ème", "🥉 3ème", "🔹 4ème", "🔹 5ème"]
        if not tops: txt += "Aucune vente enregistrée pour le moment."
        for idx, item in enumerate(tops):
            vu = get_user(item["_id"])
            txt += f"{meds[idx]} : @{safe_html(vu.get('username','Anonyme'))} — <b>{item['total']} ventes</b>\n"
        await safe_edit(query, txt, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "parrainage":
        bot_username = (await ctx.bot.get_me()).username
        lien = f"https://t.me/{bot_username}?start=ref_{uid}"
        txt = (
            f"🎁 <b>PROGRAMME DE PARRAINAGE</b>\n\n"
            f"Gagnez 50 points par ami actif inscrit !\n\n"
            f"🔗 <b>Votre lien :</b>\n<code>{lien}</code>\n\n"
            f"👥 Filleuls actuels : <code>{u.get('parrainages_comptes',0)}</code>"
        )
        await safe_edit(query, txt, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "mes_alertes":
        db.alertes.update_one({"user_id": uid}, {"$addToSet": {"jeux": "Tous"}}, upsert=True)
        await safe_edit(query, "🔔 Abonné aux alertes générales.\nUtilise /alerte [jeu] pour cibler un jeu précis.",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "mes_litiges":
        save_user(uid, {"state": "LITIGE_INPUT_RECOURS"})
        await safe_edit(query, "⚖️ <b>OUVERTURE DE LITIGE</b>\n\nExpliquez précisément le problème rencontré :",
                         InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif cible == "admin_root":
        if uid != SUPER_ADMIN_ID:
            await query.answer("⚠️ Accès réservé au Fondateur.", show_alert=True)
            return
        cfg = get_config()
        st_rec = "OUVERT ✅" if cfg.get("recrutement_ouvert") else "FERMÉ ❌"
        st_urg = "ACTIF 🚨" if cfg.get("mode_urgence") else "INACTIF ✅"
        nb_litiges = db.litiges.count_documents({"statut": "ouvert"})
        nb_attente = db.annonces.count_documents({"statut": "en_attente"})
        txt = (
            f"🛠️ <b>PANNEAU D'ADMINISTRATION</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"Recrutement : <code>{st_rec}</code>\n"
            f"Mode Urgence : <code>{st_urg}</code>\n"
            f"📋 Annonces en attente : <code>{nb_attente}</code>\n"
            f"⚖️ Litiges ouverts : <code>{nb_litiges}</code>\n"
            f"💼 Commission : <code>{cfg.get('commission_pct',5)}%</code>"
        )
        kb = [
            [InlineKeyboardButton("🔄 Recrutement", callback_data="admact:toggle_rec"),
             InlineKeyboardButton("🚨 Urgence", callback_data="admact:toggle_urg")],
            [InlineKeyboardButton("📋 Annonces en attente", callback_data="admact:voir_attente"),
             InlineKeyboardButton("⚖️ Litiges", callback_data="admact:voir_litiges")],
            [InlineKeyboardButton("📊 Export rapport", callback_data="admact:export_pdf")],
            [InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]
        ]
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

# ──────────────── TUNNEL VENTE : PLATEFORME / PHOTOS ────────────────

async def handle_plat(query, ctx, uid, parts):
    action = parts[1]
    if action == "fin_photos":
        save_user(uid, {"state": "VENTE_PRIX"})
        await safe_edit(query, "💰 <b>Étape 5/7 : Prix</b>\n\nIndiquez le montant (ex: 15000, 25, 100) :")
    else:
        db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"plateforme": action}})
        save_user(uid, {"state": "VENTE_DESC"})
        await safe_edit(query, "📝 <b>Étape 3/7 : Description</b>\n\nDécrivez le compte (skins, rang, niveau...) :")

async def handle_devise(query, ctx, uid, parts):
    devise = parts[1]
    db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"},
                           {"$set": {"devise": devise, "statut": "en_attente", "date_depot": time.time()}})
    save_user(uid, {"state": "IDLE"})
    ann = db.annonces.find_one({"vendeur_id": uid, "statut": "en_attente"}, sort=[("date_depot", -1)])
    if not ann:
        await safe_edit(query, "⚠️ Erreur lors de la création. Réessaie /vendre.")
        return

    txt_mod = (
        f"⚖️ <b>MODÉRATION REQUISE</b>\n\n"
        f"Jeu : {safe_html(ann.get('categorie'))}\n"
        f"Plateforme : {safe_html(ann.get('plateforme'))}\n"
        f"Prix : {safe_html(ann.get('prix'))} {devise}\n"
        f"Description : {safe_html(ann.get('description',''))[:200]}"
    )
    kb_mod = [[
        InlineKeyboardButton("✅ Accepter", callback_data=f"modact:approuve:{ann['_id']}"),
        InlineKeyboardButton("❌ Rejeter", callback_data=f"modact:rejete:{ann['_id']}")
    ]]
    try:
        await ctx.bot.send_message(SUPER_ADMIN_ID, txt_mod, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_mod))
    except Exception as e:
        log.error(f"Échec notification modération : {e}")
    await safe_edit(query, "🎉 <b>Annonce envoyée à l'équipe !</b> Publication après validation.")

# ──────────────── MODÉRATION ────────────────

async def handle_moderation(query, ctx, parts):
    if query.from_user.id != SUPER_ADMIN_ID:
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True)
        return
    act, id_a = parts[1], parts[2]
    oid = try_objectid(id_a)
    if not oid:
        await safe_edit(query, "❌ ID d'annonce invalide.")
        return

    if act == "approuve":
        db.annonces.update_one({"_id": oid}, {"$set": {"statut": "approuve"}})
        item = db.annonces.find_one({"_id": oid})
        if not item: return
        v = get_user(item["vendeur_id"])
        bot_username = (await ctx.bot.get_me()).username
        txt_pub = (
            f"📣 <b>COMPTE DISPONIBLE !</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎮 Jeu : #{safe_html(item.get('categorie','').replace(' ', '_'))}\n"
            f"📱 Support : <code>{safe_html(item.get('plateforme'))}</code>\n"
            f"💰 Prix : <b>{safe_html(item.get('prix'))} {safe_html(item.get('devise'))}</b>\n"
            f"📝 {safe_html(item.get('description',''))}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 Vendeur : @{safe_html(v.get('username'))}\n\n"
            f"🤝 <i>Achat sécurisé via notre Escrow :</i>"
        )
        kb_pub = [[InlineKeyboardButton("🛒 Acheter en Escrow Sécurisé", url=f"https://t.me/{bot_username}?start=acheter_{item['_id']}")]]
        try:
            if item.get("photos"):
                await ctx.bot.send_photo(PUBLIC_CHANNEL_ID, item["photos"][0], caption=txt_pub,
                                         reply_markup=InlineKeyboardMarkup(kb_pub), parse_mode="HTML")
            else:
                await ctx.bot.send_message(PUBLIC_CHANNEL_ID, txt_pub, reply_markup=InlineKeyboardMarkup(kb_pub), parse_mode="HTML")
        except Exception as e:
            log.error(f"Échec publication canal : {e}")
        await safe_edit(query, "🟢 Annonce validée et publiée sur le canal.")
    else:
        db.annonces.update_one({"_id": oid}, {"$set": {"statut": "rejete"}})
        await safe_edit(query, "❌ Annonce rejetée.")

# ──────────────── VUE ANNONCE ────────────────

async def handle_view_annonce(query, ctx, parts):
    action, id_a = parts[1], parts[2]
    oid = try_objectid(id_a)
    if not oid:
        await query.answer("❌ Annonce invalide.", show_alert=True)
        return
    item = db.annonces.find_one({"_id": oid})
    if not item:
        await query.answer("❌ Annonce introuvable.", show_alert=True)
        return

    if action == "suppr":
        if item.get("vendeur_id") != query.from_user.id:
            await query.answer("🚫 Tu n'es pas le vendeur.", show_alert=True)
            return
        db.annonces.delete_one({"_id": oid})
        await safe_edit(query, "🗑️ Annonce supprimée.",
                         InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))
        return

    bot_username = (await ctx.bot.get_me()).username
    txt = f"🎮 <b>{safe_html(item.get('categorie'))}</b>\n\nPrix : {safe_html(item.get('prix'))} {safe_html(item.get('devise'))}\nDescription : {safe_html(item.get('description',''))}"
    kb = [[
        InlineKeyboardButton("🤝 Acheter via Escrow", url=f"https://t.me/{bot_username}?start=acheter_{item['_id']}"),
        InlineKeyboardButton("🔙 Marché", callback_data="nav:marche_global")
    ]]
    try:
        if item.get("photos"):
            await ctx.bot.send_photo(query.from_user.id, item["photos"][0], caption=txt,
                                     reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        else:
            await ctx.bot.send_message(query.from_user.id, txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    except Exception as e:
        log.error(f"Échec affichage annonce : {e}")

# ──────────────── ESCROW (séquestre bilatéral) ────────────────

async def simuler_demande_achat(update: Update, ctx: ContextTypes.DEFAULT_TYPE, id_ann, uid):
    oid = try_objectid(id_ann)
    if not oid:
        await update.message.reply_text("❌ Lien d'achat invalide.")
        return
    ann = db.annonces.find_one({"_id": oid})
    if not ann or ann.get("statut") != "approuve":
        await update.message.reply_text("❌ Cette annonce n'est plus active ou a déjà été vendue.")
        return
    if ann.get("vendeur_id") == uid:
        await update.message.reply_text("⚠️ Tu ne peux pas acheter ta propre annonce.")
        return

    tx_id = db.transactions.insert_one({
        "annonce_id": oid, "vendeur_id": ann["vendeur_id"], "acheteur_id": uid,
        "statut": "en_cours", "date_creation": time.time(),
        "confirmation_vendeur": False, "confirmation_acheteur": False
    }).inserted_id

    kb_v = [[InlineKeyboardButton("✅ Confirmer la livraison des accès", callback_data=f"escrowact:conf_vendeur:{tx_id}")]]
    kb_a = [[InlineKeyboardButton("✅ Confirmer la réception conforme", callback_data=f"escrowact:conf_acheteur:{tx_id}")]]

    try:
        await ctx.bot.send_message(
            ann["vendeur_id"],
            f"🚨 <b>UN ACHETEUR EST INTÉRESSÉ !</b>\n\nL'utilisateur <code>{uid}</code> a initié l'achat de <b>{safe_html(ann.get('categorie'))}</b>.\nTransmets les accès puis confirme :",
            reply_markup=InlineKeyboardMarkup(kb_v), parse_mode="HTML")
    except Exception as e:
        log.error(f"Échec notification vendeur : {e}")

    await update.message.reply_text(
        "⏳ <b>Procédure de sécurisation initiée !</b>\n\nLe vendeur va te transmettre les accès. Vérifie-les puis confirme :",
        reply_markup=InlineKeyboardMarkup(kb_a), parse_mode="HTML")

async def handle_escrow_action(query, ctx, parts):
    act, tx_id = parts[1], parts[2]
    oid = try_objectid(tx_id)
    if not oid: return
    tx = db.transactions.find_one({"_id": oid})
    if not tx: return

    if act == "conf_vendeur":
        db.transactions.update_one({"_id": oid}, {"$set": {"confirmation_vendeur": True}})
    elif act == "conf_acheteur":
        db.transactions.update_one({"_id": oid}, {"$set": {"confirmation_acheteur": True}})

    tx = db.transactions.find_one({"_id": oid})
    if tx.get("confirmation_vendeur") and tx.get("confirmation_acheteur"):
        db.transactions.update_one({"_id": oid}, {"$set": {"statut": "valide"}})
        db.annonces.update_one({"_id": tx["annonce_id"]}, {"$set": {"statut": "vendu"}})
        db.users.update_one({"_id": tx["vendeur_id"]}, {"$inc": {"points": 100}})
        msg = "🟢 <b>TRANSACTION TERMINÉE !</b>\n\nLes deux parties ont confirmé. Échange validé."
        for dest in (tx["vendeur_id"], tx["acheteur_id"]):
            try:
                await ctx.bot.send_message(dest, msg, parse_mode="HTML")
            except Exception: pass
    else:
        await safe_edit(query, "⏳ En attente de la confirmation de l'autre partie.")

# ──────────────── ADMIN ────────────────

async def handle_admin_action(query, ctx, uid, parts):
    if uid != SUPER_ADMIN_ID:
        await query.answer("🚫 Réservé au Fondateur.", show_alert=True)
        return
    act = parts[1]
    cfg = get_config()

    if act == "toggle_rec":
        db.config.update_one({"type": "global"}, {"$set": {"recrutement_ouvert": not cfg.get("recrutement_ouvert", False)}})
        await query.answer("✅ Statut recrutement modifié !")
        await handle_nav(query, ctx, uid, get_user(uid), ["nav", "admin_root"])

    elif act == "toggle_urg":
        db.config.update_one({"type": "global"}, {"$set": {"mode_urgence": not cfg.get("mode_urgence", False)}})
        await query.answer("🚨 Mode urgence modifié !")
        await handle_nav(query, ctx, uid, get_user(uid), ["nav", "admin_root"])

    elif act == "voir_attente":
        items = list(db.annonces.find({"statut": "en_attente"}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucune annonce en attente.",
                             InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]]))
            return
        kb = []
        for it in items:
            kb.append([
                InlineKeyboardButton(f"✅ {it.get('categorie','?')[:15]}", callback_data=f"modact:approuve:{it['_id']}"),
                InlineKeyboardButton("❌", callback_data=f"modact:rejete:{it['_id']}")
            ])
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, f"📋 <b>{len(items)} annonce(s) en attente</b>", InlineKeyboardMarkup(kb))

    elif act == "voir_litiges":
        items = list(db.litiges.find({"statut": "ouvert"}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucun litige ouvert.",
                             InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]]))
            return
        txt = f"⚖️ <b>{len(items)} litige(s) ouvert(s)</b>\n\n"
        kb = []
        for it in items:
            txt += f"🆔 {it['_id']} — <code>{it.get('demandeur_id')}</code>\n📝 {safe_html(it.get('description',''))[:60]}\n\n"
            kb.append([
                InlineKeyboardButton("✅ Résolu", callback_data=f"litact:resolu:{it['_id']}"),
                InlineKeyboardButton("🚫 Sanctionner", callback_data=f"litact:sanction:{it['_id']}")
            ])
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "export_pdf":
        buffer = io.BytesIO()
        nb_vendu = db.annonces.count_documents({"statut": "vendu"})
        nb_users = db.users.count_documents({})
        nb_litiges = db.litiges.count_documents({})
        buffer.write(
            f"RAPPORT BOT MARKET — {fmt_date()}\n================================\n"
            f"Utilisateurs : {nb_users}\nTransactions validées : {nb_vendu}\nLitiges (total) : {nb_litiges}\n".encode())
        buffer.seek(0)
        try:
            await ctx.bot.send_document(uid, document=InputFile(buffer, filename=f"rapport_{fmt_date()}.txt"),
                                        caption="📊 Rapport exporté.")
        except Exception as e:
            log.error(f"Échec export : {e}")

# ──────────────── LITIGES (admin) ────────────────

async def handle_litige_action(query, ctx, uid, parts):
    if uid != SUPER_ADMIN_ID:
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True)
        return
    act, lit_id = parts[1], parts[2]
    oid = try_objectid(lit_id)
    if not oid: return
    lit = db.litiges.find_one({"_id": oid})
    if not lit: return

    if act == "resolu":
        db.litiges.update_one({"_id": oid}, {"$set": {"statut": "resolu", "date_cloture": time.time()}})
        await safe_edit(query, "✅ Litige marqué résolu.")
        try:
            await ctx.bot.send_message(lit["demandeur_id"], "✅ Ton litige a été résolu par l'équipe.")
        except Exception: pass
    elif act == "sanction":
        db.litiges.update_one({"_id": oid}, {"$set": {"statut": "resolu", "sanction": True, "date_cloture": time.time()}})
        await safe_edit(query, "🚫 Sanction enregistrée.")

# ══════════════════════════════════════════════════════════════
#  COMMANDE /alerte
# ══════════════════════════════════════════════════════════════

async def cmd_alerte(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("🔔 Format : /alerte [nom du jeu]\nEx : /alerte Fortnite")
        return
    jeu = " ".join(ctx.args)
    db.alertes.update_one({"user_id": uid}, {"$addToSet": {"jeux": jeu}}, upsert=True)
    await update.message.reply_text(f"🔔 Alerte activée pour : <b>{safe_html(jeu)}</b>", parse_mode="HTML")

# ══════════════════════════════════════════════════════════════
#  GESTIONNAIRE D'ERREURS GLOBAL
# ══════════════════════════════════════════════════════════════

async def global_error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Exception non gérée :", exc_info=ctx.error)
    try:
        if SUPER_ADMIN_ID:
            await ctx.bot.send_message(
                SUPER_ADMIN_ID,
                f"🐛 <b>Erreur bot</b> :\n<code>{safe_html(str(ctx.error))[:500]}</code>",
                parse_mode="HTML")
    except Exception: pass

# ══════════════════════════════════════════════════════════════
#  POST INIT — supprime tout webhook résiduel
# ══════════════════════════════════════════════════════════════

async def post_init(application: Application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        log.info("✅ Webhook supprimé — mode polling propre.")
    except Exception as e:
        log.warning(f"Suppression webhook échouée (sans gravité) : {e}")
    log.info("✅ Bot Market Ultra v3.1 démarré avec succès.")

# ══════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("alerte", cmd_alerte))
    app.add_handler(CallbackQueryHandler(central_callback_router))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, central_text_and_media_handler))
    app.add_error_handler(global_error_handler)
    log.info("🚀 Lancement du polling Telegram...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
