"""
╔══════════════════════════════════════════════════════════════╗
║    BOT MARKET ULTRA v4.21 — PROFIL PROPRE + WALLET SPOILER    ║
║   Fichier principal — importe escrow_ton.py pour la crypto   ║
╚══════════════════════════════════════════════════════════════╝

v4.21 – Profil plus propre + wallet masqué (spoiler Telegram)
- v4.20 – Certification des vendeurs de confiance + vérification disponibilité (Direct)
- v4.19 – Gestion d'équipe complète : rémunération hybride (points + salaire fixe)
- Interrupteur ON/OFF, dashboard équipe, historique paiements, reset mensuel
- Wallet TON obligatoire pour publier une annonce
- v4.18 – Évaluations vendeurs après transaction, limite photos configurable
- Recherche avec boutons Acheter, gestion des alertes, dashboard stats admin
- Nettoyage automatique des annonces expirées et brouillons abandonnés
- v4.17 – Parrainage, alertes, points équipe corrigés + animations menu
- Taux de secours TON ajoutés dans Config TON (modifiables)
- v4.16 – GIFs, stickers & vocaux autorisés dans le groupe
- Wallets TON gérables via le menu admin (plus besoin de Render env vars)
- v4.15 – Modération groupe : liens/images/vidéos bloqués, texte autorisé
- Affiche les vrais noms (prénom/nom) dans la liste des membres
- Ajout config : max avertissements, durée mute (superadmin)
- Boutons admin : lever sourdine, réinitialiser avertissements
- v4.14 – Message de bienvenue automatique dans le groupe
- Détecte les nouveaux membres et envoie un message de bienvenue
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
from bson.objectid import ObjectId
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ChatMemberHandler
)
from telegram.error import TelegramError

from utils import client, db, MONGO_URI, safe_html, fmt_date, try_objectid, log_audit
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

BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAEOWHMNfBVzYgsvl6LXZ0DZ8i2YsO6Zyuw")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
PUBLIC_CHANNEL_ID = os.environ.get("PUBLIC_CHANNEL_ID", "@comptedejeux")   # Canal de publication
SECURITY_GROUP_ID = os.environ.get("SECURITY_GROUP_ID", "@comptedejeu")   # Groupe pour la sécurité
TEAM_CHANNEL_ID = os.environ.get("TEAM_CHANNEL_ID", "")

# Variable qui stockera l'ID numérique du groupe de sécurité (résolu au démarrage)
SECURITY_GROUP_ID_NUM = None

DEFAULTS_USER = {
    "username": "Inconnu", "first_name": "", "last_name": "",
    "role": "membre", "state": "IDLE",
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
    "evaluations": [],
    "certifie": False,
}

DEFAULTS_CONFIG = {
    "type": "global", "recrutement_ouvert": False, "mode_urgence": False,
    "delai_anti_arnaque": 3600, "limite_annonces_membre": 3,
    "commission_pct": 5, "admin_ton_wallet": "",
    "ton_wallet_address": "", "ton_private_key": "", "toncenter_api_key": "",
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
    "delai_rappel_annonce_jours": 30,
    "delai_inactivite_annonce_jours": 3,
    "moderation_auto_canal": True,
    "groupe_max_avertissements": 3,
    "groupe_duree_mute_heures": 24,
    "limite_photos_annonce": 5,
    "remuneration_active": True,
    "remuneration_ton_par_point": 0.05,
    "points_annonce_validee": 10,
    "points_litige_resolu": 20,
    "points_modification_validee": 5,
    "points_demande_validee": 5,
    "salaires_fixes": {},
    "dernier_reset_remuneration": "",
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

def is_blacklisted(uid):
    return db.blacklist.find_one({"user_id": uid}) is not None

MAX_MESSAGE_LENGTH = 4000

def truncate_text(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> str:
    if len(text) > max_len:
        return text[:max_len-2] + "…"
    return text

async def safe_edit(query, text, reply_markup=None, parse_mode="HTML"):
    try:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "not modified" not in str(e).lower():
            try:
                truncated = truncate_text(text)
                await query.message.reply_text(truncated, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception as e2:
                log.error(f"safe_edit a échoué : {e2}")

# ══════════════════════════════════════════════════════════════
#  MESSAGE DE BIENVENUE
# ══════════════════════════════════════════════════════════════

async def nouveau_membre(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Souhaite la bienvenue aux nouveaux membres du groupe."""
    chat_member = update.chat_member
    # On ne réagit que si le statut est devenu "member" (nouveau membre)
    if chat_member.new_chat_member.status == "member":
        user = chat_member.new_chat_member.user
        username = f"@{user.username}" if user.username else user.first_name
        try:
            await ctx.bot.send_message(
                chat_id=SECURITY_GROUP_ID,
                text=f"👋 Bienvenue {username} ! Merci d'avoir rejoint le groupe. "
                     f"Utilise le bot en message privé pour acheter ou vendre des comptes."
            )
        except Exception as e:
            log.warning(f"Échec envoi message de bienvenue : {e}")

# ══════════════════════════════════════════════════════════════
#  MODÉRATION AUTOMATIQUE DU GROUPE (SECURITY_GROUP_ID)
# ══════════════════════════════════════════════════════════════

async def supprimer_et_sanctionner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = msg.from_user.id

    if uid == ctx.bot.id:
        return

    cfg = get_config()
    if not cfg.get("moderation_auto_canal", True):
        return

    u = get_user(uid)
    if has_level(uid, u, "gerant"):
        return

    # Détecter si le message contient un élément interdit
    # GIFs (animation), stickers et messages vocaux sont autorisés
    raison = None
    if msg.photo or msg.video:
        raison = "photo/vidéo"
    elif msg.entities:
        for ent in msg.entities:
            if ent.type in ("url", "text_link"):
                raison = "lien externe"
                break
    elif msg.caption_entities:
        for ent in msg.caption_entities:
            if ent.type in ("url", "text_link"):
                raison = "lien externe"
                break
    # Détecter les URLs brutes dans le texte
    if not raison and msg.text:
        if re.search(r'https?://\S+|t\.me/\S+', msg.text):
            raison = "lien externe"

    if not raison:
        return  # Message texte normal → autorisé

    # Supprimer le message interdit
    try:
        await msg.delete()
    except Exception as e:
        log.warning(f"Échec suppression message groupe (uid {uid}): {e}")
        return

    max_av = cfg.get("groupe_max_avertissements", 3)
    mute_heures = cfg.get("groupe_duree_mute_heures", 24)

    doc = db.infractions_canal.find_one({"user_id": uid})
    if doc:
        nb = doc.get("compteur", 0) + 1
        db.infractions_canal.update_one({"user_id": uid}, {"$set": {"compteur": nb, "derniere": time.time()}})
    else:
        nb = 1
        db.infractions_canal.insert_one({"user_id": uid, "compteur": nb, "derniere": time.time()})

    if nb < max_av:
        restant = max_av - nb
        try:
            await ctx.bot.send_message(uid,
                f"⚠️ Votre message ({raison}) a été supprimé. Les photos, vidéos et liens ne sont pas autorisés dans le groupe.\n"
                f"✅ Les GIFs, stickers et messages vocaux sont autorisés.\n"
                f"Avertissement {nb}/{max_av}. Après {max_av} infractions, vous serez mis en sourdine {mute_heures}h."
            )
        except Exception as e:
            log.warning(f"Échec envoi avertissement à {uid}: {e}")
    else:
        mute_until = int(time.time() + mute_heures * 3600)
        try:
            await ctx.bot.restrict_chat_member(
                chat_id=SECURITY_GROUP_ID,
                user_id=uid,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=mute_until
            )
            db.infractions_canal.update_one({"user_id": uid}, {"$set": {"compteur": 0}})
            await ctx.bot.send_message(uid,
                f"🔇 Vous avez été mis en sourdine pendant {mute_heures}h pour avoir ignoré les avertissements "
                f"({raison}). Les GIFs, stickers et vocaux restent autorisés. Utilisez le bot pour vos annonces."
            )
            log_audit("MUTE_GROUPE", f"uid={uid} pour {mute_heures}h ({raison})", 0)
        except Exception as e:
            log.error(f"Échec restriction groupe pour {uid}: {e}")

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
        cgu_texte = truncate_text(cgu_texte, 3800)
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

def _extraire_message(update):
    if isinstance(update, Update):
        return update.effective_message
    if hasattr(update, 'message') and update.message:
        return update.message
    return None

async def traiter_achat_en_attente(ctx, update, uid):
    doc = db.achat_attente.find_one({"user_id": uid})
    if not doc:
        return False
    annonce_id = doc["annonce_id"]
    db.achat_attente.delete_one({"user_id": uid})
    try:
        message = _extraire_message(update)
        if not message:
            log.error("Pas de message pour déclencher l'achat en attente")
            return False
        await proposer_choix_achat(message, ctx, annonce_id, uid)
        return True
    except Exception as e:
        log.error(f"Erreur lors du déclenchement de l'achat {annonce_id} pour {uid}: {e}")
        msg_error = _extraire_message(update)
        if msg_error:
            try:
                await msg_error.reply_text(
                    "⚠️ Impossible d'afficher l'annonce demandée (erreur interne). Retour au menu.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]])
                )
            except Exception:
                pass
        return True

# ══════════════════════════════════════════════════════════════
#  MENU PRINCIPAL (avec bouton Demande)
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
        [InlineKeyboardButton("📢 Demander un compte", callback_data="nav:demande_compte")],
        [InlineKeyboardButton("❓ Aide", callback_data="nav:help")],
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
        f"🎮 <b>BIENVENUE SUR BOT MARKET ULTRA v4.21</b>\n"
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
        await _envoyer_etape(query.message, ctx, uid, 1, "Nom du Jeu",
            "🎮 Quel est le nom exact du jeu vidéo ?",
            kb=[[InlineKeyboardButton("❌ Annuler", callback_data="nav:annuler_vente")]])
    else:
        await query.message.reply_text("📝 Tu as déjà un brouillon en cours. Continue ou annule.")

# ══════════════════════════════════════════════════════════════
#  COMMANDE /start (avec traitement immédiat de l'achat si vérifié)
# ══════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or f"User_{uid}"
    first_name = update.effective_user.first_name or ""
    last_name = update.effective_user.last_name or ""
    cfg = get_config()

    if is_blacklisted(uid) and uid != SUPER_ADMIN_ID:
        target = update.callback_query.message if update.callback_query else update.message
        if target:
            await target.reply_text("🚫 Tu es banni du Marketplace.")
        return

    if cfg.get("mode_urgence") and uid != SUPER_ADMIN_ID:
        target = update.callback_query.message if update.callback_query else update.message
        if target:
            await target.reply_text("⚠️ <b>MAINTENANCE CRITIQUE</b>\n\nLe bot est gelé temporairement.", parse_mode="HTML")
        return

    # ═══ CORRECTION v4.17 : Vérifier si l'utilisateur est NOUVEAU avant que get_user ne le crée ═══
    existant = db.users.find_one({"_id": uid})
    est_nouveau = existant is None

    # Traiter le parrainage PENDANT que l'utilisateur est encore "nouveau"
    parrain_id = None
    if est_nouveau and ctx.args:
        arg = ctx.args[0]
        if arg.startswith("ref_"):
            try:
                pid = int(arg.split("_")[1])
                if pid != uid:
                    parrain_id = pid
            except Exception as e:
                log.warning(f"Erreur traitement ref_: {e}")

    # Maintenant on peut créer l'utilisateur (get_user le fera si nouveau)
    u = get_user(uid)
    if u.get("banni_jusqua", 0) > time.time():
        rem = int(u["banni_jusqua"] - time.time())
        await update.effective_message.reply_text(f"🔴 Suspendu encore {rem // 60} minutes.")
        return

    save_user(uid, {"username": uname, "first_name": first_name, "last_name": last_name, "state": "IDLE"})
    u["username"] = uname
    u["first_name"] = first_name
    u["last_name"] = last_name

    # Appliquer le parrainage si l'utilisateur est vraiment nouveau
    if est_nouveau and parrain_id:
        save_user(uid, {"parrain": parrain_id})
        db.users.update_one({"_id": parrain_id}, {"$inc": {"points": 50, "parrainages_comptes": 1}})
        try:
            await ctx.bot.send_message(parrain_id, "🎁 +50 Points ! Un nouvel utilisateur a rejoint via ton lien de parrainage.")
        except Exception as e:
            log.warning(f"Impossible de notifier parrain {parrain_id}: {e}")

    # Traiter les liens d'achat (acheter_XXX)
    if ctx.args:
        arg = ctx.args[0]
        if arg.startswith("acheter_"):
            annonce_id = arg.split("_", 1)[1]
            if uid != SUPER_ADMIN_ID:
                if await est_abonne_canal(ctx, uid) and u.get("cgu_acceptees", False):
                    await proposer_choix_achat(update.effective_message, ctx, annonce_id, uid)
                    return
                else:
                    db.achat_attente.update_one(
                        {"user_id": uid},
                        {"$set": {"annonce_id": annonce_id, "date": time.time()}},
                        upsert=True
                    )
            else:
                await proposer_choix_achat(update.effective_message, ctx, annonce_id, uid)
                return

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
    "/info [id] – (équipe) Fiche détaillée d'un membre"
)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")

# ══════════════════════════════════════════════════════════════
#  TUNNEL DE VENTE (photo obligatoire) — v4.18 FLUIDE
# ══════════════════════════════════════════════════════════════

LIMITES = {
    "categorie": 50,
    "description": 500,
    "prix": 20,
    "devise": 30,
}

# Barres de progression visuelles
BARRES = {1: "⬜⬜⬜⬜⬜⬜⬜", 2: "🟩⬜⬜⬜⬜⬜⬜", 3: "🟩🟩⬜⬜⬜⬜⬜", 4: "🟩🟩🟩⬜⬜⬜⬜",
          5: "🟩🟩🟩🟩⬜⬜⬜", 6: "🟩🟩🟩🟩🟩⬜⬜", 7: "🟩🟩🟩🟩🟩🟩⬜"}

def nettoyer_prix(texte):
    return ''.join(c for c in texte if c.isdigit() or c == '.')[:20]

async def _nettoyer_ancien_message(ctx, uid):
    """Supprime l'ancien message d'étape pour garder le chat propre."""
    ancien_id = ctx.user_data.pop("tunnel_msg_id", None)
    if ancien_id:
        try:
            await ctx.bot.delete_message(chat_id=uid, message_id=ancien_id)
        except Exception:
            pass  # Message déjà supprimé ou introuvable

async def _envoyer_etape(message, ctx, uid, etape, titre, texte, kb=None):
    """Envoie une étape du tunnel avec barre de progression et nettoie la précédente."""
    await _nettoyer_ancien_message(ctx, uid)
    barre = BARRES.get(etape, "🟩🟩🟩🟩🟩🟩🟩")
    msg = await message.reply_text(
        f"{barre}\n<b>Étape {etape}/7 : {titre}</b>\n\n{texte}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb) if kb else None
    )
    ctx.user_data["tunnel_msg_id"] = msg.message_id
    return msg

async def executer_tunnel_vente(update, ctx, uid, text=None, photo_id=None, album_photos=None):
    u = get_user(uid)
    state = u.get("state", "IDLE")
    ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})
    message = update.effective_message

    if not ann:
        db.annonces.insert_one({"vendeur_id": uid, "statut": "brouillon", "photos": [], "booste": False, "date_creation": time.time()})
        save_user(uid, {"state": "VENTE_JEU"})
        await _envoyer_etape(message, ctx, uid, 1, "Nom du Jeu",
            "🎮 Quel est le nom exact du jeu vidéo ?",
            kb=[[InlineKeyboardButton("❌ Annuler", callback_data="nav:annuler_vente")]])
        return

    if state == "VENTE_JEU" and text:
        if len(text) > LIMITES["categorie"]:
            await message.reply_text(f"⚠️ Maximum {LIMITES['categorie']} caractères.")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"categorie": text}})
        save_user(uid, {"state": "VENTE_PLATEFORME"})
        kb = [[InlineKeyboardButton(p, callback_data=f"plat:{p}") for p in ["Android", "iOS", "PC", "Console"]]]
        await _envoyer_etape(message, ctx, uid, 2, "Plateforme",
            f"✅ Jeu : <b>{safe_html(text)}</b>\n\n📱 Sur quelle plateforme est le compte ?", kb=kb)

    elif state == "VENTE_DESC" and text:
        if len(text) > LIMITES["description"]:
            await message.reply_text(f"⚠️ Maximum {LIMITES['description']} caractères.")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"description": text}})
        save_user(uid, {"state": "VENTE_PHOTOS"})
        cfg = get_config()
        limite = cfg.get("limite_photos_annonce", 5)
        await _envoyer_etape(message, ctx, uid, 4, "Photos",
            f"✅ Description enregistrée.\n\n📸 Envoyez vos photos (max {limite}).\n⚠️ Au moins 1 photo obligatoire.",
            kb=[[InlineKeyboardButton("🏁 Terminer", callback_data="plat:fin_photos")]])

    elif state == "VENTE_PHOTOS":
        cfg = get_config()
        limite = cfg.get("limite_photos_annonce", 5)
        nb_actuelles = len(ann.get("photos", []))
        if photo_id:
            if nb_actuelles >= limite:
                await message.reply_text(f"⚠️ Limite de {limite} photos atteinte. Cliquez sur 🏁 Terminer.")
                return
            db.annonces.update_one({"_id": ann["_id"]}, {"$push": {"photos": photo_id}})
            await message.reply_text(f"📸 Photo ajoutée ({nb_actuelles+1}/{limite}). Continuez ou cliquez Terminer.")
        elif album_photos:
            restant = limite - nb_actuelles
            ajouts = album_photos[:restant]
            if ajouts:
                db.annonces.update_one({"_id": ann["_id"]}, {"$push": {"photos": {"$each": ajouts}}})
            if restant < len(album_photos):
                await message.reply_text(f"⚠️ Limite de {limite} photos. Seules {len(ajouts)} ont été ajoutées.")
            else:
                await message.reply_text(f"📸 {len(ajouts)} photo(s) ajoutée(s). Continuez ou cliquez Terminer.")

    elif state == "VENTE_PRIX" and text:
        prix_nettoye = nettoyer_prix(text)
        if not prix_nettoye:
            await message.reply_text("⚠️ Prix invalide (chiffres uniquement).")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"prix": prix_nettoye}})
        save_user(uid, {"state": "VENTE_DEVISE"})
        await _envoyer_etape(message, ctx, uid, 6, "Devise",
            f"✅ Prix : <b>{prix_nettoye}</b>\n\n💱 Dans quelle devise ? (ex: FCFA, EUR, USD)", kb=None)

    elif state == "VENTE_DEVISE" and text:
        if len(text) > LIMITES["devise"]:
            await message.reply_text(f"⚠️ Maximum {LIMITES['devise']} caractères.")
            return
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"devise": text, "statut": "en_attente", "date_depot": time.time()}})
        save_user(uid, {"state": "IDLE"})
        await _nettoyer_ancien_message(ctx, uid)
        await message.reply_text(
            f"✅ <b>Annonce complète !</b>\n\n"
            f"🎮 {safe_html(ann.get('categorie','?'))}\n"
            f"📱 {safe_html(ann.get('plateforme','?'))}\n"
            f"💰 {safe_html(ann.get('prix','?'))} {safe_html(text)}\n\n"
            f"⏳ Envoi à l'équipe pour validation...",
            parse_mode="HTML")
        await soumettre_a_moderation(message, ctx, ann["_id"])
    else:
        save_user(uid, {"state": "IDLE"})
        await message.reply_text("⚠️ Étape incohérente. Relance /start.")

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

# ═══ NOUVEAU v4.17 : Notifier les utilisateurs ayant des alertes sur un jeu ═══
async def notifier_alertes_jeu(ctx, categorie: str, annonce_id):
    """Envoie une notification aux utilisateurs qui ont une alerte correspondant à cette annonce."""
    jeu_lower = categorie.lower().strip()
    alertes = list(db.alertes.find({}))
    if not alertes:
        return
    bot_username = (await ctx.bot.get_me()).username
    notified = set()
    for alerte in alertes:
        uid = alerte["user_id"]
        if uid in notified:
            continue
        jeux = alerte.get("jeux", [])
        for j in jeux:
            j_lower = j.lower().strip()
            # "Tous" = abonné à tout, ou correspondance partielle
            if j_lower == "tous" or j_lower in jeu_lower or jeu_lower in j_lower:
                try:
                    await ctx.bot.send_message(uid,
                        f"🔔 <b>Nouvelle annonce correspondant à ton alerte !</b>\n\n"
                        f"🎮 <b>{safe_html(categorie)}</b>\n\n"
                        f"Une nouvelle annonce vient d'être publiée.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🛒 Voir l'annonce", url=f"https://t.me/{bot_username}?start=acheter_{annonce_id}")
                        ]]))
                    notified.add(uid)
                except Exception as e:
                    log.warning(f"Échec notification alerte à {uid}: {e}")
                break  # Ne pas notifier plusieurs fois pour le même jeu

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

    if state.startswith("DEMANDE_"):
        await executer_demande_tunnel(update, ctx, uid, text=text)
        return

    if state == "RECHERCHE_INPUT" and text:
        save_user(uid, {"state": "IDLE"})
        escaped_text = re.escape(text)
        res = list(db.annonces.find({"statut": "approuve",
            "$or": [{"categorie": {"$regex": escaped_text, "$options": "i"}},
                    {"description": {"$regex": escaped_text, "$options": "i"}}]}))
        kb = []
        if not res:
            kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
            await update.message.reply_text("🔍 Aucun résultat.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            txt = f"🔍 <b>RÉSULTATS ({len(res)}) :</b>\n\n"
            for idx, item in enumerate(res[:10]):
                categ = safe_html(item.get('categorie', '?'))
                prix = safe_html(item.get('prix', '?'))
                devise = safe_html(item.get('devise', '?'))
                plateforme = safe_html(item.get('plateforme', '?'))
                txt += f"{idx+1}. 🎮 <b>{categ}</b> — 💰 {prix} {devise} — 📱 {plateforme}\n\n"
                kb.append([InlineKeyboardButton(f"🛒 {categ[:25]} ({prix} {devise})", callback_data=f"viewann:inspecte:{item['_id']}")])
            kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
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
        # Trouver le libellé du champ pour un affichage propre
        label = champ
        emoji = "✏️"
        for key, (em, lib, db_field, _ex) in LABELS_CHAMPS.items():
            if db_field == champ:
                label = lib
                emoji = em
                break
        ancien = u.get(champ, "") or "Non défini"
        save_user(uid, {champ: text, "state": "IDLE"})
        await update.message.reply_text(
            f"{emoji} <b>Profil mis à jour !</b>\n\n"
            f"{safe_html(label)} :\n"
            f"<s>{safe_html(ancien)}</s> → <b>{safe_html(text)}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 Voir mon profil", callback_data="nav:mon_profil")]]))
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
    "ADMCFG_GROUPE_AV": ("groupe_max_avertissements", int),
    "ADMCFG_GROUPE_MUTE": ("groupe_duree_mute_heures", int),
    "ADMCFG_LIMITE_PHOTOS": ("limite_photos_annonce", int),
    "ADMCFG_TON_WALLET": ("ton_wallet_address", str),
    "ADMCFG_TON_PRIVATE_KEY": ("ton_private_key", str),
    "ADMCFG_TONCENTER_KEY": ("toncenter_api_key", str),
    "ADMCFG_TAUX_TON_USD": ("taux_secours_ton_usd", float),
    "ADMCFG_TAUX_USD_XOF": ("taux_secours_usd_to_xof", float),
    "ADMCFG_TON_PAR_POINT": ("remuneration_ton_par_point", float),
    "ADMCFG_PTS_ANNONCE": ("points_annonce_validee", int),
    "ADMCFG_PTS_LITIGE": ("points_litige_resolu", int),
    "ADMCFG_PTS_MODIF": ("points_modification_validee", int),
    "ADMCFG_PTS_DEMANDE": ("points_demande_validee", int),
}

async def traiter_config_admin(update, ctx, state, text):
    # ═══ v4.19 : Gestion spéciale du salaire fixe (dict imbriqué) ═══
    if state == "ADMCFG_SALAIRE":
        try:
            montant = float(text.replace(",", "."))
        except Exception:
            await update.message.reply_text("⚠️ Montant invalide.")
            return
        target = ctx.user_data.get("salaire_target")
        if not target:
            await update.message.reply_text("⚠️ Erreur : membre introuvable.")
            save_user(update.effective_user.id, {"state": "IDLE"})
            return
        cfg = get_config()
        salaires = dict(cfg.get("salaires_fixes", {}))
        if montant <= 0:
            salaires.pop(str(target), None)
        else:
            salaires[str(target)] = montant
        db.config.update_one({"type": "global"}, {"$set": {"salaires_fixes": salaires}})
        log_audit("SALAIRE_FIXE", f"{target} = {montant} TON", update.effective_user.id)
        save_user(update.effective_user.id, {"state": "IDLE"})
        ctx.user_data.pop("salaire_target", None)
        await update.message.reply_text(f"✅ Salaire fixe mis à jour : {montant} TON/mois pour {target}.")
        return

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
        elif prefix == "rappelannonce":
            await handle_rappel_annonce(query, uid, parts)
        elif prefix == "demandeplat":
            await handle_demande_plat(query, ctx, uid, parts)
        elif prefix == "modactdemande":
            await handle_moderation_demande(query, ctx, parts)
        elif prefix == "evaluer":
            await handle_evaluation(query, ctx, uid, parts)
        elif prefix == "dispo":
            await handle_dispo_callback(query, ctx, uid, parts)
    except Exception as e:
        log.error(f"Erreur callback '{data}' : {e}\n{traceback.format_exc()}")
        try:
            await query.message.reply_text("⚠️ Erreur survenue. Tape /start pour revenir au menu.")
        except Exception as e2:
            log.warning(f"Impossible de notifier l'erreur callback: {e2}")

# ══════════════════════════════════════════════════════════════
#  NAVIGATION
# ══════════════════════════════════════════════════════════════

async def handle_nav(query, ctx, uid, u, parts):
    cible = parts[1]
    cfg = get_config()

    # ═══ v4.17 : Animations de navigation (feedback visuel) ═══
    NAV_EMOJIS = {
        "recherche": "🔍", "vendre": "🎮", "marche_global": "🛍️", "mon_profil": "👤",
        "mes_annonces": "📦", "cgu": "📜", "leaderboard": "📊", "parrainage": "🎁",
        "mes_alertes": "🔔", "mes_litiges": "⚖️", "blacklist_pub": "🚫",
        "demande_compte": "📢", "help": "❓", "devenir_gerant": "🎯", "admin_root": "⚡",
        "retour": "◀️",
    }
    if cible in NAV_EMOJIS:
        await query.answer(f"{NAV_EMOJIS[cible]} Chargement...")
    elif cible == "verifier_abonnement":
        await query.answer("🔒 Vérification...")
    elif cible == "accepter_cgu":
        await query.answer("📜 CGU...")

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
        await safe_edit(query, HELP_TEXT, reply_markup=kb, parse_mode="HTML")
        return

    if cible == "cgu":
        cgu_texte = cfg.get('cgu_text','')
        if len(cgu_texte) > 4000:
            cgu_texte = cgu_texte[:4000] + "...\n\n(texte complet dans le message original)"
        kb_rows = []
        if not u.get("cgu_acceptees", False):
            kb_rows.append([InlineKeyboardButton("✅ J'accepte les CGU", callback_data="nav:accepter_cgu")])
        kb_rows.append([InlineKeyboardButton("🔙 Retour", callback_data="nav:retour")])
        await safe_edit(query, f"📜 <b>CONDITIONS GÉNÉRALES D'UTILISATION</b>\n\n{safe_html(cgu_texte)}",
                        reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="HTML")
        return

    if cible == "annuler_ton_wallet":
        ctx.user_data.pop("ton_state", None)
        save_user(uid, {"state": "IDLE"})
        await query.message.edit_text("❌ Saisie du wallet annulée.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))
        return

    if cible == "demande_compte":
        save_user(uid, {"state": "DEMANDE_JEU"})
        await query.message.reply_text(
            "🎮 <b>Quel jeu recherchez-vous ?</b>\n\nEntrez le nom du jeu :",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]])
        )
        return

    if cible == "annuler_vente":
        db.annonces.delete_one({"vendeur_id": uid, "statut": "brouillon"})
        save_user(uid, {"state": "IDLE"})
        await _nettoyer_ancien_message(ctx, uid)
        await safe_edit(query, "❌ Annonce annulée. Retour au menu.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

    elif cible == "recherche":
        save_user(uid, {"state": "RECHERCHE_INPUT"})
        await safe_edit(query, "🔍 Mot-clé recherché :", InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif cible == "vendre":
        # ═══ v4.19 : Wallet TON obligatoire pour vendre ═══
        if not u.get("wallet_ton") or not ton.WALLET_TON_PATTERN.match(u.get("wallet_ton", "")):
            kb_wallet = [[InlineKeyboardButton("💼 Configurer mon Wallet TON", callback_data="setprof:WALLET_TON")],
                         [InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]
            await safe_edit(query,
                "⚠️ <b>Wallet TON requis</b>\n\n"
                "Pour vendre un compte et recevoir tes paiements via Escrow, tu dois d'abord renseigner un wallet TON valide.\n\n"
                "C'est l'adresse où tu recevras l'argent de tes ventes.",
                InlineKeyboardMarkup(kb_wallet))
            return
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
        certif_badge = "🔷 <b>Vendeur certifié</b>\n" if u.get("certifie", False) else ""
        txt = (
            f"👤 <b>VOTRE PROFIL</b>\n\n🆔 <code>{uid}</code>\n"
            f"🎭 Rôle : <code>{ROLE_LABEL.get(get_role(uid,u))}</code>\n"
            f"{certif_badge}"
            f"🌍 {safe_html(u.get('nationalite'))}\n"
            f"📞 {safe_html(u.get('telephone') or 'Non configuré')} ({safe_html(u.get('tel_visibilite'))})\n"
            f"⏰ {safe_html(u.get('plage_horaire'))}\n"
            f"🟢 <b>{safe_html(u.get('status_dispo','en ligne')).upper()}</b>\n"
            f"💼 Wallet TON : <tg-spoiler><code>{safe_html(wallet)}</code></tg-spoiler>\n"
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
        # ═══ v4.18 : Menu de gestion des alertes ═══
        alerte_doc = db.alertes.find_one({"user_id": uid})
        jeux = alerte_doc.get("jeux", []) if alerte_doc else []
        if not jeux:
            txt = "🔔 <b>MES ALERTES</b>\n\nAucune alerte configurée.\n\nUtilise /alerte [jeu] pour être notifié des nouvelles annonces."
        else:
            txt = f"🔔 <b>MES ALERTES</b> ({len(jeux)})\n\n"
            for j in jeux:
                txt += f"• {safe_html(j)}\n"
            txt += "\nClique sur une alerte pour la supprimer."
        kb = []
        for j in jeux[:10]:
            kb.append([InlineKeyboardButton(f"🗑️ Supprimer « {safe_html(j)[:25]} »", callback_data=f"nav:suppr_alerte:{j}")])
        kb.append([InlineKeyboardButton("➕ Ajouter une alerte", callback_data="nav:ajouter_alerte")])
        kb.append([InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif cible == "suppr_alerte":
        jeu_a_supprimer = ":".join(parts[2:]) if len(parts) > 2 else parts[2]
        db.alertes.update_one({"user_id": uid}, {"$pull": {"jeux": jeu_a_supprimer}})
        await query.answer(f"🗑️ Alerte « {jeu_a_supprimer[:20]} » supprimée !")
        # Re-afficher le menu des alertes
        await handle_nav(query, ctx, uid, u, ["nav", "mes_alertes"])

    elif cible == "ajouter_alerte":
        save_user(uid, {"state": "RECHERCHE_INPUT"})
        await safe_edit(query, "🔔 Entre le nom du jeu pour lequel tu veux être alerté :", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

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

# ──────────────── SETPROF (wallet TON corrigé) ────────────────

LABELS_CHAMPS = {
    "NATIONALITE": ("🌍", "Pays", "nationalite", "ex: Sénégal, Côte d'Ivoire, France..."),
    "TELEPHONE": ("📞", "Téléphone", "telephone", "ex: +221 77 123 45 67"),
    "PLAGE_HORAIRE": ("⏰", "Horaires", "plage_horaire", "ex: 08:00 - 22:00"),
}

async def handle_setprof(query, ctx, uid, parts):
    champ = parts[1]
    if champ == "WALLET_TON":
        ctx.user_data["ton_state"] = "saisir_wallet_ton"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:annuler_ton_wallet")]])
        await query.message.reply_text(
            "💼 <b>Wallet TON</b>\n\n"
            "Envoie ton adresse wallet TON.\n"
            "Elle commence par <b>EQ</b> ou <b>UQ</b> et fait 48 caractères.\n\n"
            "<i>💡 C'est l'adresse où tu recevras l'argent de tes ventes.</i>",
            parse_mode="HTML", reply_markup=kb)
        return
    if champ not in LABELS_CHAMPS:
        await query.answer("❌ Champ inconnu.", show_alert=True)
        return
    emoji, label, champ_db, exemple = LABELS_CHAMPS[champ]
    u = get_user(uid)
    ancien = u.get(champ_db, "") or "Non défini"
    save_user(uid, {"state": f"SETPROF_{champ}"})
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]])
    await safe_edit(query,
        f"{emoji} <b>Modification : {label}</b>\n\n"
        f"Valeur actuelle : <b>{safe_html(ancien)}</b>\n\n"
        f"Envoie la nouvelle valeur ({exemple}) :",
        kb)

# ──────────────── GESTION PHOTOS (fin_photos vérifie photo obligatoire) ────────────────

async def handle_plat(query, ctx, uid, parts):
    action = parts[1]
    if action == "fin_photos":
        ann = db.annonces.find_one({"vendeur_id": uid, "statut": "brouillon"})
        if not ann or len(ann.get("photos", [])) == 0:
            await query.answer("⚠️ Vous devez ajouter au moins une photo.", show_alert=True)
            return
        save_user(uid, {"state": "VENTE_PRIX"})
        await _nettoyer_ancien_message(ctx, uid)
        await _envoyer_etape(query.message, ctx, uid, 5, "Prix",
            f"📸 {len(ann.get('photos',[]))} photo(s) enregistrée(s).\n\n💰 Quel est le prix du compte ?\n(ex: 15000, 25, 100)",
            kb=None)
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        db.annonces.update_one({"vendeur_id": uid, "statut": "brouillon"}, {"$set": {"plateforme": action}})
        save_user(uid, {"state": "VENTE_DESC"})
        await _nettoyer_ancien_message(ctx, uid)
        await _envoyer_etape(query.message, ctx, uid, 3, "Description",
            f"✅ Plateforme : <b>{safe_html(action)}</b>\n\n📝 Décrivez le compte à vendre :\n(niveau, skins, rang, etc.)",
            kb=None)
        try:
            await query.message.delete()
        except Exception:
            pass

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
        badge = " 🔷 <b>Vendeur certifié</b>" if v.get("certifie", False) else ""
        txt_pub = (
            f"📣 <b>COMPTE DISPONIBLE !</b>\n\n🎮 #{safe_html(item.get('categorie','').replace(' ', '_'))}\n"
            f"📱 <code>{safe_html(item.get('plateforme'))}</code>\n💰 <b>{safe_html(item.get('prix'))} {safe_html(item.get('devise'))}</b>\n"
            f"📝 {safe_html(item.get('description',''))}\n\n👤 Vendeur : @{safe_html(v.get('username'))}{badge}"
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

        # ═══ CORRECTION v4.17 : Un filleul ne compte qu'UNE SEULE fois (1ère annonce approuvée) ═══
        parrain = v.get("parrain")
        if parrain and parrain != item["vendeur_id"]:
            # Vérifier si c'est la PREMIÈRE annonce approuvée de ce vendeur
            nb_avant = db.annonces.count_documents({
                "vendeur_id": item["vendeur_id"],
                "statut": "approuve",
                "_id": {"$ne": oid}
            })
            if nb_avant == 0:
                # Première annonce approuvée = ce filleul compte VRAIMENT
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
        # ═══ v4.17 : Notifier les utilisateurs ayant des alertes sur ce jeu ═══
        await notifier_alertes_jeu(ctx, item.get("categorie", ""), str(oid))
        # ═══ v4.17 : Attribuer des points au modérateur ═══
        ton.ajouter_points_gerant(query.from_user.id, 0, "annonce_validee")
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
        ton.ajouter_points_gerant(query.from_user.id, 0, "modification_validee")
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

# ──────────────── CHOIX ACHAT (protection renforcée + gestion erreur escrow) ────────────────

async def proposer_choix_achat(message, ctx, id_ann, uid):
    try:
        oid = try_objectid(id_ann)
        if not oid:
            await message.reply_text("❌ Lien invalide.")
            return
        ann = db.annonces.find_one({"_id": oid})
        if not ann:
            await message.reply_text("❌ Annonce introuvable.")
            return
        if ann.get("statut") != "approuve":
            await message.reply_text("❌ Cette annonce n'est plus disponible.")
            return
        if ann.get("vendeur_id") == uid:
            await message.reply_text("⚠️ Tu ne peux pas acheter ta propre annonce.")
            return

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
    except Exception as e:
        log.error(f"Erreur dans proposer_choix_achat: {e}\n{traceback.format_exc()}")
        await message.reply_text("⚠️ Une erreur est survenue lors de l'affichage de l'annonce.")

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
        try:
            escrow_id = await ton.initier_escrow(ctx.bot, ann, uid, query.from_user.username or str(uid))
            if escrow_id:
                await query.message.reply_text("🔒 Procédure Escrow lancée, regarde le message reçu.")
            else:
                await query.message.reply_text("⚠️ Impossible de lancer l'Escrow (vérifie les montants ou réessaie plus tard).")
        except Exception as e:
            log.error(f"Erreur initier_escrow pour annonce {id_ann}: {e}\n{traceback.format_exc()}")
            await query.message.reply_text(
                f"⚠️ <b>Erreur Escrow</b>\n\n"
                f"<code>{safe_html(str(e)[:300])}</code>\n\n"
                f"Contacte le support avec ce message.",
                parse_mode="HTML"
            )

    elif mode == "passer_escrow":
        trx_id = parts[2]
        trx = db.transactions_directes.find_one({"_id": try_objectid(trx_id)})
        if not trx:
            await query.answer("❌ Transaction introuvable.", show_alert=True)
            return
        ann2 = db.annonces.find_one({"_id": trx["ann_id"]})
        if not ann2:
            await query.answer("❌ Annonce introuvable.", show_alert=True)
            return
        acheteur = db.users.find_one({"_id": trx["acheteur_id"]})
        acheteur_username = acheteur.get("username", str(trx["acheteur_id"])) if acheteur else str(trx["acheteur_id"])
        escrow_id = await ton.initier_escrow(ctx.bot, ann2, trx["acheteur_id"], acheteur_username)
        if escrow_id:
            await ctx.bot.send_message(trx["acheteur_id"],
                "🔒 Le vendeur a basculé la transaction en mode Escrow sécurisé. Regarde le message reçu pour payer.")
            await query.message.edit_text(
                "✅ Vous avez basculé la transaction en mode Escrow. L'acheteur va recevoir les instructions de paiement.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="nav:retour")]]))

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
        ton.ajouter_points_gerant(uid, 0, "litige_resolu")
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
    elif act == "retrograder_membre":
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
        f"🎯 Candidatures en attente : {nb_cand}\n\n"
        f"📊 <i>Dashboard disponible pour les admins</i>"
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
        kb.append([InlineKeyboardButton("📊 Dashboard Stats", callback_data="admact:dashboard")])
    if get_role(uid, u) == "superadmin":
        kb.append([InlineKeyboardButton("🔄 Recrutement", callback_data="admact:toggle_rec"),
                   InlineKeyboardButton("🚨 Urgence", callback_data="admact:toggle_urg")])
        kb.append([InlineKeyboardButton("👥 Gérer Rôles", callback_data="admact:gerer_roles")])
        kb.append([InlineKeyboardButton("⚙️ Config Générale", callback_data="admact:config")])
        kb.append([InlineKeyboardButton("💰 Config TON", callback_data="admact:config_ton")])
        kb.append([InlineKeyboardButton("💼 Gestion Wallets", callback_data="admact:gestion_wallets")])
        kb.append([InlineKeyboardButton("📊 Stats & Export", callback_data="admact:export_pdf")])
        kb.append([InlineKeyboardButton("📜 Audit Log", callback_data="admact:audit_log")])
        kb.append([InlineKeyboardButton("💸 Rémunération équipe", callback_data="tonact:rapport_remuneration")])
        kb.append([InlineKeyboardButton("👥 Équipe & Rémunération", callback_data="admact:equipe")])
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
        first = memb.get("first_name", "")
        last = memb.get("last_name", "")
        nom_reel = f"{first} {last}".strip() if (first or last) else uname
        role = memb.get("role", "membre")
        date_inscr = fmt_date(memb.get("date_inscription", 0))
        bl = "🚫" if is_blacklisted(mid) else ""
        certif = "🔷" if memb.get("certifie", False) else ""
        infractions = db.infractions_canal.find_one({"user_id": mid})
        infra_str = f" ⚠️{infractions['compteur']}" if infractions and infractions.get("compteur", 0) > 0 else ""
        txt += f"{bl}{certif}<b>{safe_html(nom_reel)}</b>{infra_str} — @{safe_html(uname)} ({ROLE_LABEL.get(role, '?')}) — {date_inscr}\n"
        kb.append([InlineKeyboardButton(f"🔍 Détails {safe_html(nom_reel)[:20]}", callback_data=f"memberinfo:{mid}")])
        if get_role(uid) == "superadmin" and role != "membre":
            kb.append([InlineKeyboardButton(f"⏬ Rétrograder {mid}", callback_data=f"admact:retrograder_membre:{mid}")])
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
    first = target.get("first_name", "")
    last = target.get("last_name", "")
    nom_reel = f"{first} {last}".strip() if (first or last) else target.get("username", "Inconnu")
    blacklist_status = "🚫 OUI" if is_blacklisted(target_id) else "✅ Non"
    infractions = db.infractions_canal.find_one({"user_id": target_id})
    nb_infractions = infractions["compteur"] if infractions else 0
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
        f"👤 <b>Nom :</b> {safe_html(nom_reel)}\n"
        f"📛 <b>Username :</b> @{safe_html(target.get('username', 'Inconnu'))}\n"
        f"🎭 <b>Rôle :</b> {ROLE_LABEL.get(role, role)}\n"
        f"🔷 <b>Certification :</b> {'Vendeur certifié' if target.get('certifie', False) else 'Non certifié'}\n"
        f"🌍 <b>Nationalité :</b> {safe_html(target.get('nationalite', 'Non définie'))}\n"
        f"📞 <b>Téléphone :</b> {safe_html(target.get('telephone') or 'Non renseigné')} ({safe_html(target.get('tel_visibilite', 'masque'))})\n"
        f"💼 <b>Wallet TON :</b> <tg-spoiler><code>{safe_html(target.get('wallet_ton') or 'Non renseigné')}</code></tg-spoiler>\n"
        f"🚫 <b>Blacklisté :</b> {blacklist_status}\n"
        f"⚠️ <b>Avertissements groupe :</b> {nb_infractions}\n"
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
    kb = []
    # Boutons admin : lever sanction, réinitialiser avertissements
    if has_level(uid, get_user(uid), "admin"):
        if nb_infractions > 0:
            kb.append([InlineKeyboardButton("🔄 Réinitialiser les avertissements", callback_data=f"admact:reset_infractions:{target_id}")])
        kb.append([InlineKeyboardButton("🔓 Lever la sourdine", callback_data=f"admact:lever_mute:{target_id}")])
    # ═══ v4.20 : Certification des vendeurs (superadmin uniquement) ═══
    if get_role(uid) == "superadmin":
        if target.get("certifie", False):
            kb.append([InlineKeyboardButton("❌ Retirer la certification", callback_data=f"admact:retirer_certif:{target_id}")])
        else:
            kb.append([InlineKeyboardButton("🔷 Certifier ce vendeur", callback_data=f"admact:certifier:{target_id}")])
    kb.append([InlineKeyboardButton("🔙 Retour à la liste", callback_data="memberspage:0")])
    await query.message.edit_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# ──────────────── AUTRES HANDLERS ADMIN (rétrogradation incluse) ────────────────

async def handle_admin_action(query, ctx, uid, parts):
    u = get_user(uid)
    if not has_level(uid, u, "gerant"):
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True); return
    act = parts[1]
    cfg = get_config()

    if act == "liste_membres":
        await handle_members_page(query, ctx, uid, u, ["memberspage", "0"])
        return

    if act == "certifier":
        if uid != SUPER_ADMIN_ID: return
        target = int(parts[2])
        save_user(target, {"certifie": True})
        log_audit("CERTIFICATION", f"{target} certifié", uid)
        await query.message.edit_text(
            f"🔷 <b>{target} certifié comme vendeur de confiance.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data=f"memberinfo:{target}")]])
        )
        try:
            await ctx.bot.send_message(target, "🔷 <b>Félicitations !</b> Tu es maintenant un vendeur certifié de confiance.", parse_mode="HTML")
        except Exception as e:
            log.warning(f"Notification certification {target}: {e}")
        return

    if act == "retirer_certif":
        if uid != SUPER_ADMIN_ID: return
        target = int(parts[2])
        save_user(target, {"certifie": False})
        log_audit("RETRAIT_CERTIFICATION", str(target), uid)
        await query.message.edit_text(
            f"❌ Certification retirée pour <b>{target}</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data=f"memberinfo:{target}")]])
        )
        return

    if act == "lever_mute":
        target = int(parts[2])
        try:
            await ctx.bot.restrict_chat_member(
                chat_id=SECURITY_GROUP_ID,
                user_id=target,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            await query.message.edit_text(
                f"🔓 Sourdine levée pour <code>{target}</code>.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])
            )
            log_audit("LEVER_MUTE", str(target), uid)
        except Exception as e:
            await query.answer(f"Erreur : {e}", show_alert=True)
        return

    if act == "reset_infractions":
        target = int(parts[2])
        db.infractions_canal.delete_one({"user_id": target})
        await query.message.edit_text(
            f"🔄 Avertissements réinitialisés pour <code>{target}</code>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])
        )
        log_audit("RESET_INFRACTIONS", str(target), uid)
        return

    if act == "supprimer_annonce":
        ann_id = parts[2]
        oid = try_objectid(ann_id)
        if not oid:
            await query.answer("ID invalide.")
            return
        annonce = db.annonces.find_one({"_id": oid})
        if not annonce:
            await query.answer("Annonce introuvable.")
            return
        chat_id = annonce.get("canal_chat_id")
        msg_id = annonce.get("canal_message_id")
        if chat_id and msg_id:
            try:
                await ctx.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                log.warning(f"Échec suppression message canal: {e}")
        db.annonces.delete_one({"_id": oid})
        log_audit("ANNONCE_SUPPRIMEE_ADMIN", str(ann_id), uid)
        try:
            await ctx.bot.send_message(annonce["vendeur_id"], f"🗑️ Votre annonce '{annonce.get('categorie','')}' a été supprimée par l'équipe.")
        except Exception as e:
            log.warning(f"Notification vendeur suppression: {e}")
        await query.message.edit_text("🗑️ Annonce supprimée.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]]))
        return

    if act == "voir_attente":
        items = list(db.annonces.find({"statut": "en_attente"}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucune annonce en attente.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])); return
        kb = []
        for it in items:
            kb.append([
                InlineKeyboardButton(f"✅ {it.get('categorie','?')[:15]}", callback_data=f"modact:approuve:{it['_id']}"),
                InlineKeyboardButton("❌", callback_data=f"modact:rejete:{it['_id']}"),
                InlineKeyboardButton("🗑️", callback_data=f"admact:supprimer_annonce:{it['_id']}")
            ])
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, f"📋 {len(items)} en attente", InlineKeyboardMarkup(kb))

    elif act == "voir_modifs":
        items = list(db.annonces.find({"modification_en_attente": True}).limit(10))
        if not items:
            await safe_edit(query, "✅ Aucune modification en attente.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]])); return
        kb = []
        for it in items:
            kb.append([
                InlineKeyboardButton(f"✅ {it.get('categorie','?')[:15]}", callback_data=f"modifact:approuver:{it['_id']}"),
                InlineKeyboardButton("❌", callback_data=f"modifact:refuser:{it['_id']}"),
                InlineKeyboardButton("🗑️", callback_data=f"admact:supprimer_annonce:{it['_id']}")
            ])
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
        kb = [
            [InlineKeyboardButton("⬆️ Promouvoir Admin", callback_data="admact:promouvoir")],
            [InlineKeyboardButton("⬇️ Rétrograder Membre", callback_data="admact:retrograder")],
            [InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]
        ]
        await safe_edit(query, "👥 <b>Gestion des rôles</b>\nChoisissez une action :", InlineKeyboardMarkup(kb))

    elif act == "promouvoir":
        if uid != SUPER_ADMIN_ID: return
        save_user(uid, {"state": "ADMIN_PROMOUVOIR"})
        await query.message.edit_text("⬆️ <b>Promotion Admin</b>\nEntrez l'ID de l'utilisateur à promouvoir :",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif act == "retrograder":
        if uid != SUPER_ADMIN_ID: return
        save_user(uid, {"state": "ADMIN_RETROGRADER"})
        await query.message.edit_text("⬇️ <b>Rétrogradation Membre</b>\nEntrez l'ID de l'utilisateur à rétrograder :",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]]))

    elif act == "retrograder_membre":
        if uid != SUPER_ADMIN_ID: return
        target = int(parts[2])
        save_user(target, {"role": "membre"})
        log_audit("RETROGRADATION", str(target), uid)
        await query.message.edit_text(f"✅ {target} rétrogradé Membre.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]]))

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
            [InlineKeyboardButton(f"📸 Limite photos ({cfg.get('limite_photos_annonce', 5)})", callback_data="admact:set_limite_photos")],
            [InlineKeyboardButton(f"⏱️ Délai anti-arnaque ({cfg.get('delai_anti_arnaque')}s)", callback_data="admact:set_delai")],
            [InlineKeyboardButton(f"🔧 Config Groupe ▼", callback_data="admact:config_groupe")],
            [InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]
        ]
        await safe_edit(query, "⚙️ <b>Configuration générale</b>", InlineKeyboardMarkup(kb))

    elif act == "config_groupe":
        if uid != SUPER_ADMIN_ID: return
        kb = [
            [InlineKeyboardButton(f"⚠️ Max avertissements ({cfg.get('groupe_max_avertissements', 3)})", callback_data="admact:set_groupe_av")],
            [InlineKeyboardButton(f"⏳ Durée mute ({cfg.get('groupe_duree_mute_heures', 24)}h)", callback_data="admact:set_groupe_mute")],
            [InlineKeyboardButton("🔙 Config", callback_data="admact:config")]
        ]
        await safe_edit(query, "🔧 <b>Configuration du groupe</b>\n\nRègles de modération automatique :\n• Les messages texte sont autorisés\n• Les GIFs, stickers et messages vocaux sont autorisés\n• Les photos, vidéos et liens sont bloqués", InlineKeyboardMarkup(kb))

    elif act == "set_limite":
        save_user(uid, {"state": "ADMCFG_LIMITE"})
        await safe_edit(query, "📋 Nouvelle limite d'annonces par membre :")

    elif act == "set_limite_photos":
        save_user(uid, {"state": "ADMCFG_LIMITE_PHOTOS"})
        await safe_edit(query, "📸 Nombre maximum de photos par annonce (défaut: 5) :")

    elif act == "set_delai":
        save_user(uid, {"state": "ADMCFG_DELAI"})
        await safe_edit(query, "⏱️ Nouveau délai anti-arnaque en secondes :")

    elif act == "config_ton":
        if uid != SUPER_ADMIN_ID: return
        taux_ton = cfg.get("taux_secours_ton_usd", 5.0)
        taux_xof = cfg.get("taux_secours_usd_to_xof", 600.0)
        kb = [
            [InlineKeyboardButton(f"💼 Commission ({cfg.get('commission_pct')}%)", callback_data="admact:set_commission")],
            [InlineKeyboardButton(f"🔐 Seuil double validation ({cfg.get('seuil_double_validation_ton')} TON)", callback_data="admact:set_seuil")],
            [InlineKeyboardButton(f"📊 Taux secours TON/USD ({taux_ton}$)", callback_data="admact:set_taux_ton")],
            [InlineKeyboardButton(f"💱 Taux secours USD→XOF ({taux_xof} F)", callback_data="admact:set_taux_xof")],
            [InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]
        ]
        await safe_edit(query, "💰 <b>Configuration TON</b>\n\n<i>Les taux de secours sont utilisés quand les API (CoinGecko/Frankfurter) sont indisponibles.</i>", InlineKeyboardMarkup(kb))

    elif act == "gestion_wallets":
        if uid != SUPER_ADMIN_ID: return
        tw = cfg.get("ton_wallet_address", "") or "Non défini"
        tp = cfg.get("ton_private_key", "")
        tk = cfg.get("toncenter_api_key", "") or "Non définie"
        aw = cfg.get("admin_ton_wallet", "") or "Non défini"
        # Masquer la clé privée pour l'affichage
        pk_display = (tp[:6] + "…" + tp[-4:]) if len(tp) > 10 else ("✅ Définie" if tp else "❌ Non définie")
        tw_display = (tw[:6] + "…" + tw[-4:]) if len(tw) > 10 else ("✅ Définie" if tw else "❌ Non défini")
        txt_wallets = (
            f"💼 <b>GESTION DES WALLETS</b>\n\n"
            f"🏦 <b>Wallet du bot :</b>\n<code>{safe_html(tw_display)}</code>\n\n"
            f"🔐 <b>Clé privée du bot :</b>\n<code>{safe_html(pk_display)}</code>\n\n"
            f"📡 <b>Clé API TonCenter :</b>\n<code>{safe_html(tk[:8] + '…' if len(tk) > 8 else tk)}</code>\n\n"
            f"💸 <b>Wallet commission admin :</b>\n<code>{safe_html(aw[:10] + '…' if len(aw) > 10 else aw)}</code>\n\n"
            f"<i>⚠️ Ces informations sont sensibles. Ne les partagez jamais.</i>"
        )
        kb = [
            [InlineKeyboardButton("🏦 Modifier wallet bot", callback_data="admact:set_ton_wallet")],
            [InlineKeyboardButton("🔐 Modifier clé privée bot", callback_data="admact:set_ton_private_key")],
            [InlineKeyboardButton("📡 Modifier clé API TonCenter", callback_data="admact:set_toncenter_key")],
            [InlineKeyboardButton("💸 Modifier wallet commission", callback_data="admact:set_wallet")],
            [InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]
        ]
        await safe_edit(query, txt_wallets, InlineKeyboardMarkup(kb))

    elif act == "set_commission":
        save_user(uid, {"state": "ADMCFG_COMMISSION"})
        await safe_edit(query, "💼 Nouvelle commission en % (ex: 5) :")

    elif act == "set_seuil":
        save_user(uid, {"state": "ADMCFG_SEUIL"})
        await safe_edit(query, "🔐 Nouveau seuil de double validation en TON :")

    elif act == "set_wallet":
        save_user(uid, {"state": "ADMCFG_WALLET"})
        await safe_edit(query, "💸 Adresse wallet TON pour recevoir la commission :")

    elif act == "set_ton_wallet":
        save_user(uid, {"state": "ADMCFG_TON_WALLET"})
        await safe_edit(query, "🏦 <b>Wallet TON du bot</b>\n\nEntre l'adresse du wallet qui reçoit les paiements Escrow (format EQ... ou UQ...) :")

    elif act == "set_ton_private_key":
        save_user(uid, {"state": "ADMCFG_TON_PRIVATE_KEY"})
        await safe_edit(query, "🔐 <b>Clé privée du bot</b>\n\nEntre la phrase mnémonique de 24 mots du wallet bot.\n⚠️ Cette information est TRÈS sensible. Assure-toi que personne ne peut voir ton écran.")

    elif act == "set_toncenter_key":
        save_user(uid, {"state": "ADMCFG_TONCENTER_KEY"})
        await safe_edit(query, "📡 <b>Clé API TonCenter</b>\n\nEntre ta clé API TonCenter (gratuite sur toncenter.com) :")

    elif act == "set_taux_ton":
        save_user(uid, {"state": "ADMCFG_TAUX_TON_USD"})
        await safe_edit(query, "📊 <b>Taux de secours TON → USD</b>\n\nQuand CoinGecko est indisponible, 1 TON = X USD.\nValeur actuelle du marché : ~3-5$\nEntre la nouvelle valeur (ex: 3.5) :")

    elif act == "set_taux_xof":
        save_user(uid, {"state": "ADMCFG_TAUX_USD_XOF"})
        await safe_edit(query, "💱 <b>Taux de secours USD → FCFA</b>\n\nQuand Frankfurter est indisponible, 1 USD = X FCFA.\nValeur standard : ~600 FCFA\nEntre la nouvelle valeur (ex: 620) :")

    elif act == "set_groupe_av":
        save_user(uid, {"state": "ADMCFG_GROUPE_AV"})
        await safe_edit(query, "⚠️ Nombre max d'avertissements avant mute (défaut: 3) :")

    elif act == "set_groupe_mute":
        save_user(uid, {"state": "ADMCFG_GROUPE_MUTE"})
        await safe_edit(query, "⏳ Durée de la sourdine en heures (défaut: 24) :")

    elif act == "dashboard":
        if not has_level(uid, u, "admin"):
            await query.answer("🚫 Réservé Admin+.", show_alert=True); return
        now = time.time()
        debut_mois = now - 30*86400
        debut_semaine = now - 7*86400
        nb_users = db.users.count_documents({})
        nb_new_users = db.users.count_documents({"date_inscription": {"$gte": debut_semaine}})
        nb_annonces_actives = db.annonces.count_documents({"statut": "approuve"})
        nb_ventes_mois = db.annonces.count_documents({"statut": "vendu", "date_depot": {"$gte": debut_mois}})
        nb_escrows_actifs = db.escrows.count_documents({"statut": {"$in": ["attente_paiement", "fonds_bloques", "acces_envoyes", "litige"]}})
        nb_escrows_termines = db.escrows.count_documents({"statut": "libere"})
        # Total TON en escrow actif
        escrows_actifs = list(db.escrows.find({"statut": {"$in": ["attente_paiement", "fonds_bloques", "acces_envoyes", "litige"]}}))
        total_ton = round(sum(e.get("montant_ton", 0) for e in escrows_actifs), 4)
        nb_litiges_ouverts = db.litiges.count_documents({"statut": "ouvert"})
        nb_blacklist = db.blacklist.count_documents({})
        txt = (
            f"📊 <b>DASHBOARD STATISTIQUES</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"👥 <b>Membres</b>\n"
            f"• Total : {nb_users}\n"
            f"• Nouveaux (7j) : {nb_new_users}\n\n"
            f"📦 <b>Annonces</b>\n"
            f"• Actives : {nb_annonces_actives}\n"
            f"• Ventes (30j) : {nb_ventes_mois}\n\n"
            f"🔒 <b>Escrow TON</b>\n"
            f"• Actifs : {nb_escrows_actifs}\n"
            f"• Terminés : {nb_escrows_termines}\n"
            f"• Volume bloqué : {total_ton} TON\n\n"
            f"⚖️ <b>Sécurité</b>\n"
            f"• Litiges ouverts : {nb_litiges_ouverts}\n"
            f"• Blacklistés : {nb_blacklist}\n"
        )
        kb = [
            [InlineKeyboardButton("🔄 Actualiser", callback_data="admact:dashboard")],
            [InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")]
        ]
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "equipe":
        if uid != SUPER_ADMIN_ID:
            await query.answer("🚫 Superadmin uniquement.", show_alert=True); return
        rem_active = cfg.get("remuneration_active", True)
        etat = "🟢 ACTIVE" if rem_active else "🔴 DÉSACTIVÉE"
        taux = cfg.get("remuneration_ton_par_point", 0.05)
        salaires = cfg.get("salaires_fixes", {})
        # Liste des membres de l'équipe (gérants + admins)
        equipe = list(db.users.find({"role": {"$in": ["gerant", "admin"]}}))
        txt = (
            f"👥 <b>ÉQUIPE & RÉMUNÉRATION</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"⚙️ Statut rémunération : <b>{etat}</b>\n"
            f"💰 Taux : 1 point = <b>{taux} TON</b>\n"
            f"👥 Membres : <b>{len(equipe)}</b>\n\n"
            f"📋 <b>Membres de l'équipe :</b>\n"
        )
        if not equipe:
            txt += "\n<i>Aucun gérant/admin pour le moment.</i>"
        else:
            for m in equipe:
                stats = db.team_stats.find_one({"_id": m["_id"]}) or {}
                pts = stats.get("points_mois", 0)
                salaire = salaires.get(str(m["_id"]), 0)
                nom = m.get("first_name", "") or m.get("username", "?")
                txt += f"• <b>{safe_html(nom)}</b> ({ROLE_LABEL.get(m.get('role','membre'))}) — {pts} pts | Fixe : {salaire} TON\n"
        kb = [
            [InlineKeyboardButton("📊 Fiches détaillées", callback_data="admact:equipe_fiches")],
            [InlineKeyboardButton("⚙️ Config rémunération", callback_data="admact:equipe_config")],
            [InlineKeyboardButton("📜 Historique paiements", callback_data="admact:historique_paiements")],
        ]
        if rem_active:
            kb.append([InlineKeyboardButton("🔴 Désactiver la rémunération", callback_data="admact:toggle_remuneration")])
        else:
            kb.append([InlineKeyboardButton("🟢 Activer la rémunération", callback_data="admact:toggle_remuneration")])
        kb.append([InlineKeyboardButton("🔙 Admin", callback_data="nav:admin_root")])
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "equipe_fiches":
        if uid != SUPER_ADMIN_ID: return
        equipe = list(db.users.find({"role": {"$in": ["gerant", "admin"]}}))
        kb = []
        for m in equipe:
            nom = m.get("first_name", "") or m.get("username", "?")
            kb.append([InlineKeyboardButton(f"📊 {safe_html(nom)}", callback_data=f"admact:fiche_gerant:{m['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Équipe", callback_data="admact:equipe")])
        await safe_edit(query, f"📊 <b>Fiches des membres</b>\n\nSélectionne un membre :", InlineKeyboardMarkup(kb))

    elif act.startswith("fiche_gerant"):
        if uid != SUPER_ADMIN_ID: return
        target = int(parts[2])
        m = db.users.find_one({"_id": target})
        if not m:
            await query.answer("Membre introuvable.", show_alert=True); return
        stats = db.team_stats.find_one({"_id": target}) or {}
        pts_mois = stats.get("points_mois", 0)
        pts_total = stats.get("points_total", 0)
        actions = stats.get("actions", {})
        salaires = cfg.get("salaires_fixes", {})
        salaire = salaires.get(str(target), 0)
        nom = m.get("first_name", "") or m.get("username", "?")
        actions_txt = "\n".join([f"• {k.replace('_',' ')} : {v}" for k, v in actions.items()]) if actions else "• Aucune action"
        txt = (
            f"📊 <b>FICHE — {safe_html(nom)}</b>\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"🎭 Rôle : {ROLE_LABEL.get(m.get('role','membre'))}\n"
            f"🆔 ID : <code>{target}</code>\n\n"
            f"⚡ Points ce mois : <b>{pts_mois}</b>\n"
            f"⚡ Points cumulés : <b>{pts_total}</b>\n"
            f"💰 Salaire fixe : <b>{salaire} TON/mois</b>\n\n"
            f"📋 <b>Actions :</b>\n{actions_txt}"
        )
        kb = [
            [InlineKeyboardButton("💰 Modifier salaire fixe", callback_data=f"admact:set_salaire:{target}")],
            [InlineKeyboardButton("🔙 Équipe", callback_data="admact:equipe")]
        ]
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "equipe_config":
        if uid != SUPER_ADMIN_ID: return
        taux = cfg.get("remuneration_ton_par_point", 0.05)
        p_ann = cfg.get("points_annonce_validee", 10)
        p_lit = cfg.get("points_litige_resolu", 20)
        p_mod = cfg.get("points_modification_validee", 5)
        p_dem = cfg.get("points_demande_validee", 5)
        txt = (
            f"⚙️ <b>CONFIG RÉMUNÉRATION</b>\n\n"
            f"💰 1 point = {taux} TON\n"
            f"📋 Points par action :\n"
            f"• Annonce validée : {p_ann} pts\n"
            f"• Litige résolu : {p_lit} pts\n"
            f"• Modification validée : {p_mod} pts\n"
            f"• Demande validée : {p_dem} pts"
        )
        kb = [
            [InlineKeyboardButton(f"💰 Taux (1 pt = {taux} TON)", callback_data="admact:set_ton_par_point")],
            [InlineKeyboardButton(f"📋 Annonce ({p_ann} pts)", callback_data="admact:set_pts_annonce")],
            [InlineKeyboardButton(f"📋 Litige ({p_lit} pts)", callback_data="admact:set_pts_litige")],
            [InlineKeyboardButton(f"📋 Modification ({p_mod} pts)", callback_data="admact:set_pts_modif")],
            [InlineKeyboardButton(f"📋 Demande ({p_dem} pts)", callback_data="admact:set_pts_demande")],
            [InlineKeyboardButton("🔙 Équipe", callback_data="admact:equipe")]
        ]
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

    elif act == "toggle_remuneration":
        if uid != SUPER_ADMIN_ID: return
        nouvel_etat = not cfg.get("remuneration_active", True)
        db.config.update_one({"type": "global"}, {"$set": {"remuneration_active": nouvel_etat}})
        log_audit("TOGGLE_REMUNERATION", f"→ {nouvel_etat}", uid)
        await afficher_admin_root(query, ctx, uid, u)

    elif act == "set_ton_par_point":
        save_user(uid, {"state": "ADMCFG_TON_PAR_POINT"})
        await safe_edit(query, "💰 Combien de TON vaut 1 point ? (ex: 0.05) :")

    elif act == "set_pts_annonce":
        save_user(uid, {"state": "ADMCFG_PTS_ANNONCE"})
        await safe_edit(query, "📋 Points pour une annonce validée :")
    elif act == "set_pts_litige":
        save_user(uid, {"state": "ADMCFG_PTS_LITIGE"})
        await safe_edit(query, "📋 Points pour un litige résolu :")
    elif act == "set_pts_modif":
        save_user(uid, {"state": "ADMCFG_PTS_MODIF"})
        await safe_edit(query, "📋 Points pour une modification validée :")
    elif act == "set_pts_demande":
        save_user(uid, {"state": "ADMCFG_PTS_DEMANDE"})
        await safe_edit(query, "📋 Points pour une demande validée :")

    elif act.startswith("set_salaire"):
        if uid != SUPER_ADMIN_ID: return
        target = int(parts[2])
        ctx.user_data["salaire_target"] = target
        save_user(uid, {"state": "ADMCFG_SALAIRE"})
        await safe_edit(query, f"💰 Salaire fixe mensuel en TON pour <code>{target}</code> (0 = aucun) :")

    elif act == "historique_paiements":
        if uid != SUPER_ADMIN_ID: return
        paiements = list(db.team_paiements.find({}).sort("timestamp", -1).limit(15))
        if not paiements:
            txt = "📜 <b>Historique des paiements</b>\n\nAucun paiement effectué pour le moment."
        else:
            txt = "📜 <b>HISTORIQUE DES PAIEMENTS</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            for p in paiements:
                gid = p.get("gerant_id", 0)
                gu = db.users.find_one({"_id": gid}) or {}
                nom = gu.get("first_name", "") or gu.get("username", str(gid))
                txt += f"• <b>{safe_html(nom)}</b> : {p.get('montant_ton', 0)} TON ({p.get('date', '?')})\n"
        kb = [[InlineKeyboardButton("🔙 Équipe", callback_data="admact:equipe")]]
        await safe_edit(query, txt, InlineKeyboardMarkup(kb))

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
#  TUNNEL DE DEMANDE DE COMPTE (avec modération)
# ══════════════════════════════════════════════════════════════

async def executer_demande_tunnel(update, ctx, uid, text=None):
    u = get_user(uid)
    state = u.get("state", "IDLE")
    if not state.startswith("DEMANDE_"):
        return
    if state == "DEMANDE_JEU" and text:
        if len(text) > 50:
            await update.effective_message.reply_text("⚠️ Nom du jeu trop long (max 50 caractères).")
            return
        save_user(uid, {"state": "DEMANDE_PLATEFORME"})
        ctx.user_data["demande_jeu"] = text
        kb = [[InlineKeyboardButton(p, callback_data=f"demandeplat:{p}") for p in ["Android", "iOS", "PC", "Console"]]]
        await update.effective_message.reply_text("📱 <b>Plateforme recherchée :</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return
    elif state == "DEMANDE_DESC" and text:
        if len(text) > 500:
            await update.effective_message.reply_text("⚠️ Description trop longue (max 500 caractères).")
            return
        jeu = ctx.user_data.get("demande_jeu", "?")
        plateforme = ctx.user_data.get("demande_plateforme", "?")
        description = text
        save_user(uid, {"state": "IDLE"})
        demande_id = db.demandes.insert_one({
            "user_id": uid,
            "username": u.get("username", "Inconnu"),
            "jeu": jeu,
            "plateforme": plateforme,
            "description": description,
            "statut": "en_attente",
            "date_creation": time.time()
        }).inserted_id
        txt_mod = (
            f"📢 <b>DEMANDE DE COMPTE À VALIDER</b>\n\n"
            f"👤 Demandeur : @{safe_html(u.get('username'))} (<code>{uid}</code>)\n"
            f"🎮 Jeu : {safe_html(jeu)}\n"
            f"📱 Plateforme : {safe_html(plateforme)}\n"
            f"📝 Description : {safe_html(description)}"
        )
        kb_mod = [[
            InlineKeyboardButton("✅ Accepter", callback_data=f"modactdemande:approuve:{demande_id}"),
            InlineKeyboardButton("❌ Rejeter", callback_data=f"modactdemande:rejete:{demande_id}")
        ]]
        for gid in get_gerants_et_plus():
            try:
                await ctx.bot.send_message(gid, txt_mod, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_mod))
            except Exception as e:
                log.warning(f"Notification modération demande {demande_id} à {gid} : {e}")
        await update.effective_message.reply_text("✅ Votre demande a été transmise à l'équipe. Elle sera publiée après validation.")
        ctx.user_data.pop("demande_jeu", None)
        ctx.user_data.pop("demande_plateforme", None)
        return

async def handle_demande_plat(query, ctx, uid, parts):
    plateforme = parts[1]
    ctx.user_data["demande_plateforme"] = plateforme
    save_user(uid, {"state": "DEMANDE_DESC"})
    await safe_edit(query, "📝 <b>Décrivez le compte recherché :</b>", parse_mode="HTML")

async def handle_moderation_demande(query, ctx, parts):
    if not has_level(query.from_user.id, get_user(query.from_user.id), "gerant"):
        await query.answer("🚫 Réservé à l'équipe.", show_alert=True)
        return
    act, demande_id = parts[1], parts[2]
    oid = try_objectid(demande_id)
    if not oid:
        await query.answer("ID invalide.")
        return
    demande = db.demandes.find_one({"_id": oid})
    if not demande:
        await query.answer("Demande introuvable.")
        return
    if demande["statut"] != "en_attente":
        await query.answer("Demande déjà traitée.")
        return

    if act == "approuve":
        txt_pub = (
            f"🔍 <b>DEMANDE DE COMPTE</b>\n\n"
            f"🎮 <b>Jeu :</b> {safe_html(demande['jeu'])}\n"
            f"📱 <b>Plateforme :</b> {safe_html(demande['plateforme'])}\n"
            f"📝 <b>Description :</b> {safe_html(demande['description'])}\n\n"
            f"👤 <b>Demandeur :</b> @{safe_html(demande['username'])}"
        )
        kb_pub = [[InlineKeyboardButton("💬 Contacter le demandeur", url=f"tg://user?id={demande['user_id']}")]]
        try:
            await ctx.bot.send_message(PUBLIC_CHANNEL_ID, txt_pub, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_pub))
            db.demandes.update_one({"_id": oid}, {"$set": {"statut": "approuve"}})
            ton.ajouter_points_gerant(query.from_user.id, 0, "demande_validee")
            await ctx.bot.send_message(demande["user_id"], "✅ Votre demande de compte a été validée et publiée sur le canal !")
            await query.message.edit_text("✅ Demande approuvée et publiée.")
        except Exception as e:
            log.error(f"Échec publication demande : {e}")
            await query.answer("Erreur lors de la publication.", show_alert=True)
        return
    else:
        db.demandes.update_one({"_id": oid}, {"$set": {"statut": "rejete"}})
        try:
            await ctx.bot.send_message(demande["user_id"], "❌ Votre demande de compte a été refusée par l'équipe.")
        except Exception as e:
            log.warning(f"Notification refus demande {demande_id}: {e}")
        await query.message.edit_text("❌ Demande rejetée.")
        return

# ══════════════════════════════════════════════════════════════
#  RAPPEL AUTOMATIQUE DE VALIDITÉ DES ANNONCES
# ══════════════════════════════════════════════════════════════

async def handle_rappel_annonce(query, uid, parts):
    annonce_id = parts[2]
    oid = try_objectid(annonce_id)
    if not oid:
        await query.answer("Annonce invalide.")
        return
    annonce = db.annonces.find_one({"_id": oid})
    if not annonce or annonce["vendeur_id"] != uid:
        await query.answer("Ce n'est pas votre annonce.")
        return
    db.annonces.update_one({"_id": oid}, {"$set": {"dernier_rappel": time.time()}})
    await query.answer("✅ Merci d'avoir confirmé ! Votre annonce reste active.")
    await query.message.edit_text("✅ Votre annonce a bien été confirmée comme toujours d'actualité.")

async def job_rappel_annonces(ctx: ContextTypes.DEFAULT_TYPE):
    maintenant = time.time()
    cfg = get_config()
    delai_rappel = cfg.get("delai_rappel_annonce_jours", 30) * 86400
    delai_inactivite = cfg.get("delai_inactivite_annonce_jours", 3) * 86400

    seuil_rappel = maintenant - delai_rappel
    annonces_a_rappeler = db.annonces.find({
        "statut": "approuve",
        "$or": [
            {"dernier_rappel": {"$lt": seuil_rappel}},
            {"dernier_rappel": {"$exists": False}}
        ]
    })
    for ann in annonces_a_rappeler:
        dernier_rappel = ann.get("dernier_rappel", 0)
        if dernier_rappel and (maintenant - dernier_rappel) < delai_rappel:
            continue
        vendeur_id = ann["vendeur_id"]
        try:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Toujours valable", callback_data=f"rappelannonce:confirmer:{ann['_id']}")
            ]])
            await ctx.bot.send_message(vendeur_id,
                f"🔔 <b>Rappel : votre annonce est-elle toujours d'actualité ?</b>\n\n"
                f"<b>{ann.get('categorie','')}</b> — {ann.get('prix','')} {ann.get('devise','')}\n\n"
                f"Si oui, cliquez sur le bouton ci-dessous. Sans réponse d'ici {delai_inactivite//86400} jours, l'annonce sera désactivée.",
                parse_mode="HTML", reply_markup=kb)
            db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"dernier_rappel": maintenant}})
        except Exception as e:
            log.warning(f"Échec d'envoi du rappel pour l'annonce {ann['_id']}: {e}")

    seuil_desactivation = maintenant - delai_inactivite
    annonces_a_desactiver = db.annonces.find({
        "statut": "approuve",
        "dernier_rappel": {"$lt": seuil_desactivation}
    })
    for ann in annonces_a_desactiver:
        dernier_rappel = ann.get("dernier_rappel", 0)
        if not dernier_rappel or (maintenant - dernier_rappel) < delai_inactivite:
            continue
        db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"statut": "expire"}})
        chat_id = ann.get("canal_chat_id")
        msg_id = ann.get("canal_message_id")
        if chat_id and msg_id:
            try:
                await ctx.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                log.warning(f"Échec suppression message canal expiré: {e}")
        try:
            await ctx.bot.send_message(ann["vendeur_id"],
                f"⏰ Votre annonce '{ann.get('categorie','')}' a été automatiquement désactivée car vous n'avez pas confirmé sa validité à temps.")
        except Exception as e:
            log.warning(f"Notification désactivation: {e}")
        log_audit("ANNONCE_EXPIREE_AUTO", str(ann["_id"]), 0)

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
    first = target.get("first_name", "")
    last = target.get("last_name", "")
    nom_reel = f"{first} {last}".strip() if (first or last) else target.get("username", "Inconnu")
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
        f"👤 <b>Nom :</b> {safe_html(nom_reel)}\n"
        f"📛 <b>Username :</b> @{safe_html(target.get('username', 'Inconnu'))}\n"
        f"🎭 <b>Rôle :</b> {ROLE_LABEL.get(role, role)}\n"
        f"🔷 <b>Certification :</b> {'Vendeur certifié' if target.get('certifie', False) else 'Non certifié'}\n"
        f"🌍 <b>Nationalité :</b> {safe_html(target.get('nationalite', 'Non définie'))}\n"
        f"📞 <b>Téléphone :</b> {safe_html(target.get('telephone') or 'Non renseigné')} ({safe_html(target.get('tel_visibilite', 'masque'))})\n"
        f"💼 <b>Wallet TON :</b> <tg-spoiler><code>{safe_html(target.get('wallet_ton') or 'Non renseigné')}</code></tg-spoiler>\n"
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
#  ÉTATS ADMIN (blacklist, rôles) — mis à jour
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
    if state == "ADMIN_PROMOUVOIR":
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
    if state == "ADMIN_RETROGRADER":
        try:
            target = int(text)
            save_user(target, {"role": "membre"})
            log_audit("RETROGRADATION", str(target), uid)
            save_user(uid, {"state": "IDLE"})
            await update.message.reply_text(f"✅ {target} rétrogradé Membre.")
            try: await ctx.bot.send_message(target, "🔔 Votre rôle a été modifié. Vous êtes maintenant Membre.")
            except Exception as e: log.warning(f"Notification rétrogradation: {e}")
        except Exception:
            await update.message.reply_text("⚠️ ID invalide.")
        return True
    return False

# ══════════════════════════════════════════════════════════════
#  SYSTÈME D'ÉVALUATION DES VENDEURS — v4.18
# ══════════════════════════════════════════════════════════════

async def envoyer_prompt_evaluation(bot, acheteur_id: int, vendeur_id: int, escrow_id):
    """Envoie un message à l'acheteur pour noter le vendeur après une transaction réussie."""
    stars_kb = []
    row = []
    for note in range(1, 6):
        row.append(InlineKeyboardButton("⭐" * note, callback_data=f"evaluer:{note}:{vendeur_id}:{escrow_id}"))
    stars_kb.append(row)
    try:
        await bot.send_message(acheteur_id,
            f"⭐ <b>Évalue ta transaction !</b>\n\n"
            f"Quelle note donnes-tu au vendeur ?\n"
            f"De 1⭐ (mauvais) à 5⭐ (excellent)",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(stars_kb))
    except Exception as e:
        log.warning(f"Échec envoi prompt évaluation à {acheteur_id}: {e}")

async def handle_evaluation(query, ctx, uid, parts):
    """Traite la note donnée par l'acheteur."""
    try:
        note = int(parts[1])
        vendeur_id = int(parts[2])
        escrow_id = parts[3]
    except (IndexError, ValueError):
        await query.answer("❌ Erreur.", show_alert=True)
        return
    if note < 1 or note > 5:
        await query.answer("❌ Note invalide.", show_alert=True)
        return
    # Enregistrer l'évaluation
    evaluation = {
        "note": note,
        "de": uid,
        "escrow_id": escrow_id,
        "date": fmt_date()
    }
    db.users.update_one({"_id": vendeur_id}, {"$push": {"evaluations": evaluation}})
    log_audit("EVALUATION", f"Vendeur {vendeur_id} noté {note}⭐ par {uid}", uid)
    await query.answer(f"✅ Note {note}⭐ enregistrée !", show_alert=True)
    try:
        await query.message.edit_text(f"⭐ <b>Merci pour ton évaluation !</b>\n\nTu as donné {note}⭐ au vendeur.", parse_mode="HTML")
    except Exception as e:
        log.warning(f"Échec édition message évaluation: {e}")
    # Notifier le vendeur
    try:
        await ctx.bot.send_message(vendeur_id,
            f"⭐ <b>Nouvelle évaluation reçue !</b>\n\nUn acheteur t'a donné {note}⭐ après une transaction.",
            parse_mode="HTML")
    except Exception as e:
        log.warning(f"Notification évaluation vendeur {vendeur_id}: {e}")

# ══════════════════════════════════════════════════════════════
#  GESTIONNAIRE D'ERREURS GLOBAL AMÉLIORÉ
# ══════════════════════════════════════════════════════════════

async def global_error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.error is None:
        log.warning("Signal d'erreur reçu sans exception.")
        return
    tb_str = traceback.format_exc()
    log.error(f"Exception non gérée :\n{tb_str}")
    safe_error = str(ctx.error)
    for sensitive in [os.environ.get("TON_PRIVATE_KEY", ""), os.environ.get("MONGO_URI", ""),
                      os.environ.get("TONCENTER_API_KEY", ""), BOT_TOKEN]:
        if sensitive:
            safe_error = safe_error.replace(sensitive, "[REDACTED]")
    try:
        for i in range(0, len(safe_error), 4000):
            await ctx.bot.send_message(SUPER_ADMIN_ID, f"🐛 <b>Erreur bot</b> :\n<code>{safe_html(safe_error[i:i+4000])}</code>", parse_mode="HTML")
    except Exception as e:
        log.warning(f"Notification erreur superadmin impossible: {e}")

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
#  VÉRIFICATION DISPONIBILITÉ (DIRECT) — v4.20
# ══════════════════════════════════════════════════════════════

async def job_verif_dispo(ctx: ContextTypes.DEFAULT_TYPE):
    """Après 24h de contact Direct, demande au vendeur si l'article est toujours dispo."""
    maintenant = time.time()
    seuil = maintenant - 24*3600  # transactions de plus de 24h
    transactions = db.transactions_directes.find({
        "statut": "en_cours",
        "verif_dispo_envoyee": {"$ne": True},
        "date_creation": {"$lt": seuil}
    })
    for trx in transactions:
        ann = db.annonces.find_one({"_id": trx["ann_id"]})
        if not ann or ann.get("statut") != "approuve":
            # L'annonce n'existe plus ou n'est plus active
            db.transactions_directes.update_one({"_id": trx["_id"]}, {"$set": {"statut": "termine"}})
            continue
        kb = [[
            InlineKeyboardButton("✅ Toujours disponible", callback_data=f"dispo:oui:{trx['_id']}"),
            InlineKeyboardButton("❌ Vendu / retiré", callback_data=f"dispo:non:{trx['_id']}")
        ]]
        try:
            await ctx.bot.send_message(trx["vendeur_id"],
                f"⏰ <b>Rappel disponibilité</b>\n\n"
                f"Il y a 24h, un acheteur t'a contacté pour ton annonce :\n"
                f"🎮 <b>{safe_html(ann.get('categorie', '?'))}</b> ({safe_html(ann.get('prix', '?'))} {safe_html(ann.get('devise', '?'))})\n\n"
                f"Cet article est-il toujours disponible ?",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            db.transactions_directes.update_one({"_id": trx["_id"]}, {"$set": {"verif_dispo_envoyee": True}})
        except Exception as e:
            log.warning(f"Échec rappel dispo pour {trx['vendeur_id']}: {e}")

async def handle_dispo_callback(query, ctx, uid, parts):
    """Traite la réponse du vendeur sur la disponibilité."""
    reponse = parts[1]
    trx_id = parts[2]
    oid = try_objectid(trx_id)
    trx = db.transactions_directes.find_one({"_id": oid}) if oid else None
    if not trx or trx["vendeur_id"] != uid:
        await query.answer("❌ Transaction introuvable.", show_alert=True)
        return
    ann = db.annonces.find_one({"_id": trx["ann_id"]})
    if reponse == "oui":
        db.transactions_directes.update_one({"_id": oid}, {"$set": {"statut": "verifie", "verif_date": time.time()}})
        await query.answer("✅ Merci ! L'annonce reste active.", show_alert=True)
        try:
            await query.message.edit_text("✅ <b>Confirmé : l'annonce est toujours disponible.</b>", parse_mode="HTML")
        except Exception:
            pass
    else:
        db.transactions_directes.update_one({"_id": oid}, {"$set": {"statut": "termine", "verif_date": time.time()}})
        if ann:
            db.annonces.update_one({"_id": trx["ann_id"]}, {"$set": {"statut": "vendu"}})
            # Supprimer le message du canal
            chat_id = ann.get("canal_chat_id")
            msg_id = ann.get("canal_message_id")
            if chat_id and msg_id:
                try:
                    await ctx.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception as e:
                    log.warning(f"Échec suppression canal (vendu): {e}")
        await query.answer("✅ Annonce marquée comme vendue.", show_alert=True)
        try:
            await query.message.edit_text("✅ <b>Merci ! L'annonce a été retirée du marché.</b>", parse_mode="HTML")
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════
#  RESET MENSUEL DES POINTS — v4.19
# ══════════════════════════════════════════════════════════════

async def job_reset_remuneration(ctx: ContextTypes.DEFAULT_TYPE):
    """Remet à zéro les points mensuels de l'équipe au début de chaque mois."""
    now = datetime.datetime.now()
    mois_courant = f"{now.year}-{now.month}"
    cfg = get_config()
    dernier_mois = cfg.get("dernier_reset_remuneration", "")
    if dernier_mois == mois_courant:
        return  # Déjà fait ce mois-ci
    # Remettre à zéro les points mensuels
    result = db.team_stats.update_many({}, {"$set": {"points_mois": 0}})
    db.config.update_one({"type": "global"}, {"$set": {"dernier_reset_remuneration": mois_courant}})
    if result.modified_count > 0:
        log_audit("RESET_REMUNERATION_MENSUEL", f"{result.modified_count} membres remis à zéro", 0)
        log.info(f"🔄 Points mensuels réinitialisés pour {result.modified_count} membres.")

# ══════════════════════════════════════════════════════════════
#  NETTOYAGE AUTOMATIQUE — v4.18
# ══════════════════════════════════════════════════════════════

async def job_nettoyage_auto(ctx: ContextTypes.DEFAULT_TYPE):
    """Supprime les brouillons abandonnés (7j) et les annonces expirées (90j)."""
    maintenant = time.time()
    # Brouillons de plus de 7 jours
    seuil_brouillon = maintenant - 7*86400
    brouillons = db.annonces.delete_many({
        "statut": "brouillon",
        "date_creation": {"$lt": seuil_brouillon}
    })
    if brouillons.deleted_count > 0:
        log_audit("NETTOYAGE_BROUILLONS", f"{brouillons.deleted_count} supprimés", 0)
        log.info(f"🧹 {brouillons.deleted_count} brouillons abandonnés supprimés.")
    # Annonces expirées/rejetées de plus de 90 jours
    seuil_expire = maintenant - 90*86400
    expires = db.annonces.delete_many({
        "statut": {"$in": ["expire", "rejete"]},
        "date_depot": {"$lt": seuil_expire}
    })
    if expires.deleted_count > 0:
        log_audit("NETTOYAGE_EXPIRES", f"{expires.deleted_count} supprimés", 0)
        log.info(f"🧹 {expires.deleted_count} annonces expirées/rejetées supprimées (90j+).")

# ══════════════════════════════════════════════════════════════
#  POST INIT / SHUTDOWN
# ══════════════════════════════════════════════════════════════

async def post_init(application: Application):
    global SECURITY_GROUP_ID_NUM
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning(f"Suppression webhook : {e}")

    # Résoudre l'ID numérique du groupe de sécurité
    try:
        chat = await application.bot.get_chat(SECURITY_GROUP_ID)
        SECURITY_GROUP_ID_NUM = chat.id
        log.info(f"🛡️ Sécurité groupe activée pour {SECURITY_GROUP_ID} (ID numérique: {SECURITY_GROUP_ID_NUM})")

        # Handler de bienvenue pour les nouveaux membres du groupe
        application.add_handler(ChatMemberHandler(
            nouveau_membre,
            chat_member_types=ChatMemberHandler.CHAT_MEMBER,
            chat_id=SECURITY_GROUP_ID_NUM
        ))

        # Handler prioritaire pour le GROUPE (suppression messages + sanctions)
        application.add_handler(MessageHandler(
            filters.Chat(chat_id=SECURITY_GROUP_ID_NUM) & ~filters.COMMAND,
            supprimer_et_sanctionner
        ), group=-1)

        log.info("🛡️ Handlers de sécurité du groupe activés.")
    except Exception as e:
        log.error(f"Impossible de résoudre l'ID du groupe {SECURITY_GROUP_ID}: {e}")
        log.warning("⚠️ Sécurité groupe désactivée — ID numérique non résolu.")
        SECURITY_GROUP_ID_NUM = None

    ton.demarrer_scanner(application.bot)
    log.info("✅ Bot Market Ultra v4.21 démarré — profil propre + wallet masqué actifs.")

async def post_shutdown(application: Application):
    await ton.arreter_scanner()
    log.info("Scanner TON arrêté proprement.")

# ══════════════════════════════════════════════════════════════
#  ROUTEUR MESSAGES FINAL
# ══════════════════════════════════════════════════════════════

async def central_text_and_media_handler_v2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    state = u.get("state", "IDLE")
    text = update.message.text if update.message else None

    if uid != SUPER_ADMIN_ID and state not in ("ADMIN_BL_ID", "ADMIN_BL_RAISON", "ADMIN_PROMOUVOIR", "ADMIN_RETROGRADER"):
        if not await verifier_etapes_obligatoires(update, ctx, uid, u):
            return

    if state in ("ADMIN_BL_ID", "ADMIN_BL_RAISON", "ADMIN_PROMOUVOIR", "ADMIN_RETROGRADER") and text:
        if await handle_admin_states(update, ctx, uid, state, text):
            return

    await central_text_and_media_handler(update, ctx)

# ══════════════════════════════════════════════════════════════
#  LANCEMENT
# ══════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()

    # Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("alerte", cmd_alerte))
    app.add_handler(CommandHandler("info", cmd_info))

    # Callback
    app.add_handler(CallbackQueryHandler(central_callback_router))

    # Handler général (messages privés uniquement — le groupe est géré par le handler sécurité)
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & filters.ChatType.PRIVATE, central_text_and_media_handler_v2), group=1)

    app.add_error_handler(global_error_handler)

    if app.job_queue:
        if TEAM_CHANNEL_ID:
            app.job_queue.run_repeating(job_resume_hebdo, interval=604800, first=60)
        app.job_queue.run_repeating(job_notif_tickets, interval=86400, first=3600)
        app.job_queue.run_repeating(job_rappel_annonces, interval=3600, first=600)
        app.job_queue.run_repeating(job_nettoyage_auto, interval=86400, first=3600)  # v4.18 : nettoyage quotidien
        app.job_queue.run_repeating(job_reset_remuneration, interval=86400, first=1800)  # v4.19 : reset mensuel des points
        app.job_queue.run_repeating(job_verif_dispo, interval=3600, first=600)  # v4.20 : vérif dispo direct (toutes les heures)

    log.info("🚀 Lancement du polling Telegram...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
