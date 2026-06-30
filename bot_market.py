"""
╔══════════════════════════════════════════════════════════════╗
║         BOT MARKET ULTRA v4.0 — VERSION FINALE               ║
║   Fichier principal — importe escrow_ton.py pour la crypto   ║
╚══════════════════════════════════════════════════════════════╝

v4.6 – Corrections critiques + améliorations
- Achat par lien profond totalement réparé (stockage base, reprise automatique)
- Bouton Aide dans le menu (liste des commandes)
- Bouton CGU/CGV corrigé : affichage + acceptation intégrée
- Toutes les fonctionnalités antérieures conservées
"""

import os
import time
import io
import logging
import traceback
import threading
import datetime
import re
from flask import Flask
from pymongo import MongoClient
from bson.objectid import ObjectId
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import TelegramError

import escrow_ton as ton

# ══════════════════════════════════════════════════════════════
# ⚠️ BLOC FLASK — NE PAS MODIFIER
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

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(name)s - %(message)s", level=logging.INFO)
log = logging.getLogger("BotMarket")

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAEnLhcBXGUEoPMauQx8iP3TYvC2xMwkodU")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
PUBLIC_CHANNEL_ID = os.environ.get("PUBLIC_CHANNEL_ID", "@comptedejeux")
TEAM_CHANNEL_ID = os.environ.get("TEAM_CHANNEL_ID", "")

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
    "banni_jusqua": 0, "tmp_litige_desc": "", "wallet_ton": "",
    "tickets": [],
    "filleuls_qualifies": 0,
    "cgu_acceptees": False,
    "evaluations": [],       # liste de {de_user_id, note, commentaire, date}
}

DEFAULTS_CONFIG = {
    "type": "global", "recrutement_ouvert": False, "mode_urgence": False,
    "delai_anti_arnaque": 3600, "limite_annonces_membre": 3,
    "commission_pct": 5, "admin_ton_wallet": "",
    "seuil_double_validation_ton": 5.0,
    "taux_secours_ton_usd": 5.0, "taux_secours_usd_to_xof": 600.0,
    "cgu_text": (
        "📋 CONDITIONS GÉNÉRALES D'UTILISATION\n\n"
        "1. L'utilisation de l'arbitrage intermédiaire (Escrow) est recommandée.\n"
        "2. Toute tentative d'arnaque entraîne un bannissement immédiat.\n"
        "3. Les annonces doivent être honnêtes et vérifiables.\n"
        "4. Le bot et son équipe ne sont pas responsables hors du cadre prévu.\n"
        "5. Tout litige doit être signalé via le Centre des Litiges."
    ),
}

if not db.config.find_one({"type": "global"}):
    db.config.insert_one(DEFAULTS_CONFIG)

ROLE_LEVEL = {"membre": 0, "gerant": 1, "admin": 2, "superadmin": 3}
ROLE_LABEL = {"membre": "👤 Membre", "gerant": "🛡️ Gérant", "admin": "⚙️ Admin", "superadmin": "⚡ FONDATEUR"}

_callback_timestamps = {}
MAX_CALLBACKS_PER_SEC = 4

def check_callback_rate(user_id: int) -> bool:
    now = time.time()
    timestamps = _callback_timestamps.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < 1.0]
    if len(timestamps) >= MAX_CALLBACKS_PER_SEC:
        return False
    timestamps.append(now)
    _callback_timestamps[user_id] = timestamps
    return True

def safe_html(text) -> str:
    if text is None: return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def get_config():
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

def save_user(uid, data):
    db.users.update_one({"_id": uid}, {"$set": data}, upsert=True)

def get_role(uid, u=None):
    if uid == SUPER_ADMIN_ID:
        return "superadmin"
    u = u or get_user(uid)
    return u.get("role", "membre")

def has_level(uid, u, min_role):
    return ROLE_LEVEL.get(get_role(uid, u), 0) >= ROLE_LEVEL.get(min_role, 99)

def fmt_date(ts=None):
    if ts is None: ts = time.time()
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")

def try_objectid(val):
    try: return ObjectId(val)
    except: return None

def log_audit(action, details, acted_by):
    db.audit_logs.insert_one({"action": action, "details": details, "acted_by": acted_by,
                              "date": fmt_date(), "timestamp": time.time()})

def is_blacklisted(uid):
    return db.blacklist.find_one({"user_id": uid}) is not None

async def safe_edit(query, text, reply_markup=None, parse_mode="HTML"):
    try:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "not modified" not in str(e).lower():
            try:
                await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception as e2:
                log.error(f"safe_edit a échoué : {e2}")

# ══════════════════════════════════════════════════════════════
#  VÉRIFICATIONS OBLIGATOIRES (ABONNEMENT + CGU)
# ══════════════════════════════════════════════════════════════

async def est_abonne_canal(ctx, user_id):
    try:
        membre = await ctx.bot.get_chat_member(chat_id=PUBLIC_CHANNEL_ID, user_id=user_id)
        return membre.status in ["member", "administrator", "creator"]
    except TelegramError as e:
        log.warning(f"Erreur vérification canal pour {user_id}: {e}")
        return False

async def verifier_etapes_obligatoires(update, ctx, uid, u):
    if uid == SUPER_ADMIN_ID:
        return True
    if not await est_abonne_canal(ctx, uid):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ J'ai rejoint, vérifier", callback_data="nav:verifier_abonnement")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "🔒 Pour utiliser le bot, tu dois d'abord t'abonner à notre canal :\n👉 "
                + PUBLIC_CHANNEL_ID + "\n\nClique sur le bouton ci-dessous après avoir rejoint.",
                reply_markup=kb)
        else:
            await update.effective_message.reply_text(
                "🔒 Pour utiliser le bot, tu dois d'abord t'abonner à notre canal :\n👉 "
                + PUBLIC_CHANNEL_ID + "\n\nClique sur le bouton ci-dessous après avoir rejoint.",
                reply_markup=kb)
        return False
    if not u.get("cgu_acceptees", False):
        cfg = get_config()
        cgu_texte = cfg.get("cgu_text", "CGU non disponibles.")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📜 J'accepte les CGU", callback_data="nav:accepter_cgu")]])
        if update.callback_query:
            await update.callback_query.edit_message_text(
                f"📜 <b>CONDITIONS GÉNÉRALES D'UTILISATION</b>\n\n{cgu_texte}\n\nEn appuyant sur le bouton, tu acceptes ces conditions.",
                parse_mode="HTML", reply_markup=kb)
        else:
            await update.effective_message.reply_text(
                f"📜 <b>CONDITIONS GÉNÉRALES D'UTILISATION</b>\n\n{cgu_texte}\n\nEn appuyant sur le bouton, tu acceptes ces conditions.",
                parse_mode="HTML", reply_markup=kb)
        return False
    return True

# ══════════════════════════════════════════════════════════════
#  GESTION DE L'ACHAT EN ATTENTE (stockage base)
# ══════════════════════════════════════════════════════════════

async def traiter_achat_en_attente(ctx, update, uid):
    """Vérifie si un achat est en attente pour cet utilisateur et le déclenche."""
    doc = db.achat_attente.find_one({"user_id": uid})
    if not doc:
        return False
    annonce_id = doc["annonce_id"]
    db.achat_attente.delete_one({"user_id": uid})  # Nettoyage immédiat
    try:
        message = update.effective_message if update else None
        if not message:
            log.error("Pas de message pour déclencher l'achat en attente")
            return False
        await proposer_choix_achat(message, ctx, annonce_id, uid)
        return True
    except Exception as e:
        log.error(f"Erreur lors du déclenchement de l'achat {annonce_id} pour {uid}: {e}")
        try:
            await update.effective_message.reply_text(
                "⚠️ Impossible d'afficher l'annonce demandée (erreur interne). Retour au menu.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]])
            )
        except Exception:
            pass
        return True  # On considère l'achat comme traité (même en erreur) pour ne pas bloquer

# ══════════════════════════════════════════════════════════════
#  MENU PRINCIPAL (avec bouton Aide)
# ══════════════════════════════════════════════════════════════

def build_main_menu(uid, u, cfg):
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
        [InlineKeyboardButton("🚫 Blacklist publique", callback_data="nav:blacklist_pub")],
        [InlineKeyboardButton("❓ Aide", callback_data="nav:help")],  # Nouveau
    ]
    if cfg.get("recrutement_ouvert") and get_role(uid, u) == "membre":
        kb.append([InlineKeyboardButton("🎯 Devenir Gérant", callback_data="nav:devenir_gerant")])
    if has_level(uid, u, "gerant"):
        kb.append([InlineKeyboardButton("⚡ Panneau d'Administration ⚡", callback_data="nav:admin_root")])
    return kb

async def afficher_menu_principal(update, ctx, uid, u=None, message=None):
    if message is None:
        message = update.effective_message if update else None
    if not message:
        return
    cfg = get_config()
    u = u or get_user(uid)
    txt = (
        f"🎮 <b>BIENVENUE SUR BOT MARKET ULTRA v4.0</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"Sécurité, Rapidité, Intermédiation automatisée.\n\n"
        f"👑 Rôle : <code>{ROLE_LABEL.get(get_role(uid,u))}</code>\n"
        f"💰 Points : <code>{u.get('points',0)}</code>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"💡 <i>Faites votre choix via le tableau de bord :</i>"
    )
    kb = InlineKeyboardMarkup(build_main_menu(uid, u, cfg))
    await message.reply_text(txt, reply_markup=kb, parse_mode="HTML")

async def executer_tunnel_vente_depuis_callback(query, ctx, uid):
    u = get_user(uid)
    ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})
    if not ann:
        db.annonces.insert_one({"vendeur_id": uid, "statut": "brouillon", "photos": [], "booste": False, "date_creation": time.time()})
        save_user(uid, {"state": "VENTE_JEU"})
        await query.message.reply_text(
            "🎮 <b>Étape 1/7 : Nom du Jeu</b>\n\nQuel est le nom exact du jeu vidéo ?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:annuler_vente")]]))
    else:
        await query.message.reply_text("Tu as déjà un brouillon en cours. Continue ou annule.")

# ══════════════════════════════════════════════════════════════
#  COMMANDE /start (avec sauvegarde achat en base)
# ══════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or f"User_{uid}"
    cfg = get_config()

    if is_blacklisted(uid) and uid != SUPER_ADMIN_ID:
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text("🚫 Tu es banni du Marketplace.")
        return

    if cfg.get("mode_urgence") and uid != SUPER_ADMIN_ID:
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text("⚠️ <b>MAINTENANCE CRITIQUE</b>\n\nLe bot est gelé temporairement.", parse_mode="HTML")
        return

    u = get_user(uid)
    if u.get("banni_jusqua", 0) > time.time():
        rem = int(u["banni_jusqua"] - time.time())
        await update.effective_message.reply_text(f"🔴 Suspendu encore {rem // 60} minutes.")
        return

    save_user(uid, {"username": uname, "state": "IDLE"})
    u["username"] = uname

    # Traitement des arguments (parrainage / achat)
    if ctx.args:
        arg = ctx.args[0]
        if arg.startswith("ref_"):
            try:
                parrain_id = int(arg.split("_")[1])
                if parrain_id != uid and not db.users.find_one({"_id": uid}):
                    save_user(uid, {"parrain": parrain_id})
                    db.users.update_one({"_id": parrain_id}, {"$inc": {"points": 50, "parrainages_comptes": 1}})
                    try:
                        await ctx.bot.send_message(parrain_id, "🎁 +50 Points ! Un nouvel utilisateur a rejoint via ton lien.")
                    except Exception as e:
                        log.warning(f"Impossible de notifier parrain {parrain_id}: {e}")
            except Exception as e:
                log.warning(f"Erreur traitement ref_: {e}")
        elif arg.startswith("acheter_"):
            annonce_id = arg.split("_", 1)[1]
            # Stockage en base pour persistance même après redémarrage
            db.achat_attente.update_one(
                {"user_id": uid},
                {"$set": {"annonce_id": annonce_id, "date": time.time()}},
                upsert=True
            )

    # Vérifications obligatoires
    if uid != SUPER_ADMIN_ID:
        if not await verifier_etapes_obligatoires(update, ctx, uid, u):
            return
        if await traiter_achat_en_attente(ctx, update, uid):
            return

    await afficher_menu_principal(update, ctx, uid, u)

# ══════════════════════════════════════════════════════════════
#  COMMANDE /help
# ══════════════════════════════════════════════════════════════

HELP_TEXT = (
    "📖 <b>GUIDE DU BOT MARKET ULTRA</b>\n"
    "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
    "🛍️ <b>Marketplace de comptes/jeux</b> : publie tes comptes, recherche ou achète via un système sécurisé.\n\n"
    "🔹 <b>Vendre</b> : dépose une annonce (7 étapes), elle sera validée par un modérateur puis publiée sur le canal.\n"
    "🔹 <b>Acheter</b> : depuis le canal ou la liste, choisis un compte et sélectionne :\n"
    "   - <b>Direct</b> : négociation libre, aucune protection.\n"
    "   - <b>Escrow</b> : le bot bloque tes fonds jusqu'à confirmation de réception, puis libère au vendeur (petite commission).\n\n"
    "🎁 <b>Parrainage</b> : partage ton lien et gagne des tickets 'sans commission' tous les 5 filleuls actifs.\n"
    "⚖️ <b>Litiges</b> : en cas de problème, signale un litige. L'équipe tranche dans un délai de 7 jours.\n"
    "📜 <b>CGU</b> : lis et accepte les conditions dans le menu.\n\n"
    "💡 <i>Commandes :</i>\n"
    "/start – Menu principal\n"
    "/help – Cette aide\n"
    "/alerte [jeu] – Être notifié des nouvelles annonces pour un jeu\n"
    "/info <ID> – (équipe) Fiche détaillée d'un membre"
)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")

# ══════════════════════════════════════════════════════════════
#  TUNNEL DE VENTE (photo obligatoire, album, confirmation)
# ══════════════════════════════════════════════════════════════

LIMITES = {
    "categorie": 50,
    "description": 500,
    "prix": 20,
    "devise": 30,
}

def nettoyer_prix(texte):
    return ''.join(c for c in texte if c.isdigit() or c == '.')[:20]

async def executer_tunnel_vente(update, ctx, uid, text=None, photo_id=None, album_photos=None):
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
        if len(text) > LIMITES["categorie"]:
            await update.effective_message.reply_text(f"⚠️ Maximum {LIMITES['categorie']} caractères.")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"categorie": text}})
        save_user(uid, {"state": "VENTE_PLATEFORME"})
        kb = [[InlineKeyboardButton(p, callback_data=f"plat:{p}") for p in ["Android", "iOS", "PC", "Console"]]]
        await update.effective_message.reply_text("📱 <b>Étape 2/7 : Plateforme</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    elif state == "VENTE_DESC" and text:
        if len(text) > LIMITES["description"]:
            await update.effective_message.reply_text(f"⚠️ Maximum {LIMITES['description']} caractères.")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"description": text}})
        save_user(uid, {"state": "VENTE_PHOTOS"})
        await update.effective_message.reply_text(
            "📸 <b>Étape 4/7 : Photos</b>\n\nEnvoyez vos photos puis cliquez Terminer. ⚠️ Au moins une photo est obligatoire.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏁 Terminer", callback_data="plat:fin_photos")]]))

    elif state == "VENTE_PHOTOS":
        if photo_id:
            db.annonces.update_one({"_id": ann["_id"]}, {"$push": {"photos": photo_id}})
            await update.effective_message.reply_text("✅ Photo ajoutée.")
        elif album_photos:
            db.annonces.update_one({"_id": ann["_id"]}, {"$push": {"photos": {"$each": album_photos}}})
            await update.effective_message.reply_text(f"✅ {len(album_photos)} photo(s) ajoutée(s).")

    elif state == "VENTE_PRIX" and text:
        prix_nettoye = nettoyer_prix(text)
        if not prix_nettoye:
            await update.effective_message.reply_text("⚠️ Prix invalide (chiffres uniquement).")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"prix": prix_nettoye}})
        save_user(uid, {"state": "VENTE_DEVISE"})
        await update.effective_message.reply_text("💱 <b>Étape 6/7 : Devise</b>", parse_mode="HTML")

    elif state == "VENTE_DEVISE" and text:
        if len(text) > LIMITES["devise"]:
            await update.effective_message.reply_text(f"⚠️ Maximum {LIMITES['devise']} caractères.")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"devise": text, "statut": "en_attente", "date_depot": time.time()}})
        save_user(uid, {"state": "IDLE"})
        await soumettre_a_moderation(update.effective_message, ctx, ann["_id"])
    else:
        save_user(uid, {"state": "IDLE"})
        await update.effective_message.reply_text("⚠️ Étape incohérente. Relance /start.")

async def soumettre_a_moderation(message, ctx, ann_id):
    ann = db.annonces.find_one({"_id": ann_id})
    if not ann: return
    txt_mod = (
        f"⚖️ <b>MODÉRATION REQUISE</b>\n\n"
        f"Jeu : {safe_html(ann.get('categorie'))}\nPlateforme : {safe_html(ann.get('plateforme'))}\n"
        f"Prix : {safe_html(ann.get('prix'))} {safe_html(ann.get('devise'))}\n"
        f"Description : {safe_html(ann.get('description',''))[:200]}"
    )
    kb_mod = [[
        InlineKeyboardButton("✅ Accepter", callback_data=f"modact:approuve:{ann['_id']}"),
        InlineKeyboardButton("❌ Rejeter", callback_data=f"modact:rejete:{ann['_id']}")
    ]]
    for gid in get_gerants_et_plus():
        try:
            await ctx.bot.send_message(gid, txt_mod, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_mod))
        except Exception as e:
            log.warning(f"Impossible d'envoyer modération à {gid}: {e}")
    await message.reply_text("🎉 <b>Annonce envoyée à l'équipe !</b> Délai moyen de validation : 1 à 4 heures.", parse_mode="HTML")

def get_gerants_et_plus():
    ids = [SUPER_ADMIN_ID]
    for u in db.users.find({"role": {"$in": ["gerant", "admin"]}}):
        ids.append(u["_id"])
    return list(set(ids))

# ══════════════════════════════════════════════════════════════
#  ROUTEUR MESSAGES TEXTE & PHOTOS
# ══════════════════════════════════════════════════════════════

async def central_text_and_media_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)

    if uid != SUPER_ADMIN_ID:
        if not await verifier_etapes_obligatoires(update, ctx, uid, u):
            return

    if await ton.handle_ton_input(update, ctx, ctx.bot, SUPER_ADMIN_ID):
        return

    state = u.get("state", "IDLE")
    text = update.message.text if update.message else None
    photo_id = update.message.photo[-1].file_id if update.message and update.message.photo else None

    if state == "VENTE_PHOTOS" and photo_id:
        await executer_tunnel_vente(update, ctx, uid, photo_id=photo_id)
        return

    if state.startswith("VENTE_"):
        await executer_tunnel_vente(update, ctx, uid, text=text, photo_id=photo_id)
        return

    if state == "RECHERCHE_INPUT" and text:
        save_user(uid, {"state": "IDLE"})
        escaped_text = re.escape(text)
        res = list(db.annonces.find({"statut": "approuve",
            "$or": [{"categorie": {"$regex": escaped_text, "$options": "i"}},
                    {"description": {"$regex": escaped_text, "$options": "i"}}]}))
        kb = [[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]
        if not res:
            await update.message.reply_text("🔍 Aucun résultat.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            txt = "🔍 <b>RÉSULTATS :</b>\n\n"
            for item in res[:15]:
                txt += f"🎮 <b>[{safe_html(item.get('categorie'))}]</b> - {safe_html(item.get('prix'))} {safe_html(item.get('devise'))}\n\n"
            await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    if state == "LITIGE_INPUT_RECOURS" and text:
        save_user(uid, {"state": "LITIGE_PROOFS", "tmp_litige_desc": text})
        await update.message.reply_text("📸 Envoyez une capture d'écran comme preuve :")
        return

    if state == "LITIGE_PROOFS" and photo_id:
        desc = u.get("tmp_litige_desc", "Aucune description")
        save_user(uid, {"state": "IDLE"})
        lit_id = db.litiges.insert_one({"demandeur_id": uid, "description": desc, "preuve_photo": photo_id,
                                        "statut": "ouvert", "date_creation": time.time()}).inserted_id
        await update.message.reply_text("⚖️ Dossier transmis !")
        for gid in get_gerants_et_plus():
            try:
                await ctx.bot.send_message(gid,
                    f"🚨 <b>Nouveau litige</b> #{lit_id}\nDe : <code>{uid}</code>\n📝 {safe_html(desc)}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Résolu→Acheteur", callback_data=f"litact:faveur_ach:{lit_id}"),
                        InlineKeyboardButton("✅ Résolu→Vendeur", callback_data=f"litact:faveur_ven:{lit_id}")
                    ], [InlineKeyboardButton("🚫 Sanctionner", callback_data=f"litact:sanction:{lit_id}")]]))
            except Exception as e:
                log.warning(f"Notification litige échouée pour {gid}: {e}")
        return

    if state.startswith("SETPROF_") and text:
        champ = state.split("_", 1)[1].lower()
        save_user(uid, {champ: text, "state": "IDLE"})
        await update.message.reply_text(f"✅ Profil mis à jour ! [{champ}] enregistré.")
        return

    if state == "CANDIDATURE_MOTIF" and text:
        save_user(uid, {"state": "IDLE"})
        cand_id = db.candidatures.insert_one({
            "user_id": uid, "username": u.get("username","?"), "motif": text,
            "statut": "en_attente", "date": fmt_date()
        }).inserted_id
        await update.message.reply_text("🎯 Candidature envoyée ! Tu seras notifié de la décision.")
        try:
            await ctx.bot.send_message(SUPER_ADMIN_ID,
                f"🎯 <b>Nouvelle candidature Gérant</b>\n👤 @{safe_html(u.get('username'))} (<code>{uid}</code>)\n📝 {safe_html(text)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Accepter", callback_data=f"candidact:accepter:{cand_id}"),
                    InlineKeyboardButton("❌ Refuser", callback_data=f"candidact:refuser:{cand_id}")
                ]]))
        except Exception as e:
            log.warning(f"Notification candidature superadmin échouée: {e}")
        return

    if state == "MODIF_DESC" and text:
        ctx.user_data["modif_desc"] = text
        save_user(uid, {"state": "MODIF_PRIX"})
        await update.message.reply_text("💰 Nouveau prix :")
        return

    if state == "MODIF_PRIX" and text:
        ann_id = ctx.user_data.get("modif_ann_id")
        ancien = db.annonces.find_one({"_id": try_objectid(ann_id)})
        if not ancien:
            await update.message.reply_text("❌ Erreur, annonce introuvable.")
            save_user(uid, {"state": "IDLE"})
            return
        nouvelle_desc = ctx.user_data.get("modif_desc", ancien.get("description"))
        db.annonces.update_one({"_id": ancien["_id"]}, {"$set": {
            "modification_en_attente": True,
            "nouvelle_description": nouvelle_desc, "nouveau_prix": text
        }})
        save_user(uid, {"state": "IDLE"})
        await update.message.reply_text("✅ Modification envoyée pour validation !")
        txt_mod = (
            f"✏️ <b>MODIFICATION D'ANNONCE À VALIDER</b>\n\n"
            f"<b>AVANT :</b>\n{safe_html(ancien.get('description'))[:150]}\n💰 {safe_html(ancien.get('prix'))}\n\n"
            f"<b>APRÈS :</b>\n{safe_html(nouvelle_desc)[:150]}\n💰 {safe_html(text)}"
        )
        for gid in get_gerants_et_plus():
            try:
                await ctx.bot.send_message(gid, txt_mod, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Approuver", callback_data=f"modifact:approuver:{ancien['_id']}"),
                        InlineKeyboardButton("❌ Refuser", callback_data=f"modifact:refuser:{ancien['_id']}")
                    ]]))
            except Exception as e:
                log.warning(f"Notification modification échouée pour {gid}: {e}")
        ctx.user_data.pop("modif_desc", None)
        ctx.user_data.pop("modif_ann_id", None)
        return

    if state.startswith("ADMCFG_") and text:
        await traiter_config_admin(update, ctx, state, text)
        return

# ══════════════════════════════════════════════════════════════
#  CONFIG ADMIN
# ══════════════════════════════════════════════════════════════

ADMCFG_FIELDS = {
    "ADMCFG_LIMITE": ("limite_annonces_membre", int),
    "ADMCFG_DELAI": ("delai_anti_arnaque", int),
    "ADMCFG_COMMISSION": ("commission_pct", float),
    "ADMCFG_SEUIL": ("seuil_double_validation_ton", float),
    "ADMCFG_WALLET": ("admin_ton_wallet", str),
}

async def traiter_config_admin(update, ctx, state, text):
    if state not in ADMCFG_FIELDS:
        return
    key, caster = ADMCFG_FIELDS[state]
    try:
        value = caster(text.replace(",", ".")) if caster != str else text.strip()
    except Exception:
        await update.message.reply_text("⚠️ Valeur invalide.")
        return
    db.config.update_one({"type": "global"}, {"$set": {key: value}}, upsert=True)
    log_audit("CONFIG_MODIFIEE", f"{key} = {value}", update.effective_user.id)
    save_user(update.effective_user.id, {"state": "IDLE"})
    await update.message.reply_text(f"✅ {key} mis à jour : {value}")

# ══════════════════════════════════════════════════════════════
#  ROUTEUR CALLBACKS
# ══════════════════════════════════════════════════════════════

async def central_callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    uid = update.effective_user.id
    u = get_user(uid)

    if not check_callback_rate(uid):
        log.warning(f"Rate limit callback atteint pour {uid}")
        return

    if uid != SUPER_ADMIN_ID and data not in ("nav:verifier_abonnement", "nav:accepter_cgu"):
        if not await verifier_etapes_obligatoires(update, ctx, uid, u):
            return

    try:
        if data.startswith("tonact:"):
            if await ton.handle_ton_callbacks(query, ctx, ctx.bot, SUPER_ADMIN_ID):
                return

        parts = data.split(":")
        prefix = parts[0]

        if prefix == "nav":
            await handle_nav(query, ctx, uid, u, parts)
        elif prefix == "setprof":
            await handle_setprof(query, ctx, uid, parts)
        elif prefix == "plat":
            await handle_plat(query, ctx, uid, parts)
        elif prefix == "modact":
            await handle_moderation(query, ctx, parts)
        elif prefix == "modifact":
            await handle_modification_annonce(query, ctx, parts)
        elif prefix == "admact":
            await handle_admin_action(query, ctx, uid, parts)
        elif prefix == "viewann":
            await handle_view_annonce(query, ctx, parts)
        elif prefix == "achatchoice":
            await handle_achat_choice(query, ctx, uid, parts)
        elif prefix == "litact":
            await handle_litige_action(query, ctx, uid, parts)
        elif prefix == "candidact":
            await handle_candidature_action(query, ctx, uid, parts)
        elif prefix == "roleact":
            await handle_role_action(query, ctx, uid, parts)
        elif prefix == "blact":
            await handle_blacklist_action(query, ctx, uid, parts)
        elif prefix == "memberspage":
            await handle_members_page(query, ctx, uid, u, parts)
        elif prefix == "memberinfo":
            await handle_member_info(query, uid, parts)
    except Exception as e:
        log.error(f"Erreur callback '{data}' : {e}\n{traceback.format_exc()}")
        try:
            await query.message.reply_text("⚠️ Erreur survenue. Tape /start pour revenir au menu.")
        except Exception as e2:
            log.warning(f"Impossible de notifier l'erreur callback: {e2}")

# ══════════════════════════════════════════════════════════════
#  NAVIGATION (avec nouvel aide, cgu corrigé, reprise achat)
# ══════════════════════════════════════════════════════════════

async def handle_nav(query, ctx, uid, u, parts):
    cible = parts[1]
    cfg = get_config()

    if cible == "verifier_abonnement":
        if uid != SUPER_ADMIN_ID and await est_abonne_canal(ctx, uid):
            if not u.get("cgu_acceptees", False):
                cgu_texte = cfg.get("cgu_text", "")
                await query.message.edit_text(
                    f"📜 <b>CONDITIONS GÉNÉRALES D'UTILISATION</b>\n\n{cgu_texte}\n\nEn appuyant sur le bouton, tu acceptes ces conditions.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 J'accepte les CGU", callback_data="nav:accepter_cgu")]]))
                return
            else:
                if await traiter_achat_en_attente(ctx, query, uid):
                    return
                await afficher_menu_principal(None, ctx, uid, u, message=query.message)
                return
        else:
            await query.answer("Tu n'es pas encore abonné au canal !", show_alert=True)
            return

    if cible == "accepter_cgu":
        if uid != SUPER_ADMIN_ID:
            save_user(uid, {"cgu_acceptees": True})
            await query.answer("✅ CGU acceptées !", show_alert=True)
            if await traiter_achat_en_attente(ctx, query, uid):
                return
            await afficher_menu_principal(None, ctx, uid, u, message=query.message)
            return

    if cible == "retour":
        if await traiter_achat_en_attente(ctx, query, uid):
            return
        await afficher_menu_principal(None, ctx, uid, u, message=query.message)
        return

    if cible == "help":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]])
        await query.message.edit_text(HELP_TEXT, parse_mode="HTML", reply_markup=kb)
        return

    if cible == "cgu":
        # Afficher les CGU, avec bouton d'acceptation si pas encore acceptées
        kb_rows = []
        if not u.get("cgu_acceptees", False):
            kb_rows.append([InlineKeyboardButton("✅ J'accepte les CGU", callback_data="nav:accepter_cgu")])
        kb_rows.append([InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")])
        await query.message.edit_text(
            f"📜 <b>CONDITIONS GÉNÉRALES D'UTILISATION</b>\n\n{safe_html(cfg.get('cgu_text',''))}",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # --- Les autres cibles (inchangées) ---
    if cible == "annuler_vente":
        db.annonces.delete_one({"vendeur_id": uid, "statut": "brouillon"})
        save_user(uid, {"state": "IDLE"})
        await safe_edit(query, "❌ Annulé.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "recherche":
        save_user(uid, {"state": "RECHERCHE_INPUT"})
        await safe_edit(query, "🔍 Mot-clé recherché :", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif cible == "vendre":
        if get_role(uid, u) == "membre":
            anciennete = time.time() - u.get("date_inscription", time.time())
            delai = cfg.get("delai_anti_arnaque", 3600)
            if anciennete < delai:
                rem = int(delai - anciennete)
                await safe_edit(query, f"⏳ <b>Anti-arnaque :</b> Tu peux publier ta première annonce dans {rem // 60} min.",
                                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))
                return
        limite = cfg.get("limite_annonces_membre", 3)
        compte = db.annonces.count_documents({"vendeur_id": uid, "statut": "approuve"})
        if compte >= limite:
            await safe_edit(query, f"⚠️ Quota atteint ({compte}/{limite}).",
                            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")]]))
            return
        await executer_tunnel_vente_depuis_callback(query, ctx, uid)

    elif cible == "marche_global":
        annonces = list(db.annonces.find({"statut": "approuve"}).sort("booste", -1).limit(20))
        txt = "🛍️ <b>ANNONCES ACTIVES :</b>\n\n"
        if not annonces: txt += "Aucun compte disponible."
        kb = []
        for item in annonces:
            pref = "🔥 " if item.get("booste") else "🔹 "
            txt += f"{pref}<b>{safe_html(item.get('categorie'))}</b> - {safe_html(item.get('prix'))} {safe_html(item.get('devise'))}\n"
            kb.append([InlineKeyboardButton(f"🛒 {item.get('categorie','?')} ({item.get('prix','?')})", callback_data=f"viewann:inspecte:{item['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif cible == "mon_profil":
        nb_ventes = db.annonces.count_documents({"vendeur_id": uid, "statut": "vendu"})
        wallet = u.get("wallet_ton") or "Non renseigné"
        evals = u.get("evaluations", [])
        if evals:
            moyenne = round(sum(e["note"] for e in evals) / len(evals), 1)
            stars = "⭐" * int(moyenne) + f" ({moyenne}/5 - {len(evals)} avis)"
        else:
            stars = "ℹ️ Aucun avis"
        txt = (
            f"👤 <b>VOTRE PROFIL</b>\n\n🆔 <code>{uid}</code>\n"
            f"🎭 Rôle : <code>{ROLE_LABEL.get(get_role(uid,u))}</code>\n"
            f"🌍 {safe_html(u.get('nationalite'))}\n"
            f"📞 {safe_html(u.get('telephone') or 'Non configuré')} ({safe_html(u.get('tel_visibilite'))})\n"
            f"⏰ {safe_html(u.get('plage_horaire'))}\n"
            f"🟢 <b>{safe_html(u.get('status_dispo','en ligne')).upper()}</b>\n"
            f"💼 Wallet TON : <code>{safe_html(wallet)}</code>\n"
            f"🤝 Ventes : {nb_ventes} | 🎁 Filleuls qualifiés : {u.get('filleuls_qualifies',0)} | ⚡ Points : {u.get('points',0)}\n"
            f"📈 Réputation : {stars}"
        )
        kb = [
            [InlineKeyboardButton("🌍 Pays", callback_data="setprof:NATIONALITE"),
             InlineKeyboardButton("📞 Téléphone", callback_data="setprof:TELEPHONE")],
            [InlineKeyboardButton("⏰ Horaires", callback_data="setprof:PLAGE_HORAIRE"),
             InlineKeyboardButton("💼 Wallet TON", callback_data="setprof:WALLET_TON")],
            [InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]
        ]
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif cible == "mes_annonces":
        mine = list(db.annonces.find({"vendeur_id": uid, "statut": {"$ne": "brouillon"}}).limit(15))
        if not mine:
            await safe_edit(query, "📦 Aucune annonce.", InlineKeyboardMarkup([[InlineKeyboardButton("➕ Créer", callback_data="nav:vendre")],[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))
            return
        txt = "📦 <b>VOS ANNONCES :</b>\n\n"
        kb = []
        lbl = {"en_attente": "🟡 En attente", "approuve": "✅ En ligne", "vendu": "🏷️ Vendu", "rejete": "❌ Rejeté", "en_cours": "🔄 En transaction"}
        for item in mine:
            st = lbl.get(item.get("statut"), item.get("statut", "?"))
            modif_flag = " ✏️(modif en attente)" if item.get("modification_en_attente") else ""
            txt += f"{st} — <b>{safe_html(item.get('categorie','?'))}</b> ({safe_html(item.get('prix','?'))}){modif_flag}\n"
            if item.get("statut") == "approuve" and not item.get("modification_en_attente"):
                kb.append([InlineKeyboardButton(f"✏️ Modifier {item.get('categorie','?')[:15]}", callback_data=f"viewann:modifier:{item['_id']}")])
            if item.get("statut") in ("en_attente", "approuve"):
                kb.append([InlineKeyboardButton(f"🗑️ Supprimer {item.get('categorie','?')[:15]}", callback_data=f"viewann:suppr:{item['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif cible == "leaderboard":
        pipeline = [{"$match": {"statut": "vendu"}}, {"$group": {"_id": "$vendeur_id", "total": {"$sum": 1}}}, {"$sort": {"total": -1}}, {"$limit": 5}]
        tops = list(db.annonces.aggregate(pipeline))
        txt = "📊 <b>TOP VENDEURS</b>\n\n"
        meds = ["👑 1er", "🥈 2ème", "🥉 3ème", "🔹 4ème", "🔹 5ème"]
        if not tops: txt += "Aucune vente."
        for idx, item in enumerate(tops):
            vu = get_user(item["_id"])
            txt += f"{meds[idx]} : @{safe_html(vu.get('username','Anonyme'))} — {item['total']} ventes\n"
        await safe_edit(query, txt, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "parrainage":
        bot_username = (await ctx.bot.get_me()).username
        lien = f"https://t.me/{bot_username}?start=ref_{uid}"
        txt = f"🎁 <b>PARRAINAGE</b>\n\n50 points par ami inscrit !\n\n🔗 <code>{lien}</code>\n\n👥 Filleuls qualifiés : {u.get('filleuls_qualifies',0)}"
        await safe_edit(query, txt, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "mes_alertes":
        db.alertes.update_one({"user_id": uid}, {"$addToSet": {"jeux": "Tous"}}, upsert=True)
        await safe_edit(query, "🔔 Abonné aux alertes générales.\n/alerte [jeu] pour cibler.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "mes_litiges":
        save_user(uid, {"state": "LITIGE_INPUT_RECOURS"})
        await safe_edit(query, "⚖️ Expliquez le problème :", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif cible == "blacklist_pub":
        bl = list(db.blacklist.find({}).limit(20))
        if not bl:
            txt = "🚫 <b>Blacklist publique</b>\n\nAucun arnaqueur signalé."
        else:
            txt = "🚫 <b>Blacklist publique</b>\n\n"
            for b in bl:
                bu = get_user(b["user_id"])
                txt += f"• @{safe_html(bu.get('username','?'))} — {safe_html(b.get('raison','Arnaque'))}\n"
        await safe_edit(query, txt, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "devenir_gerant":
        save_user(uid, {"state": "CANDIDATURE_MOTIF"})
        await safe_edit(query, "🎯 <b>Candidature Gérant</b>\n\nPourquoi veux-tu rejoindre l'équipe ?", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif cible == "admin_root":
        if not has_level(uid, u, "gerant"):
            await query.answer("⚠️ Accès réservé à l'équipe.", show_alert=True)
            return
        await afficher_admin_root(query, ctx, uid, u)

# (La suite du code avec toutes les autres fonctions est inchangée. Je les inclus ci-dessous.)

# ──────────────── GESTION PHOTOS (fin_photos vérifie photo obligatoire) ────────────────

async def handle_plat(query, ctx, uid, parts):
    action = parts[1]
    if action == "fin_photos":
        ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})
        if not ann or len(ann.get("photos", [])) == 0:
            await query.answer("⚠️ Vous devez ajouter au moins une photo.", show_alert=True)
            return
        save_user(uid, {"state": "VENTE_PRIX"})
        await safe_edit(query, "💰 <b>Étape 5/7 : Prix</b>\n\nMontant (ex: 15000, 25, 100) :")
    else:
        db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"plateforme": action}})
        save_user(uid, {"state": "VENTE_DESC"})
        await safe_edit(query, "📝 <b>Étape 3/7 : Description</b>\n\nDécrivez le compte :")

# ──────────────── MODÉRATION (avec lien contact direct) ────────────────

async def handle_moderation(query, ctx, parts):
    if not has_level(query.from_user.id, get_user(query.from_user.id), "gerant"):
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True)
        return
    act, id_a = parts[1], parts[2]
    oid = try_objectid(id_a)
    if not oid: return

    if act == "approuve":
        item = db.annonces.find_one({"_id": oid})
        if not item: return
        v = get_user(item["vendeur_id"])
        bot_username = (await ctx.bot.get_me()).username
        txt_pub = (
            f"📣 <b>COMPTE DISPONIBLE !</b>\n\n🎮 #{safe_html(item.get('categorie','').replace(' ', '_'))}\n"
            f"📱 <code>{safe_html(item.get('plateforme'))}</code>\n💰 <b>{safe_html(item.get('prix'))} {safe_html(item.get('devise'))}</b>\n"
            f"📝 {safe_html(item.get('description',''))}\n\n👤 Vendeur : @{safe_html(v.get('username'))}"
        )
        kb_pub = [
            [InlineKeyboardButton("🛒 Acheter", url=f"https://t.me/{bot_username}?start=acheter_{item['_id']}")],
            [InlineKeyboardButton("💬 Contacter le vendeur", url=f"tg://user?id={item['vendeur_id']}")]
        ]
        msg_sent = None
        try:
            if item.get("photos"):
                msg_sent = await ctx.bot.send_photo(PUBLIC_CHANNEL_ID, item["photos"][0], caption=txt_pub,
                                                    reply_markup=InlineKeyboardMarkup(kb_pub), parse_mode="HTML")
            else:
                msg_sent = await ctx.bot.send_message(PUBLIC_CHANNEL_ID, txt_pub, reply_markup=InlineKeyboardMarkup(kb_pub), parse_mode="HTML")
        except Exception as e:
            log.error(f"Échec publication canal : {e}")

        update_fields = {"statut": "approuve"}
        if msg_sent:
            update_fields["canal_chat_id"] = msg_sent.chat_id
            update_fields["canal_message_id"] = msg_sent.message_id
        db.annonces.update_one({"_id": oid}, {"$set": update_fields})
        log_audit("ANNONCE_APPROUVEE", str(oid), query.from_user.id)

        parrain = v.get("parrain")
        if parrain and parrain != item["vendeur_id"]:
            filleuls_qualifies = db.users.find_one_and_update(
                {"_id": parrain},
                {"$inc": {"filleuls_qualifies": 1}},
                return_document=True
            )
            if filleuls_qualifies and filleuls_qualifies.get("filleuls_qualifies", 0) % 5 == 0:
                ticket = {
                    "id": str(ObjectId()),
                    "expiration": time.time() + 30*86400,
                    "utilise": False
                }
                db.users.update_one({"_id": parrain}, {"$push": {"tickets": ticket}})
                try:
                    await ctx.bot.send_message(parrain,
                        f"🎟️ <b>Ticket Sans Commission !</b>\nTu as parrainé 5 vendeurs actifs. "
                        f"Utilisable pendant 30 jours sur une transaction Escrow.",
                        parse_mode="HTML")
                except Exception as e:
                    log.warning(f"Notification ticket parrain {parrain}: {e}")
        try:
            await ctx.bot.send_message(item["vendeur_id"], "🟢 Ton annonce a été validée et publiée !")
        except Exception as e:
            log.warning(f"Notification vendeur {item['vendeur_id']}: {e}")
        await safe_edit(query, "🟢 Annonce validée et publiée.")
    else:
        db.annonces.update_one({"_id": oid}, {"$set": {"statut": "rejete"}})
        log_audit("ANNONCE_REJETEE", str(oid), query.from_user.id)
        item = db.annonces.find_one({"_id": oid})
        if item:
            try: await ctx.bot.send_message(item["vendeur_id"], "❌ Ton annonce a été refusée.")
            except Exception as e: log.warning(f"Notification refus vendeur: {e}")
        await safe_edit(query, "❌ Annonce rejetée.")

# ──────────────── MODIFICATION D'ANNONCE (inchangé) ────────────────

async def handle_modification_annonce(query, ctx, parts):
    if not has_level(query.from_user.id, get_user(query.from_user.id), "gerant"):
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True)
        return
    act, id_a = parts[1], parts[2]
    oid = try_objectid(id_a)
    item = db.annonces.find_one({"_id": oid}) if oid else None
    if not item: return

    if act == "approuver":
        db.annonces.update_one({"_id": oid}, {"$set": {
            "description": item.get("nouvelle_description", item.get("description")),
            "prix": item.get("nouveau_prix", item.get("prix")),
            "modification_en_attente": False
        }})
        updated = db.annonces.find_one({"_id": oid})
        chat_id, msg_id = updated.get("canal_chat_id"), updated.get("canal_message_id")
        if chat_id and msg_id:
            txt_pub = (
                f"📣 <b>COMPTE DISPONIBLE !</b>\n\n🎮 #{safe_html(updated.get('categorie','').replace(' ', '_'))}\n"
                f"📱 <code>{safe_html(updated.get('plateforme'))}</code>\n💰 <b>{safe_html(updated.get('prix'))} {safe_html(updated.get('devise'))}</b>\n"
                f"📝 {safe_html(updated.get('description',''))}"
            )
            try:
                if updated.get("photos"):
                    await ctx.bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=txt_pub, parse_mode="HTML")
                else:
                    await ctx.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=txt_pub, parse_mode="HTML")
            except Exception as e:
                log.warning(f"Échec édition canal : {e}")
        log_audit("MODIF_ANNONCE_APPROUVEE", str(oid), query.from_user.id)
        try: await ctx.bot.send_message(item["vendeur_id"], "✅ Ta modification a été approuvée et publiée !")
        except Exception as e: log.warning(f"Notification modif vendeur: {e}")
        await safe_edit(query, "✅ Modification approuvée et appliquée.")
    else:
        db.annonces.update_one({"_id": oid}, {"$set": {"modification_en_attente": False}, "$unset": {"nouvelle_description": "", "nouveau_prix": ""}})
        log_audit("MODIF_ANNONCE_REFUSEE", str(oid), query.from_user.id)
        try: await ctx.bot.send_message(item["vendeur_id"], "❌ Ta modification a été refusée. L'ancienne version reste active.")
        except Exception as e: log.warning(f"Notification refus modif vendeur: {e}")
        await safe_edit(query, "❌ Modification refusée.")

# ──────────────── VUE ANNONCE ────────────────

async def handle_view_annonce(query, ctx, parts):
    action, id_a = parts[1], parts[2]
    oid = try_objectid(id_a)
    if not oid:
        await query.answer("❌ Invalide.", show_alert=True); return
    item = db.annonces.find_one({"_id": oid})
    if not item:
        await query.answer("❌ Introuvable.", show_alert=True); return

    if action == "suppr":
        if item.get("vendeur_id") != query.from_user.id:
            await query.answer("🚫 Pas ton annonce.", show_alert=True); return
        db.annonces.delete_one({"_id": oid})
        await safe_edit(query, "🗑️ Supprimée.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))
        return

    if action == "modifier":
        if item.get("vendeur_id") != query.from_user.id:
            await query.answer("🚫 Pas ton annonce.", show_alert=True); return
        ctx.user_data["modif_ann_id"] = str(oid)
        save_user(query.from_user.id, {"state": "MODIF_DESC"})
        await safe_edit(query, "✏️ Nouvelle description :")
        return

    bot_username = (await ctx.bot.get_me()).username
    txt = f"🎮 <b>{safe_html(item.get('categorie'))}</b>\n\nPrix : {safe_html(item.get('prix'))} {safe_html(item.get('devise'))}\n{safe_html(item.get('description',''))}"
    kb = [[InlineKeyboardButton("🤝 Acheter", url=f"https://t.me/{bot_username}?start=acheter_{item['_id']}")]]
    try:
        if item.get("photos"):
            await ctx.bot.send_photo(query.from_user.id, item["photos"][0], caption=txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        else:
            await ctx.bot.send_message(query.from_user.id, txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    except Exception as e:
        log.error(f"Échec affichage : {e}")

# ──────────────── CHOIX ACHAT (inchangé) ────────────────

async def proposer_choix_achat(message, ctx, id_ann, uid):
    oid = try_objectid(id_ann)
    if not oid:
        await message.reply_text("❌ Lien invalide."); return
    ann = db.annonces.find_one({"_id": oid})
    if not ann or ann.get("statut") != "approuve":
        await message.reply_text("❌ Annonce indisponible."); return
    if ann.get("vendeur_id") == uid:
        await message.reply_text("⚠️ Tu ne peux pas acheter ta propre annonce."); return

    kb = [[
        InlineKeyboardButton("🤝 Direct (sans frais)", callback_data=f"achatchoice:direct:{oid}"),
        InlineKeyboardButton("🔒 Escrow sécurisé", callback_data=f"achatchoice:escrow:{oid}")
    ]]
    await message.reply_text(
        f"🛒 <b>{safe_html(ann.get('categorie'))}</b>\n💰 {safe_html(ann.get('prix'))} {safe_html(ann.get('devise'))}\n\n"
        f"Comment veux-tu procéder ?\n\n"
        f"🤝 <b>Direct</b> : tu négocies seul avec le vendeur, aucune protection.\n"
        f"🔒 <b>Escrow</b> : le bot bloque les fonds jusqu'à confirmation, plus sûr (petite commission).",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )

async def handle_achat_choice(query, ctx, uid, parts):
    mode, id_ann = parts[1], parts[2]
    oid = try_objectid(id_ann)
    ann = db.annonces.find_one({"_id": oid})
    if not ann: return

    if mode == "direct":
        trx_id = db.transactions_directes.insert_one({
            "ann_id": oid, "vendeur_id": ann["vendeur_id"], "acheteur_id": uid,
            "statut": "en_cours", "date_creation": time.time()
        }).inserted_id
        v = get_user(ann["vendeur_id"])
        kb_switch = [[InlineKeyboardButton("🔄 Passer en Escrow", callback_data=f"achatchoice:passer_escrow:{trx_id}")]]
        try:
            await ctx.bot.send_message(ann["vendeur_id"],
                f"🤝 Un acheteur (@{query.from_user.username or uid}) veut ton annonce <b>{safe_html(ann.get('categorie'))}</b> en mode direct.\nContacte-le directement.",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_switch))
        except Exception as e:
            log.warning(f"Notification direct vendeur: {e}")
        await safe_edit(query, f"🤝 Mise en relation faite avec @{safe_html(v.get('username'))}. Vous pouvez négocier directement.",
                        InlineKeyboardMarkup(kb_switch))

    elif mode == "escrow":
        escrow_id = await ton.initier_escrow(ctx.bot, ann, uid, query.from_user.username or str(uid))
        if escrow_id:
            await query.message.reply_text("🔒 Procédure Escrow lancée, regarde le message reçu.")

    elif mode == "passer_escrow":
        trx_id = id_ann
        trx = db.transactions_directes.find_one({"_id": try_objectid(trx_id)})
        if not trx: return
        ann2 = db.annonces.find_one({"_id": trx["ann_id"]})
        escrow_id = await ton.initier_escrow(ctx.bot, ann2, trx["acheteur_id"], "acheteur")
        if escrow_id:
            await ctx.bot.send_message(trx["acheteur_id"], "🔒 Le vendeur (ou toi) a basculé en mode Escrow sécurisé. Regarde le message reçu.")

# ──────────────── LITIGES, CANDIDATURES, RÔLES, BLACKLIST, ADMIN (inchangé mais inclus) ────────────────

async def handle_litige_action(query, ctx, uid, parts):
    if not has_level(uid, get_user(uid), "gerant"):
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True); return
    act, lit_id = parts[1], parts[2]
    oid = try_objectid(lit_id)
    lit = db.litiges.find_one({"_id": oid}) if oid else None
    if not lit: return
    if lit.get("demandeur_id") == uid:
        await query.answer("🚫 Tu ne peux pas traiter ton propre litige.", show_alert=True); return
    if act in ("faveur_ach", "faveur_ven"):
        faveur = "acheteur" if act == "faveur_ach" else "vendeur"
        db.litiges.update_one({"_id": oid}, {"$set": {"statut": "resolu", "faveur": faveur, "resolu_par": uid, "date_cloture": time.time()}})
        log_audit("LITIGE_RESOLU", f"{oid} en faveur {faveur}", uid)
        await safe_edit(query, f"✅ Litige résolu en faveur {faveur}.")
        try: await ctx.bot.send_message(lit["demandeur_id"], f"⚖️ Ton litige a été résolu (en faveur : {faveur}).")
        except Exception as e: log.warning(f"Notification résolution litige: {e}")
    elif act == "sanction":
        db.litiges.update_one({"_id": oid}, {"$set": {"statut": "resolu", "sanction": True, "resolu_par": uid, "date_cloture": time.time()}})
        log_audit("SANCTION_APPLIQUEE", str(oid), uid)
        await safe_edit(query, "🚫 Sanction enregistrée.")

async def handle_candidature_action(query, ctx, uid, parts):
    if uid != SUPER_ADMIN_ID:
        await query.answer("🚫 Réservé au Fondateur.", show_alert=True); return
    act, cand_id = parts[1], parts[2]
    oid = try_objectid(cand_id)
    cand = db.candidatures.find_one({"_id": oid}) if oid else None
    if not cand: return
    if act == "accepter":
        save_user(cand["user_id"], {"role": "gerant"})
        db.candidatures.update_one({"_id": oid}, {"$set": {"statut": "acceptee"}})
        log_audit("CANDIDATURE_ACCEPTEE", str(cand["user_id"]), uid)
        try: await ctx.bot.send_message(cand["user_id"], "🎉 Félicitations, tu es maintenant Gérant ! Tape /start.")
        except Exception as e: log.warning(f"Notification candidat: {e}")
        await safe_edit(query, "✅ Candidature acceptée, rôle Gérant attribué.")
    else:
        db.candidatures.update_one({"_id": oid}, {"$set": {"statut": "refusee"}})
        try: await ctx.bot.send_message(cand["user_id"], "❌ Ta candidature n'a pas été retenue cette fois.")
        except Exception as e: log.warning(f"Notification refus candidat: {e}")
        await safe_edit(query, "❌ Candidature refusée.")

async def handle_role_action(query, ctx, uid, parts):
    if uid != SUPER_ADMIN_ID:
        await query.answer("🚫 Réservé au Fondateur.", show_alert=True); return
    act = parts[1]
    if act == "promouvoir_admin":
        target = int(parts[2])
        save_user(target, {"role": "admin"})
        log_audit("PROMOTION_ADMIN", str(target), uid)
        await query.message.reply_text(f"✅ {target} promu Admin.")
    elif act == "retrograder":
        target = int(parts[2])
        save_user(target, {"role": "membre"})
        log_audit("RETROGRADATION", str(target), uid)
        await query.message.reply_text(f"✅ {target} rétrogradé Membre.")

async def handle_blacklist_action(query, ctx, uid, parts):
    if not has_level(uid, get_user(uid), "admin"):
        await query.answer("🚫 Réservé à l'équipe (Admin+).", show_alert=True); return
    act = parts[1]
    if act == "retirer":
        target = int(parts[2])
        db.blacklist.delete_one({"user_id": target})
        log_audit("BLACKLIST_RETIRE", str(target), uid)
        await query.message.reply_text(f"✅ {target} retiré de la blacklist.")

# ──────────────── PANNEAU ADMIN (liste membres, etc.) ────────────────

async def afficher_admin_root(query, ctx, uid, u):
    cfg = get_config()
    role = get_role(uid, u)
    st_rec = "OUVERT ✅" if cfg.get("recrutement_ouvert") else "FERMÉ ❌"
    st_urg = "ACTIF 🚨" if cfg.get("mode_urgence") else "INACTIF ✅"
    nb_litiges = db.litiges.count_documents({"statut": "ouvert"})
    nb_attente = db.annonces.count_documents({"statut": "en_attente"})
    nb_modif = db.annonces.count_documents({"modification_en_attente": True})
    nb_cand = db.candidatures.count_documents({"statut": "en_attente"})

    txt = (
        f"🛠️ <b>PANNEAU D'ADMINISTRATION</b>\nTon rôle : {ROLE_LABEL.get(role)}\n\n"
        f"📋 Annonces en attente : {nb_attente}\n"
        f"✏️ Modifications en attente : {nb_modif}\n"
        f"⚖️ Litiges ouverts : {nb_litiges}\n"
        f"🎯 Candidatures en attente : {nb_cand}\n"
    )
    kb = [
        [InlineKeyboardButton("📋 Annonces en attente", callback_data="admact:voir_attente"),
         InlineKeyboardButton("✏️ Modifications", callback_data="admact:voir_modifs")],
        [InlineKeyboardButton("⚖️ Litiges", callback_data="admact:voir_litiges")],
        [InlineKeyboardButton("👥 Liste des membres", callback_data="admact:liste_membres")],
    ]
    if has_level(uid, u, "admin"):
        kb.append([InlineKeyboardButton("🚫 Gérer Blacklist", callback_data="admact:gerer_blacklist")])
        kb.append([InlineKeyboardButton("🎯 Candidatures", callback_data="admact:voir_candidatures")])
    if get_role(uid, u) == "superadmin":
        kb.append([InlineKeyboardButton("🔄 Recrutement", callback_data="admact:toggle_rec"),
                   InlineKeyboardButton("🚨 Urgence", callback_data="admact:toggle_urg")])
        kb.append([InlineKeyboardButton("👥 Gérer Rôles", callback_data="admact:gerer_roles")])
        kb.append([InlineKeyboardButton("⚙️ Config Générale", callback_data="admact:config")])
        kb.append([InlineKeyboardButton("💰 Config TON", callback_data="admact:config_ton")])
        kb.append([InlineKeyboardButton("📊 Stats & Export", callback_data="admact:export_pdf")])
        kb.append([InlineKeyboardButton("📜 Audit Log", callback_data="admact:audit_log")])
        kb.append([InlineKeyboardButton("💸 Rémunération équipe", callback_data="tonact:rapport_remuneration")])
    kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
    await safe_edit(query, txt, InlineKeyboardMarkup(kb))

async def handle_members_page(query, ctx, uid, u, parts):
    if not has_level(uid, u, "gerant"):
        await query.answer("🚫 Accès réservé à l'équipe.", show_alert=True)
        return
    try:
        page = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        page = 0
    per_page = 10
    total = db.users.count_documents({})
    max_page = (total - 1) // per_page if total > 0 else 0
    if page < 0: page = 0
    if page > max_page: page = max_page

    users = list(db.users.find({}).sort("date_inscription", -1).skip(page * per_page).limit(per_page))
    txt = f"👥 <b>LISTE DES MEMBRES</b> (page {page+1}/{max_page+1})\n\n"
    kb = []
    for memb in users:
        mid = memb["_id"]
        uname = memb.get("username", "Inconnu")
        role = memb.get("role", "membre")
        date_inscr = fmt_date(memb.get("date_inscription", 0))
        bl = "🚫" if is_blacklisted(mid) else ""
        txt += f"{bl}<code>{mid}</code> — @{safe_html(uname)} ({ROLE_LABEL.get(role, '?')}) — {date_inscr}\n"
        kb.append([InlineKeyboardButton(f"🔍 Détails {mid}", callback_data=f"memberinfo:{mid}")])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Précédent", callback_data=f"memberspage:{page-1}"))
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton("Suivant ▶️", callback_data=f"memberspage:{page+1}"))
    if nav_buttons:
        kb.append(nav_buttons)
    kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
    await safe_edit(query, txt, InlineKeyboardMarkup(kb))

async def handle_member_info(query, uid, parts):
    if not has_level(uid, get_user(uid), "gerant"):
        await query.answer("🚫 Accès réservé à l'équipe.", show_alert=True)
        return
    try:
        target_id = int(parts[1])
    except (IndexError, ValueError):
        await query.answer("ID invalide.")
        return
    target = db.users.find_one({"_id": target_id})
    if not target:
        await query.answer("Utilisateur introuvable.")
        return
    role = get_role(target_id, target)
    blacklist_status = "🚫 OUI" if is_blacklisted(target_id) else "✅ Non"
    nb_annonces_actives = db.annonces.count_documents({"vendeur_id": target_id, "statut": "approuve"})
    nb_ventes = db.annonces.count_documents({"vendeur_id": target_id, "statut": "vendu"})
    evals = target.get("evaluations", [])
    if evals:
        moyenne = round(sum(e["note"] for e in evals) / len(evals), 1)
        stars = "⭐" * int(moyenne) + f" ({moyenne}/5 - {len(evals)} avis)"
    else:
        stars = "ℹ️ Aucun avis"
    derniere_annonces = list(db.annonces.find(
        {"vendeur_id": target_id, "statut": {"$ne": "brouillon"}}
    ).sort("date_creation", -1).limit(3))
    txt = (
        f"👤 <b>FICHE UTILISATEUR</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🆔 <b>ID :</b> <code>{target_id}</code>\n"
        f"👤 <b>Username :</b> @{safe_html(target.get('username', 'Inconnu'))}\n"
        f"🎭 <b>Rôle :</b> {ROLE_LABEL.get(role, role)}\n"
        f"🌍 <b>Nationalité :</b> {safe_html(target.get('nationalite', 'Non définie'))}\n"
        f"📞 <b>Téléphone :</b> {safe_html(target.get('telephone') or 'Non renseigné')} ({safe_html(target.get('tel_visibilite', 'masque'))})\n"
        f"💼 <b>Wallet TON :</b> <code>{safe_html(target.get('wallet_ton') or 'Non renseigné')}</code>\n"
        f"🚫 <b>Blacklisté :</b> {blacklist_status}\n"
        f"📅 <b>Inscription :</b> {fmt_date(target.get('date_inscription', 0))}\n"
        f"📦 <b>Annonces actives :</b> {nb_annonces_actives}\n"
        f"🏷️ <b>Ventes validées :</b> {nb_ventes}\n"
        f"📈 <b>Réputation :</b> {stars}\n"
        f"🎁 <b>Filleuls qualifiés :</b> {target.get('filleuls_qualifies', 0)}\n"
        f"⚡ <b>Points :</b> {target.get('points', 0)}\n"
    )
    if derniere_annonces:
        txt += "\n📌 <b>Dernières annonces :</b>\n"
        for ann in derniere_annonces:
            statut_lbl = {"en_attente": "🟡", "approuve": "✅", "rejete": "❌", "vendu": "🏷️"}.get(ann.get("statut"), "❓")
            txt += f"{statut_lbl} {safe_html(ann.get('categorie','?'))} — {safe_html(ann.get('prix','?'))} {safe_html(ann.get('devise','?'))}\n"
    kb = [[InlineKeyboardButton("🔙 Retour à la liste", callback_data="memberspage:0")]]
    await query.message.edit_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# ──────────────── AUTRES HANDLERS ADMIN ────────────────

async def handle_admin_action(query, ctx, uid, parts):
    u = get_user(uid)
    if not has_level(uid, u, "gerant"):
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True); return
    act = parts[1]
    cfg = get_config()

    if act == "liste_membres":
        await handle_members_page(query, ctx, uid, u, ["memberspage", "0"])
        return

    if act == "voir_attente":
        items = list(db.annonces.find({"statut": "en_attente"}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucune annonce en attente.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])); return
        kb = [[InlineKeyboardButton(f"✅ {it.get('categorie','?')[:15]}", callback_data=f"modact:approuve:{it['_id']}"),
               InlineKeyboardButton("❌", callback_data=f"modact:rejete:{it['_id']}")] for it in items]
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, f"📋 {len(items)} en attente", InlineKeyboardMarkup(kb))

    elif act == "voir_modifs":
        items = list(db.annonces.find({"modification_en_attente": True}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucune modification en attente.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])); return
        kb = [[InlineKeyboardButton(f"✅ {it.get('categorie','?')[:15]}", callback_data=f"modifact:approuver:{it['_id']}"),
               InlineKeyboardButton("❌", callback_data=f"modifact:refuser:{it['_id']}")] for it in items]
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, f"✏️ {len(items)} modification(s)", InlineKeyboardMarkup(kb))

    elif act == "voir_litiges":
        items = list(db.litiges.find({"statut": "ouvert"}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucun litige ouvert.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])); return
        txt = f"⚖️ {len(items)} litige(s)\n\n"
        kb = []
        for it in items:
            txt += f"🆔 {it['_id']} — <code>{it.get('demandeur_id')}</code>\n"
            kb.append([InlineKeyboardButton("✅→Ach", callback_data=f"litact:faveur_ach:{it['_id']}"),
                       InlineKeyboardButton("✅→Ven", callback_data=f"litact:faveur_ven:{it['_id']}"),
                       InlineKeyboardButton("🚫", callback_data=f"litact:sanction:{it['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "voir_candidatures":
        items = list(db.candidatures.find({"statut": "en_attente"}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucune candidature.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])); return
        txt = f"🎯 {len(items)} candidature(s)\n\n"
        kb = []
        for it in items:
            txt += f"👤 @{safe_html(it.get('username'))} — {safe_html(it.get('motif',''))[:60]}\n\n"
            kb.append([InlineKeyboardButton("✅", callback_data=f"candidact:accepter:{it['_id']}"),
                       InlineKeyboardButton("❌", callback_data=f"candidact:refuser:{it['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "gerer_blacklist":
        if not has_level(uid, u, "admin"):
            await query.answer("🚫 Réservé Admin+.", show_alert=True); return
        bl = list(db.blacklist.find({}).limit(10))
        txt = f"🚫 Blacklist ({len(bl)})\n\n"
        kb = []
        for b in bl:
            txt += f"• <code>{b['user_id']}</code> — {safe_html(b.get('raison',''))}\n"
            kb.append([InlineKeyboardButton(f"➖ Retirer {b['user_id']}", callback_data=f"blact:retirer:{b['user_id']}")])
        kb.append([InlineKeyboardButton("➕ Ajouter (tape l'ID puis la raison)", callback_data="admact:ajouter_bl")])
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "ajouter_bl":
        save_user(uid, {"state": "ADMIN_BL_ID"})
        await safe_edit(query, "🚫 Tape l'ID Telegram à blacklister :")

    elif act == "gerer_roles":
        if uid != SUPER_ADMIN_ID:
            await query.answer("🚫 Superadmin uniquement.", show_alert=True); return
        save_user(uid, {"state": "ADMIN_ROLE_ID"})
        await safe_edit(query, "👥 Tape l'ID Telegram à promouvoir Admin :")

    elif act == "toggle_rec":
        if uid != SUPER_ADMIN_ID: return
        db.config.update_one({"type": "global"}, {"$set": {"recrutement_ouvert": not cfg.get("recrutement_ouvert", False)}})
        log_audit("TOGGLE_RECRUTEMENT", "", uid)
        await afficher_admin_root(query, ctx, uid, u)

    elif act == "toggle_urg":
        if uid != SUPER_ADMIN_ID: return
        db.config.update_one({"type": "global"}, {"$set": {"mode_urgence": not cfg.get("mode_urgence", False)}})
        log_audit("TOGGLE_URGENCE", "", uid)
        await afficher_admin_root(query, ctx, uid, u)

    elif act == "config":
        if uid != SUPER_ADMIN_ID: return
        kb = [
            [InlineKeyboardButton(f"📋 Limite annonces ({cfg.get('limite_annonces_membre')})", callback_data="admact:set_limite")],
            [InlineKeyboardButton(f"⏱️ Délai anti-arnaque ({cfg.get('delai_anti_arnaque')}s)", callback_data="admact:set_delai")],
            [InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]
        ]
        await safe_edit(query, "⚙️ <b>Configuration générale</b>", InlineKeyboardMarkup(kb))

    elif act == "set_limite":
        save_user(uid, {"state": "ADMCFG_LIMITE"})
        await safe_edit(query, "📋 Nouvelle limite d'annonces par membre :")

    elif act == "set_delai":
        save_user(uid, {"state": "ADMCFG_DELAI"})
        await safe_edit(query, "⏱️ Nouveau délai anti-arnaque en secondes :")

    elif act == "config_ton":
        if uid != SUPER_ADMIN_ID: return
        kb = [
            [InlineKeyboardButton(f"💼 Commission ({cfg.get('commission_pct')}%)", callback_data="admact:set_commission")],
            [InlineKeyboardButton(f"🔐 Seuil double validation ({cfg.get('seuil_double_validation_ton')} TON)", callback_data="admact:set_seuil")],
            [InlineKeyboardButton("🏦 Wallet TON admin", callback_data="admact:set_wallet")],
            [InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]
        ]
        await safe_edit(query, "💰 <b>Configuration TON</b>", InlineKeyboardMarkup(kb))

    elif act == "set_commission":
        save_user(uid, {"state": "ADMCFG_COMMISSION"})
        await safe_edit(query, "💼 Nouvelle commission en % (ex: 5) :")

    elif act == "set_seuil":
        save_user(uid, {"state": "ADMCFG_SEUIL"})
        await safe_edit(query, "🔐 Nouveau seuil de double validation en TON :")

    elif act == "set_wallet":
        save_user(uid, {"state": "ADMCFG_WALLET"})
        await safe_edit(query, "🏦 Adresse wallet TON pour recevoir la commission :")

    elif act == "audit_log":
        if uid != SUPER_ADMIN_ID: return
        logs = list(db.audit_logs.find({}).sort("timestamp", -1).limit(15))
        txt = "📜 <b>Audit Log (15 dernières actions)</b>\n\n"
        for l in logs:
            txt += f"🕐 {l.get('date')} — {l.get('action')} par <code>{l.get('acted_by')}</code>\n{safe_html(l.get('details',''))[:60]}\n\n"
        await safe_edit(query, txt or "Aucune action.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]]))

    elif act == "export_pdf":
        buffer = io.BytesIO()
        nb_vendu = db.annonces.count_documents({"statut": "vendu"})
        nb_users = db.users.count_documents({})
        nb_rejete = db.annonces.count_documents({"statut": "rejete"})
        nb_litiges = db.litiges.count_documents({})
        buffer.write(
            f"RAPPORT BOT MARKET — {fmt_date()}\n================================\n"
            f"Membres : {nb_users}\nVentes validées : {nb_vendu}\nAnnonces refusées : {nb_rejete}\nLitiges (total) : {nb_litiges}\n".encode())
        buffer.seek(0)
        try:
            await ctx.bot.send_document(uid, document=InputFile(buffer, filename=f"rapport_{fmt_date()}.txt"), caption="📊 Rapport exporté.")
        except Exception as e:
            log.error(f"Échec export : {e}")

# ══════════════════════════════════════════════════════════════
#  COMMANDE /alerte, /info (inchangé)
# ══════════════════════════════════════════════════════════════

async def cmd_alerte(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("🔔 Format : /alerte [jeu]"); return
    jeu = " ".join(ctx.args)
    db.alertes.update_one({"user_id": uid}, {"$addToSet": {"jeux": jeu}}, upsert=True)
    await update.message.reply_text(f"🔔 Alerte activée pour : <b>{safe_html(jeu)}</b>", parse_mode="HTML")

async def cmd_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    if not has_level(uid, u, "gerant"):
        await update.message.reply_text("🚫 Réservé à l'équipe (Gérant+).")
        return
    if not ctx.args:
        await update.message.reply_text("Format : /info <ID>")
        return
    try:
        target_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ ID invalide.")
        return

    target = db.users.find_one({"_id": target_id})
    if not target:
        await update.message.reply_text(f"❌ Aucun utilisateur trouvé avec l'ID {target_id}.")
        return

    role = get_role(target_id, target)
    blacklist_status = "🚫 OUI" if is_blacklisted(target_id) else "✅ Non"
    nb_annonces_actives = db.annonces.count_documents({"vendeur_id": target_id, "statut": "approuve"})
    nb_ventes = db.annonces.count_documents({"vendeur_id": target_id, "statut": "vendu"})
    evals = target.get("evaluations", [])
    if evals:
        moyenne = round(sum(e["note"] for e in evals) / len(evals), 1)
        stars = "⭐" * int(moyenne) + f" ({moyenne}/5 - {len(evals)} avis)"
    else:
        stars = "ℹ️ Aucun avis"
    derniere_annonces = list(db.annonces.find(
        {"vendeur_id": target_id, "statut": {"$ne": "brouillon"}}
    ).sort("date_creation", -1).limit(3))

    txt = (
        f"👤 <b>FICHE UTILISATEUR</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"🆔 <b>ID :</b> <code>{target_id}</code>\n"
        f"👤 <b>Username :</b> @{safe_html(target.get('username', 'Inconnu'))}\n"
        f"🎭 <b>Rôle :</b> {ROLE_LABEL.get(role, role)}\n"
        f"🌍 <b>Nationalité :</b> {safe_html(target.get('nationalite', 'Non définie'))}\n"
        f"📞 <b>Téléphone :</b> {safe_html(target.get('telephone') or 'Non renseigné')} ({safe_html(target.get('tel_visibilite', 'masque'))})\n"
        f"💼 <b>Wallet TON :</b> <code>{safe_html(target.get('wallet_ton') or 'Non renseigné')}</code>\n"
        f"🚫 <b>Blacklisté :</b> {blacklist_status}\n"
        f"📅 <b>Inscription :</b> {fmt_date(target.get('date_inscription', 0))}\n"
        f"📦 <b>Annonces actives :</b> {nb_annonces_actives}\n"
        f"🏷️ <b>Ventes validées :</b> {nb_ventes}\n"
        f"📈 <b>Réputation :</b> {stars}\n"
        f"🎁 <b>Filleuls qualifiés :</b> {target.get('filleuls_qualifies', 0)}\n"
        f"⚡ <b>Points :</b> {target.get('points', 0)}\n"
    )
    if derniere_annonces:
        txt += "\n📌 <b>Dernières annonces :</b>\n"
        for ann in derniere_annonces:
            statut_lbl = {"en_attente": "🟡", "approuve": "✅", "rejete": "❌", "vendu": "🏷️"}.get(ann.get("statut"), "❓")
            txt += f"{statut_lbl} {safe_html(ann.get('categorie','?'))} — {safe_html(ann.get('prix','?'))} {safe_html(ann.get('devise','?'))}\n"

    await update.message.reply_text(txt, parse_mode="HTML")

# ══════════════════════════════════════════════════════════════
#  ÉTATS ADMIN (blacklist, rôles)
# ══════════════════════════════════════════════════════════════

async def handle_admin_states(update, ctx, uid, state, text):
    if state == "ADMIN_BL_ID":
        try:
            target = int(text)
            ctx.user_data["bl_target"] = target
            save_user(uid, {"state": "ADMIN_BL_RAISON"})
            await update.message.reply_text("📋 Raison du blacklist :")
        except Exception:
            await update.message.reply_text("⚠️ ID invalide.")
        return True
    if state == "ADMIN_BL_RAISON":
        target = ctx.user_data.get("bl_target")
        db.blacklist.insert_one({"user_id": target, "raison": text, "date": fmt_date(), "admin_id": uid})
        log_audit("BLACKLIST_AJOUT", f"{target} — {text}", uid)
        save_user(uid, {"state": "IDLE"})
        await update.message.reply_text(f"🚫 {target} blacklisté.")
        try: await ctx.bot.send_message(target, "🚫 Tu as été blacklisté du Marketplace.")
        except Exception as e: log.warning(f"Notification blacklist: {e}")
        return True
    if state == "ADMIN_ROLE_ID":
        try:
            target = int(text)
            save_user(target, {"role": "admin"})
            log_audit("PROMOTION_ADMIN", str(target), uid)
            save_user(uid, {"state": "IDLE"})
            await update.message.reply_text(f"✅ {target} promu Admin.")
            try: await ctx.bot.send_message(target, "🎉 Tu es maintenant Admin du Marketplace !")
            except Exception as e: log.warning(f"Notification promo: {e}")
        except Exception:
            await update.message.reply_text("⚠️ ID invalide.")
        return True
    return False

# ══════════════════════════════════════════════════════════════
#  GESTIONNAIRE D'ERREURS GLOBAL (anti-fuite)
# ══════════════════════════════════════════════════════════════

async def global_error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Exception non gérée :", exc_info=ctx.error)
    safe_error = str(ctx.error)
    for sensitive in [os.environ.get("TON_PRIVATE_KEY", ""), os.environ.get("MONGO_URI", ""),
                      os.environ.get("TONCENTER_API_KEY", ""), BOT_TOKEN]:
        if sensitive:
            safe_error = safe_error.replace(sensitive, "[REDACTED]")
    try:
        await ctx.bot.send_message(SUPER_ADMIN_ID, f"🐛 <b>Erreur bot</b> :\n<code>{safe_html(safe_error)[:500]}</code>", parse_mode="HTML")
    except Exception as e:
        log.warning(f"Notification erreur superadmin: {e}")

# ══════════════════════════════════════════════════════════════
#  TÂCHES PLANIFIÉES
# ══════════════════════════════════════════════════════════════

async def job_resume_hebdo(ctx: ContextTypes.DEFAULT_TYPE):
    await ton.resume_hebdo_litiges(ctx.bot, TEAM_CHANNEL_ID)

async def job_notif_tickets(ctx: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    seuil = now + 3 * 86400
    users = db.users.find({"tickets": {"$not": {"$size": 0}}})
    for u in users:
        for ticket in u.get("tickets", []):
            if not ticket.get("utilise", False) and ticket.get("expiration", 0) <= seuil and ticket.get("expiration", 0) > now:
                try:
                    await ctx.bot.send_message(u["_id"],
                        f"🎟️ <b>Rappel Ticket Sans Commission</b>\n"
                        f"Ton ticket expire dans moins de 3 jours ! Utilise-le vite lors d'un achat Escrow.",
                        parse_mode="HTML")
                except Exception as e:
                    log.warning(f"Échec rappel ticket pour {u['_id']}: {e}")

# ══════════════════════════════════════════════════════════════
#  POST INIT
# ══════════════════════════════════════════════════════════════

async def post_init(application: Application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"Suppression webhook : {e}")
    ton.demarrer_scanner(application.bot)
    log.info("✅ Bot Market Ultra v4.0 démarré — scanner TON actif.")

# ══════════════════════════════════════════════════════════════
#  ROUTEUR MESSAGES FINAL
# ══════════════════════════════════════════════════════════════

async def central_text_and_media_handler_v2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    state = u.get("state", "IDLE")
    text = update.message.text if update.message else None

    if uid != SUPER_ADMIN_ID and state not in ("ADMIN_BL_ID", "ADMIN_BL_RAISON", "ADMIN_ROLE_ID"):
        if not await verifier_etapes_obligatoires(update, ctx, uid, u):
            return

    if state in ("ADMIN_BL_ID", "ADMIN_BL_RAISON", "ADMIN_ROLE_ID") and text:
        if await handle_admin_states(update, ctx, uid, state, text):
            return

    await central_text_and_media_handler(update, ctx)

# ══════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("alerte", cmd_alerte))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CallbackQueryHandler(central_callback_router))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, central_text_and_media_handler_v2))
    app.add_error_handler(global_error_handler)

    if app.job_queue:
        if TEAM_CHANNEL_ID:
            app.job_queue.run_repeating(job_resume_hebdo, interval=604800, first=60)
        app.job_queue.run_repeating(job_notif_tickets, interval=86400, first=3600)

    log.info("🚀 Lancement du polling Telegram...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
