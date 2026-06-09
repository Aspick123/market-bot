"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 4 — TRANSACTIONS.PY                      ║
║  • Mise en relation acheteur ↔ vendeur                       ║
║  • Accord mutuel obligatoire                                 ║
║  • Confirmation des deux parties                             ║
║  • Historique des transactions                               ║
║  • Export PDF historique                                     ║
╚══════════════════════════════════════════════════════════════╝
"""

import datetime
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, mdb_config,
    get_user, save_user, get_annonce, save_annonce,
    get_transaction, save_transaction, next_transaction_id,
    get_transactions_user, add_log, update_stat,
    format_date, stars, niveau_label
)

STATUTS_TRX = {
    "contact_demande":  "🟡 Contact demandé",
    "contact_accepte":  "🔵 En contact",
    "contact_refuse":   "❌ Contact refusé",
    "en_cours":         "🔄 Transaction en cours",
    "confirmee_vendeur":"⏳ En attente confirmation acheteur",
    "confirmee_acheteur":"⏳ En attente confirmation vendeur",
    "completee":        "✅ Complétée",
    "annulee":          "🔴 Annulée",
    "litige":          "⚖️ En litige",
}

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 1 — ACHETEUR EXPRIME SON INTÉRÊT
# ══════════════════════════════════════════════════════════════

async def exprimer_interet(query, ctx, bot, super_admin_id: int):
    """Acheteur clique sur 'Je suis intéressé'."""
    ann_id = query.data.replace("interesse_", "")
    annonce = get_annonce(ann_id)
    uid = query.from_user.id

    if not annonce:
        await query.message.reply_text("❌ Annonce introuvable.")
        return

    if annonce["vendeur_id"] == uid:
        await query.message.reply_text("⚠️ Tu ne peux pas acheter ta propre annonce !")
        return

    if annonce.get("statut") not in ["active", "boostee"]:
        await query.message.reply_text("⚠️ Cette annonce n'est plus disponible.")
        return

    # Vérifier CGU
    from cgu import user_a_accepte_cgu_acheteur
    if not await user_a_accepte_cgu_acheteur(query.message, uid, ctx):
        return

    # Vérifier si déjà une transaction en cours pour cette annonce
    transactions = mdb_read("transactions.json")
    for tid, trx in transactions.items():
        if (trx.get("ann_id") == ann_id and
            trx.get("acheteur_id") == uid and
            trx.get("statut") in ["contact_demande", "contact_accepte", "en_cours"]):
            await query.message.reply_text(
                "ℹ️ Tu as déjà une demande en cours pour cette annonce."
            )
            return

    config = mdb_config()
    delai = config.get("delai_anti_arnaque_minutes", 5)

    kb = [
        [
            InlineKeyboardButton("✅ Confirmer ma demande", callback_data=f"trx_confirmer_{ann_id}"),
            InlineKeyboardButton("❌ Annuler", callback_data="trx_annuler")
        ]
    ]

    await query.message.reply_text(
        f"🤝 *Demande de contact*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 Annonce : *{annonce['titre']}*\n"
        f"💰 Prix : *{annonce['prix']}*\n\n"
        f"⚠️ *Important :*\n"
        f"• Les transactions se font directement\n"
        f"  entre toi et le vendeur\n"
        f"• Le bot n'est qu'un intermédiaire\n"
        f"• Vérifie bien le profil du vendeur\n\n"
        f"⏱️ Le vendeur aura le contact dans *{delai} minutes*\n"
        f"après ta confirmation.\n\n"
        f"Confirmes-tu ta demande ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 2 — CONFIRMATION DE L'ACHETEUR
# ══════════════════════════════════════════════════════════════

async def confirmer_interet(query, ctx, bot):
    """Acheteur confirme sa demande de contact."""
    ann_id = query.data.replace("trx_confirmer_", "")
    annonce = get_annonce(ann_id)
    acheteur = query.from_user
    config = mdb_config()
    delai = config.get("delai_anti_arnaque_minutes", 5)

    trx_id = next_transaction_id()
    trx = {
        "id": trx_id,
        "ann_id": ann_id,
        "vendeur_id": annonce["vendeur_id"],
        "vendeur_username": annonce["vendeur_username"],
        "acheteur_id": acheteur.id,
        "acheteur_username": acheteur.username or acheteur.first_name,
        "jeu": annonce["jeu"],
        "titre": annonce["titre"],
        "prix": annonce["prix"],
        "type_transaction": annonce["type_transaction"],
        "statut": "contact_demande",
        "date_demande": format_date(),
        "date_contact": None,
        "date_completion": None,
        "delai_anti_arnaque": delai,
        "confirmation_vendeur": False,
        "confirmation_acheteur": False,
        "note_acheteur": None,
        "note_vendeur": None,
        "avis_acheteur": None,
        "avis_vendeur": None,
        "reponse_avis_vendeur": None,
        "reponse_avis_acheteur": None,
    }

    save_transaction(trx_id, trx)
    update_stat("total_transactions")
    add_log("TRX_DEMANDEE", f"{trx_id} — {ann_id}", acheteur.id)

    # Incrémenter contacts sur l'annonce
    annonce["contacts"] = annonce.get("contacts", 0) + 1
    save_annonce(ann_id, annonce)

    # Notifier le vendeur après délai anti-arnaque
    await notify_vendeur_contact(bot, trx_id, trx, delai)

    await query.message.reply_text(
        f"✅ *Demande envoyée !*\n\n"
        f"🎫 Transaction : *{trx_id}*\n\n"
        f"⏱️ Le vendeur sera notifié dans *{delai} minutes*.\n"
        f"Tu seras contacté dès qu'il accepte.",
        parse_mode="Markdown"
    )

async def notify_vendeur_contact(bot, trx_id: str, trx: dict, delai: int):
    """Notifie le vendeur d'une demande de contact."""
    import asyncio
    await asyncio.sleep(delai * 60)

    # Vérifier que la transaction est toujours valide
    trx_actuelle = get_transaction(trx_id)
    if not trx_actuelle or trx_actuelle.get("statut") != "contact_demande":
        return

    kb = [
        [
            InlineKeyboardButton("✅ Accepter le contact", callback_data=f"trx_accepter_{trx_id}"),
            InlineKeyboardButton("❌ Refuser", callback_data=f"trx_refuser_{trx_id}")
        ]
    ]

    try:
        await bot.send_message(
            trx["vendeur_id"],
            f"🤝 *Nouvelle demande de contact !*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Acheteur : @{trx['acheteur_username']}\n"
            f"📝 Annonce : *{trx['titre']}*\n"
            f"💰 Prix : *{trx['prix']}*\n"
            f"🎫 Réf : *{trx_id}*\n\n"
            f"Veux-tu accepter ce contact ?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except: pass

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 3 — RÉPONSE DU VENDEUR
# ══════════════════════════════════════════════════════════════

async def accepter_contact(query, ctx, bot):
    """Vendeur accepte le contact."""
    trx_id = query.data.replace("trx_accepter_", "")
    trx = get_transaction(trx_id)

    if not trx or trx["vendeur_id"] != query.from_user.id:
        await query.message.reply_text("❌ Transaction introuvable.")
        return

    vendeur = get_user(trx["vendeur_id"])
    acheteur = get_user(trx["acheteur_id"])
    profil_vendeur = vendeur.get("profil", {})

    trx["statut"] = "contact_accepte"
    trx["date_contact"] = format_date()
    save_transaction(trx_id, trx)
    add_log("TRX_CONTACT_ACCEPTE", trx_id, query.from_user.id)

    # Partager les contacts
    tel_vendeur = ""
    if profil_vendeur.get("telephone") and profil_vendeur.get("telephone_public"):
        tel_vendeur = f"\n📱 Tél : `{profil_vendeur['telephone']}`"

    whatsapp = f"\n💬 WhatsApp : {profil_vendeur.get('whatsapp','')}" if profil_vendeur.get("whatsapp") else ""
    instagram = f"\n📸 Instagram : {profil_vendeur.get('instagram','')}" if profil_vendeur.get("instagram") else ""

    monnaies = ", ".join(profil_vendeur.get("monnaies_acceptees", [])[:3])
    methodes = ", ".join(profil_vendeur.get("methodes_paiement", [])[:3])

    msg_acheteur = (
        f"🎉 *Contact accepté !*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎫 Transaction : *{trx_id}*\n"
        f"📝 Annonce : *{trx['titre']}*\n\n"
        f"👤 *Infos Vendeur :*\n"
        f"Nom : @{trx['vendeur_username']}{tel_vendeur}{whatsapp}{instagram}\n"
        f"💰 Monnaies acceptées : {monnaies or 'Non précisé'}\n"
        f"💳 Méthodes : {methodes or 'Non précisé'}\n\n"
        f"⚠️ *Rappel :*\n"
        f"La transaction se fait directement entre vous.\n"
        f"Le bot n'est pas responsable.\n\n"
        f"Une fois la transaction terminée,\n"
        f"confirme-le ici :"
    )

    kb_acheteur = [[InlineKeyboardButton(
        "✅ Confirmer transaction effectuée",
        callback_data=f"trx_confirmer_acheteur_{trx_id}"
    )]]

    try:
        await bot.send_message(
            trx["acheteur_id"],
            msg_acheteur,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb_acheteur)
        )
    except: pass

    # Notifier le vendeur
    kb_vendeur = [[InlineKeyboardButton(
        "✅ Confirmer transaction effectuée",
        callback_data=f"trx_confirmer_vendeur_{trx_id}"
    )]]

    await query.message.reply_text(
        f"✅ *Contact partagé avec l'acheteur !*\n\n"
        f"🎫 *{trx_id}*\n\n"
        f"Une fois la transaction terminée,\n"
        f"confirme-le ici :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_vendeur)
    )

async def refuser_contact(query, ctx, bot):
    """Vendeur refuse le contact."""
    trx_id = query.data.replace("trx_refuser_", "")
    trx = get_transaction(trx_id)

    if not trx:
        await query.message.reply_text("❌ Transaction introuvable.")
        return

    trx["statut"] = "contact_refuse"
    save_transaction(trx_id, trx)
    add_log("TRX_CONTACT_REFUSE", trx_id, query.from_user.id)

    try:
        await bot.send_message(
            trx["acheteur_id"],
            f"❌ *Contact refusé*\n\n"
            f"Le vendeur a refusé ta demande pour\n"
            f"l'annonce *{trx['titre']}*.\n\n"
            f"Cherche d'autres annonces similaires.",
            parse_mode="Markdown"
        )
    except: pass

    await query.message.reply_text("✅ Demande refusée.")

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 4 — CONFIRMATION DES DEUX PARTIES
# ══════════════════════════════════════════════════════════════

async def confirmer_transaction_acheteur(query, ctx, bot):
    """Acheteur confirme que la transaction est effectuée."""
    trx_id = query.data.replace("trx_confirmer_acheteur_", "")
    trx = get_transaction(trx_id)

    if not trx:
        await query.message.reply_text("❌ Transaction introuvable.")
        return

    trx["confirmation_acheteur"] = True
    trx["statut"] = "confirmee_acheteur"
    save_transaction(trx_id, trx)

    if trx.get("confirmation_vendeur"):
        await finaliser_transaction(trx_id, trx, bot)
    else:
        await query.message.reply_text(
            "✅ Ta confirmation est enregistrée !\n"
            "En attente de confirmation du vendeur."
        )
        try:
            await bot.send_message(
                trx["vendeur_id"],
                f"📬 *L'acheteur a confirmé la transaction {trx_id}.*\n\n"
                f"Confirme toi aussi pour finaliser !",
                parse_mode="Markdown"
            )
        except: pass

async def confirmer_transaction_vendeur(query, ctx, bot):
    """Vendeur confirme que la transaction est effectuée."""
    trx_id = query.data.replace("trx_confirmer_vendeur_", "")
    trx = get_transaction(trx_id)

    if not trx:
        await query.message.reply_text("❌ Transaction introuvable.")
        return

    trx["confirmation_vendeur"] = True
    trx["statut"] = "confirmee_vendeur"
    save_transaction(trx_id, trx)

    if trx.get("confirmation_acheteur"):
        await finaliser_transaction(trx_id, trx, bot)
    else:
        await query.message.reply_text(
            "✅ Ta confirmation est enregistrée !\n"
            "En attente de confirmation de l'acheteur."
        )
        try:
            await bot.send_message(
                trx["acheteur_id"],
                f"📬 *Le vendeur a confirmé la transaction {trx_id}.*\n\n"
                f"Confirme toi aussi pour finaliser !",
                parse_mode="Markdown"
            )
        except: pass

async def finaliser_transaction(trx_id: str, trx: dict, bot):
    """Les deux parties ont confirmé — finalise la transaction."""
    trx["statut"] = "completee"
    trx["date_completion"] = format_date()
    save_transaction(trx_id, trx)

    # Marquer l'annonce comme vendue
    annonce = get_annonce(trx["ann_id"])
    if annonce:
        annonce["statut"] = "vendue"
        annonce["acheteur_id"] = trx["acheteur_id"]
        save_annonce(trx["ann_id"], annonce)

    # Mettre à jour stats
    vendeur = get_user(trx["vendeur_id"])
    acheteur_user = get_user(trx["acheteur_id"])

    if trx.get("type_transaction") == "vente":
        vendeur["stats"]["ventes"] = vendeur["stats"].get("ventes", 0) + 1
        acheteur_user["stats"]["achats"] = acheteur_user["stats"].get("achats", 0) + 1
    else:
        vendeur["stats"]["echanges"] = vendeur["stats"].get("echanges", 0) + 1
        acheteur_user["stats"]["echanges"] = acheteur_user["stats"].get("echanges", 0) + 1

    save_user(trx["vendeur_id"], vendeur)
    save_user(trx["acheteur_id"], acheteur_user)
    add_log("TRX_COMPLETEE", trx_id, 0)

    # Demander les notes
    kb_note = [[
        InlineKeyboardButton("⭐1", callback_data=f"note_{trx_id}_1"),
        InlineKeyboardButton("⭐2", callback_data=f"note_{trx_id}_2"),
        InlineKeyboardButton("⭐3", callback_data=f"note_{trx_id}_3"),
        InlineKeyboardButton("⭐4", callback_data=f"note_{trx_id}_4"),
        InlineKeyboardButton("⭐5", callback_data=f"note_{trx_id}_5"),
    ]]

    for user_id, role in [(trx["vendeur_id"], "acheteur"), (trx["acheteur_id"], "vendeur")]:
        try:
            await bot.send_message(
                user_id,
                f"🎉 *Transaction {trx_id} complétée !*\n\n"
                f"Note ton expérience avec {'l' + chr(39) + role} :\n"
                f"_(1 = très mauvais, 5 = excellent)_",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_note)
            )
        except: pass

# ══════════════════════════════════════════════════════════════
#  HISTORIQUE DES TRANSACTIONS
# ══════════════════════════════════════════════════════════════

async def show_historique(message, user_id: int):
    """Affiche l'historique des transactions d'un utilisateur."""
    transactions = get_transactions_user(user_id)

    if not transactions:
        await message.reply_text(
            "📊 *Mon historique*\n\nAucune transaction pour le moment.",
            parse_mode="Markdown"
        )
        return

    msg = f"📊 *Mon historique* ({len(transactions)} transactions)\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for trx_id, trx in transactions[-10:]:
        statut = STATUTS_TRX.get(trx.get("statut",""), "?")
        role = "Vendeur" if trx.get("vendeur_id") == user_id else "Acheteur"
        msg += (
            f"🎫 *{trx_id}* — {role}\n"
            f"📝 {trx.get('titre','?')[:30]}\n"
            f"💰 {trx.get('prix','?')}\n"
            f"{statut}\n"
            f"📅 {trx.get('date_demande','?')}\n\n"
        )

    kb = [[InlineKeyboardButton("📄 Exporter en PDF", callback_data=f"export_historique_{user_id}")]]
    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

async def exporter_historique_pdf(message, user_id: int, bot, is_admin: bool = False):
    """Génère et envoie un PDF de l'historique."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        import io

        transactions = get_transactions_user(user_id)
        user = get_user(user_id)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(f"Historique Transactions — {user_id}", styles['Title']))
        story.append(Paragraph(f"Généré le : {format_date()}", styles['Normal']))
        story.append(Spacer(1, 20))

        data = [["Réf", "Titre", "Prix", "Rôle", "Statut", "Date"]]
        for trx_id, trx in transactions:
            role = "Vendeur" if trx.get("vendeur_id") == user_id else "Acheteur"
            data.append([
                trx_id,
                trx.get("titre","?")[:25],
                trx.get("prix","?"),
                role,
                trx.get("statut","?"),
                trx.get("date_demande","?")
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        story.append(table)
        doc.build(story)
        buffer.seek(0)
        buffer.name = f"historique_{user_id}_{datetime.date.today()}.pdf"

        await message.reply_document(
            document=buffer,
            caption=f"📄 Historique transactions — {len(transactions)} entrées"
        )
    except ImportError:
        await message.reply_text(
            "⚠️ PDF non disponible sur ce serveur.\n"
            "Installe reportlab : `pip install reportlab`",
            parse_mode="Markdown"
        )

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_transactions_callbacks(query, ctx, bot, super_admin_id: int) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data.startswith("interesse_"):
        await exprimer_interet(query, ctx, bot, super_admin_id)
        return True

    if data.startswith("trx_confirmer_") and not data.startswith("trx_confirmer_acheteur_") and not data.startswith("trx_confirmer_vendeur_"):
        await confirmer_interet(query, ctx, bot)
        return True

    if data == "trx_annuler":
        await msg.reply_text("❌ Demande annulée.")
        return True

    if data.startswith("trx_accepter_"):
        await accepter_contact(query, ctx, bot)
        return True

    if data.startswith("trx_refuser_"):
        await refuser_contact(query, ctx, bot)
        return True

    if data.startswith("trx_confirmer_acheteur_"):
        await confirmer_transaction_acheteur(query, ctx, bot)
        return True

    if data.startswith("trx_confirmer_vendeur_"):
        await confirmer_transaction_vendeur(query, ctx, bot)
        return True

    if data == "menu_historique":
        await show_historique(msg, uid)
        return True

    if data.startswith("export_historique_"):
        target_id = int(data.replace("export_historique_", ""))
        is_admin = target_id != uid
        await exporter_historique_pdf(msg, target_id, bot, is_admin)
        return True

    if data.startswith("note_"):
        parts = data.split("_")
        trx_id = f"{parts[1]}_{parts[2]}" if len(parts) > 3 else parts[1]
        note = int(parts[-1])
        from reputation import enregistrer_note
        await enregistrer_note(query, ctx, bot, trx_id, note, uid)
        return True

    return False
