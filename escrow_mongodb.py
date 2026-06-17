"""
╔══════════════════════════════════════════════════════════════╗
║                    ESCROW.PY                                 ║
║         Système de séquestre TON automatique                 ║
║  • Génération mémo unique par transaction                    ║
║  • Scanner blockchain TON Center API                         ║
║  • Gestion timeouts (30min paiement, 30min confirmation)     ║
║  • Libération vendeur / Remboursement acheteur               ║
║  • Rémunération équipe par points                            ║
╚══════════════════════════════════════════════════════════════╝

Variables d'environnement Render :
  TON_WALLET_ADDRESS  = adresse publique wallet bot
  TON_PRIVATE_KEY     = clé privée wallet bot
  TONCENTER_API_KEY   = clé API TON Center
"""

import os
import asyncio
import aiohttp
import hashlib
import datetime
import logging
from database_market import mdb_read, mdb_write, format_date

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════

TON_WALLET_ADDRESS = os.environ.get("TON_WALLET_ADDRESS", "")
TON_PRIVATE_KEY    = os.environ.get("TON_PRIVATE_KEY", "")
TONCENTER_API_KEY  = os.environ.get("TONCENTER_API_KEY", "")
TONCENTER_URL      = "https://toncenter.com/api/v2"

TIMEOUT_PAIEMENT_MIN    = 30
TIMEOUT_CONFIRMATION_MIN = 30
SCAN_INTERVAL_SEC       = 10

# ══════════════════════════════════════════════════════════════
#  GESTION BASE DE DONNÉES ESCROW
# ══════════════════════════════════════════════════════════════

def get_escrow_config() -> dict:
    config = mdb_read("config.json")
    return {
        "commission_pct": config.get("ton_commission_pct", 5),
        "wallet_address": TON_WALLET_ADDRESS,
    }

def get_all_escrows() -> dict:
    return mdb_read("escrows.json") if _escrow_exists() else {}

def _escrow_exists() -> bool:
    try:
        mdb_read("escrows.json")
        return True
    except:
        mdb_write("escrows.json", {})
        return True

def get_escrow(escrow_id: str) -> dict:
    escrows = mdb_read("escrows.json")
    return escrows.get(escrow_id)

def save_escrow(escrow_id: str, data: dict):
    escrows = mdb_read("escrows.json")
    escrows[escrow_id] = data
    mdb_write("escrows.json", escrows)

def next_escrow_id() -> str:
    escrows = mdb_read("escrows.json")
    num = len(escrows) + 1
    return f"ESC{num:04d}"

def generer_memo(escrow_id: str) -> str:
    """Génère un mémo unique basé sur l'ID escrow."""
    h = hashlib.md5(escrow_id.encode()).hexdigest()[:6].upper()
    return f"TX-{h}"

# ══════════════════════════════════════════════════════════════
#  STATUTS ESCROW
# ══════════════════════════════════════════════════════════════

STATUTS = {
    "attente_paiement":   "⏳ En attente de paiement",
    "fonds_bloques":      "🔒 Fonds sécurisés",
    "acces_envoyes":      "📦 Accès transmis",
    "confirme":           "✅ Transaction confirmée",
    "litige":             "⚖️ Litige en cours",
    "rembourse":          "↩️ Remboursé",
    "libere":             "💰 Fonds libérés",
    "expire":             "⏰ Expiré",
}

# ══════════════════════════════════════════════════════════════
#  INITIATION D'UN ESCROW
# ══════════════════════════════════════════════════════════════

async def initier_escrow(
    bot, ann_id: str, annonce: dict,
    acheteur_id: int, acheteur_username: str,
    montant_ton: float
) -> str:
    """Crée un escrow et envoie les instructions à l'acheteur."""

    escrow_id = next_escrow_id()
    memo = generer_memo(escrow_id)
    config = get_escrow_config()
    commission_pct = config["commission_pct"]
    commission = round(montant_ton * commission_pct / 100, 4)
    montant_vendeur = round(montant_ton - commission, 4)
    now = datetime.datetime.now()
    deadline = now + datetime.timedelta(minutes=TIMEOUT_PAIEMENT_MIN)

    escrow = {
        "id": escrow_id,
        "ann_id": ann_id,
        "vendeur_id": annonce["vendeur_id"],
        "vendeur_username": annonce.get("vendeur_username", "?"),
        "vendeur_wallet": None,
        "acheteur_id": acheteur_id,
        "acheteur_username": acheteur_username,
        "montant_ton": montant_ton,
        "commission_pct": commission_pct,
        "commission": commission,
        "montant_vendeur": montant_vendeur,
        "memo": memo,
        "statut": "attente_paiement",
        "date_creation": format_date(now),
        "deadline_paiement": deadline.isoformat(),
        "deadline_confirmation": None,
        "tx_hash": None,
        "date_paiement": None,
        "date_confirmation": None,
        "date_cloture": None,
        "litige_id": None,
        "points_moderation": {},
    }

    save_escrow(escrow_id, escrow)

    # Figer l'annonce
    annonces = mdb_read("annonces.json")
    if ann_id in annonces:
        annonces[ann_id]["statut"] = "en_cours"
        annonces[ann_id]["escrow_id"] = escrow_id
        mdb_write("annonces.json", annonces)

    # Message à l'acheteur
    wallet = config["wallet_address"]
    msg = (
        f"🛒 *TRANSACTION SÉCURISÉE — {escrow_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 Article : *{annonce.get('titre','?')}*\n"
        f"👤 Vendeur : @{annonce.get('vendeur_username','?')}\n\n"
        f"💰 *Montant à envoyer : `{montant_ton} TON`*\n\n"
        f"🏦 *Adresse wallet du bot :*\n"
        f"`{wallet}`\n\n"
        f"💬 *Mémo OBLIGATOIRE :*\n"
        f"`{memo}`\n\n"
        f"⚠️ _Sans le mémo, ton paiement ne sera pas reconnu !_\n\n"
        f"⏳ Tu as *{TIMEOUT_PAIEMENT_MIN} minutes* pour effectuer le transfert.\n"
        f"🕐 Expiration : {deadline.strftime('%H:%M')}\n\n"
        f"📲 Utilise *Tonkeeper* ou *Telegram Wallet*."
    )

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = [[
        InlineKeyboardButton("📋 Copier l'adresse", callback_data=f"copy_wallet_{escrow_id}"),
        InlineKeyboardButton("📋 Copier le mémo", callback_data=f"copy_memo_{escrow_id}")
    ], [
        InlineKeyboardButton("❌ Annuler", callback_data=f"escrow_annuler_{escrow_id}")
    ]]

    try:
        await bot.send_message(
            acheteur_id, msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        log.error(f"Erreur envoi message acheteur : {e}")

    return escrow_id

# ══════════════════════════════════════════════════════════════
#  SCANNER BLOCKCHAIN TON
# ══════════════════════════════════════════════════════════════

async def scanner_transactions_ton() -> list:
    """Interroge TON Center API pour les transactions entrantes."""
    if not TON_WALLET_ADDRESS or not TONCENTER_API_KEY:
        return []

    headers = {"X-API-Key": TONCENTER_API_KEY}
    params = {
        "address": TON_WALLET_ADDRESS,
        "limit": 20,
        "to_lt": 0,
        "archival": False
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{TONCENTER_URL}/getTransactions",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", [])
    except Exception as e:
        log.error(f"Erreur scan TON : {e}")
    return []

def extraire_memo(transaction: dict) -> str:
    """Extrait le mémo/commentaire d'une transaction TON."""
    try:
        msg = transaction.get("in_msg", {})
        # Mémo en texte
        if msg.get("message"):
            return msg["message"].strip()
        # Mémo encodé
        body = msg.get("msg_data", {})
        if body.get("text"):
            import base64
            decoded = base64.b64decode(body["text"]).decode("utf-8", errors="ignore")
            return decoded.strip()
    except:
        pass
    return ""

def extraire_montant(transaction: dict) -> float:
    """Extrait le montant en TON (depuis nanotons)."""
    try:
        nanotons = int(transaction.get("in_msg", {}).get("value", 0))
        return round(nanotons / 1_000_000_000, 4)
    except:
        return 0.0

def extraire_expediteur(transaction: dict) -> str:
    """Extrait l'adresse de l'expéditeur."""
    try:
        return transaction.get("in_msg", {}).get("source", "")
    except:
        return ""

def extraire_hash(transaction: dict) -> str:
    try:
        return transaction.get("transaction_id", {}).get("hash", "")
    except:
        return ""

# ══════════════════════════════════════════════════════════════
#  MATCHING MEMO → ESCROW
# ══════════════════════════════════════════════════════════════

async def matcher_paiement(bot, transactions: list):
    """Cherche si une transaction correspond à un escrow en attente."""
    escrows = mdb_read("escrows.json")

    for tx in transactions:
        memo = extraire_memo(tx)
        montant = extraire_montant(tx)
        tx_hash = extraire_hash(tx)
        expediteur = extraire_expediteur(tx)

        if not memo or not tx_hash:
            continue

        for escrow_id, escrow in escrows.items():
            if (escrow.get("statut") == "attente_paiement" and
                escrow.get("memo") == memo):

                # Vérifier si déjà traité
                if escrow.get("tx_hash") == tx_hash:
                    continue

                # Vérifier le montant (tolérance 0.01 TON pour les frais)
                montant_attendu = escrow["montant_ton"]
                if abs(montant - montant_attendu) > 0.05:
                    await bot.send_message(
                        escrow["acheteur_id"],
                        f"⚠️ Montant incorrect reçu : `{montant} TON`\n"
                        f"Attendu : `{montant_attendu} TON`\n"
                        f"Renvoie la différence ou contacte le support.",
                        parse_mode="Markdown"
                    )
                    continue

                # Vérifier timeout
                deadline = datetime.datetime.fromisoformat(escrow["deadline_paiement"])
                if datetime.datetime.now() > deadline:
                    await expirer_escrow(bot, escrow_id, escrow)
                    continue

                # ✅ Paiement valide !
                await confirmer_paiement(bot, escrow_id, escrow, tx_hash, montant, expediteur)
                break

# ══════════════════════════════════════════════════════════════
#  CONFIRMATION PAIEMENT REÇU
# ══════════════════════════════════════════════════════════════

async def confirmer_paiement(
    bot, escrow_id: str, escrow: dict,
    tx_hash: str, montant: float, expediteur: str
):
    """Fonds reçus — notifier les deux parties."""
    now = datetime.datetime.now()
    deadline_conf = now + datetime.timedelta(minutes=TIMEOUT_CONFIRMATION_MIN)

    escrow["statut"] = "fonds_bloques"
    escrow["tx_hash"] = tx_hash
    escrow["montant_recu"] = montant
    escrow["expediteur_wallet"] = expediteur
    escrow["date_paiement"] = format_date(now)
    escrow["deadline_confirmation"] = deadline_conf.isoformat()
    save_escrow(escrow_id, escrow)

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    # Message acheteur
    kb_acheteur = [[
        InlineKeyboardButton("✅ Confirmer la réception", callback_data=f"escrow_confirmer_{escrow_id}"),
        InlineKeyboardButton("🚨 Ouvrir un litige", callback_data=f"escrow_litige_{escrow_id}")
    ]]
    await bot.send_message(
        escrow["acheteur_id"],
        f"🟡 *PAIEMENT REÇU & SÉCURISÉ*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ `{montant} TON` verrouillés par le bot.\n\n"
        f"@{escrow['vendeur_username']} va t'envoyer les accès.\n"
        f"Vérifie le compte et confirme dans *{TIMEOUT_CONFIRMATION_MIN} min*.\n\n"
        f"⏰ Expiration : {deadline_conf.strftime('%H:%M')}\n"
        f"_(Remboursement auto si pas de confirmation)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_acheteur)
    )

    # Message vendeur
    kb_vendeur = [[
        InlineKeyboardButton("📦 J'ai envoyé les accès", callback_data=f"escrow_acces_envoyes_{escrow_id}")
    ]]
    await bot.send_message(
        escrow["vendeur_id"],
        f"🟢 *FONDS SÉCURISÉS !*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"`{montant} TON` bloqués en séquestre.\n\n"
        f"👉 Envoie maintenant les accès du compte\n"
        f"à @{escrow['acheteur_username']} en message privé.\n\n"
        f"Clique ci-dessous une fois envoyés :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_vendeur)
    )

    log.info(f"✅ Paiement confirmé pour {escrow_id} : {montant} TON")

# ══════════════════════════════════════════════════════════════
#  ACTIONS UTILISATEURS
# ══════════════════════════════════════════════════════════════

async def acces_envoyes(bot, escrow_id: str, vendeur_id: int):
    """Vendeur confirme avoir envoyé les accès."""
    escrow = get_escrow(escrow_id)
    if not escrow or escrow["statut"] != "fonds_bloques":
        return

    if escrow["vendeur_id"] != vendeur_id:
        return

    escrow["statut"] = "acces_envoyes"
    save_escrow(escrow_id, escrow)

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = [[
        InlineKeyboardButton("✅ Confirmer la réception", callback_data=f"escrow_confirmer_{escrow_id}"),
        InlineKeyboardButton("🚨 Litige", callback_data=f"escrow_litige_{escrow_id}")
    ]]

    await bot.send_message(
        escrow["acheteur_id"],
        f"📦 *Le vendeur a transmis les accès !*\n\n"
        f"Vérifie le compte et confirme ici.\n"
        f"⏰ Tu as *{TIMEOUT_CONFIRMATION_MIN} min* pour confirmer.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def confirmer_reception(bot, escrow_id: str, acheteur_id: int):
    """Acheteur confirme avoir reçu et vérifié le compte."""
    escrow = get_escrow(escrow_id)
    if not escrow or escrow["statut"] not in ["fonds_bloques", "acces_envoyes"]:
        return

    if escrow["acheteur_id"] != acheteur_id:
        return

    escrow["statut"] = "confirme"
    escrow["date_confirmation"] = format_date()
    save_escrow(escrow_id, escrow)

    # Libérer les fonds vers le vendeur
    await liberer_fonds(bot, escrow_id, escrow)

async def ouvrir_litige_escrow(bot, escrow_id: str, acheteur_id: int, super_admin_id: int):
    """Acheteur ouvre un litige — fonds bloqués."""
    escrow = get_escrow(escrow_id)
    if not escrow:
        return

    escrow["statut"] = "litige"
    escrow["date_litige"] = format_date()
    save_escrow(escrow_id, escrow)

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    # Notifier l'acheteur
    await bot.send_message(
        acheteur_id,
        f"⚖️ *Litige ouvert — {escrow_id}*\n\n"
        f"Les fonds sont bloqués.\n"
        f"Un admin va examiner votre dossier.\n"
        f"Envoie tes preuves en réponse à ce message.",
        parse_mode="Markdown"
    )

    # Notifier le vendeur
    await bot.send_message(
        escrow["vendeur_id"],
        f"⚖️ *Litige ouvert sur {escrow_id}*\n\n"
        f"L'acheteur a signalé un problème.\n"
        f"Les fonds sont bloqués en attente de résolution.",
        parse_mode="Markdown"
    )

    # Notifier le super admin
    kb_admin = [[
        InlineKeyboardButton("💰 Rembourser acheteur", callback_data=f"escrow_rembourser_{escrow_id}"),
        InlineKeyboardButton("✅ Libérer vendeur", callback_data=f"escrow_liberer_{escrow_id}")
    ]]

    await bot.send_message(
        super_admin_id,
        f"🚨 *LITIGE ESCROW — {escrow_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Acheteur : @{escrow['acheteur_username']} (`{escrow['acheteur_id']}`)\n"
        f"👤 Vendeur : @{escrow['vendeur_username']} (`{escrow['vendeur_id']}`)\n"
        f"💰 Montant : `{escrow['montant_ton']} TON`\n"
        f"📝 Article : {escrow.get('ann_id','?')}\n\n"
        f"Examine les preuves et décide :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_admin)
    )

# ══════════════════════════════════════════════════════════════
#  TRANSFERTS TON
# ══════════════════════════════════════════════════════════════

async def envoyer_ton(to_address: str, amount_ton: float, comment: str = "") -> bool:
    """Envoie des TON depuis le wallet du bot."""
    try:
        from tonsdk.contract.wallet import Wallets, WalletVersionEnum
        from tonsdk.utils import to_nano, bytes_to_b64str
        import base64

        # Créer le wallet depuis la clé privée
        mnemonics = TON_PRIVATE_KEY.split()
        _mnemonics, pub_k, priv_k, wallet = Wallets.from_mnemonics(
            mnemonics, WalletVersionEnum.v4r2, 0
        )

        # Construire la transaction
        seqno = await get_seqno(wallet.address.to_string(True, True, True))
        query = wallet.create_transfer_message(
            to_addr=to_address,
            amount=to_nano(amount_ton, "ton"),
            seqno=seqno,
            payload=comment
        )

        boc = bytes_to_b64str(query["message"].to_boc(False))

        # Envoyer via TON Center
        headers = {"X-API-Key": TONCENTER_API_KEY, "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{TONCENTER_URL}/sendBoc",
                headers=headers,
                json={"boc": boc},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                if result.get("ok"):
                    log.info(f"✅ Envoi {amount_ton} TON → {to_address}")
                    return True
                else:
                    log.error(f"❌ Erreur envoi TON : {result}")
                    return False

    except ImportError:
        log.error("❌ tonsdk non installé — pip install tonsdk")
        return False
    except Exception as e:
        log.error(f"❌ Erreur envoi TON : {e}")
        return False

async def get_seqno(address: str) -> int:
    """Récupère le seqno du wallet pour les transactions."""
    headers = {"X-API-Key": TONCENTER_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{TONCENTER_URL}/runGetMethod",
                headers=headers,
                params={"address": address, "method": "seqno", "stack": "[]"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                stack = data.get("result", {}).get("stack", [])
                if stack:
                    return int(stack[0][1], 16)
    except Exception as e:
        log.error(f"Erreur seqno : {e}")
    return 0

async def liberer_fonds(bot, escrow_id: str, escrow: dict):
    """Libère les fonds vers le vendeur après confirmation."""
    montant_vendeur = escrow["montant_vendeur"]
    vendeur_wallet = escrow.get("vendeur_wallet")

    if not vendeur_wallet:
        # Demander le wallet du vendeur
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        await bot.send_message(
            escrow["vendeur_id"],
            f"💰 *Transaction confirmée !*\n\n"
            f"Pour recevoir `{montant_vendeur} TON`,\n"
            f"envoie ton adresse wallet TON :",
            parse_mode="Markdown"
        )
        escrow["statut"] = "attente_wallet_vendeur"
        save_escrow(escrow_id, escrow)
        return

    success = await envoyer_ton(
        vendeur_wallet, montant_vendeur,
        f"Vente {escrow_id}"
    )

    if success:
        escrow["statut"] = "libere"
        escrow["date_cloture"] = format_date()
        save_escrow(escrow_id, escrow)

        # Mettre à jour stats annonce
        annonces = mdb_read("annonces.json")
        if escrow["ann_id"] in annonces:
            annonces[escrow["ann_id"]]["statut
