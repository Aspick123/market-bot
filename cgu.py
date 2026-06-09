"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 9 — CGU.PY                               ║
║  • CGU commune + clauses vendeur                             ║
║  • Acceptation obligatoire à chaque transaction              ║
║  • Re-acceptation si CGU modifiées                           ║
║  • Traçabilité exportable PDF                                ║
║  • Modification via panel admin                              ║
╚══════════════════════════════════════════════════════════════╝
"""

import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, get_user, save_user,
    get_cgu, save_cgu, user_a_accepte_cgu,
    enregistrer_acceptation_cgu, format_date
)

# ══════════════════════════════════════════════════════════════
#  AFFICHAGE CGU
# ══════════════════════════════════════════════════════════════

async def show_cgu(message, type_cgu: str = "commune", callback_apres: str = None):
    """Affiche les CGU avec bouton d'acceptation."""
    cgu = get_cgu()
    version = cgu.get("version", "1.0")
    texte = cgu.get("commune", "")
    if type_cgu == "vendeur":
        texte += cgu.get("vendeur", "")

    titre = "📋 Conditions Générales d'Utilisation"
    if type_cgu == "vendeur":
        titre += " — Vendeur"

    # Découper si trop long
    if len(texte) > 3500:
        texte = texte[:3500] + "\n\n_... (suite)_"

    cb_accepter = f"cgu_accepter_{type_cgu}"
    if callback_apres:
        cb_accepter += f"_{callback_apres}"

    kb = [
        [InlineKeyboardButton("✅ J'accepte les CGU", callback_data=cb_accepter)],
        [InlineKeyboardButton("❌ Je refuse", callback_data="cgu_refuser")],
    ]

    await message.reply_text(
        f"{titre}\n"
        f"Version : *{version}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{texte}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def user_a_accepte_cgu_acheteur(message, user_id: int, ctx) -> bool:
    """Vérifie si l'utilisateur a accepté les CGU. Sinon les affiche."""
    if user_a_accepte_cgu(user_id):
        return True

    ctx.user_data["cgu_callback_apres"] = "acheteur"
    await show_cgu(message, "commune", "acheteur")
    return False

async def user_a_accepte_cgu_vendeur(message, user_id: int, ctx) -> bool:
    """Vérifie si le vendeur a accepté les CGU vendeur."""
    cgu = get_cgu()
    user = get_user(user_id)
    if (user.get("cgu_acceptee") and
        user.get("cgu_version_acceptee") == cgu.get("version")):
        return True

    ctx.user_data["cgu_callback_apres"] = "vendeur"
    await show_cgu(message, "vendeur", "vendeur")
    return False

# ══════════════════════════════════════════════════════════════
#  ACCEPTATION / REFUS
# ══════════════════════════════════════════════════════════════

async def accepter_cgu(query, ctx, bot):
    """Traite l'acceptation des CGU."""
    parts = query.data.replace("cgu_accepter_", "").split("_")
    type_cgu = parts[0]
    callback_apres = parts[1] if len(parts) > 1 else None

    uid = query.from_user.id
    enregistrer_acceptation_cgu(uid, type_cgu)

    await query.message.reply_text(
        "✅ *CGU acceptées !*\n\nMerci. Tu peux continuer.",
        parse_mode="Markdown"
    )

    # Reprendre l'action interrompue
    if callback_apres == "acheteur":
        await query.message.reply_text(
            "💡 Tu peux maintenant exprimer ton intérêt\n"
            "pour l'annonce. Retourne sur l'annonce."
        )
    elif callback_apres == "vendeur":
        await query.message.reply_text(
            "💡 Tu peux maintenant créer ton annonce.\n"
            "Tape /vendre pour commencer."
        )

async def refuser_cgu(query):
    """Traite le refus des CGU."""
    await query.message.reply_text(
        "⚠️ *CGU refusées*\n\n"
        "Tu peux consulter les annonces mais\n"
        "tu ne peux pas effectuer de transactions\n"
        "tant que tu n'as pas accepté les CGU.\n\n"
        "Tape /cgu pour les consulter à nouveau.",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════
#  VÉRIFICATION RE-ACCEPTATION
# ══════════════════════════════════════════════════════════════

async def verifier_reacceptation(message, user_id: int, ctx) -> bool:
    """Vérifie si l'utilisateur doit re-accepter les CGU (version changée)."""
    cgu = get_cgu()
    user = get_user(user_id)

    if user.get("cgu_version_acceptee") != cgu.get("version"):
        ctx.user_data["cgu_callback_apres"] = "renouvellement"
        await message.reply_text(
            "📋 *Les CGU ont été mises à jour !*\n\n"
            f"Nouvelle version : *{cgu.get('version')}*\n\n"
            "Tu dois re-accepter les nouvelles CGU\n"
            "pour continuer à utiliser le marketplace.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Lire et accepter", callback_data="cgu_relire")
            ]])
        )
        return False
    return True

# ══════════════════════════════════════════════════════════════
#  ADMIN — MODIFIER LES CGU
# ══════════════════════════════════════════════════════════════

async def show_cgu_admin_menu(message):
    cgu = get_cgu()
    kb = [
        [InlineKeyboardButton("✏️ Modifier CGU commune", callback_data="cgu_adm_edit_commune")],
        [InlineKeyboardButton("✏️ Modifier clauses vendeur", callback_data="cgu_adm_edit_vendeur")],
        [InlineKeyboardButton("📊 Incrementer version", callback_data="cgu_adm_version")],
        [InlineKeyboardButton("📋 Voir CGU actuelle", callback_data="cgu_adm_voir")],
        [InlineKeyboardButton("📄 Exporter acceptations", callback_data="cgu_adm_exporter")],
        [InlineKeyboardButton("🔙 Retour admin", callback_data="adm_market_panel")],
    ]
    await message.reply_text(
        f"📋 *Gestion CGU*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Version actuelle : *{cgu.get('version','1.0')}*\n"
        f"Dernière modif : {cgu.get('modifiee_le','?')}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def incrementer_version_cgu(query, ctx, bot):
    """Incrémente la version des CGU et force re-acceptation."""
    cgu = get_cgu()
    try:
        version_parts = cgu.get("version","1.0").split(".")
        version_parts[-1] = str(int(version_parts[-1]) + 1)
        nouvelle_version = ".".join(version_parts)
    except:
        nouvelle_version = "1.1"

    cgu["version"] = nouvelle_version
    cgu["modifiee_le"] = format_date()
    save_cgu(cgu)

    # Notifier tous les utilisateurs
    users = mdb_read("users.json")
    notifies = 0
    for uid_str, u in users.items():
        try:
            await bot.send_message(
                int(uid_str),
                f"📋 *Les CGU ont été mises à jour !*\n\n"
                f"Nouvelle version : *{nouvelle_version}*\n\n"
                f"Tu devras les re-accepter lors\n"
                f"de ta prochaine transaction.",
                parse_mode="Markdown"
            )
            notifies += 1
        except: pass

    await query.message.reply_text(
        f"✅ Version CGU → *{nouvelle_version}*\n"
        f"{notifies} utilisateurs notifiés.",
        parse_mode="Markdown"
    )

async def exporter_acceptations_pdf(message, bot):
    """Exporte toutes les acceptations CGU en PDF."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        import io

        acceptations = mdb_read("cgu_acceptations.json")
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("Registre des Acceptations CGU", styles['Title']))
        story.append(Paragraph(f"Généré le : {format_date()}", styles['Normal']))
        story.append(Spacer(1, 20))

        data = [["User ID", "Type", "Version", "Date", "Timestamp"]]
        for acc in acceptations:
            data.append([
                str(acc.get("user_id","")),
                acc.get("type",""),
                acc.get("version",""),
                acc.get("date",""),
                acc.get("timestamp","")[:19]
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        story.append(table)
        doc.build(story)
        buffer.seek(0)
        buffer.name = f"cgu_acceptations_{datetime.date.today()}.pdf"

        await message.reply_document(
            document=buffer,
            caption=f"📄 Acceptations CGU — {len(acceptations)} entrées (preuve juridique)"
        )
    except ImportError:
        await message.reply_text(
            "⚠️ Installe reportlab : `pip install reportlab`",
            parse_mode="Markdown"
        )

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_cgu_callbacks(query, ctx, bot, super_admin_id: int) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data == "menu_cgu" or data == "cgu_relire":
        user = get_user(uid)
        type_cgu = "vendeur" if user.get("est_vendeur") else "commune"
        await show_cgu(msg, type_cgu)
        return True

    if data.startswith("cgu_accepter_"):
        await accepter_cgu(query, ctx, bot)
        return True

    if data == "cgu_refuser":
        await refuser_cgu(query)
        return True

    if data == "adm_cgu":
        await show_cgu_admin_menu(msg)
        return True

    if data == "cgu_adm_voir":
        await show_cgu(msg, "commune")
        return True

    if data == "cgu_adm_edit_commune":
        ctx.user_data["cgu_adm_state"] = "edit_commune"
        cgu = get_cgu()
        await msg.reply_text(
            f"✏️ *Modifier CGU commune*\n\n"
            f"Envoie le nouveau texte :\n"
            f"_(actuel : {len(cgu.get('commune',''))} caractères)_",
            parse_mode="Markdown"
        )
        return True

    if data == "cgu_adm_edit_vendeur":
        ctx.user_data["cgu_adm_state"] = "edit_vendeur"
        await msg.reply_text("✏️ Envoie le nouveau texte des clauses vendeur :")
        return True

    if data == "cgu_adm_version":
        await incrementer_version_cgu(query, ctx, bot)
        return True

    if data == "cgu_adm_exporter":
        await exporter_acceptations_pdf(msg, bot)
        return True

    return False

async def handle_cgu_input(update, ctx) -> bool:
    state = ctx.user_data.get("cgu_adm_state")
    if not state:
        return False

    text = update.message.text.strip() if update.message and update.message.text else ""
    cgu = get_cgu()

    if state == "edit_commune":
        cgu["commune"] = text
        cgu["modifiee_le"] = format_date()
        save_cgu(cgu)
        await update.message.reply_text("✅ CGU commune mise à jour !")
        ctx.user_data.pop("cgu_adm_state", None)
        return True

    if state == "edit_vendeur":
        cgu["vendeur"] = text
        cgu["modifiee_le"] = format_date()
        save_cgu(cgu)
        await update.message.reply_text("✅ Clauses vendeur mises à jour !")
        ctx.user_data.pop("cgu_adm_state", None)
        return True

    return False
