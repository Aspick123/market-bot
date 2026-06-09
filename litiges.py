"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 5 — LITIGES.PY                           ║
║  • Ouverture de litige avec preuves                          ║
║  • Notification équipe de modération                         ║
║  • Gestion des statuts                                       ║
║  • Sanctions (avertissement/suspension/ban)                  ║
║  • Historique des litiges                                    ║
╚══════════════════════════════════════════════════════════════╝
"""

import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, get_user, save_user,
    get_transaction, save_transaction,
    get_litige, save_litige, next_litige_id,
    get_litiges_en_cours, add_log, update_stat,
    add_to_blacklist, format_date,
    get_team_ids_by_role, has_perm, ROLES_EQUIPE
)

CATEGORIES_LITIGE = [
    ("non_livraison",   "📦 Article non livré"),
    ("arnaque",         "🚨 Arnaque / Fraude"),
    ("fausse_annonce",  "📋 Fausse description"),
    ("compte_vole",     "🔐 Compte volé/piraté"),
    ("paiement",        "💰 Problème de paiement"),
    ("autre",           "❓ Autre problème"),
]

STATUTS_LITIGE = {
    "ouvert":       "🟡 Ouvert",
    "en_cours":     "🔵 En cours d'examen",
    "resolu":       "✅ Résolu",
    "ferme":        "🔴 Fermé sans suite",
    "sanctionne":   "⚖️ Sanction appliquée",
}

SANCTIONS = [
    ("avertissement",  "⚠️ Avertissement"),
    ("suspension_7",   "🔴 Suspension 7 jours"),
    ("suspension_30",  "🔴 Suspension 30 jours"),
    ("ban",            "🚫 Ban définitif"),
    ("aucune",         "✅ Aucune sanction"),
]

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 1 — OUVRIR UN LITIGE
# ══════════════════════════════════════════════════════════════

async def start_litige(message, user_id: int, ctx):
    """Lance le processus d'ouverture de litige."""
    transactions = get_user(user_id)

    kb = [[InlineKeyboardButton(label, callback_data=f"lit_cat_{key}")]
          for key, label in CATEGORIES_LITIGE]
    kb.append([InlineKeyboardButton("❌ Annuler", callback_data="lit_annuler")])

    await message.reply_text(
        "⚖️ *Ouvrir un litige*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ *Avant tout :*\n"
        "Essaie d'abord de régler le problème\n"
        "directement avec l'autre partie.\n\n"
        "Si ça ne marche pas, choisis la catégorie :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 2 — RÉFÉRENCE TRANSACTION
# ══════════════════════════════════════════════════════════════

async def ask_transaction_ref(message, categorie: str):
    await message.reply_text(
        f"⚖️ *{dict(CATEGORIES_LITIGE).get(categorie, categorie)}*\n\n"
        f"Indique la référence de la transaction concernée :\n"
        f"_(ex: TRX0001)_\n\n"
        f"Ou tape *AUCUNE* si pas de transaction.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data="lit_annuler")
        ]])
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 3 — DESCRIPTION DU PROBLÈME
# ══════════════════════════════════════════════════════════════

async def ask_description_litige(message):
    await message.reply_text(
        "📋 *Décris ton problème en détail*\n\n"
        "💡 *Précise :*\n"
        "• Ce qui s'est passé exactement\n"
        "• Les dates et montants\n"
        "• Ce que tu as perdu\n"
        "• Les tentatives de résolution\n\n"
        "Tape ta description :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data="lit_annuler")
        ]])
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 4 — PREUVES (SCREENSHOTS)
# ══════════════════════════════════════════════════════════════

async def ask_preuves(message):
    await message.reply_text(
        "📸 *Preuves (obligatoires)*\n\n"
        "Envoie des screenshots comme preuves :\n"
        "• Conversations avec le vendeur/acheteur\n"
        "• Reçus de paiement\n"
        "• Screenshots du compte/article\n\n"
        "Envoie jusqu'à *5 photos*, puis appuie sur\n"
        "*'Preuves envoyées'*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Preuves envoyées", callback_data="lit_preuves_ok"),
            InlineKeyboardButton("❌ Annuler", callback_data="lit_annuler")
        ]])
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 5 — CONFIRMATION
# ══════════════════════════════════════════════════════════════

async def confirm_litige(message, ctx):
    d = ctx.user_data.get("lit_data", {})
    cat_label = dict(CATEGORIES_LITIGE).get(d.get("categorie",""), "?")
    nb_preuves = len(d.get("preuves", []))

    kb = [
        [
            InlineKeyboardButton("✅ Soumettre le litige", callback_data="lit_soumettre"),
            InlineKeyboardButton("🔄 Recommencer", callback_data="lit_recommencer")
        ],
        [InlineKeyboardButton("❌ Annuler", callback_data="lit_annuler")]
    ]

    await message.reply_text(
        f"⚖️ *Récapitulatif du litige*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📂 Catégorie : *{cat_label}*\n"
        f"🎫 Transaction : *{d.get('trx_ref', 'Aucune')}*\n"
        f"📸 Preuves : *{nb_preuves}*\n\n"
        f"📋 *Description :*\n_{d.get('description','?')}_\n\n"
        f"Soumettre ce litige ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  SOUMISSION DU LITIGE
# ══════════════════════════════════════════════════════════════

async def soumettre_litige(message, ctx, user, bot, super_admin_id: int):
    d = ctx.user_data.get("lit_data", {})
    lit_id = next_litige_id()

    # Trouver l'autre partie
    autre_id = None
    trx_ref = d.get("trx_ref", "AUCUNE")
    if trx_ref != "AUCUNE":
        trx = get_transaction(trx_ref)
        if trx:
            autre_id = trx["acheteur_id"] if trx["vendeur_id"] == user.id else trx["vendeur_id"]
            # Marquer la transaction en litige
            trx["statut"] = "litige"
            save_transaction(trx_ref, trx)

    litige = {
        "id": lit_id,
        "plaignant_id": user.id,
        "plaignant_username": user.username or user.first_name,
        "mis_en_cause_id": autre_id,
        "trx_ref": trx_ref,
        "categorie": d.get("categorie"),
        "description": d.get("description"),
        "preuves": d.get("preuves", []),
        "statut": "ouvert",
        "date_ouverture": format_date(),
        "date_cloture": None,
        "assigne_a": None,
        "resolution": None,
        "sanction": None,
        "notes_equipe": [],
    }

    save_litige(lit_id, litige)
    update_stat("total_litiges")
    add_log("LITIGE_OUVERT", f"{lit_id} par {user.id}", user.id)

    # Mettre à jour stats utilisateur
    user_data = get_user(user.id)
    user_data["stats"]["litiges_ouverts"] = user_data["stats"].get("litiges_ouverts", 0) + 1
    save_user(user.id, user_data)

    # Notifier l'équipe
    await notifier_equipe_litige(bot, lit_id, litige, super_admin_id)

    await message.reply_text(
        f"✅ *Litige soumis !*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎫 Référence : *{lit_id}*\n\n"
        f"Notre équipe va examiner ton dossier\n"
        f"et te répondre dans les plus brefs délais.\n\n"
        f"💡 Garde toutes tes preuves disponibles.",
        parse_mode="Markdown"
    )

    ctx.user_data.pop("lit_state", None)
    ctx.user_data.pop("lit_data", None)

async def notifier_equipe_litige(bot, lit_id: str, litige: dict, super_admin_id: int):
    cat_label = dict(CATEGORIES_LITIGE).get(litige.get("categorie",""), "?")
    msg = (
        f"⚖️ *Nouveau litige — {lit_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Plaignant : @{litige['plaignant_username']} (`{litige['plaignant_id']}`)\n"
        f"🎫 Transaction : {litige.get('trx_ref','Aucune')}\n"
        f"📂 Catégorie : {cat_label}\n"
        f"📸 Preuves : {len(litige.get('preuves',[]))}\n\n"
        f"📋 _{litige['description'][:200]}_"
    )

    kb = [
        [InlineKeyboardButton("🔵 Prendre en charge", callback_data=f"lit_prendre_{lit_id}")],
        [InlineKeyboardButton("👤 Voir plaignant", callback_data=f"voir_profil_{litige['plaignant_id']}")],
    ]
    if litige.get("mis_en_cause_id"):
        kb.append([InlineKeyboardButton("👤 Voir mis en cause",
                   callback_data=f"voir_profil_{litige['mis_en_cause_id']}")])

    for dest_id in [super_admin_id] + get_team_ids_by_role("mod_litiges"):
        try:
            await bot.send_message(dest_id, msg, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))
            for photo_id in litige.get("preuves", [])[:5]:
                try:
                    await bot.send_photo(dest_id, photo_id, caption=f"📸 Preuve {lit_id}")
                except: pass
        except: pass

# ══════════════════════════════════════════════════════════════
#  GESTION ÉQUIPE — TRAITEMENT DES LITIGES
# ══════════════════════════════════════════════════════════════

async def prendre_en_charge_litige(query, ctx, bot):
    lit_id = query.data.replace("lit_prendre_", "")
    litige = get_litige(lit_id)
    if not litige:
        await query.message.reply_text("❌ Litige introuvable.")
        return

    litige["statut"] = "en_cours"
    litige["assigne_a"] = query.from_user.id
    litige["date_prise_en_charge"] = format_date()
    save_litige(lit_id, litige)
    add_log("LITIGE_PRIS_EN_CHARGE", lit_id, query.from_user.id)

    # Notifier le plaignant
    try:
        await bot.send_message(
            litige["plaignant_id"],
            f"🔵 *Ton litige {lit_id} est pris en charge !*\n\n"
            f"Un membre de notre équipe examine ton dossier.\n"
            f"Tu seras contacté prochainement.",
            parse_mode="Markdown"
        )
    except: pass

    kb = [
        [InlineKeyboardButton("✅ Résoudre en faveur du plaignant",
                              callback_data=f"lit_resoudre_plaignant_{lit_id}")],
        [InlineKeyboardButton("❌ Résoudre en faveur du mis en cause",
                              callback_data=f"lit_resoudre_cause_{lit_id}")],
        [InlineKeyboardButton("⚖️ Appliquer une sanction",
                              callback_data=f"lit_sanctionner_{lit_id}")],
        [InlineKeyboardButton("🔴 Fermer sans suite",
                              callback_data=f"lit_fermer_{lit_id}")],
    ]

    await query.message.reply_text(
        f"✅ *Litige {lit_id} assigné à toi*\n\n"
        f"Examine les preuves et choisis une action :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def resoudre_litige(query, ctx, bot, faveur: str):
    parts = query.data.split("_")
    lit_id = parts[-1]
    litige = get_litige(lit_id)
    if not litige:
        await query.message.reply_text("❌ Litige introuvable.")
        return

    ctx.user_data["lit_resolution_state"] = "resolution"
    ctx.user_data["lit_resolution_data"] = {"lit_id": lit_id, "faveur": faveur}

    faveur_label = "plaignant" if faveur == "plaignant" else "mis en cause"
    await query.message.reply_text(
        f"⚖️ *Résolution en faveur du {faveur_label}*\n\n"
        f"Écris le message de résolution\n"
        f"(sera envoyé aux deux parties) :",
        parse_mode="Markdown"
    )

async def finaliser_resolution(message, ctx, bot, lit_id: str, faveur: str, resolution_text: str):
    litige = get_litige(lit_id)
    if not litige:
        return

    litige["statut"] = "resolu"
    litige["resolution"] = resolution_text
    litige["faveur"] = faveur
    litige["date_cloture"] = format_date()
    save_litige(lit_id, litige)
    add_log("LITIGE_RESOLU", f"{lit_id} — faveur: {faveur}", message.from_user.id)

    # Mettre à jour stats
    user_data = get_user(litige["plaignant_id"])
    user_data["stats"]["litiges_resolus"] = user_data["stats"].get("litiges_resolus", 0) + 1
    save_user(litige["plaignant_id"], user_data)

    faveur_label = "en ta faveur ✅" if faveur == "plaignant" else "en faveur de l'autre partie"
    msg_plaignant = (
        f"⚖️ *Litige {lit_id} résolu*\n\n"
        f"Décision : *{faveur_label}*\n\n"
        f"📋 *Résolution :*\n_{resolution_text}_"
    )

    for dest_id in [litige["plaignant_id"], litige.get("mis_en_cause_id")]:
        if dest_id:
            try:
                await bot.send_message(dest_id, msg_plaignant, parse_mode="Markdown")
            except: pass

    await message.reply_text(f"✅ Litige *{lit_id}* résolu !", parse_mode="Markdown")

async def sanctionner_user(query, ctx):
    lit_id = query.data.replace("lit_sanctionner_", "")
    litige = get_litige(lit_id)
    if not litige:
        await query.message.reply_text("❌ Litige introuvable.")
        return

    ctx.user_data["lit_sanction_data"] = {"lit_id": lit_id}

    # Choisir qui sanctionner
    kb = []
    if litige.get("plaignant_id"):
        kb.append([InlineKeyboardButton(
            f"👤 Plaignant (@{litige['plaignant_username']})",
            callback_data=f"lit_sanc_cible_{lit_id}_plaignant"
        )])
    if litige.get("mis_en_cause_id"):
        kb.append([InlineKeyboardButton(
            f"👤 Mis en cause",
            callback_data=f"lit_sanc_cible_{lit_id}_cause"
        )])

    await query.message.reply_text(
        "⚖️ *Qui sanctionner ?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def choisir_sanction(query, ctx, bot, super_admin_id: int):
    parts = query.data.replace("lit_sanc_cible_", "").rsplit("_", 1)
    lit_id = parts[0]
    cible = parts[1]
    litige = get_litige(lit_id)

    ctx.user_data["lit_sanction_data"] = {"lit_id": lit_id, "cible": cible}

    kb = [[InlineKeyboardButton(label, callback_data=f"lit_sanc_appliquer_{lit_id}_{cible}_{key}")]
          for key, label in SANCTIONS]

    await query.message.reply_text(
        "⚖️ *Choisir la sanction :*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def appliquer_sanction(query, ctx, bot, super_admin_id: int):
    parts = query.data.replace("lit_sanc_appliquer_", "").split("_")
    lit_id = parts[0]
    cible = parts[1]
    sanction = "_".join(parts[2:])

    litige = get_litige(lit_id)
    if not litige:
        await query.message.reply_text("❌ Litige introuvable.")
        return

    target_id = litige["plaignant_id"] if cible == "plaignant" else litige.get("mis_en_cause_id")
    sanction_label = dict(SANCTIONS).get(sanction, sanction)

    if target_id:
        user_data = get_user(target_id)
        if sanction == "avertissement":
            user_data["avertissements"] = user_data.get("avertissements", 0) + 1
        elif sanction.startswith("suspension"):
            user_data["suspendu"] = True
            jours = int(sanction.split("_")[1])
            user_data["suspension_fin"] = (
                datetime.datetime.now() + datetime.timedelta(days=jours)
            ).strftime("%d/%m/%Y")
        elif sanction == "ban":
            add_to_blacklist(target_id, f"Litige {lit_id}", query.from_user.id)

        save_user(target_id, user_data)

        try:
            await bot.send_message(
                target_id,
                f"⚖️ *Sanction appliquée*\n\n"
                f"Suite au litige *{lit_id}* :\n"
                f"Sanction : *{sanction_label}*\n\n"
                f"Respecte les règles de la plateforme.",
                parse_mode="Markdown"
            )
        except: pass

    litige["statut"] = "sanctionne"
    litige["sanction"] = sanction
    litige["date_cloture"] = format_date()
    save_litige(lit_id, litige)
    add_log("SANCTION_APPLIQUEE", f"{lit_id} — {sanction} sur {target_id}", query.from_user.id)

    await query.message.reply_text(
        f"✅ Sanction *{sanction_label}* appliquée !", parse_mode="Markdown"
    )

async def fermer_litige(query, ctx, bot):
    lit_id = query.data.replace("lit_fermer_", "")
    litige = get_litige(lit_id)
    if not litige:
        await query.message.reply_text("❌ Litige introuvable.")
        return

    litige["statut"] = "ferme"
    litige["date_cloture"] = format_date()
    save_litige(lit_id, litige)
    add_log("LITIGE_FERME", lit_id, query.from_user.id)

    try:
        await bot.send_message(
            litige["plaignant_id"],
            f"🔴 *Litige {lit_id} fermé*\n\n"
            f"Notre équipe a examiné ton dossier et\n"
            f"a décidé de le clore sans suite.\n\n"
            f"Si tu penses que c'est une erreur,\n"
            f"contacte notre support.",
            parse_mode="Markdown"
        )
    except: pass

    await query.message.reply_text(f"🔴 Litige *{lit_id}* fermé.", parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  LISTE DES LITIGES (ADMIN)
# ══════════════════════════════════════════════════════════════

async def show_litiges_admin(message, filtre: str = "ouvert"):
    litiges = mdb_read("litiges.json")
    filtered = [(lid, l) for lid, l in litiges.items() if l.get("statut") == filtre]

    statut_label = STATUTS_LITIGE.get(filtre, filtre)
    kb_filtres = [[
        InlineKeyboardButton("🟡 Ouverts", callback_data="litiges_filtre_ouvert"),
        InlineKeyboardButton("🔵 En cours", callback_data="litiges_filtre_en_cours"),
        InlineKeyboardButton("✅ Résolus", callback_data="litiges_filtre_resolu"),
    ]]

    if not filtered:
        await message.reply_text(
            f"⚖️ *Litiges — {statut_label}*\n\nAucun litige dans cette catégorie.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb_filtres)
        )
        return

    msg = f"⚖️ *Litiges — {statut_label}* ({len(filtered)})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    kb = list(kb_filtres)
    for lid, l in filtered[-10:]:
        cat = dict(CATEGORIES_LITIGE).get(l.get("categorie",""), "?")
        msg += (
            f"🎫 *{lid}*\n"
            f"👤 @{l.get('plaignant_username','?')}\n"
            f"📂 {cat} | 📅 {l.get('date_ouverture','?')}\n\n"
        )
        kb.append([InlineKeyboardButton(
            f"⚖️ {lid}", callback_data=f"lit_prendre_{lid}"
        )])

    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_litiges_callbacks(query, ctx, user, bot, super_admin_id: int) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data == "menu_litige":
        await start_litige(msg, uid, ctx)
        return True

    if data.startswith("lit_cat_"):
        cat = data.replace("lit_cat_", "")
        ctx.user_data["lit_state"] = "trx_ref"
        ctx.user_data["lit_data"] = {"categorie": cat, "preuves": []}
        await ask_transaction_ref(msg, cat)
        return True

    if data == "lit_annuler":
        ctx.user_data.pop("lit_state", None)
        ctx.user_data.pop("lit_data", None)
        await msg.reply_text("❌ Litige annulé.")
        return True

    if data == "lit_preuves_ok":
        preuves = ctx.user_data.get("lit_data", {}).get("preuves", [])
        if not preuves:
            await msg.reply_text("⚠️ Envoie au moins 1 preuve.")
            return True
        ctx.user_data["lit_state"] = "confirmation"
        await confirm_litige(msg, ctx)
        return True

    if data == "lit_soumettre":
        await soumettre_litige(msg, ctx, user, bot, super_admin_id)
        return True

    if data == "lit_recommencer":
        ctx.user_data.pop("lit_state", None)
        ctx.user_data.pop("lit_data", None)
        await start_litige(msg, uid, ctx)
        return True

    if data.startswith("lit_prendre_"):
        await prendre_en_charge_litige(query, ctx, bot)
        return True

    if data.startswith("lit_resoudre_plaignant_"):
        await resoudre_litige(query, ctx, bot, "plaignant")
        return True

    if data.startswith("lit_resoudre_cause_"):
        await resoudre_litige(query, ctx, bot, "cause")
        return True

    if data.startswith("lit_sanctionner_"):
        await sanctionner_user(query, ctx)
        return True

    if data.startswith("lit_sanc_cible_"):
        await choisir_sanction(query, ctx, bot, super_admin_id)
        return True

    if data.startswith("lit_sanc_appliquer_"):
        await appliquer_sanction(query, ctx, bot, super_admin_id)
        return True

    if data.startswith("lit_fermer_"):
        await fermer_litige(query, ctx, bot)
        return True

    if data.startswith("litiges_filtre_"):
        filtre = data.replace("litiges_filtre_", "")
        await show_litiges_admin(msg, filtre)
        return True

    if data == "adm_litiges":
        await show_litiges_admin(msg, "ouvert")
        return True

    return False

# ══════════════════════════════════════════════════════════════
#  HANDLER MESSAGES TEXTE
# ══════════════════════════════════════════════════════════════

async def handle_litiges_input(update, ctx, user, bot, super_admin_id: int) -> bool:
    state = ctx.user_data.get("lit_state")
    text = update.message.text.strip() if update.message and update.message.text else ""
    d = ctx.user_data.get("lit_data", {})

    if state == "trx_ref":
        d["trx_ref"] = text.upper() if text.upper() != "AUCUNE" else "AUCUNE"
        ctx.user_data["lit_data"] = d
        ctx.user_data["lit_state"] = "description"
        await ask_description_litige(update.message)
        return True

    if state == "description":
        if len(text) < 30:
            await update.message.reply_text("⚠️ Description trop courte (min 30 caractères).")
            return True
        d["description"] = text
        ctx.user_data["lit_data"] = d
        ctx.user_data["lit_state"] = "preuves"
        await ask_preuves(update.message)
        return True

    # Résolution litige
    if ctx.user_data.get("lit_resolution_state") == "resolution":
        res_data = ctx.user_data.get("lit_resolution_data", {})
        await finaliser_resolution(
            update.message, ctx, bot,
            res_data["lit_id"], res_data["faveur"], text
        )
        ctx.user_data.pop("lit_resolution_state", None)
        ctx.user_data.pop("lit_resolution_data", None)
        return True

    return False

async def handle_litiges_photos(update, ctx) -> bool:
    """Gère les photos de preuves pour un litige."""
    state = ctx.user_data.get("lit_state")
    if state != "preuves":
        return False
    if not update.message.photo:
        return False

    d = ctx.user_data.get("lit_data", {})
    preuves = d.get("preuves", [])
    if len(preuves) >= 5:
        await update.message.reply_text("⚠️ Maximum 5 preuves atteint.")
        return True

    photo_id = update.message.photo[-1].file_id
    preuves.append(photo_id)
    d["preuves"] = preuves
    ctx.user_data["lit_data"] = d

    await update.message.reply_text(
        f"✅ Preuve {len(preuves)}/5 reçue !",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Preuves envoyées", callback_data="lit_preuves_ok"),
            InlineKeyboardButton("❌ Annuler", callback_data="lit_annuler")
        ]])
    )
    return True
