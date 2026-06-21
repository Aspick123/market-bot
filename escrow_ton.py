"""
╔══════════════════════════════════════════════════════════════╗
║                  ESCROW_TON.PY                                ║
║  Séquestre TON complet : memo, scan blockchain, conversion   ║
║  live, commission auto, double validation, reçus, paie équipe║
╚══════════════════════════════════════════════════════════════╝

Variables d'environnement nécessaires :
  TON_WALLET_ADDRESS   = adresse publique du wallet du bot
  TON_PRIVATE_KEY       = phrase mnémonique (24 mots, séparés par espace)
  TONCENTER_API_KEY     = clé API toncenter.com
  MONGO_URI             = (déjà utilisée par bot_market.py)
"""

import os
import io
import time
import hashlib
import logging
import datetime
import aiohttp
from pymongo import MongoClient
from bson.objectid import ObjectId
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

log = logging.getLogger("EscrowTON")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION & CONNEXION (partage la même base que bot_market)
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
#  CONVERSION DEVISE → TON (live + filet de sécurité)
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
    return "USD"  # par défaut si non reconnu (approximation documentée)

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
    """Retourne (montant_ton, code_devise, fallback_utilise: bool) ou (None, None, None) si impossible."""
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
#  INITIATION DE L'ESCROW (depuis le choix Direct/Escrow)
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
    }
    escrow_id = db.escrows.insert_one(escrow_doc).inserted_id
    memo = generer_memo(escrow_id)
    db.escrows.update_one({"_id": escrow_id}, {"$set": {"memo": memo}})

    db.annonces.update_one({"_id": ann["_id"]}, {"$set": {"statut": "en_cours", "escrow_id": escrow_id}})

    fallback_note = "\n⚠️ <i>(taux de secours utilisé — APIs temporairement indisponibles)</i>" if fallback else ""

    nanotons = int(ton_amount * 1_000_000_000)
    lien_tonkeeper = f"https://app.tonkeeper.com/transfer/{TON_WALLET_ADDRESS}?amount={nanotons}&text={memo}"

    kb = [[
        InlineKeyboardButton("📲 Payer avec Tonkeeper (pré-rempli)", url=lien_tonkeeper)
    ], [
        InlineKeyboardButton("❌ Annuler", callback_data=f"tonact:annuler:{escrow_id}")
    ]]
    await bot.send_message(
        acheteur_id,
        f"🛒 <b>TRANSACTION SÉCURISÉE — ESC{str(escrow_id)[-6:]}</b>\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
        f"💰 <b>Montant à envoyer : {ton_amount} TON</b>\n"
        f"<i>(≈ {montant_num} {code} au cours actuel)</i>{fallback_note}\n\n"
        f"📲 <b>Le plus simple :</b> clique sur le bouton Tonkeeper ci-dessous,\n"
        f"tout sera pré-rempli (adresse, montant, mémo) !\n\n"
        f"🏦 <i>Ou manuellement :</i>\n<code>{TON_WALLET_ADDRESS}</code>\n"
        f"💬 Mémo : <code>{memo}</code>\n\n"
        f"⏳ Tu as <b>{TIMEOUT_PAIEMENT_MIN} minutes</b> pour transférer.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb)
    )
    return escrow_id

# ══════════════════════════════════════════════════════════════
#  SCANNER BLOCKCHAIN TON
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
    except Exception: pass
    return ""

def extraire_montant(tx) -> float:
    try:
        return round(int(tx.get("in_msg", {}).get("value", 0)) / 1_000_000_000, 4)
    except Exception: return 0.0

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
                    continue
            except Exception: pass
            await confirmer_paiement_recu(bot, esc["_id"], esc, tx_hash, montant, expediteur)
            break

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
    except Exception: pass
    try:
        await bot.send_message(esc["acheteur_id"],
            f"🟡 <b>PAIEMENT REÇU & SÉCURISÉ</b>\n\n{montant} TON verrouillés. Le vendeur va t'envoyer les accès.\n"
            f"⏳ Confirme dans les {TIMEOUT_CONFIRMATION_MIN} minutes suivant réception.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_a))
    except Exception: pass

async def acces_envoyes(bot, escrow_id, vendeur_id):
    esc = get_escrow(escrow_id)
    if not esc or esc["vendeur_id"] != vendeur_id: return
    save_escrow_update(escrow_id, {"statut": "acces_envoyes"})
    kb_a = [[
        InlineKeyboardButton("✅ Confirmer réception", callback_data=f"tonact:confirmer:{escrow_id}"),
        InlineKeyboardButton("🚨 Litige", callback_data=f"tonact:litige:{escrow_id}")
    ]]
    try:
        await bot.send_message(esc["acheteur_id"], "📦 <b>Le vendeur a transmis les accès !</b>\nVérifie puis confirme.",
                               parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_a))
    except Exception: pass

# ══════════════════════════════════════════════════════════════
#  TRANSFERT TON RÉEL
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
#  CONFIRMATION RÉCEPTION → LIBÉRATION DES FONDS
# ══════════════════════════════════════════════════════════════

async def confirmer_reception(bot, escrow_id, acheteur_id):
    esc = get_escrow(escrow_id)
    if not esc or esc["acheteur_id"] != acheteur_id: return
    if esc["statut"] not in ("fonds_bloques", "acces_envoyes"): return
    save_escrow_update(escrow_id, {"statut": "confirme", "date_confirmation": fmt_date()})
    await liberer_fonds(bot, escrow_id, esc)

async def liberer_fonds(bot, escrow_id, esc: dict):
    cfg = get_escrow_config()
    montant = esc.get("montant_recu", esc["montant_ton"])
    commission_pct = esc.get("commission_pct", cfg.get("commission_pct", 5))
    commission = round(montant * commission_pct / 100, 4)
    montant_vendeur = round(montant - commission, 4)

    from_db_users = db.users.find_one({"_id": esc["vendeur_id"]}) or {}
    vendeur_wallet = from_db_users.get("wallet_ton")

    if not vendeur_wallet:
        kb_aide = [[InlineKeyboardButton("📲 Ouvrir Tonkeeper pour copier mon adresse", url="https://app.tonkeeper.com/")]]
        try:
            await bot.send_message(esc["vendeur_id"],
                f"💰 <b>Transaction confirmée !</b>\n\nPour recevoir {montant_vendeur} TON, envoie ton adresse wallet TON.\n\n"
                f"💡 Ouvre Tonkeeper, copie ton adresse (icône 📋 en haut), puis colle-la ici :",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_aide))
        except Exception: pass
        save_escrow_update(escrow_id, {"statut": "attente_wallet_vendeur", "montant_vendeur_calc": montant_vendeur,
                                       "commission_calc": commission})
        return

    success_v = await envoyer_ton(vendeur_wallet, montant_vendeur, f"Vente ESC{str(escrow_id)[-6:]}")

    admin_wallet = cfg.get("admin_ton_wallet", "")
    if admin_wallet:
        await envoyer_ton(admin_wallet, commission, f"Commission ESC{str(escrow_id)[-6:]}")

    if success_v:
        save_escrow_update(escrow_id, {"statut": "libere", "date_cloture": fmt_date(),
                                       "montant_vendeur_final": montant_vendeur, "commission_finale": commission})
        db.annonces.update_one({"_id": esc["ann_id"]}, {"$set": {"statut": "vendu"}})
        db.users.update_one({"_id": esc["vendeur_id"]}, {"$inc": {"points": 100}})

        await generer_recu(bot, escrow_id, esc, montant, montant_vendeur, commission)

        try:
            await bot.send_message(esc["acheteur_id"], "🎉 <b>Transaction terminée !</b> Merci pour ton achat.", parse_mode="HTML")
            await bot.send_message(esc["vendeur_id"],
                f"🎉 <b>Vente confirmée !</b>\n\n✅ {montant_vendeur} TON envoyés.\n💼 Commission : {commission} TON",
                parse_mode="HTML")
        except Exception: pass
    else:
        try:
            await bot.send_message(esc["vendeur_id"], "⚠️ Erreur transfert. Le support a été notifié.")
        except Exception: pass

# ══════════════════════════════════════════════════════════════
#  LITIGE ESCROW + DOUBLE VALIDATION
# ══════════════════════════════════════════════════════════════

async def ouvrir_litige_escrow(bot, escrow_id, acheteur_id, super_admin_id):
    esc = get_escrow(escrow_id)
    if not esc: return
    save_escrow_update(escrow_id, {"statut": "litige", "date_litige": fmt_date()})
    lit_id = db.litiges.insert_one({
        "escrow_id": escrow_id, "demandeur_id": acheteur_id, "vendeur_id": esc["vendeur_id"],
        "montant_ton": esc["montant_ton"], "statut": "ouvert", "date_creation": time.time(),
        "description": "Litige sur transaction Escrow", "via_escrow": True
    }).inserted_id

    kb = [[
        InlineKeyboardButton("💰 Rembourser acheteur", callback_data=f"tonact:rembourser:{escrow_id}"),
        InlineKeyboardButton("✅ Libérer vendeur", callback_data=f"tonact:forcer_liberer:{escrow_id}")
    ]]
    try:
        await bot.send_message(super_admin_id,
            f"🚨 <b>LITIGE ESCROW — {esc['montant_ton']} TON</b>\n\n"
            f"Acheteur : <code>{acheteur_id}</code>\nVendeur : <code>{esc['vendeur_id']}</code>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception: pass
    try:
        await bot.send_message(acheteur_id, "⚖️ Litige ouvert. Les fonds sont bloqués en attente de résolution.")
        await bot.send_message(esc["vendeur_id"], "⚖️ Un litige a été ouvert sur cette vente. Fonds bloqués.")
    except Exception: pass

async def rembourser_acheteur(bot, escrow_id, acted_by, super_admin_id):
    esc = get_escrow(escrow_id)
    if not esc: return False
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
        except Exception: pass
    return success

async def forcer_liberer_fonds(bot, escrow_id, acted_by, super_admin_id):
    esc = get_escrow(escrow_id)
    if not esc: return False
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
    except Exception: pass

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
        except Exception: pass

# ══════════════════════════════════════════════════════════════
#  REÇU DE TRANSACTION (PDF)
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
            except Exception: pass
    except ImportError:
        log.warning("reportlab non installé — reçu PDF ignoré.")
    except Exception as e:
        log.error(f"Erreur génération reçu : {e}")

# ══════════════════════════════════════════════════════════════
#  RÉMUNÉRATION ÉQUIPE
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
        except Exception: pass
        return True, "Paiement effectué."
    return False, "Échec de l'envoi TON."

# ══════════════════════════════════════════════════════════════
#  AUDIT & ANOMALIES
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
    except Exception: pass

# ══════════════════════════════════════════════════════════════
#  BOUCLE SCANNER
# ══════════════════════════════════════════════════════════════

async def boucle_scanner(bot):
    log.info("🔍 Scanner TON démarré.")
    while True:
        try:
            await matcher_paiements(bot)
            await verifier_timeouts(bot)
        except Exception as e:
            log.error(f"Erreur boucle scanner : {e}")
        import asyncio
        await asyncio.sleep(SCAN_INTERVAL_SEC)

async def verifier_timeouts(bot):
    now = datetime.datetime.now()
    for esc in db.escrows.find({"statut": {"$in": ["fonds_bloques", "acces_envoyes"]}}):
        if not esc.get("deadline_confirmation"): continue
        try:
            deadline = datetime.datetime.fromisoformat(esc["deadline_confirmation"])
            if now > deadline:
                await rembourser_acheteur(bot, esc["_id"], 0, 0)
        except Exception: pass

def demarrer_scanner(bot):
    import asyncio
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
        if ok: await query.message.reply_text("↩️ Remboursement effectué.")
        else: await query.message.reply_text("⏳ Validation superadmin requise (montant élevé) ou erreur.")

    elif act == "forcer_liberer":
        ok = await forcer_liberer_fonds(bot, parts[2], uid, super_admin_id)
        if ok: await query.message.reply_text("✅ Fonds libérés.")
        else: await query.message.reply_text("⏳ Validation superadmin requise (montant élevé) ou erreur.")

    elif act == "valider_double":
        await traiter_double_validation(bot, parts[2], True, super_admin_id)
        await query.message.reply_text("✅ Validé.")

    elif act == "refuser_double":
        await traiter_double_validation(bot, parts[2], False, super_admin_id)
        await query.message.reply_text("❌ Refusé.")

    elif act == "payer_gerant":
        gerant_id = int(parts[2])
        s = db.team_stats.find_one({"_id": gerant_id}) or {}
        pts = s.get("points_mois", 0)
        montant_suggere = round(pts * 0.05, 2)  # 1 point ≈ 0.05 TON, ajustable
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
        if not (text.startswith("EQ") or text.startswith("UQ")):
            await update.message.reply_text("⚠️ Adresse TON invalide (doit commencer par EQ ou UQ).")
            return True
        db.users.update_one({"_id": uid}, {"$set": {"wallet_ton": text}})
        await update.message.reply_text("✅ Wallet TON enregistré !")
        ctx.user_data.pop("ton_state", None)

        esc_attente = db.escrows.find_one({"vendeur_id": uid, "statut": "attente_wallet_vendeur"})
        if esc_attente:
            await liberer_fonds(bot, esc_attente["_id"], esc_attente)
        return True

    return False
