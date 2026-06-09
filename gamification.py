"""
╔══════════════════════════════════════════════════════════════╗
║           MODULE 10 — GAMIFICATION + RAPPORTS               ║
║  • Niveaux Bronze/Argent/Or/Platine                          ║
║  • Points de fidélité                                        ║
║  • Défis hebdomadaires                                       ║
║  • Rapports auto hebdo + mensuel vendeurs                    ║
║  • Dashboard admin exportable                                ║
╚══════════════════════════════════════════════════════════════╝
"""

import datetime
import io
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, get_user, save_user,
    format_date, niveau_label
)

# ══════════════════════════════════════════════════════════════
#  DÉFIS HEBDOMADAIRES
# ══════════════════════════════════════════════════════════════

DEFIS_DISPONIBLES = [
    {"id": "vente_1",     "titre": "Premier pas",      "desc": "Complète 1 vente",              "objectif": 1,  "type": "ventes",    "points": 20},
    {"id": "vente_3",     "titre": "Vendeur actif",    "desc": "Complète 3 ventes cette semaine","objectif": 3,  "type": "ventes",    "points": 50},
    {"id": "annonce_1",   "titre": "Ma première annonce","desc": "Publie 1 annonce",             "objectif": 1,  "type": "annonces",  "points": 15},
    {"id": "note_5",      "titre": "Parfait !",         "desc": "Reçois une note de 5 étoiles",  "objectif": 1,  "type": "note_5",    "points": 30},
    {"id": "parrain_1",   "titre": "Parrain débutant",  "desc": "Parraine 1 ami",                "objectif": 1,  "type": "parrainages","points": 25},
    {"id": "achat_2",     "titre": "Bon acheteur",      "desc": "Effectue 2 achats",             "objectif": 2,  "type": "achats",    "points": 30},
]

def get_gamification_user(user_id: int) -> dict:
    gamif = mdb_read("gamification.json")
    uid = str(user_id)
    if uid not in gamif:
        gamif[uid] = {"points": 0, "defis": {}, "defis_completes": []}
        mdb_write("gamification.json", gamif)
    return gamif[uid]

def save_gamification_user(user_id: int, data: dict):
    gamif = mdb_read("gamification.json")
    gamif[str(user_id)] = data
    mdb_write("gamification.json", gamif)

def ajouter_points(user_id: int, points: int, raison: str = ""):
    gamif = get_gamification_user(user_id)
    gamif["points"] = gamif.get("points", 0) + points
    save_gamification_user(user_id, gamif)

def progresser_defi(user_id: int, type_defi: str, quantite: int = 1) -> list:
    """Met à jour la progression des défis et retourne les défis complétés."""
    gamif = get_gamification_user(user_id)
    completes = []

    for defi in DEFIS_DISPONIBLES:
        if defi["type"] != type_defi:
            continue
        if defi["id"] in gamif.get("defis_completes", []):
            continue

        defis_progress = gamif.setdefault("defis", {})
        progress = defis_progress.get(defi["id"], 0) + quantite
        defis_progress[defi["id"]] = progress

        if progress >= defi["objectif"]:
            gamif.setdefault("defis_completes", []).append(defi["id"])
            ajouter_points(user_id, defi["points"])
            completes.append(defi)

    save_gamification_user(user_id, gamif)
    return completes

async def notifier_defi_complete(bot, user_id: int, defis: list):
    """Notifie l'utilisateur des défis complétés."""
    if not defis:
        return
    for defi in defis:
        try:
            await bot.send_message(
                user_id,
                f"🎯 *Défi complété !*\n\n"
                f"*{defi['titre']}*\n"
                f"_{defi['desc']}_\n\n"
                f"🎁 +{defi['points']} points gagnés !",
                parse_mode="Markdown"
            )
        except: pass

async def show_mes_defis(message, user_id: int):
    gamif = get_gamification_user(user_id)
    points = gamif.get("points", 0)
    completes = gamif.get("defis_completes", [])
    progres = gamif.get("defis", {})

    msg = (
        f"🎯 *Mes Défis*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Points totaux : *{points}*\n\n"
    )

    for defi in DEFIS_DISPONIBLES:
        if defi["id"] in completes:
            msg += f"✅ *{defi['titre']}* — Complété ! (+{defi['points']} pts)\n\n"
        else:
            prog = progres.get(defi["id"], 0)
            barre = f"{prog}/{defi['objectif']}"
            msg += (
                f"🔒 *{defi['titre']}*\n"
                f"  {defi['desc']}\n"
                f"  Progression : {barre} | +{defi['points']} pts\n\n"
            )

    await message.reply_text(msg, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  RAPPORTS VENDEURS
# ══════════════════════════════════════════════════════════════

async def generer_rapport_vendeur(bot, user_id: int, periode: str = "hebdo"):
    """Génère et envoie le rapport d'activité à un vendeur."""
    user = get_user(user_id)
    if not user.get("est_vendeur"):
        return

    if periode == "hebdo" and not user.get("rapport_hebdo", True):
        return
    if periode == "mensuel" and not user.get("rapport_mensuel", True):
        return

    # Calculer les stats de la période
    now = datetime.datetime.now()
    if periode == "hebdo":
        debut = now - datetime.timedelta(days=7)
        titre = "📊 Rapport Hebdomadaire"
    else:
        debut = now - datetime.timedelta(days=30)
        titre = "📊 Rapport Mensuel"

    transactions = mdb_read("transactions.json")
    annonces = mdb_read("annonces.json")
    rep_data = mdb_read("reputation.json")

    ventes_periode = 0
    contacts_recus = 0
    for tid, trx in transactions.items():
        if trx.get("vendeur_id") != user_id:
            continue
        try:
            date_trx = datetime.datetime.strptime(trx.get("date_demande","01/01/2020 00:00"), "%d/%m/%Y %H:%M")
            if date_trx >= debut:
                if trx.get("statut") == "completee":
                    ventes_periode += 1
                contacts_recus += 1
        except: pass

    vues_periode = 0
    for aid, ann in annonces.items():
        if ann.get("vendeur_id") == user_id:
            vues_periode += ann.get("vues", 0)

    rep = rep_data.get(str(user_id), {})
    note_moy = rep.get("note_moyenne", 0)
    nb_avis = rep.get("nb_avis", 0)

    gamif = get_gamification_user(user_id)
    points = gamif.get("points", 0)

    stats_globales = user.get("stats", {})
    total_ventes = stats_globales.get("ventes", 0) + stats_globales.get("echanges", 0)

    msg = (
        f"{titre}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Période : {debut.strftime('%d/%m')} → {now.strftime('%d/%m/%Y')}\n\n"
        f"📈 *Cette période :*\n"
        f"  💰 Ventes/échanges : {ventes_periode}\n"
        f"  👁️ Vues totales : {vues_periode}\n"
        f"  🤝 Contacts reçus : {contacts_recus}\n\n"
        f"📊 *Depuis le début :*\n"
        f"  💰 Total transactions : {total_ventes}\n"
        f"  ⭐ Note moyenne : {note_moy:.1f}/5 ({nb_avis} avis)\n"
        f"  ⚡ Points fidélité : {points}\n"
        f"  🏅 Niveau : {niveau_label(user.get('niveau','bronze'))}"
    )

    kb = [[InlineKeyboardButton(
        "🔕 Désactiver ce rapport",
        callback_data=f"rapport_desactiver_{periode}"
    )]]

    try:
        await bot.send_message(user_id, msg, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(kb))
    except: pass

async def envoyer_rapports_periodiques(bot, periode: str):
    """Envoie les rapports à tous les vendeurs actifs."""
    users = mdb_read("users.json")
    envoyes = 0
    for uid_str, u in users.items():
        if u.get("est_vendeur"):
            try:
                await generer_rapport_vendeur(bot, int(uid_str), periode)
                envoyes += 1
            except: pass
    return envoyes

# ══════════════════════════════════════════════════════════════
#  DASHBOARD ADMIN
# ══════════════════════════════════════════════════════════════

async def show_dashboard_admin(message):
    """Affiche le dashboard complet pour l'admin."""
    stats = mdb_read("stats.json")
    users = mdb_read("users.json")
    annonces = mdb_read("annonces.json")
    transactions = mdb_read("transactions.json")
    litiges = mdb_read("litiges.json")

    nb_users = len(users)
    nb_vendeurs = sum(1 for u in users.values() if u.get("est_vendeur"))
    nb_annonces_actives = sum(1 for a in annonces.values() if a.get("statut") in ["active","boostee"])
    nb_annonces_attente = sum(1 for a in annonces.values() if a.get("statut") == "en_attente")
    nb_trx_total = len(transactions)
    nb_trx_completees = sum(1 for t in transactions.values() if t.get("statut") == "completee")
    nb_litiges_ouverts = sum(1 for l in litiges.values() if l.get("statut") in ["ouvert","en_cours"])

    top_jeux = sorted(
        stats.get("annonces_par_jeu", {}).items(),
        key=lambda x: x[1], reverse=True
    )[:5]
    top_jeux_txt = "\n".join([f"  • {j} : {n}" for j, n in top_jeux]) or "  Aucune donnée"

    msg = (
        f"📊 *Dashboard Admin — Marketplace*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {format_date()}\n\n"
        f"👥 *Utilisateurs :*\n"
        f"  Total : {nb_users} | Vendeurs : {nb_vendeurs}\n\n"
        f"📋 *Annonces :*\n"
        f"  Actives : {nb_annonces_actives}\n"
        f"  En attente : {nb_annonces_attente}\n\n"
        f"💰 *Transactions :*\n"
        f"  Total : {nb_trx_total}\n"
        f"  Complétées : {nb_trx_completees}\n\n"
        f"⚖️ *Litiges ouverts :* {nb_litiges_ouverts}\n\n"
        f"🎮 *Top jeux :*\n{top_jeux_txt}"
    )

    kb = [
        [InlineKeyboardButton("📤 Exporter rapport PDF", callback_data="dashboard_export_pdf")],
        [InlineKeyboardButton("📊 Rapport hebdo manuel", callback_data="dashboard_rapport_hebdo")],
        [InlineKeyboardButton("🔙 Retour admin", callback_data="adm_market_panel")],
    ]

    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

async def exporter_dashboard_pdf(message):
    """Exporte le dashboard en PDF."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        stats = mdb_read("stats.json")
        users = mdb_read("users.json")
        annonces = mdb_read("annonces.json")
        transactions = mdb_read("transactions.json")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("Rapport Marketplace — Dashboard Admin", styles['Title']))
        story.append(Paragraph(f"Généré le : {format_date()}", styles['Normal']))
        story.append(Spacer(1, 12))

        data_stats = [
            ["Métrique", "Valeur"],
            ["Total utilisateurs", str(len(users))],
            ["Vendeurs actifs", str(sum(1 for u in users.values() if u.get("est_vendeur")))],
            ["Annonces actives", str(sum(1 for a in annonces.values() if a.get("statut") in ["active","boostee"]))],
            ["Total transactions", str(len(transactions))],
            ["Transactions complétées", str(sum(1 for t in transactions.values() if t.get("statut")=="completee"))],
        ]

        table = Table(data_stats, colWidths=[250, 100])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
        ]))
        story.append(table)
        story.append(Spacer(1, 20))

        story.append(Paragraph("Top Jeux", styles['Heading2']))
        top_jeux = sorted(stats.get("annonces_par_jeu",{}).items(), key=lambda x: x[1], reverse=True)[:10]
        for jeu, nb in top_jeux:
            story.append(Paragraph(f"• {jeu} : {nb} annonces", styles['Normal']))

        doc.build(story)
        buffer.seek(0)
        buffer.name = f"dashboard_{datetime.date.today()}.pdf"

        await message.reply_document(document=buffer, caption="📊 Dashboard Marketplace")
    except ImportError:
        await message.reply_text("⚠️ Installe reportlab : `pip install reportlab`",
                                 parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_gamification_callbacks(query, ctx, bot, super_admin_id: int) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data == "menu_defis":
        await show_mes_defis(msg, uid)
        return True

    if data == "adm_dashboard":
        await show_dashboard_admin(msg)
        return True

    if data == "dashboard_export_pdf":
        await exporter_dashboard_pdf(msg)
        return True

    if data == "dashboard_rapport_hebdo":
        nb = await envoyer_rapports_periodiques(bot, "hebdo")
        await msg.reply_text(f"✅ Rapports hebdo envoyés à {nb} vendeurs.")
        return True

    if data == "dashboard_rapport_mensuel":
        nb = await envoyer_rapports_periodiques(bot, "mensuel")
        await msg.reply_text(f"✅ Rapports mensuels envoyés à {nb} vendeurs.")
        return True

    if data.startswith("rapport_desactiver_"):
        periode = data.replace("rapport_desactiver_", "")
        user = get_user(uid)
        if periode == "hebdo":
            user["rapport_hebdo"] = False
        else:
            user["rapport_mensuel"] = False
        save_user(uid, user)
        await msg.reply_text(f"✅ Rapport {periode} désactivé.")
        return True

    return False
