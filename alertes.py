"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 6 — ALERTES.PY                           ║
║  • Alertes personnalisées par jeu                            ║
║  • Gestion des abonnements                                   ║
║  • Notification baisse de prix                               ║
║  • Rappel d'expiration annonces                              ║
╚══════════════════════════════════════════════════════════════╝
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import mdb_read, mdb_write, get_user, save_user, format_date

# ══════════════════════════════════════════════════════════════
#  GESTION DES ALERTES
# ══════════════════════════════════════════════════════════════

def get_alertes_user(user_id: int) -> list:
    alertes = mdb_read("alertes.json")
    return alertes.get(str(user_id), [])

def save_alertes_user(user_id: int, alertes_list: list):
    alertes = mdb_read("alertes.json")
    alertes[str(user_id)] = alertes_list
    mdb_write("alertes.json", alertes)

def add_alerte(user_id: int, jeu: str, type_article: str = "tous"):
    alertes = get_alertes_user(user_id)
    # Éviter les doublons
    for a in alertes:
        if a["jeu"].lower() == jeu.lower() and a["type"] == type_article:
            return False
    alertes.append({
        "jeu": jeu,
        "type": type_article,
        "date": format_date()
    })
    save_alertes_user(user_id, alertes)
    return True

def remove_alerte(user_id: int, index: int) -> bool:
    alertes = get_alertes_user(user_id)
    if 0 <= index < len(alertes):
        alertes.pop(index)
        save_alertes_user(user_id, alertes)
        return True
    return False

# ══════════════════════════════════════════════════════════════
#  MENU ALERTES
# ══════════════════════════════════════════════════════════════

async def show_menu_alertes(message, user_id: int):
    alertes = get_alertes_user(user_id)
    kb = [
        [InlineKeyboardButton("➕ Ajouter une alerte", callback_data="alerte_ajouter")],
        [InlineKeyboardButton("📋 Mes alertes", callback_data="alerte_mes_alertes")],
        [InlineKeyboardButton("🔕 Tout désactiver", callback_data="alerte_tout_supprimer")],
    ]
    await message.reply_text(
        f"🔔 *Mes alertes* ({len(alertes)} active{'s' if len(alertes) > 1 else ''})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Je te notifie quand une nouvelle annonce\n"
        f"correspond à tes critères.\n\n"
        f"Que veux-tu faire ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  AJOUTER UNE ALERTE
# ══════════════════════════════════════════════════════════════

async def show_ajouter_alerte(message):
    jeux = mdb_read("jeux.json")
    kb = []
    row = []
    for jeu in list(jeux.keys()) + ["Tous les jeux"]:
        row.append(InlineKeyboardButton(jeu, callback_data=f"alerte_jeu_{jeu}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🔙 Retour", callback_data="menu_alertes")])

    await message.reply_text(
        "🔔 *Nouvelle alerte*\n\n"
        "Pour quel jeu veux-tu être alerté ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_alerte_type(message, jeu: str):
    kb = [
        [InlineKeyboardButton("👤 Compte uniquement", callback_data=f"alerte_confirm_{jeu}_compte")],
        [InlineKeyboardButton("💎 Monnaie uniquement", callback_data=f"alerte_confirm_{jeu}_monnaie")],
        [InlineKeyboardButton("🔍 Tout type", callback_data=f"alerte_confirm_{jeu}_tous")],
        [InlineKeyboardButton("🔙 Retour", callback_data="alerte_ajouter")],
    ]
    await message.reply_text(
        f"🔔 *Alerte — {jeu}*\n\n"
        f"Quel type d'article ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def confirmer_alerte(query, user_id: int):
    parts = query.data.replace("alerte_confirm_", "").rsplit("_", 1)
    jeu = parts[0]
    type_art = parts[1]

    success = add_alerte(user_id, jeu, type_art)
    type_label = {"compte": "👤 Compte", "monnaie": "💎 Monnaie", "tous": "🔍 Tout"}.get(type_art, type_art)

    if success:
        await query.message.reply_text(
            f"✅ *Alerte activée !*\n\n"
            f"🎮 Jeu : *{jeu}*\n"
            f"📦 Type : *{type_label}*\n\n"
            f"Tu seras notifié à chaque nouvelle annonce.",
            parse_mode="Markdown"
        )
    else:
        await query.message.reply_text(
            "ℹ️ Tu as déjà une alerte pour ce jeu et ce type."
        )

# ══════════════════════════════════════════════════════════════
#  MES ALERTES
# ══════════════════════════════════════════════════════════════

async def show_mes_alertes(message, user_id: int):
    alertes = get_alertes_user(user_id)
    if not alertes:
        await message.reply_text(
            "🔔 *Mes alertes*\n\nAucune alerte active.\n"
            "Ajoute-en une pour être notifié !",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Ajouter une alerte", callback_data="alerte_ajouter")
            ]])
        )
        return

    msg = f"🔔 *Mes alertes* ({len(alertes)})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    kb = []
    for i, alerte in enumerate(alertes):
        type_label = {"compte": "👤", "monnaie": "💎", "tous": "🔍"}.get(alerte["type"], "🔍")
        msg += f"{i+1}. {type_label} *{alerte['jeu']}* — depuis {alerte['date']}\n"
        kb.append([InlineKeyboardButton(
            f"🗑️ Supprimer {i+1}. {alerte['jeu']}",
            callback_data=f"alerte_supprimer_{i}"
        )])

    kb.append([InlineKeyboardButton("➕ Ajouter", callback_data="alerte_ajouter")])
    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

async def supprimer_alerte(query, user_id: int):
    index = int(query.data.replace("alerte_supprimer_", ""))
    alertes = get_alertes_user(user_id)
    if 0 <= index < len(alertes):
        jeu = alertes[index]["jeu"]
        remove_alerte(user_id, index)
        await query.message.reply_text(f"✅ Alerte *{jeu}* supprimée.", parse_mode="Markdown")
    else:
        await query.message.reply_text("❌ Alerte introuvable.")

async def supprimer_toutes_alertes(query, user_id: int):
    save_alertes_user(user_id, [])
    await query.message.reply_text("✅ Toutes tes alertes ont été supprimées.")

# ══════════════════════════════════════════════════════════════
#  NOTIFICATIONS AUTOMATIQUES
# ══════════════════════════════════════════════════════════════

async def notifier_baisse_prix(bot, ann_id: str, ancien_prix: str, nouveau_prix: str):
    """Notifie les membres intéressés par une annonce d'une baisse de prix."""
    transactions = mdb_read("transactions.json")
    notifies = set()

    for tid, trx in transactions.items():
        if trx.get("ann_id") == ann_id and trx.get("statut") == "contact_refuse":
            uid = trx.get("acheteur_id")
            if uid and uid not in notifies:
                notifies.add(uid)
                try:
                    await bot.send_message(
                        uid,
                        f"📉 *Baisse de prix !*\n\n"
                        f"Une annonce qui t'intéressait\n"
                        f"a baissé de prix :\n\n"
                        f"Ancien prix : ~~{ancien_prix}~~\n"
                        f"Nouveau prix : *{nouveau_prix}*\n\n"
                        f"Tape /ann_{ann_id} pour voir l'annonce.",
                        parse_mode="Markdown"
                    )
                except: pass

async def notifier_expiration_proche(bot):
    """Notifie les vendeurs dont l'annonce expire dans 3 jours."""
    import datetime
    annonces = mdb_read("annonces.json")
    now = datetime.datetime.now()
    dans_3_jours = now + datetime.timedelta(days=3)

    for ann_id, ann in annonces.items():
        if ann.get("statut") not in ["active", "boostee"]:
            continue
        try:
            exp = datetime.datetime.strptime(ann["expiration"], "%d/%m/%Y")
            if now < exp <= dans_3_jours and not ann.get("notif_expiration_envoyee"):
                try:
                    await bot.send_message(
                        ann["vendeur_id"],
                        f"⏰ *Annonce bientôt expirée !*\n\n"
                        f"🎫 *{ann_id}* — {ann['titre']}\n\n"
                        f"Ton annonce expire le *{ann['expiration']}*.\n"
                        f"Renouvelle-la pour qu'elle reste visible !",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                "🔄 Renouveler",
                                callback_data=f"ann_renouveler_{ann_id}"
                            )
                        ]])
                    )
                    ann["notif_expiration_envoyee"] = True
                    from database_market import save_annonce
                    save_annonce(ann_id, ann)
                except: pass
        except: pass

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_alertes_callbacks(query, ctx) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data == "menu_alertes":
        await show_menu_alertes(msg, uid)
        return True

    if data == "alerte_ajouter":
        await show_ajouter_alerte(msg)
        return True

    if data == "alerte_mes_alertes":
        await show_mes_alertes(msg, uid)
        return True

    if data == "alerte_tout_supprimer":
        await supprimer_toutes_alertes(query, uid)
        return True

    if data.startswith("alerte_jeu_"):
        jeu = data.replace("alerte_jeu_", "")
        await show_alerte_type(msg, jeu)
        return True

    if data.startswith("alerte_confirm_"):
        await confirmer_alerte(query, uid)
        return True

    if data.startswith("alerte_supprimer_"):
        await supprimer_alerte(query, uid)
        return True

    return False
