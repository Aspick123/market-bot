"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 7 — REPUTATION.PY                        ║
║  • Notes 1-5 étoiles                                         ║
║  • Commentaires + réponses vendeur                           ║
║  • Badges automatiques                                       ║
║  • Leaderboard vendeurs + acheteurs                          ║
║  • Profil public                                             ║
╚══════════════════════════════════════════════════════════════╝
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, get_user, save_user,
    get_transaction, format_date, stars, niveau_label
)

# ══════════════════════════════════════════════════════════════
#  BADGES DISPONIBLES
# ══════════════════════════════════════════════════════════════

BADGES = {
    "nouveau":      ("🆕", "Nouveau membre"),
    "verifie":      ("✅", "Vendeur vérifié"),
    "pro":          ("🥇", "Vendeur Pro"),
    "fiable":       ("🛡️", "Vendeur Fiable"),
    "top_vendeur":  ("👑", "Top Vendeur"),
    "actif":        ("⚡", "Très Actif"),
    "sans_litige":  ("🕊️", "Zéro Litige"),
    "parrain":      ("🎁", "Parrain Actif"),
    "premium":      ("💎", "Premium"),
}

# ══════════════════════════════════════════════════════════════
#  CALCUL RÉPUTATION
# ══════════════════════════════════════════════════════════════

def get_reputation(user_id: int) -> dict:
    rep = mdb_read("reputation.json")
    uid = str(user_id)
    if uid not in rep:
        rep[uid] = {
            "note_moyenne": 0,
            "nb_avis": 0,
            "avis": [],
            "score_risque": 0
        }
        mdb_write("reputation.json", rep)
    return rep[uid]

def save_reputation(user_id: int, data: dict):
    rep = mdb_read("reputation.json")
    rep[str(user_id)] = data
    mdb_write("reputation.json", rep)

def calculer_note_moyenne(avis: list) -> float:
    if not avis:
        return 0.0
    return round(sum(a["note"] for a in avis) / len(avis), 1)

def calculer_score_risque(user_id: int) -> int:
    """Score de 0 (sûr) à 100 (risqué)."""
    user = get_user(user_id)
    rep = get_reputation(user_id)
    score = 0

    # Nouveau compte = +20
    from database_market import get_all_users
    import datetime
    try:
        joined = datetime.datetime.strptime(user.get("joined","01/01/2020"), "%d/%m/%Y")
        anciennete = (datetime.datetime.now() - joined).days
        if anciennete < 7:
            score += 30
        elif anciennete < 30:
            score += 15
    except: pass

    # Pas de note = +15
    if rep.get("nb_avis", 0) == 0:
        score += 15

    # Note basse = +20
    note = rep.get("note_moyenne", 0)
    if note > 0 and note < 3:
        score += 20

    # Litiges = +15 chacun
    litiges = user.get("stats", {}).get("litiges_ouverts", 0)
    score += min(litiges * 15, 45)

    # Avertissements = +10 chacun
    score += min(user.get("avertissements", 0) * 10, 30)

    # Suspendu = +50
    if user.get("suspendu"):
        score += 50

    return min(score, 100)

def badge_risque(score: int) -> str:
    if score <= 20:
        return "🟢 Fiable"
    elif score <= 50:
        return "🟡 Modéré"
    elif score <= 75:
        return "🟠 Risqué"
    else:
        return "🔴 Très risqué"

def mettre_a_jour_badges(user_id: int):
    """Met à jour automatiquement les badges d'un utilisateur."""
    user = get_user(user_id)
    rep = get_reputation(user_id)
    stats = user.get("stats", {})
    badges = []

    # Badge nouveau
    import datetime
    try:
        joined = datetime.datetime.strptime(user.get("joined","01/01/2020"), "%d/%m/%Y")
        anciennete = (datetime.datetime.now() - joined).days
        if anciennete < 30:
            badges.append("nouveau")
    except: pass

    # Badge vérifié
    if user.get("vendeur_verifie"):
        badges.append("verifie")

    # Badge pro (10+ ventes)
    if stats.get("ventes", 0) >= 10:
        badges.append("pro")

    # Badge fiable (note >= 4.5 + 5+ avis)
    if rep.get("note_moyenne", 0) >= 4.5 and rep.get("nb_avis", 0) >= 5:
        badges.append("fiable")

    # Badge sans litige
    if stats.get("litiges_ouverts", 0) == 0 and stats.get("ventes", 0) >= 3:
        badges.append("sans_litige")

    # Badge actif (20+ transactions)
    total_trx = stats.get("ventes", 0) + stats.get("achats", 0) + stats.get("echanges", 0)
    if total_trx >= 20:
        badges.append("actif")

    user["badges"] = badges
    save_user(user_id, user)
    return badges

def mettre_a_jour_niveau(user_id: int):
    """Met à jour le niveau Bronze/Argent/Or/Platine."""
    user = get_user(user_id)
    stats = user.get("stats", {})
    total_trx = stats.get("ventes", 0) + stats.get("achats", 0) + stats.get("echanges", 0)

    if total_trx >= 50:
        niveau = "platine"
    elif total_trx >= 20:
        niveau = "or"
    elif total_trx >= 5:
        niveau = "argent"
    else:
        niveau = "bronze"

    if user.get("niveau") != niveau:
        user["niveau"] = niveau
        save_user(user_id, user)
        return niveau, True
    return niveau, False

# ══════════════════════════════════════════════════════════════
#  ENREGISTRER UNE NOTE
# ══════════════════════════════════════════════════════════════

async def enregistrer_note(query, ctx, bot, trx_id: str, note: int, noter_id: int):
    """Enregistre la note après une transaction."""
    trx = get_transaction(trx_id)
    if not trx:
        await query.message.reply_text("❌ Transaction introuvable.")
        return

    # Déterminer qui est noté
    if noter_id == trx["acheteur_id"]:
        note_key = "note_acheteur"
        note_pour_id = trx["vendeur_id"]
        role_note = "vendeur"
    elif noter_id == trx["vendeur_id"]:
        note_key = "note_vendeur"
        note_pour_id = trx["acheteur_id"]
        role_note = "acheteur"
    else:
        await query.message.reply_text("❌ Tu n'es pas concerné par cette transaction.")
        return

    if trx.get(note_key) is not None:
        await query.message.reply_text("ℹ️ Tu as déjà noté cette transaction.")
        return

    trx[note_key] = note
    from database_market import save_transaction
    save_transaction(trx_id, trx)

    # Demander un commentaire
    ctx.user_data["rep_state"] = "commentaire"
    ctx.user_data["rep_data"] = {
        "trx_id": trx_id,
        "note": note,
        "note_pour_id": note_pour_id,
        "role_note": role_note
    }

    kb = [[
        InlineKeyboardButton("⏭️ Passer sans commentaire", callback_data=f"rep_sans_commentaire_{trx_id}")
    ]]

    await query.message.reply_text(
        f"{'⭐' * note} Note *{note}/5* enregistrée !\n\n"
        f"Laisse un commentaire (optionnel) :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def finaliser_note(message, ctx, bot, commentaire: str = None):
    """Finalise la note avec commentaire optionnel."""
    d = ctx.user_data.get("rep_data", {})
    trx_id = d.get("trx_id")
    note = d.get("note")
    note_pour_id = d.get("note_pour_id")

    if not note_pour_id:
        return

    rep = get_reputation(note_pour_id)
    avis = rep.get("avis", [])

    avis_entry = {
        "trx_id": trx_id,
        "noter_id": message.from_user.id if hasattr(message, 'from_user') else 0,
        "note": note,
        "commentaire": commentaire,
        "date": format_date(),
        "reponse": None
    }
    avis.append(avis_entry)
    rep["avis"] = avis
    rep["nb_avis"] = len(avis)
    rep["note_moyenne"] = calculer_note_moyenne(avis)
    save_reputation(note_pour_id, rep)

    # Mettre à jour badges et niveau
    badges = mettre_a_jour_badges(note_pour_id)
    nouveau_niveau, niveau_change = mettre_a_jour_niveau(note_pour_id)

    # Notifier si niveau changé
    if niveau_change:
        try:
            await bot.send_message(
                note_pour_id,
                f"🎉 *Nouveau niveau atteint !*\n\n"
                f"Tu es maintenant *{niveau_label(nouveau_niveau)}* ! 🏆",
                parse_mode="Markdown"
            )
        except: pass

    await message.reply_text(
        "✅ Avis enregistré ! Merci.",
        parse_mode="Markdown"
    )

    ctx.user_data.pop("rep_state", None)
    ctx.user_data.pop("rep_data", None)

# ══════════════════════════════════════════════════════════════
#  RÉPONSE DU VENDEUR À UN AVIS
# ══════════════════════════════════════════════════════════════

async def show_avis_a_repondre(message, user_id: int):
    """Affiche les avis sans réponse du vendeur."""
    rep = get_reputation(user_id)
    avis = rep.get("avis", [])
    sans_reponse = [(i, a) for i, a in enumerate(avis)
                   if a.get("commentaire") and not a.get("reponse")]

    if not sans_reponse:
        await message.reply_text(
            "✅ Tous tes avis ont une réponse !",
            parse_mode="Markdown"
        )
        return

    kb = []
    for i, avis_item in sans_reponse[:5]:
        note_stars = "⭐" * avis_item["note"]
        commentaire = avis_item["commentaire"][:30]
        kb.append([InlineKeyboardButton(
            f"{note_stars} — {commentaire}...",
            callback_data=f"rep_repondre_{i}"
        )])

    await message.reply_text(
        f"💬 *{len(sans_reponse)} avis sans réponse*\n\n"
        f"Choisis un avis auquel répondre :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def start_repondre_avis(query, ctx, user_id: int):
    index = int(query.data.replace("rep_repondre_", ""))
    rep = get_reputation(user_id)
    avis = rep.get("avis", [])

    if index >= len(avis):
        await query.message.reply_text("❌ Avis introuvable.")
        return

    avis_item = avis[index]
    ctx.user_data["rep_state"] = "reponse_avis"
    ctx.user_data["rep_data"] = {"index": index, "user_id": user_id}

    await query.message.reply_text(
        f"💬 *Répondre à cet avis :*\n\n"
        f"{'⭐' * avis_item['note']} {avis_item['note']}/5\n"
        f"_{avis_item.get('commentaire','')}_\n\n"
        f"Ta réponse :",
        parse_mode="Markdown"
    )

async def finaliser_reponse_avis(message, ctx, user_id: int):
    d = ctx.user_data.get("rep_data", {})
    index = d.get("index")
    rep = get_reputation(user_id)
    avis = rep.get("avis", [])

    if index is not None and index < len(avis):
        avis[index]["reponse"] = message.text.strip()
        avis[index]["date_reponse"] = format_date()
        rep["avis"] = avis
        save_reputation(user_id, rep)
        await message.reply_text("✅ Réponse publiée !")
    else:
        await message.reply_text("❌ Erreur lors de l'enregistrement.")

    ctx.user_data.pop("rep_state", None)
    ctx.user_data.pop("rep_data", None)

# ══════════════════════════════════════════════════════════════
#  PROFIL PUBLIC
# ══════════════════════════════════════════════════════════════

async def show_profil_public(message, target_id: int, viewer_id: int):
    """Affiche le profil public d'un utilisateur."""
    user = get_user(target_id)
    rep = get_reputation(target_id)
    profil = user.get("profil", {})
    stats = user.get("stats", {})
    badges = user.get("badges", [])
    score_risque = calculer_score_risque(target_id)

    note_txt = stars(rep.get("note_moyenne", 0)) if rep.get("nb_avis", 0) > 0 else "Aucun avis"
    badges_txt = " ".join([BADGES.get(b, ("?",""))[0] for b in badges]) or "Aucun badge"
    total_trx = (stats.get("ventes", 0) + stats.get("achats", 0) + stats.get("echanges", 0))

    tel_txt = ""
    if profil.get("telephone"):
        if profil.get("telephone_public"):
            tel_txt = f"📱 Tél : `{profil['telephone']}`\n"
        else:
            num = profil["telephone"]
            masque = num[:6] + "••••" + num[-2:] if len(num) > 8 else "••••••••"
            tel_txt = f"📱 Tél : `{masque}` _(privé)_\n"

    whatsapp_txt = f"💬 WhatsApp : {profil.get('whatsapp','')}\n" if profil.get("whatsapp") else ""
    instagram_txt = f"📸 Instagram : {profil.get('instagram','')}\n" if profil.get("instagram") else ""

    monnaies = ", ".join(profil.get("monnaies_acceptees", [])[:4]) or "Non précisé"
    methodes = ", ".join(profil.get("methodes_paiement", [])[:4]) or "Non précisé"

    statut_map = {"en_ligne": "🟢 En ligne", "hors_ligne": "⚫ Hors ligne", "occupe": "🔴 Occupé"}
    statut = statut_map.get(profil.get("statut", "hors_ligne"), "⚫ Hors ligne")
    dispo = f" ({profil.get('heure_debut','')}–{profil.get('heure_fin','')})" if profil.get("heure_debut") else ""

    msg = (
        f"👤 *Profil — @{user.get('profil',{}).get('nom','') or target_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{statut}{dispo}\n"
        f"🌍 Nationalité : {profil.get('nationalite','Non précisé')}\n"
        f"{tel_txt}{whatsapp_txt}{instagram_txt}\n"
        f"📝 _{profil.get('bio','Aucune bio')}_\n\n"
        f"⭐ Note : {note_txt}\n"
        f"🏅 Badges : {badges_txt}\n"
        f"📊 Niveau : {niveau_label(user.get('niveau','bronze'))}\n"
        f"🛡️ Risque : {badge_risque(score_risque)}\n\n"
        f"📈 *Statistiques :*\n"
        f"  💰 Ventes : {stats.get('ventes',0)}\n"
        f"  🔄 Échanges : {stats.get('echanges',0)}\n"
        f"  🛒 Achats : {stats.get('achats',0)}\n"
        f"  📦 Annonces publiées : {stats.get('annonces_publiees',0)}\n\n"
        f"💰 Monnaies : {monnaies}\n"
        f"💳 Méthodes : {methodes}\n"
        f"📅 Membre depuis : {user.get('joined','?')}"
    )

    kb = []
    if target_id != viewer_id:
        kb.append([InlineKeyboardButton("📋 Voir ses annonces",
                   callback_data=f"annonces_user_{target_id}")])
        kb.append([InlineKeyboardButton("💬 Voir ses avis",
                   callback_data=f"voir_avis_{target_id}")])
    else:
        kb.append([InlineKeyboardButton("✏️ Modifier mon profil",
                   callback_data="menu_mon_profil")])
        kb.append([InlineKeyboardButton("💬 Mes avis reçus",
                   callback_data=f"voir_avis_{target_id}")])
        kb.append([InlineKeyboardButton("✍️ Répondre à des avis",
                   callback_data="rep_avis_a_repondre")])

    if profil.get("photo_id"):
        try:
            await message.reply_photo(
                profil["photo_id"], caption=msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        except: pass

    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

async def show_avis(message, target_id: int):
    """Affiche les avis reçus par un utilisateur."""
    rep = get_reputation(target_id)
    avis = rep.get("avis", [])

    if not avis:
        await message.reply_text("💬 Aucun avis pour le moment.")
        return

    msg = (
        f"💬 *Avis reçus* ({len(avis)})\n"
        f"⭐ Moyenne : {stars(rep.get('note_moyenne',0))}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for avis_item in avis[-10:]:
        note_stars = "⭐" * avis_item["note"]
        commentaire = avis_item.get("commentaire","_(sans commentaire)_")
        reponse = f"\n↩️ _{avis_item['reponse']}_" if avis_item.get("reponse") else ""
        msg += f"{note_stars} — _{commentaire}_{reponse}\n📅 {avis_item['date']}\n\n"

    await message.reply_text(msg, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  LEADERBOARD
# ══════════════════════════════════════════════════════════════

async def show_leaderboard(message, categorie: str = "vendeurs"):
    """Affiche le classement des meilleurs membres."""
    users = mdb_read("users.json")
    rep_data = mdb_read("reputation.json")

    if categorie == "vendeurs":
        classement = []
        for uid, u in users.items():
            stats = u.get("stats", {})
            ventes = stats.get("ventes", 0) + stats.get("echanges", 0)
            if ventes > 0:
                rep = rep_data.get(uid, {})
                classement.append({
                    "id": uid,
                    "nom": u.get("profil",{}).get("nom","") or f"User{uid[-4:]}",
                    "ventes": ventes,
                    "note": rep.get("note_moyenne", 0),
                    "nb_avis": rep.get("nb_avis", 0),
                    "niveau": u.get("niveau", "bronze"),
                    "badges": u.get("badges", [])
                })
        classement.sort(key=lambda x: (x["ventes"], x["note"]), reverse=True)
        titre = "💰 Top Vendeurs"
    else:
        classement = []
        for uid, u in users.items():
            stats = u.get("stats", {})
            achats = stats.get("achats", 0) + stats.get("echanges", 0)
            if achats > 0:
                classement.append({
                    "id": uid,
                    "nom": u.get("profil",{}).get("nom","") or f"User{uid[-4:]}",
                    "achats": achats,
                    "niveau": u.get("niveau", "bronze"),
                    "badges": u.get("badges", [])
                })
        classement.sort(key=lambda x: x.get("achats", 0), reverse=True)
        titre = "🛒 Top Acheteurs"

    if not classement:
        await message.reply_text(
            f"🏆 *{titre}*\n\nAucune donnée disponible.",
            parse_mode="Markdown"
        )
        return

    medailles = ["🥇", "🥈", "🥉"]
    msg = f"🏆 *{titre}*\n━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, entry in enumerate(classement[:10]):
        medaille = medailles[i] if i < 3 else f"{i+1}."
        badges_txt = " ".join([BADGES.get(b,("?",""))[0] for b in entry.get("badges",[])[:3]])
        if categorie == "vendeurs":
            msg += (
                f"{medaille} *{entry['nom']}* {badges_txt}\n"
                f"  💰 {entry['ventes']} ventes | "
                f"⭐ {entry['note']:.1f} ({entry['nb_avis']} avis)\n"
                f"  {niveau_label(entry['niveau'])}\n\n"
            )
        else:
            msg += (
                f"{medaille} *{entry['nom']}* {badges_txt}\n"
                f"  🛒 {entry.get('achats',0)} achats\n"
                f"  {niveau_label(entry['niveau'])}\n\n"
            )

    kb = [
        [
            InlineKeyboardButton("💰 Vendeurs", callback_data="leaderboard_vendeurs"),
            InlineKeyboardButton("🛒 Acheteurs", callback_data="leaderboard_acheteurs")
        ]
    ]
    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_reputation_callbacks(query, ctx, bot) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data.startswith("voir_profil_"):
        target_id = int(data.replace("voir_profil_", ""))
        await show_profil_public(msg, target_id, uid)
        return True

    if data.startswith("voir_avis_"):
        target_id = int(data.replace("voir_avis_", ""))
        await show_avis(msg, target_id)
        return True

    if data == "rep_avis_a_repondre":
        await show_avis_a_repondre(msg, uid)
        return True

    if data.startswith("rep_repondre_"):
        await start_repondre_avis(query, ctx, uid)
        return True

    if data.startswith("rep_sans_commentaire_"):
        await finaliser_note(msg, ctx, bot, commentaire=None)
        return True

    if data == "menu_leaderboard":
        await show_leaderboard(msg, "vendeurs")
        return True

    if data == "leaderboard_vendeurs":
        await show_leaderboard(msg, "vendeurs")
        return True

    if data == "leaderboard_acheteurs":
        await show_leaderboard(msg, "acheteurs")
        return True

    if data.startswith("annonces_user_"):
        target_id = int(data.replace("annonces_user_", ""))
        from annonces import get_annonces_user
        from database_market import get_annonce
        annonces = get_annonces_user(target_id)
        actives = [(aid, a) for aid, a in annonces if a.get("statut") in ["active","boostee"]]
        if not actives:
            await msg.reply_text("📋 Cet utilisateur n'a aucune annonce active.")
            return True
        kb = [[InlineKeyboardButton(
            f"{'🚀' if a.get('statut')=='boostee' else '📝'} {aid} — {a.get('titre','?')[:25]}",
            callback_data=f"voir_ann_{aid}"
        )] for aid, a in actives[:10]]
        await msg.reply_text(
            f"📋 *Annonces actives* ({len(actives)})",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return True

    return False

async def handle_reputation_input(update, ctx, bot) -> bool:
    state = ctx.user_data.get("rep_state")
    if not state:
        return False

    text = update.message.text.strip() if update.message and update.message.text else ""

    if state == "commentaire":
        await finaliser_note(update.message, ctx, bot, commentaire=text)
        return True

    if state == "reponse_avis":
        d = ctx.user_data.get("rep_data", {})
        await finaliser_reponse_avis(update.message, ctx, d.get("user_id", update.effective_user.id))
        return True

    return False
