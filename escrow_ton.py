"""
╔══════════════════════════════════════════════════════════════╗
║                  ESCROW_TON.PY v4.4                             ║
║  Séquestre TON complet : memo, scan blockchain, conversion   ║
║  live, commission auto, double validation, reçus, paie équipe║
║  v4.4 – Dépôt-vente : compte vérifié avant la vente           ║
╚══════════════════════════════════════════════════════════════╝

Correctifs de sécurité v4.1 (audit) :
- Regex wallet TON
- Verrou atomique libération
- Timeout litige automatique (DELAI_RESOLUTION_LITIGE_JOURS)
- Alerte commission échouée
- Alerte paiement orphelin
- Ticket parrainage atomique
- Log consommation ticket
- log.warning sur exceptions silencieuses

v4.2 : Protection vendeur en cas de litige (preuves, rappels, absence de remboursement automatique si preuve)
v4.7 : Gestion propre de la tâche scanner asynchrone (annulation à l'arrêt)
"""

import os
import io
import time
import hashlib
import logging
import datetime
import re
import base64
import asyncio
import aiohttp
from bson.objectid import ObjectId
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from utils import client, db, MONGO_URI, safe_html, fmt_date, try_objectid, log_audit

log = logging.getLogger("EscrowTON")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION & CONNEXION
# ══════════════════════════════════════════════════════════════

# Note : TON_WALLET_ADDRESS, TON_PRIVATE_KEY et TONCENTER_API_KEY sont maintenant
# stockées dans la config MongoDB (modifiables via le menu admin du bot).
# Les variables d'environnement servent de fallback au premier démarrage.

TONCENTER_URL = "https://toncenter.com/api/v2"

TIMEOUT_PAIEMENT_MIN = 30
SCAN_INTERVAL_SEC = int(os.environ.get("SCAN_INTERVAL_SEC", "20"))

DELAI_RESOLUTION_LITIGE_JOURS = int(os.environ.get("DELAI_RESOLUTION_LITIGE_JOURS", "7"))

WALLET_TON_PATTERN = re.compile(r'^(EQ|UQ)[A-Za-z0-9_-]{46}$')

DEFAULTS_ESCROW_CONFIG = {
    "commission_pct": 5,
    "admin_ton_wallet": "",
    "ton_wallet_address": "",
    "ton_private_key": "",
    "toncenter_api_key": "",
    "seuil_double_validation_ton": 5.0,
    "taux_secours_ton_usd": 5.0,
    "taux_secours_usd_to_xof": 600.0,
}

# ══════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════

def get_escrow_config() -> dict:
    cfg = db.config.find_one({"type": "global"}) or {}
    merged = {**DEFAULTS_ESCROW_CONFIG, **cfg}
    # Fallback sur les variables d'environnement si la DB est vide
    if not merged.get("ton_wallet_address"):
        merged["ton_wallet_address"] = os.environ.get("TON_WALLET_ADDRESS", "")
    if not merged.get("ton_private_key"):
        merged["ton_private_key"] = os.environ.get("TON_PRIVATE_KEY", "")
    if not merged.get("toncenter_api_key"):
        merged["toncenter_api_key"] = os.environ.get("TONCENTER_API_KEY", "")
    return merged

def set_config_value(key: str, value):
    db.config.update_one({"type": "global"}, {"$set": {key: value}}, upsert=True)

def generer_memo(escrow_id) -> str:
    h = hashlib.md5(str(escrow_id).encode()).hexdigest()[:6].upper()
    return f"TX-{h}"

# ══════════════════════════════════════════════════════════════
#  CONVERSION DEVISE → TON (inchangé)
# ══════════════════════════════════════════════════════════════

ALIASES_DEVISE = {
    "fcfa": "XOF", "cfa": "XOF", "xof": "XOF", "franc": "XOF", "francs": "XOF",
    "euro": "EUR", "euros": "EUR", "eur": "EUR", "€": "EUR",
    "dollar": "USD", "dollars": "USD", "usd": "USD", "$": "USD",
    "usdt": "USD", "tether": "USD",
    "naira": "NGN", "ngn": "NGN",
    "cedi": "GHS", "cedis": "GHS", "ghs": "GHS",
    "livre": "GBP", "gbp": "GBP",
}

def normaliser_devise(texte: str) -> str:
    t = (texte or "").strip().lower()
    for alias, code in ALIASES_DEVISE.items():
        if alias in t:
            return code
    return "USD"

async def get_ton_usd_rate() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "the-open-network", "vs_currencies": "usd"},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data["the-open-network"]["usd"])
    except Exception as e:
        log.warning(f"CoinGecko indisponible : {e}")
    return None

async def get_usd_to_currency_rate(code: str) -> float:
    if code == "USD":
        return 1.0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.frankfurter.app/latest",
                params={"from": "USD", "to": code},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data["rates"][code])
    except Exception as e:
        log.warning(f"Frankfurter indisponible pour {code} : {e}")
    return None

async def convertir_en_ton(montant: float, devise_texte: str):
    cfg = get_escrow_config()
    code = normaliser_devise(devise_texte)

    ton_usd = await get_ton_usd_rate()
    fallback_ton = False
    if ton_usd is None or ton_usd <= 0:
        ton_usd = cfg.get("taux_secours_ton_usd", 5.0)
        fallback_ton = True

    if code == "USD":
        usd_equiv = montant
    else:
        rate = await get_usd_to_currency_rate(code)
        if rate is None or rate <= 0:
            if code == "XOF":
                rate = cfg.get("taux_secours_usd_to_xof", 600.0)
                fallback_ton = True
            else:
                return None, None, None
        usd_equiv = montant / rate

    ton_amount = round(usd_equiv / ton_usd, 4)
    return ton_amount, code, fallback_ton

# ══════════════════════════════════════════════════════════════
#  GESTION ESCROW — CRUD
# ══════════════════════════════════════════════════════════════

def get_escrow(escrow_id):
    oid = try_objectid(escrow_id)
    if not oid: return None
    return db.escrows.find_one({"_id": oid})

def save_escrow_update(escrow_id, data: dict):
    oid = try_objectid(escrow_id)
    if oid:
        db.escrows.update_one({"_id": oid}, {"$set": data})

# ══════════════════════════════════════════════════════════════
#  INITIATION DE L'ESCROW (inchangé)
# ══════════════════════════════════════════════════════════════

async def initier_escrow(bot, ann: dict, acheteur_id: int, acheteur_username: str):
    # ═══ v4.23 : Le compte doit être vérifié pour pouvoir acheter via Escrow ═══
    if ann.get("compte_statut") != "verifie":
        await bot.send_message(
            acheteur_id,
            "⚠️ <b>Compte pas encore vérifié</b>\n\n"
            "Ce compte n'a pas encore été vérifié par l'équipe.\n"
            "Utilise le bouton « 👀 Je suis intéressé » pour signaler ton intérêt au vendeur.",
            parse_mode="HTML"
        )
        return None

    # Vérifier que la config TON est en place
    cfg = get_escrow_config()
    ton_wallet = cfg.get("ton_wallet_address", "")
    if not ton_wallet:
        await bot.send_message(
            acheteur_id,
            "⚠️ <b>Escrow indisponible</b>\n\n"
            "Le wallet TON du bot n'est pas encore configuré.\n"
            "Contacte le support pour activer cette fonctionnalité.",
            parse_mode="HTML"
        )
        return None
    if not cfg.get("toncenter_api_key"):
        log.warning("TONCENTER_API_KEY manquant — les transactions TON ne seront pas détectées.")

    montant_str = ann.get("prix", "0")
    try:
        montant_num = float(''.join(c for c in montant_str if c.isdigit() or c == '.'))
    except Exception:
        montant_num = 0

    if montant_num <= 0:
        await bot.send_message(
            acheteur_id,
            "⚠️ Le prix de cette annonce est invalide. Contacte le support.",
            parse_mode="HTML"
        )
        return None

    devise_texte = ann.get("devise", "USD")
    try:
        ton_amount, code, fallback = await convertir_en_ton(montant_num, devise_texte)
    except Exception as e:
        log.error(f"Échec conversion devise pour {acheteur_id}: {e}")
        await bot.send_message(
            acheteur_id,
            "⚠️ Impossible de calculer la conversion en TON (erreur réseau ou API).\n"
            "Réessaie dans quelques minutes.",
            parse_mode="HTML"
        )
        return None

    if ton_amount is None:
        await bot.send_message(
            acheteur_id,
            "⚠️ Impossible de calculer la conversion en TON pour le moment.\n"
            "Réessaie dans quelques minutes ou contacte le support."
        )
        return None

    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(minutes=TIMEOUT_PAIEMENT_MIN)
    cfg = get_escrow_config()

    u = db.users.find_one({"_id": acheteur_id})
    ticket_utilise = None
    if u and u.get("tickets"):
        now_ts = time.time()
        for ticket in u["tickets"]:
            if not ticket.get("utilise", False) and ticket.get("expiration", 0) > now_ts:
                ticket_utilise = ticket["id"]
                break

    escrow_doc = {
        "ann_id": ann["_id"],
        "vendeur_id": ann["vendeur_id"],
        "acheteur_id": acheteur_id,
        "acheteur_username": acheteur_username,
        "montant_origine": montant_num,
        "devise_origine": devise_texte,
        "montant_ton": ton_amount,
        "fallback_utilise": fallback,
        "commission_pct": cfg.get("commission_pct", 5),
        "statut": "attente_paiement",
        "date_creation": fmt_date(now),
        "deadline_paiement": deadline.isoformat(),
        "tx_hash": None,
        "expediteur_wallet": None,
        "vendeur_wallet": None,
        "ticket_id": ticket_utilise,
    }
    escrow_id = db.escrows.insert_one(escrow_doc).inserted_id
    memo = generer_memo(escrow_id)
    db.escrows.update_one({"_id": escrow_id}, {"$set": {"memo": memo}})

    db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"statut": "en_cours", "escrow_id": escrow_id}})

    fallback_note = "\n⚠️ <i>(taux de secours utilisé — APIs temporairement indisponibles)</i>" if fallback else ""

    kb = [[
        InlineKeyboardButton("❌ Annuler", callback_data=f"tonact:annuler:{escrow_id}")
    ]]
    await bot.send_message(
        acheteur_id,
        f"🛒 <b>TRANSACTION SÉCURISÉE — ESC{str(escrow_id)[-6:]}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"💰 <b>Montant à envoyer : {ton_amount} TON</b>\n"
        f"<i>(≈ {montant_num} {code} au cours actuel)</i>{fallback_note}\n\n"
        f"🏦 <b>Adresse wallet du bot :</b>\n<code>{ton_wallet}</code>\n\n"
        f"💬 <b>Mémo OBLIGATOIRE :</b>\n<code>{memo}</code>\n\n"
        f"⚠️ <i>Sans le mémo, le paiement ne sera pas reconnu !</i>\n\n"
        f"⏳ Tu as <b>{TIMEOUT_PAIEMENT_MIN} minutes</b> pour transférer.\n"
        f"📲 Utilise Tonkeeper ou le Wallet Telegram.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )
    return escrow_id

# ══════════════════════════════════════════════════════════════
#  SCANNER BLOCKCHAIN TON (inchangé)
# ══════════════════════════════════════════════════════════════

async def scanner_transactions_ton() -> list:
    cfg = get_escrow_config()
    ton_wallet = cfg.get("ton_wallet_address", "")
    toncenter_key = cfg.get("toncenter_api_key", "")
    if not ton_wallet or not toncenter_key:
        return []
    headers = {"X-API-Key": toncenter_key}
    params = {"address": ton_wallet, "limit": 20, "to_lt": 0, "archival": False}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{TONCENTER_URL}/getTransactions", headers=headers,
                                   params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", [])
    except Exception as e:
        log.error(f"Erreur scan TON : {e}")
    return []

def extraire_memo(tx) -> str:
    try:
        msg = tx.get("in_msg", {})
        if msg.get("message"):
            return msg["message"].strip()
        body = msg.get("msg_data", {})
        if body.get("text"):
            return base64.b64decode(body["text"]).decode("utf-8", errors="ignore").strip()
    except Exception:
        pass
    return ""

def extraire_montant(tx) -> float:
    try:
        return round(int(tx.get("in_msg", {}).get("value", 0)) / 1_000_000_000, 4)
    except Exception:
        return 0.0

def extraire_expediteur(tx) -> str:
    return tx.get("in_msg", {}).get("source", "")

def extraire_hash(tx) -> str:
    return tx.get("transaction_id", {}).get("hash", "")

async def matcher_paiements(bot):
    transactions = await scanner_transactions_ton()
    if not transactions:
        return
    pending = list(db.escrows.find({"statut": "attente_paiement"}))
    for tx in transactions:
        memo = extraire_memo(tx)
        montant = extraire_montant(tx)
        tx_hash = extraire_hash(tx)
        expediteur = extraire_expediteur(tx)
        if not memo or not tx_hash:
            continue
        matched = False
        for esc in pending:
            if esc.get("memo") != memo or esc.get("tx_hash") == tx_hash:
                continue
            attendu = esc["montant_ton"]
            if abs(montant - attendu) > 0.05:
                continue
            try:
                deadline = datetime.datetime.fromisoformat(esc["deadline_paiement"])
                if datetime.datetime.now() > deadline:
                    db.escrows.update_one({"_id": esc["_id"]}, {"$set": {"statut": "expire"}})
                    super_admin_id = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
                    try:
                        await bot.send_message(super_admin_id,
                            f"⚠️ Paiement orphelin détecté : memo {memo}, montant {montant} TON, tx {tx_hash[:10]}...")
                    except Exception as e:
                        log.warning(f"Impossible d'alerter superadmin (orphelin) : {e}")
                    continue
            except Exception as e:
                log.warning(f"Erreur parsing deadline : {e}")
                continue
            await confirmer_paiement_recu(bot, esc["_id"], esc, tx_hash, montant, expediteur)
            matched = True
            break
        if not matched:
            super_admin_id = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
            try:
                await bot.send_message(super_admin_id,
                    f"⚠️ Paiement entrant non reconnu : memo {memo}, {montant} TON depuis {expediteur[:10]}...")
            except Exception as e:
                log.warning(f"Alerte paiement inconnu : {e}")

async def confirmer_paiement_recu(bot, escrow_id, esc: dict, tx_hash: str, montant: float, expediteur: str):
    now = datetime.datetime.now()
    save_escrow_update(escrow_id, {
        "statut": "fonds_bloques", "tx_hash": tx_hash, "montant_recu": montant,
        "expediteur_wallet": expediteur, "date_paiement": fmt_date(now)
    })

    # ═══ v4.23 : Le compte est déjà vérifié/stocqué — l'admin doit le transmettre ═══
    try:
        await bot.send_message(esc["acheteur_id"],
            f"🟡 <b>PAIEMENT REÇU & SÉCURISÉ</b>\n\n{montant} TON verrouillés.\n"
            f"L'équipe va te transmettre le compte vérifié.\n"
            f"Tu seras contacté très bientôt.",
            parse_mode="HTML")
    except Exception as e:
        log.warning(f"Échec notification acheteur fonds bloqués : {e}")

    # Notifier l'admin (superadmin + admins) pour qu'il transmette le compte et tranche
    ann = db.annonces.find_one({"_id": esc["ann_id"]}) or {}
    compte_email = ann.get("compte_email_final", "") or ann.get("compte_email_original", "")
    compte_password = ann.get("compte_password_final", "") or ann.get("compte_password_original", "")
    admin_ids = [int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))]
    for u in db.users.find({"role": "admin"}):
        if u["_id"] not in admin_ids:
            admin_ids.append(u["_id"])
    kb_admin = [[
        InlineKeyboardButton("💰 Libérer vendeur", callback_data=f"tonact:forcer_liberer:{escrow_id}"),
        InlineKeyboardButton("↩️ Rembourser acheteur", callback_data=f"tonact:rembourser:{escrow_id}")
    ]]
    for aid in admin_ids:
        try:
            await bot.send_message(aid,
                f"🛡️ <b>PAIEMENT REÇU — TRANSMETTRE LE COMPTE</b>\n\n"
                f"Transaction : ESC{str(escrow_id)[-6:]}\n"
                f"Acheteur : <code>{esc['acheteur_id']}</code>\n"
                f"Vendeur : <code>{esc['vendeur_id']}</code>\n"
                f"Montant : {montant} TON\n\n"
                f"📧 <b>Compte (email) :</b> <tg-spoiler>{safe_html(compte_email)}</tg-spoiler>\n"
                f"🔑 <b>Mot de passe :</b> <tg-spoiler>{safe_html(compte_password)}</tg-spoiler>\n\n"
                f"<i>Transmets le compte à l'acheteur, puis choisis une action :</i>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_admin))
        except Exception as e:
            log.warning(f"Notification admin paiement reçu : {e}")

async def finaliser_soumission_compte(bot, annonce_id, vendeur_id, email, password, captures, super_admin_id):
    """Le vendeur a soumis son compte (avant la vente) : stocke sur l'annonce et notifie l'admin."""
    oid = try_objectid(annonce_id)
    ann = db.annonces.find_one({"_id": oid}) if oid else None
    if not ann or ann["vendeur_id"] != vendeur_id:
        return False
    db.annonces.update_one({"_id": oid}, {"$set": {
        "compte_statut": "soumis",
        "compte_email_original": email,
        "compte_password_original": password,
        "compte_captures": captures,
        "compte_date_soumission": fmt_date()
    }})
    # Confirmer au vendeur
    try:
        await bot.send_message(vendeur_id,
            "📤 <b>Compte transmis à l'équipe !</b>\n\n"
            "L'admin va vérifier ton compte et sécuriser l'accès (changement email/mot de passe).\n"
            "Il pourra te contacter pour la double identification (2FA).\n\n"
            "💡 Si tu veux récupérer ton compte plus tard, demande-le à tout moment.",
            parse_mode="HTML")
    except Exception as e:
        log.warning(f"Notification vendeur soumission : {e}")

    # Notifier l'admin avec le contact du vendeur (pour la 2FA)
    vendeur = db.users.find_one({"_id": vendeur_id}) or {}
    vendeur_username = vendeur.get("username", "?")
    admin_ids = [super_admin_id]
    for u in db.users.find({"role": "admin"}):
        if u["_id"] not in admin_ids:
            admin_ids.append(u["_id"])
    kb_admin = [[
        InlineKeyboardButton("💬 Contacter le vendeur", url=f"tg://user?id={vendeur_id}"),
        InlineKeyboardButton("✅ Vérifier ce compte", callback_data=f"admact:verifier_compte:{oid}")
    ]]
    for aid in admin_ids:
        try:
            await bot.send_message(aid,
                f"🛡️ <b>NOUVEAU COMPTE À VÉRIFIER</b>\n\n"
                f"Annonce : {safe_html(ann.get('categorie', '?'))}\n"
                f"Vendeur : @{safe_html(vendeur_username)} (<code>{vendeur_id}</code>)\n\n"
                f"📧 <b>Email :</b> <tg-spoiler>{safe_html(email)}</tg-spoiler>\n"
                f"🔑 <b>Mot de passe :</b> <tg-spoiler>{safe_html(password)}</tg-spoiler>\n\n"
                f"⚠️ <b>Contacte le vendeur pour la 2FA</b>, change l'email/mot de passe, "
                f"puis clique « Vérifier ce compte » pour enregistrer les nouvelles infos.",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_admin))
            for cap in captures:
                try:
                    await bot.send_photo(aid, cap, caption="📸 Capture du compte")
                except Exception as e:
                    log.warning(f"Envoi capture à {aid} échoué : {e}")
        except Exception as e:
            log.warning(f"Notification admin {aid} soumission compte : {e}")

    # ═══ v4.23 : Mettre à jour le message du canal (badge « compte en vérification ») ═══
    chat_id = ann.get("canal_chat_id")
    msg_id = ann.get("canal_message_id")
    if chat_id and msg_id:
        try:
            bot_username = (await bot.get_me()).username
            v = db.users.find_one({"_id": vendeur_id}) or {}
            vname = v.get("username", "?")
            badge = " 🔷 <b>Vendeur certifié</b>" if v.get("certifie", False) else ""
            txt = (
                f"📣 <b>COMPTE DISPONIBLE !</b>\n\n🎮 #{safe_html(ann.get('categorie','').replace(' ', '_'))}\n"
                f"📱 <code>{safe_html(ann.get('plateforme'))}</code>\n💰 <b>{safe_html(ann.get('prix'))} {safe_html(ann.get('devise'))}</b>\n"
                f"📝 {safe_html(ann.get('description',''))}\n\n"
                f"⏳ <b>Compte en vérification</b>\n"
                f"👤 Vendeur : @{safe_html(vname)}{badge}"
            )
            kb = [[InlineKeyboardButton("👀 Je suis intéressé", url=f"https://t.me/{bot_username}?start=interesse_{ann['_id']}")],
                  [InlineKeyboardButton("💬 Contacter le vendeur", url=f"tg://user?id={vendeur_id}")]]
            if ann.get("photos"):
                await bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            log.warning(f"Échec mise à jour canal (soumission): {e}")
    return True

# ══════════════════════════════════════════════════════════════
#  TRANSFERT TON RÉEL (inchangé)
# ══════════════════════════════════════════════════════════════

async def envoyer_ton(to_address: str, amount_ton: float, comment: str = "") -> bool:
    cfg = get_escrow_config()
    ton_private_key = cfg.get("ton_private_key", "")
    toncenter_key = cfg.get("toncenter_api_key", "")
    if not ton_private_key or not to_address:
        log.error("Wallet privé ou destinataire manquant.")
        return False
    try:
        from tonsdk.contract.wallet import Wallets, WalletVersionEnum
        from tonsdk.utils import to_nano, bytes_to_b64str

        mnemonics = ton_private_key.split()
        _m, pub_k, priv_k, wallet = Wallets.from_mnemonics(mnemonics, WalletVersionEnum.v4r2, 0)
        seqno = await get_seqno(wallet.address.to_string(True, True, True))
        query = wallet.create_transfer_message(to_addr=to_address, amount=to_nano(amount_ton, "ton"),
                                                seqno=seqno, payload=comment)
        boc = bytes_to_b64str(query["message"].to_boc(False))
        headers = {"X-API-Key": toncenter_key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{TONCENTER_URL}/sendBoc", headers=headers,
                                    json={"boc": boc}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                result = await resp.json()
                return bool(result.get("ok"))
    except ImportError:
        log.error("tonsdk non installé.")
        return False
    except Exception as e:
        log.error(f"Erreur envoi TON : {e}")
        return False

async def get_seqno(address: str) -> int:
    cfg = get_escrow_config()
    toncenter_key = cfg.get("toncenter_api_key", "")
    headers = {"X-API-Key": toncenter_key}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{TONCENTER_URL}/runGetMethod", headers=headers,
                                   params={"address": address, "method": "seqno", "stack": "[]"},
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                stack = data.get("result", {}).get("stack", [])
                if stack: return int(stack[0][1], 16)
    except Exception as e:
        log.error(f"Erreur seqno : {e}")
    return 0

# ══════════════════════════════════════════════════════════════
#  LIBÉRATION DES FONDS (déclenchée par l'admin)
# ══════════════════════════════════════════════════════════════

async def liberer_fonds(bot, escrow_id, esc: dict):
    lock_result = db.escrows.find_one_and_update(
        {"_id": ObjectId(escrow_id),
         "statut": {"$in": ["confirme", "attente_wallet_vendeur"]},
         "liberation_en_cours": {"$ne": True}},
        {"$set": {"liberation_en_cours": True}}
    )
    if not lock_result:
        log.warning(f"Tentative de double libération ou escrow déjà traité : {escrow_id}")
        return

    cfg = get_escrow_config()
    montant = esc.get("montant_recu", esc["montant_ton"])
    commission_pct = esc.get("commission_pct", cfg.get("commission_pct", 5))

    ticket_id = esc.get("ticket_id")
    if ticket_id:
        update_res = db.users.find_one_and_update(
            {"_id": esc["acheteur_id"], "tickets.id": ticket_id, "tickets.utilise": False},
            {"$set": {"tickets.$.utilise": True}}
        )
        if update_res:
            commission_pct = 0
            log_audit("TICKET_CONSOMME", f"Escrow {escrow_id} ticket {ticket_id}", esc["acheteur_id"])
        else:
            log.warning(f"Ticket {ticket_id} déjà utilisé ou expiré pour l'utilisateur {esc['acheteur_id']}")

    commission = round(montant * commission_pct / 100, 4)
    montant_vendeur = round(montant - commission, 4)

    vendeur_data = db.users.find_one({"_id": esc["vendeur_id"]}) or {}
    vendeur_wallet = vendeur_data.get("wallet_ton")

    if not vendeur_wallet:
        try:
            await bot.send_message(esc["vendeur_id"],
                f"💰 <b>Transaction confirmée !</b>\n\nPour recevoir {montant_vendeur} TON, envoie ton adresse wallet TON :")
        except Exception as e:
            log.warning(f"Échec demande wallet vendeur : {e}")
        save_escrow_update(escrow_id, {"statut": "attente_wallet_vendeur", "montant_vendeur_calc": montant_vendeur,
                                       "commission_calc": commission, "liberation_en_cours": False})
        return

    success_v = await envoyer_ton(vendeur_wallet, montant_vendeur, f"Vente ESC{str(escrow_id)[-6:]}")

    commission_ok = True
    if commission > 0:
        admin_wallet = cfg.get("admin_ton_wallet", "")
        if admin_wallet:
            commission_ok = await envoyer_ton(admin_wallet, commission, f"Commission ESC{str(escrow_id)[-6:]}")
            if not commission_ok:
                super_admin_id = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
                try:
                    await bot.send_message(super_admin_id,
                        f"⚠️ Échec de l'envoi de la commission de {commission} TON pour ESC{str(escrow_id)[-6:]} vers {admin_wallet}")
                except Exception as e:
                    log.warning(f"Impossible d'alerter superadmin (commission failed) : {e}")

    if success_v:
        save_escrow_update(escrow_id, {"statut": "libere", "date_cloture": fmt_date(),
                                       "montant_vendeur_final": montant_vendeur, "commission_finale": commission,
                                       "liberation_en_cours": False})
        db.annonces.update_one({"_id": esc["ann_id"]}, {"$set": {"statut": "vendu"}})
        db.users.update_one({"_id": esc["vendeur_id"]}, {"$inc": {"points": 100}})

        await generer_recu(bot, escrow_id, esc, montant, montant_vendeur, commission)

        try:
            await bot.send_message(esc["acheteur_id"], "🎉 <b>Transaction terminée !</b> Merci pour ton achat.", parse_mode="HTML")
            await bot.send_message(esc["vendeur_id"],
                f"🎉 <b>Vente confirmée !</b>\n\n✅ {montant_vendeur} TON envoyés.\n💼 Commission : {commission} TON",
                parse_mode="HTML")
            # ═══ v4.18 : Envoyer le prompt d'évaluation à l'acheteur ═══
            stars_kb = []
            row = []
            for note in range(1, 6):
                row.append(InlineKeyboardButton("⭐" * note, callback_data=f"evaluer:{note}:{esc['vendeur_id']}:{escrow_id}"))
            stars_kb.append(row)
            await bot.send_message(esc["acheteur_id"],
                f"⭐ <b>Évalue ta transaction !</b>\n\n"
                f"Quelle note donnes-tu au vendeur ?\n"
                f"De 1⭐ (mauvais) à 5⭐ (excellent)",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(stars_kb))
        except Exception as e:
            log.warning(f"Notification finale échouée : {e}")
    else:
        db.escrows.update_one({"_id": ObjectId(escrow_id)}, {"$set": {"liberation_en_cours": False}})
        try:
            await bot.send_message(esc["vendeur_id"], "⚠️ Erreur transfert. Le support a été notifié.")
        except Exception as e:
            log.warning(f"Notification échec transfert vendeur : {e}")

# ══════════════════════════════════════════════════════════════
#  LITIGE ESCROW + DOUBLE VALIDATION (avec protection vendeur)
# ══════════════════════════════════════════════════════════════

async def ouvrir_litige_escrow(bot, escrow_id, acheteur_id, super_admin_id):
    esc = get_escrow(escrow_id)
    if not esc:
        return
    save_escrow_update(escrow_id, {"statut": "litige", "date_litige": fmt_date()})
    lit_id = db.litiges.insert_one({
        "escrow_id": escrow_id, "demandeur_id": acheteur_id, "vendeur_id": esc["vendeur_id"],
        "montant_ton": esc["montant_ton"], "statut": "ouvert", "date_creation": time.time(),
        "description": "Litige sur transaction Escrow", "via_escrow": True,
        "preuve_vendeur": None,
        "dernier_rappel": None
    }).inserted_id

    kb_admin = [[
        InlineKeyboardButton("💰 Rembourser acheteur", callback_data=f"tonact:rembourser:{escrow_id}"),
        InlineKeyboardButton("✅ Libérer vendeur", callback_data=f"tonact:forcer_liberer:{escrow_id}")
    ]]
    try:
        await bot.send_message(super_admin_id,
            f"🚨 <b>LITIGE ESCROW — {esc['montant_ton']} TON</b>\n\n"
            f"Acheteur : <code>{acheteur_id}</code>\nVendeur : <code>{esc['vendeur_id']}</code>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_admin))
    except Exception as e:
        log.warning(f"Notification litige superadmin échouée : {e}")

    kb_vendeur = [[
        InlineKeyboardButton("📎 Ajouter une preuve", callback_data=f"tonact:ajouter_preuve:{escrow_id}")
    ]]
    try:
        await bot.send_message(esc["vendeur_id"],
            "⚖️ Un litige a été ouvert sur cette vente. Les fonds sont bloqués.\n"
            "Si vous avez bien livré, merci d'ajouter une preuve pour éviter un remboursement automatique.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_vendeur))
    except Exception as e:
        log.warning(f"Notification vendeur litige échouée : {e}")

    try:
        await bot.send_message(acheteur_id, "⚖️ Litige ouvert. Les fonds sont bloqués en attente de résolution.")
    except Exception as e:
        log.warning(f"Notification acheteur litige échouée : {e}")

async def ajouter_preuve_litige(bot, escrow_id, vendeur_id, contenu, est_photo=False):
    esc = get_escrow(escrow_id)
    if not esc or esc["vendeur_id"] != vendeur_id:
        return False
    litige = db.litiges.find_one({"escrow_id": escrow_id, "statut": "ouvert"})
    if not litige:
        return False
    db.litiges.update_one({"_id": litige["_id"]}, {"$set": {"preuve_vendeur": contenu, "preuve_type": "photo" if est_photo else "texte"}})
    return True

async def rembourser_acheteur(bot, escrow_id, acted_by, super_admin_id):
    esc = get_escrow(escrow_id)
    if not esc:
        return False
    montant = esc.get("montant_recu", esc["montant_ton"])
    seuil = get_escrow_config().get("seuil_double_validation_ton", 5.0)

    if montant > seuil and acted_by != super_admin_id:
        await _demander_double_validation(bot, escrow_id, "rembourser", acted_by, super_admin_id)
        return False

    wallet = esc.get("expediteur_wallet")
    if not wallet:
        return False
    success = await envoyer_ton(wallet, montant, f"Remboursement ESC{str(escrow_id)[-6:]}")
    if success:
        save_escrow_update(escrow_id, {"statut": "rembourse", "date_cloture": fmt_date()})
        db.annonces.update_one({"_id": esc["ann_id"]}, {"$set": {"statut": "approuve"}})
        log_audit("REMBOURSEMENT", f"ESC {escrow_id} — {montant} TON", acted_by)
        try:
            await bot.send_message(esc["acheteur_id"], f"↩️ Remboursement effectué : {montant} TON.")
            await bot.send_message(esc["vendeur_id"], "ℹ️ La transaction a été annulée et remboursée à l'acheteur.")
        except Exception as e:
            log.warning(f"Notification remboursement échouée : {e}")
    return success

async def forcer_liberer_fonds(bot, escrow_id, acted_by, super_admin_id):
    esc = get_escrow(escrow_id)
    if not esc:
        return False
    montant = esc.get("montant_recu", esc["montant_ton"])
    seuil = get_escrow_config().get("seuil_double_validation_ton", 5.0)

    if montant > seuil and acted_by != super_admin_id:
        await _demander_double_validation(bot, escrow_id, "liberer", acted_by, super_admin_id)
        return False

    await liberer_fonds(bot, escrow_id, esc)
    log_audit("LIBERATION_FORCEE", f"ESC {escrow_id} — {montant} TON", acted_by)
    return True

async def _demander_double_validation(bot, escrow_id, action, demandeur_id, super_admin_id):
    save_escrow_update(escrow_id, {"statut": "attente_double_validation", "action_demandee": action,
                                   "demandeur_validation": demandeur_id})
    kb = [[
        InlineKeyboardButton("✅ Valider", callback_data=f"tonact:valider_double:{escrow_id}"),
        InlineKeyboardButton("❌ Refuser", callback_data=f"tonact:refuser_double:{escrow_id}")
    ]]
    try:
        await bot.send_message(super_admin_id,
            f"🔐 <b>DOUBLE VALIDATION REQUISE</b>\n\n"
            f"Un gérant/admin (<code>{demandeur_id}</code>) veut <b>{action}</b> les fonds\n"
            f"d'une transaction dépassant le seuil. Ton accord est requis :",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.warning(f"Notification double validation échouée : {e}")

async def traiter_double_validation(bot, escrow_id, valider: bool, super_admin_id):
    esc = get_escrow(escrow_id)
    if not esc or esc.get("statut") != "attente_double_validation":
        return
    action = esc.get("action_demandee")
    if valider:
        if action == "rembourser":
            await rembourser_acheteur(bot, escrow_id, super_admin_id, super_admin_id)
        elif action == "liberer":
            await forcer_liberer_fonds(bot, escrow_id, super_admin_id, super_admin_id)
    else:
        save_escrow_update(escrow_id, {"statut": "litige"})
        try:
            await bot.send_message(esc.get("demandeur_validation"), "❌ Le Superadmin a refusé cette action.")
        except Exception as e:
            log.warning(f"Notification refus double validation : {e}")

# ══════════════════════════════════════════════════════════════
#  REÇU DE TRANSACTION (PDF) — inchangé
# ══════════════════════════════════════════════════════════════

async def generer_recu(bot, escrow_id, esc: dict, montant_total, montant_vendeur, commission):
    try:
        from reportlab.lib.pagesizes import A5
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A5)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(f"REÇU DE TRANSACTION — ESC{str(escrow_id)[-6:]}", styles['Title']),
            Spacer(1, 10),
            Paragraph(f"Date : {fmt_date()}", styles['Normal']),
            Paragraph(f"Vendeur : {esc['vendeur_id']}", styles['Normal']),
            Paragraph(f"Acheteur : {esc['acheteur_id']}", styles['Normal']),
            Paragraph(f"Montant total reçu : {montant_total} TON", styles['Normal']),
            Paragraph(f"Commission prélevée : {commission} TON", styles['Normal']),
            Paragraph(f"Montant net vendeur : {montant_vendeur} TON", styles['Normal']),
            Paragraph("Statut : Validée ✅", styles['Normal']),
        ]
        doc.build(story)
        buffer.seek(0)
        buffer.name = f"recu_ESC{str(escrow_id)[-6:]}.pdf"

        for dest in (esc["vendeur_id"], esc["acheteur_id"]):
            try:
                buffer.seek(0)
                await bot.send_document(dest, document=InputFile(io.BytesIO(buffer.read()), filename=buffer.name),
                                        caption="🧾 Reçu de ta transaction.")
            except Exception as e:
                log.warning(f"Envoi reçu PDF échoué pour {dest} : {e}")
    except ImportError:
        log.warning("reportlab non installé — reçu PDF ignoré.")
    except Exception as e:
        log.error(f"Erreur génération reçu : {e}")

# ══════════════════════════════════════════════════════════════
#  RÉMUNÉRATION ÉQUIPE — inchangé
# ══════════════════════════════════════════════════════════════

# Mapping action → clé de config pour le nombre de points
POINTS_PAR_ACTION = {
    "annonce_validee": "points_annonce_validee",
    "litige_resolu": "points_litige_resolu",
    "modification_validee": "points_modification_validee",
    "demande_validee": "points_demande_validee",
}

def ajouter_points_gerant(gerant_id: int, points: int, action: str):
    """Attribue des points à un gérant si la rémunération est active.
    Le nombre de points peut être forcé (paramètre) ou lu depuis la config."""
    cfg = get_escrow_config()
    if not cfg.get("remuneration_active", True):
        return  # Rémunération désactivée → aucun point attribué
    if points is None or points <= 0:
        key = POINTS_PAR_ACTION.get(action)
        points = cfg.get(key, 10) if key else 10
    db.team_stats.update_one(
        {"_id": gerant_id},
        {"$inc": {"points_mois": points, "points_total": points, f"actions.{action}": 1}},
        upsert=True
    )

async def afficher_rapport_remuneration(message):
    cfg = get_escrow_config()
    taux = cfg.get("remuneration_ton_par_point", 0.05)
    salaires = cfg.get("salaires_fixes", {})
    stats = list(db.team_stats.find({}))
    if not stats:
        await message.reply_text("📊 Aucune statistique d'équipe pour le moment.")
        return
    txt = (
        f"💰 <b>RAPPORT RÉMUNÉRATION ÉQUIPE</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"⚙️ Taux : 1 point = {taux} TON\n\n"
    )
    kb = []
    for s in stats:
        gid = s["_id"]
        pts = s.get("points_mois", 0)
        user = db.users.find_one({"_id": gid}) or {}
        nom = user.get("first_name", "") or user.get("username", str(gid))
        salaire = salaires.get(str(gid), 0)
        montant_points = round(pts * taux, 2)
        total_du = round(montant_points + salaire, 2)
        txt += (
            f"👤 <b>{safe_html(nom)}</b> (<code>{gid}</code>)\n"
            f"   ⚡ {pts} pts → {montant_points} TON\n"
            f"   💼 Salaire fixe : {salaire} TON\n"
            f"   💰 Total dû : <b>{total_du} TON</b>\n\n"
        )
        kb.append([InlineKeyboardButton(f"💸 Payer {safe_html(nom)[:15]} ({total_du} TON)", callback_data=f"tonact:payer_gerant:{gid}")])
    await message.reply_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def payer_gerant(bot, gerant_id: int, montant_ton: float, super_admin_id):
    user = db.users.find_one({"_id": gerant_id}) or {}
    wallet = user.get("wallet_ton")
    if not wallet:
        return False, "Ce gérant n'a pas encore renseigné son wallet TON."
    success = await envoyer_ton(wallet, montant_ton, "Rémunération équipe")
    if success:
        db.team_stats.update_one({"_id": gerant_id}, {"$set": {"points_mois": 0}})
        # ═══ v4.19 : Enregistrer le paiement dans l'historique ═══
        db.team_paiements.insert_one({
            "gerant_id": gerant_id,
            "montant_ton": montant_ton,
            "date": fmt_date(),
            "timestamp": time.time(),
            "paye_par": super_admin_id
        })
        log_audit("PAIEMENT_EQUIPE", f"{gerant_id} — {montant_ton} TON", super_admin_id)
        try:
            await bot.send_message(gerant_id, f"💸 Tu as reçu {montant_ton} TON pour ton travail ce mois !")
        except Exception as e:
            log.warning(f"Notification paiement équipe {gerant_id} : {e}")
        return True, "Paiement effectué."
    return False, "Échec de l'envoi TON."

# ══════════════════════════════════════════════════════════════
#  AUDIT & ANOMALIES — inchangé
# ══════════════════════════════════════════════════════════════

async def resume_hebdo_litiges(bot, team_channel_id):
    if not team_channel_id:
        return
    une_semaine = time.time() - (7 * 86400)
    total = db.litiges.count_documents({"date_creation": {"$gte": une_semaine}})
    faveur_acheteur = db.litiges.count_documents({"date_creation": {"$gte": une_semaine}, "faveur": "acheteur"})
    faveur_vendeur = db.litiges.count_documents({"date_creation": {"$gte": une_semaine}, "faveur": "vendeur"})
    sanctions = db.litiges.count_documents({"date_creation": {"$gte": une_semaine}, "sanction": True})
    try:
        await bot.send_message(team_channel_id,
            f"📢 <b>Résumé hebdo — Litiges</b>\n\n"
            f"{total} litiges traités cette semaine\n"
            f"{faveur_acheteur} en faveur acheteur, {faveur_vendeur} en faveur vendeur\n"
            f"{sanctions} sanction(s) appliquée(s)",
            parse_mode="HTML")
    except Exception as e:
        log.warning(f"Envoi résumé hebdo échoué : {e}")

# ══════════════════════════════════════════════════════════════
#  BOUCLE SCANNER & TIMEOUTS (avec protection vendeur)
# ══════════════════════════════════════════════════════════════

_scanner_task = None  # Pour stocker la tâche asynchrone du scanner

async def boucle_scanner(bot):
    log.info("🔍 Scanner TON démarré.")
    try:
        while True:
            try:
                await matcher_paiements(bot)
                await verifier_timeouts(bot)
            except Exception as e:
                log.error(f"Erreur boucle scanner : {e}")
            await asyncio.sleep(SCAN_INTERVAL_SEC)
    except asyncio.CancelledError:
        log.info("Scanner TON arrêté.")
        raise

async def verifier_timeouts(bot):
    now = datetime.datetime.now()
    # Gestion des litiges avec protection vendeur
    super_admin_id = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
    for esc in db.escrows.find({"statut": "litige"}):
        date_litige_str = esc.get("date_litige")
        if not date_litige_str:
            continue
        try:
            date_litige_dt = datetime.datetime.strptime(date_litige_str, "%d/%m/%Y %H:%M")
            jours_ecoules = (now - date_litige_dt).days
        except Exception:
            continue

        litige = db.litiges.find_one({"escrow_id": esc["_id"], "statut": "ouvert"})
        if not litige:
            continue

        dernier_rappel = litige.get("dernier_rappel")
        if jours_ecoules >= 3 and (dernier_rappel is None or dernier_rappel < 3):
            gerants = list(db.users.find({"role": {"$in": ["gerant", "admin"]}}))
            for g in gerants:
                try:
                    await bot.send_message(g["_id"],
                        f"🔔 <b>Litige non résolu depuis 3 jours</b>\n"
                        f"Escrow : {esc['_id']}\nVendeur : {esc['vendeur_id']}\nAcheteur : {esc['acheteur_id']}\n"
                        f"Preuve vendeur : {'oui' if litige.get('preuve_vendeur') else 'non'}",
                        parse_mode="HTML")
                except Exception as e:
                    log.warning(f"Échec rappel 3 jours à {g['_id']}: {e}")
            try:
                await bot.send_message(super_admin_id,
                    f"🔔 Litige ESC{str(esc['_id'])[-6:]} non résolu depuis 3 jours (rappel envoyé à l'équipe).",
                    parse_mode="HTML")
            except Exception as e:
                log.warning(f"Échec notification superadmin 3 jours : {e}")
            db.litiges.update_one({"_id": litige["_id"]}, {"$set": {"dernier_rappel": 3}})

        if jours_ecoules >= 6 and (dernier_rappel is None or dernier_rappel < 6):
            try:
                await bot.send_message(super_admin_id,
                    f"🚨 <b>URGENT — Litige bientôt automatique</b>\n"
                    f"Escrow : {esc['_id']}\nVendeur : {esc['vendeur_id']}\nAcheteur : {esc['acheteur_id']}\n"
                    f"Jours restants avant remboursement automatique : {DELAI_RESOLUTION_LITIGE_JOURS - jours_ecoules}",
                    parse_mode="HTML")
            except Exception as e:
                log.warning(f"Échec alerte 6 jours : {e}")
            db.litiges.update_one({"_id": litige["_id"]}, {"$set": {"dernier_rappel": 6}})

        if jours_ecoules >= DELAI_RESOLUTION_LITIGE_JOURS:
            if litige.get("preuve_vendeur") is None:
                await rembourser_acheteur(bot, esc["_id"], 0, super_admin_id)
                try:
                    await bot.send_message(super_admin_id,
                        f"⏰ Litige ESC{str(esc['_id'])[-6:]} résolu automatiquement (délai {DELAI_RESOLUTION_LITIGE_JOURS}j, aucune preuve vendeur).")
                except Exception as e:
                    log.warning(f"Notification résolution auto litige : {e}")
            else:
                log_audit("LITIGE_BLOQUE_PREUVE", f"Escrow {esc['_id']} preuve présente, pas de remboursement auto", 0)
                try:
                    await bot.send_message(super_admin_id,
                        f"🛑 <b>Litige ESC{str(esc['_id'])[-6:]} : délai de {DELAI_RESOLUTION_LITIGE_JOURS} jours atteint, mais le vendeur a fourni une preuve.</b>\n"
                        f"Le remboursement automatique est annulé. Une intervention manuelle est nécessaire.\n"
                        f"Vendeur : {esc['vendeur_id']} / Acheteur : {esc['acheteur_id']}",
                        parse_mode="HTML")
                except Exception as e:
                    log.warning(f"Échec alerte litige bloqué : {e}")
                db.litiges.update_one({"_id": litige["_id"]}, {"$set": {"dernier_rappel": 999}})

def demarrer_scanner(bot):
    global _scanner_task
    _scanner_task = asyncio.create_task(boucle_scanner(bot))

async def arreter_scanner():
    if _scanner_task and not _scanner_task.done():
        _scanner_task.cancel()
        try:
            await _scanner_task
        except asyncio.CancelledError:
            pass

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER (préfixe "tonact:") — inchangé
# ══════════════════════════════════════════════════════════════

async def handle_ton_callbacks(query, ctx, bot, super_admin_id: int) -> bool:
    data = query.data
    if not data.startswith("tonact:"):
        return False
    parts = data.split(":")
    act = parts[1]
    uid = query.from_user.id

    if act == "litige":
        await ouvrir_litige_escrow(bot, parts[2], uid, super_admin_id)

    elif act == "annuler":
        save_escrow_update(parts[2], {"statut": "annule"})
        await query.message.reply_text("❌ Transaction annulée.")

    elif act == "rembourser":
        ok = await rembourser_acheteur(bot, parts[2], uid, super_admin_id)
        if ok:
            await query.message.reply_text("↩️ Remboursement effectué.")
        else:
            await query.message.reply_text("⏳ Validation superadmin requise (montant élevé) ou erreur.")

    elif act == "forcer_liberer":
        ok = await forcer_liberer_fonds(bot, parts[2], uid, super_admin_id)
        if ok:
            await query.message.reply_text("✅ Fonds libérés.")
        else:
            await query.message.reply_text("⏳ Validation superadmin requise (montant élevé) ou erreur.")

    elif act == "valider_double":
        await traiter_double_validation(bot, parts[2], True, super_admin_id)
        await query.message.reply_text("✅ Validé.")

    elif act == "refuser_double":
        await traiter_double_validation(bot, parts[2], False, super_admin_id)
        await query.message.reply_text("❌ Refusé.")

    elif act == "ajouter_preuve":
        ctx.user_data["ton_state"] = "ajout_preuve_litige"
        ctx.user_data["preuve_escrow_id"] = parts[2]
        await query.message.reply_text(
            "📎 Envoyez une capture d'écran ou une description comme preuve de livraison.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]])
        )

    elif act == "payer_gerant":
        gerant_id = int(parts[2])
        s = db.team_stats.find_one({"_id": gerant_id}) or {}
        pts = s.get("points_mois", 0)
        montant_suggere = round(pts * 0.05, 2)
        ctx.user_data["ton_pay_gerant_id"] = gerant_id
        ctx.user_data["ton_pay_montant_suggere"] = montant_suggere
        await query.message.reply_text(
            f"💸 Montant à envoyer à {gerant_id} (suggéré : {montant_suggere} TON) :\n"
            f"Tape le montant en TON à envoyer."
        )
        ctx.user_data["ton_state"] = "saisir_montant_paiement"

    elif act == "rapport_remuneration":
        await afficher_rapport_remuneration(query.message)

    elif act == "terminer_compte":
        # Le vendeur a fini d'envoyer ses captures
        annonce_id = ctx.user_data.get("soumettre_annonce_id")
        if not annonce_id:
            await query.answer("❌ Erreur.", show_alert=True)
            return True
        captures = ctx.user_data.get("soumettre_captures", [])
        if not captures:
            await query.answer("⚠️ Envoie au moins une capture d'écran.", show_alert=True)
            return True
        email = ctx.user_data.get("soumettre_email", "")
        password = ctx.user_data.get("soumettre_password", "")
        ok = await finaliser_soumission_compte(bot, annonce_id, uid, email, password, captures, super_admin_id)
        if ok:
            ctx.user_data.pop("ton_state", None)
            ctx.user_data.pop("soumettre_annonce_id", None)
            ctx.user_data.pop("soumettre_email", None)
            ctx.user_data.pop("soumettre_password", None)
            ctx.user_data.pop("soumettre_captures", None)
            await query.message.reply_text("✅ <b>Compte transmis à l'équipe pour vérification.</b>", parse_mode="HTML")
        else:
            await query.message.reply_text("❌ Impossible de transmettre le compte.", parse_mode="HTML")

    return True

async def handle_ton_input(update, ctx, bot, super_admin_id: int) -> bool:
    state = ctx.user_data.get("ton_state")
    if not state:
        return False
    text = update.message.text.strip() if update.message and update.message.text else ""
    photo = update.message.photo[-1].file_id if update.message and update.message.photo else None

    if state == "saisir_montant_paiement":
        try:
            montant = float(text.replace(",", "."))
        except Exception:
            await update.message.reply_text("⚠️ Montant invalide.")
            return True
        gerant_id = ctx.user_data.get("ton_pay_gerant_id")
        success, msg = await payer_gerant(bot, gerant_id, montant, super_admin_id)
        await update.message.reply_text(f"{'✅' if success else '❌'} {msg}")
        ctx.user_data.pop("ton_state", None)
        ctx.user_data.pop("ton_pay_gerant_id", None)
        return True

    if state == "saisir_wallet_ton":
        uid = update.effective_user.id
        if not WALLET_TON_PATTERN.match(text):
            await update.message.reply_text("⚠️ Adresse TON invalide (format EQ... ou UQ... 48 caractères).")
            return True
        db.users.update_one({"_id": uid}, {"$set": {"wallet_ton": text}})
        await update.message.reply_text("✅ Wallet TON enregistré !")
        ctx.user_data.pop("ton_state", None)

        esc_attente = db.escrows.find_one({"vendeur_id": uid, "statut": "attente_wallet_vendeur"})
        if esc_attente:
            await liberer_fonds(bot, esc_attente["_id"], esc_attente)
        return True

    if state == "ajout_preuve_litige":
        escrow_id = ctx.user_data.get("preuve_escrow_id")
        if not escrow_id:
            await update.message.reply_text("Erreur, identifiant du litige manquant.")
            ctx.user_data.pop("ton_state", None)
            return True
        uid = update.effective_user.id
        contenu = photo if photo else text
        est_photo = bool(photo)
        if not contenu:
            await update.message.reply_text("Veuillez envoyer une photo ou un texte.")
            return True
        success = await ajouter_preuve_litige(bot, escrow_id, uid, contenu, est_photo)
        if success:
            await update.message.reply_text("✅ Preuve enregistrée. L'équipe en tiendra compte pour trancher le litige.")
        else:
            await update.message.reply_text("❌ Impossible d'ajouter la preuve (litige clos ou accès refusé).")
        ctx.user_data.pop("ton_state", None)
        ctx.user_data.pop("preuve_escrow_id", None)
        return True

    # ═══ v4.22 : Formulaire guidé de soumission du compte (email → password → captures) ═══
    if state == "soumettre_compte_email":
        if not text:
            await update.message.reply_text("⚠️ Envoie l'email ou identifiant en texte.")
            return True
        ctx.user_data["soumettre_email"] = text.strip()
        ctx.user_data["ton_state"] = "soumettre_compte_password"
        await update.message.reply_text(
            "📤 <b>Étape 2/3 : Mot de passe</b>\n\nQuel est le <b>mot de passe</b> du compte ?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]])
        )
        return True

    if state == "soumettre_compte_password":
        if not text:
            await update.message.reply_text("⚠️ Envoie le mot de passe en texte.")
            return True
        ctx.user_data["soumettre_password"] = text.strip()
        ctx.user_data["ton_state"] = "soumettre_compte_captures"
        await update.message.reply_text(
            "📤 <b>Étape 3/3 : Captures d'écran</b>\n\n"
            "Envoie une ou plusieurs captures d'écran du compte (preuves), puis clique sur <b>✅ Terminer</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Terminer", callback_data="tonact:terminer_compte")],
                                                [InlineKeyboardButton("❌ Annuler", callback_data="nav:retour")]])
        )
        return True

    if state == "soumettre_compte_captures":
        if photo:
            captures = ctx.user_data.get("soumettre_captures", [])
            captures.append(photo)
            ctx.user_data["soumettre_captures"] = captures
            await update.message.reply_text(
                f"📸 Capture {len(captures)} ajoutée. Envoie d'autres captures ou clique ✅ Terminer.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Terminer", callback_data="tonact:terminer_compte")]])
            )
            return True
        else:
            await update.message.reply_text("⚠️ Envoie une photo (capture d'écran), pas du texte.")
            return True

    return False
