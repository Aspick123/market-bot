"""
╔══════════════════════════════════════════════════════════════╗
║                  ESCROW_TON.PY                                ║
║  Séquestre TON complet : memo, scan blockchain, conversion   ║
║  live, commission auto, double validation, reçus, paie équipe║
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
"""

import os
import io
import time
import hashlib
import logging
import datetime
import re
import asyncio
import aiohttp
from pymongo import MongoClient
from bson.objectid import ObjectId
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

log = logging.getLogger("EscrowTON")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION & CONNEXION
# ══════════════════════════════════════════════════════════════

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
TON_WALLET_ADDRESS = os.environ.get("TON_WALLET_ADDRESS", "")
TON_PRIVATE_KEY = os.environ.get("TON_PRIVATE_KEY", "")
TONCENTER_API_KEY = os.environ.get("TONCENTER_API_KEY", "")
TONCENTER_URL = "https://toncenter.com/api/v2"

client = MongoClient(MONGO_URI)
db = client["bot_market_premium_db"]

TIMEOUT_PAIEMENT_MIN = 30
TIMEOUT_CONFIRMATION_MIN = 30
SCAN_INTERVAL_SEC = 20

DELAI_RESOLUTION_LITIGE_JOURS = int(os.environ.get("DELAI_RESOLUTION_LITIGE_JOURS", "7"))

WALLET_TON_PATTERN = re.compile(r'^(EQ|UQ)[A-Za-z0-9_-]{46}$')

DEFAULTS_ESCROW_CONFIG = {
    "commission_pct": 5,
    "admin_ton_wallet": "",
    "seuil_double_validation_ton": 5.0,
    "taux_secours_ton_usd": 5.0,
    "taux_secours_usd_to_xof": 600.0,
}

# ══════════════════════════════════════════════════════════════
#  UTILITAIRES
# ══════════════════════════════════════════════════════════════

def fmt_date(ts=None) -> str:
    if ts is None: ts = time.time()
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")

def try_objectid(val):
    try: return ObjectId(val)
    except Exception: return None

def safe_html(text) -> str:
    if text is None: return ""
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def get_escrow_config() -> dict:
    cfg = db.config.find_one({"type": "global"}) or {}
    return {**DEFAULTS_ESCROW_CONFIG, **cfg}

def set_config_value(key: str, value):
    db.config.update_one({"type": "global"}, {"$set": {key: value}}, upsert=True)

def generer_memo(escrow_id) -> str:
    h = hashlib.md5(str(escrow_id).encode()).hexdigest()[:6].upper()
    return f"TX-{h}"

def log_audit(action: str, details: str, acted_by: int):
    db.audit_logs.insert_one({
        "action": action, "details": details, "acted_by": acted_by,
        "date": fmt_date(), "timestamp": time.time()
    })

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
    montant_str = ann.get("prix", "0")
    try:
        montant_num = float(''.join(c for c in montant_str if c.isdigit() or c == '.'))
    except Exception:
        montant_num = 0

    devise_texte = ann.get("devise", "USD")
    ton_amount, code, fallback = await convertir_en_ton(montant_num, devise_texte)

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
        "deadline_confirmation": None,
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
        f"🏦 <b>Adresse wallet du bot :</b>\n<code>{TON_WALLET_ADDRESS}</code>\n\n"
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
    if not TON_WALLET_ADDRESS or not TONCENTER_API_KEY:
        return []
    headers = {"X-API-Key": TONCENTER_API_KEY}
    params = {"address": TON_WALLET_ADDRESS, "limit": 20, "to_lt": 0, "archival": False}
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
            import base64
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
    deadline_conf = now + datetime.timedelta(minutes=TIMEOUT_CONFIRMATION_MIN)
    save_escrow_update(escrow_id, {
        "statut": "fonds_bloques", "tx_hash": tx_hash, "montant_recu": montant,
        "expediteur_wallet": expediteur, "deadline_confirmation": deadline_conf.isoformat(),
        "date_paiement": fmt_date(now)
    })

    kb_v = [[InlineKeyboardButton("📦 J'ai envoyé les accès", callback_data=f"tonact:acces_envoyes:{escrow_id}")]]
    kb_a = [[
        InlineKeyboardButton("✅ Confirmer réception", callback_data=f"tonact:confirmer:{escrow_id}"),
        InlineKeyboardButton("🚨 Litige", callback_data=f"tonact:litige:{escrow_id}")
    ]]
    try:
        await bot.send_message(esc["vendeur_id"],
            f"🟢 <b>FONDS SÉCURISÉS !</b>\n\n{montant} TON bloqués en séquestre.\nTransmets les accès à l'acheteur puis confirme :",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_v))
    except Exception as e:
        log.warning(f"Échec notification vendeur fonds bloqués : {e}")
    try:
        await bot.send_message(esc["acheteur_id"],
            f"🟡 <b>PAIEMENT REÇU & SÉCURISÉ</b>\n\n{montant} TON verrouillés. Le vendeur va t'envoyer les accès.\n"
            f"⏳ Confirme dans les {TIMEOUT_CONFIRMATION_MIN} minutes suivant réception.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_a))
    except Exception as e:
        log.warning(f"Échec notification acheteur fonds bloqués : {e}")

async def acces_envoyes(bot, escrow_id, vendeur_id):
    esc = get_escrow(escrow_id)
    if not esc or esc["vendeur_id"] != vendeur_id:
        return
    save_escrow_update(escrow_id, {"statut": "acces_envoyes"})
    kb_a = [[
        InlineKeyboardButton("✅ Confirmer réception", callback_data=f"tonact:confirmer:{escrow_id}"),
        InlineKeyboardButton("🚨 Litige", callback_data=f"tonact:litige:{escrow_id}")
    ]]
    try:
        await bot.send_message(esc["acheteur_id"], "📦 <b>Le vendeur a transmis les accès !</b>\nVérifie puis confirme.",
                               parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_a))
    except Exception as e:
        log.warning(f"Échec notification accès envoyés : {e}")

# ══════════════════════════════════════════════════════════════
#  TRANSFERT TON RÉEL (inchangé)
# ══════════════════════════════════════════════════════════════

async def envoyer_ton(to_address: str, amount_ton: float, comment: str = "") -> bool:
    if not TON_PRIVATE_KEY or not to_address:
        log.error("Wallet privé ou destinataire manquant.")
        return False
    try:
        from tonsdk.contract.wallet import Wallets, WalletVersionEnum
        from tonsdk.utils import to_nano, bytes_to_b64str

        mnemonics = TON_PRIVATE_KEY.split()
        _m, pub_k, priv_k, wallet = Wallets.from_mnemonics(mnemonics, WalletVersionEnum.v4r2, 0)
        seqno = await get_seqno(wallet.address.to_string(True, True, True))
        query = wallet.create_transfer_message(to_addr=to_address, amount=to_nano(amount_ton, "ton"),
                                                seqno=seqno, payload=comment)
        boc = bytes_to_b64str(query["message"].to_boc(False))
        headers = {"X-API-Key": TONCENTER_API_KEY, "Content-Type": "application/json"}
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
    headers = {"X-API-Key": TONCENTER_API_KEY}
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
#  CONFIRMATION RÉCEPTION → LIBÉRATION DES FONDS (inchangé)
# ══════════════════════════════════════════════════════════════

async def confirmer_reception(bot, escrow_id, acheteur_id):
    esc = get_escrow(escrow_id)
    if not esc or esc["acheteur_id"] != acheteur_id:
        return
    if esc["statut"] not in ("fonds_bloques", "acces_envoyes"):
        return
    save_escrow_update(escrow_id, {"statut": "confirme", "date_confirmation": fmt_date()})
    await liberer_fonds(bot, escrow_id, esc)

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
        "preuve_vendeur": None,          # ajouté pour la protection vendeur
        "dernier_rappel": None           # pour les alertes progressives
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

    # Envoyer message au vendeur avec bouton pour ajouter une preuve
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

def ajouter_points_gerant(gerant_id: int, points: int, action: str):
    db.team_stats.update_one(
        {"_id": gerant_id},
        {"$inc": {"points_mois": points, "points_total": points, f"actions.{action}": 1}},
        upsert=True
    )

async def afficher_rapport_remuneration(message):
    stats = list(db.team_stats.find({}))
    if not stats:
        await message.reply_text("📊 Aucune statistique d'équipe pour le moment.")
        return
    txt = "💰 <b>RAPPORT RÉMUNÉRATION ÉQUIPE</b>\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
    kb = []
    for s in stats:
        gid = s["_id"]
        pts = s.get("points_mois", 0)
        txt += f"👤 <code>{gid}</code> — {pts} pts ce mois\n"
        kb.append([InlineKeyboardButton(f"💸 Payer {gid} ({pts} pts)", callback_data=f"tonact:payer_gerant:{gid}")])
    await message.reply_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def payer_gerant(bot, gerant_id: int, montant_ton: float, super_admin_id):
    user = db.users.find_one({"_id": gerant_id}) or {}
    wallet = user.get("wallet_ton")
    if not wallet:
        return False, "Ce gérant n'a pas encore renseigné son wallet TON."
    success = await envoyer_ton(wallet, montant_ton, "Rémunération équipe")
    if success:
        db.team_stats.update_one({"_id": gerant_id}, {"$set": {"points_mois": 0}})
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

def detecter_favoritisme(admin_id: int, beneficiaire_id: int) -> bool:
    count = db.litiges.count_documents({
        "resolu_par": admin_id, "faveur_id": beneficiaire_id
    })
    return count > 3

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

async def boucle_scanner(bot):
    log.info("🔍 Scanner TON démarré.")
    while True:
        try:
            await matcher_paiements(bot)
            await verifier_timeouts(bot)
        except Exception as e:
            log.error(f"Erreur boucle scanner : {e}")
        await asyncio.sleep(SCAN_INTERVAL_SEC)

async def verifier_timeouts(bot):
    now = datetime.datetime.now()
    # Timeout confirmation acheteur (inchangé)
    for esc in db.escrows.find({"statut": {"$in": ["fonds_bloques", "acces_envoyes"]}}):
        if not esc.get("deadline_confirmation"):
            continue
        try:
            deadline = datetime.datetime.fromisoformat(esc["deadline_confirmation"])
            if now > deadline:
                await rembourser_acheteur(bot, esc["_id"], 0, 0)
        except Exception as e:
            log.warning(f"Erreur timeout confirmation : {e}")

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

        # Rappels progressifs
        dernier_rappel = litige.get("dernier_rappel")
        if jours_ecoules >= 3 and (dernier_rappel is None or dernier_rappel < 3):
            # Rappel à l'équipe (gérants+)
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
            # Alerte critique au superadmin
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
            # Action automatique seulement si aucune preuve vendeur
            if litige.get("preuve_vendeur") is None:
                await rembourser_acheteur(bot, esc["_id"], 0, super_admin_id)
                try:
                    await bot.send_message(super_admin_id,
                        f"⏰ Litige ESC{str(esc['_id'])[-6:]} résolu automatiquement (délai {DELAI_RESOLUTION_LITIGE_JOURS}j, aucune preuve vendeur).")
                except Exception as e:
                    log.warning(f"Notification résolution auto litige : {e}")
            else:
                # Preuve fournie : pas de remboursement automatique, on bloque et on alerte
                log_audit("LITIGE_BLOQUE_PREUVE", f"Escrow {esc['_id']} preuve présente, pas de remboursement auto", 0)
                try:
                    await bot.send_message(super_admin_id,
                        f"🛑 <b>Litige ESC{str(esc['_id'])[-6:]} : délai de {DELAI_RESOLUTION_LITIGE_JOURS} jours atteint, mais le vendeur a fourni une preuve.</b>\n"
                        f"Le remboursement automatique est annulé. Une intervention manuelle est nécessaire.\n"
                        f"Vendeur : {esc['vendeur_id']} / Acheteur : {esc['acheteur_id']}",
                        parse_mode="HTML")
                except Exception as e:
                    log.warning(f"Échec alerte litige bloqué : {e}")
                # On empêche de re-déclencher l'action en mettant le dernier rappel à une valeur élevée
                db.litiges.update_one({"_id": litige["_id"]}, {"$set": {"dernier_rappel": 999}})

def demarrer_scanner(bot):
    asyncio.create_task(boucle_scanner(bot))

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER (préfixe "tonact:")
# ══════════════════════════════════════════════════════════════

async def handle_ton_callbacks(query, ctx, bot, super_admin_id: int) -> bool:
    data = query.data
    if not data.startswith("tonact:"):
        return False
    parts = data.split(":")
    act = parts[1]
    uid = query.from_user.id

    if act == "confirmer":
        await confirmer_reception(bot, parts[2], uid)
        await query.message.reply_text("✅ Réception confirmée, libération en cours...")

    elif act == "acces_envoyes":
        await acces_envoyes(bot, parts[2], uid)
        await query.message.reply_text("✅ Notifié à l'acheteur.")

    elif act == "litige":
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

    return False
