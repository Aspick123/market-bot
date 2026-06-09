"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 2 — ANNONCES.PY                          ║
║  • Création d'annonces (vente + échange)                     ║
║  • Photos obligatoires + watermark                           ║
║  • Validation manuelle admin                                 ║
║  • Gestion boost, expiration, renouvellement                 ║
║  • Publication canal Telegram                                ║
╚══════════════════════════════════════════════════════════════╝
"""

import datetime
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, mdb_config, get_user, save_user,
    get_annonce, save_annonce, next_annonce_id, get_annonces_user,
    get_annonces_en_attente, get_annonces_actives,
    add_log, update_stat, update_stat_jeu, date_expiration,
    is_expired, format_date, stars, niveau_label, has_perm,
    get_team_ids_by_role, get_all_team_ids
)

# ══════════════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════════════

TYPES_TRANSACTION = [
    ("vente",   "💰 Vente"),
    ("echange", "🔄 Échange"),
]

TYPES_ARTICLE = [
    ("compte",  "👤 Compte de jeu"),
    ("monnaie", "💎 Monnaie virtuelle"),
]

STATUTS_ANNONCE = {
    "en_attente": "🟡 En attente de validation",
    "active":     "✅ Active",
    "vendue":     "🏷️ Vendue/Échangée",
    "expiree":    "⏰ Expirée",
    "refusee":    "❌ Refusée",
    "suspendue":  "🔴 Suspendue",
    "boostee":    "🚀 Boostée",
}

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 1 — LANCER LA CRÉATION D'ANNONCE
# ══════════════════════════════════════════════════════════════

async def start_creation_annonce(message, user_id: int):
    """Lance le processus de création d'annonce."""
    config = mdb_config()
    user = get_user(user_id)

    # Vérifier limite annonces actives
    annonces_user = get_annonces_user(user_id)
    actives = [a for _, a in annonces_user if a.get("statut") in ["active", "en_attente", "boostee"]]
    max_ann = config.get("max_annonces_par_user", 3)

    if len(actives) >= max_ann:
        await message.reply_text(
            f"⚠️ *Limite atteinte !*\n\n"
            f"Tu as déjà *{len(actives)}/{max_ann}* annonces actives.\n"
            f"Attends qu'une annonce expire ou soit vendue\n"
            f"pour en publier une nouvelle.",
            parse_mode="Markdown"
        )
        return

    kb = [[InlineKeyboardButton(label, callback_data=f"ann_type_{key}")]
          for key, label in TYPES_TRANSACTION]
    kb.append([InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")])

    await message.reply_text(
        "📝 *Créer une annonce*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Quel type de transaction ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 2 — TYPE D'ARTICLE
# ══════════════════════════════════════════════════════════════

async def ask_type_article(message, type_transaction: str):
    kb = [[InlineKeyboardButton(label, callback_data=f"ann_article_{key}")]
          for key, label in TYPES_ARTICLE]
    kb.append([InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")])

    type_label = dict(TYPES_TRANSACTION).get(type_transaction, type_transaction)
    await message.reply_text(
        f"📝 *{type_label}*\n\n"
        f"Qu'est-ce que tu veux proposer ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 3 — CHOIX DU JEU
# ══════════════════════════════════════════════════════════════

async def ask_jeu(message, type_article: str):
    jeux = mdb_read("jeux.json")
    kb = []
    row = []
    for i, (jeu, data) in enumerate(jeux.items()):
        if type_article in data.get("type", []):
            row.append(InlineKeyboardButton(jeu, callback_data=f"ann_jeu_{jeu}"))
            if len(row) == 2:
                kb.append(row)
                row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")])

    await message.reply_text(
        "🎮 *Quel jeu ?*\n\n"
        "Sélectionne le jeu concerné :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 4 — TITRE DE L'ANNONCE
# ══════════════════════════════════════════════════════════════

async def ask_titre(message, jeu: str):
    await message.reply_text(
        f"📝 *Titre de l'annonce*\n\n"
        f"🎮 Jeu : *{jeu}*\n\n"
        f"Donne un titre court et clair :\n"
        f"_(ex: Compte Fortnite 150 skins Rare)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")
        ]])
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 5 — DESCRIPTION
# ══════════════════════════════════════════════════════════════

async def ask_description(message):
    await message.reply_text(
        "📋 *Description détaillée*\n\n"
        "💡 *Pour un compte, précise :*\n"
        "• Niveau / Rang\n"
        "• Skins / Cosmétiques\n"
        "• Ancienneté du compte\n"
        "• Email changeable ou non\n\n"
        "💡 *Pour une monnaie, précise :*\n"
        "• Quantité exacte\n"
        "• Plateforme (PC/Mobile/Console)\n\n"
        "Tape ta description :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")
        ]])
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 6 — PRIX / CONTRE-PARTIE
# ══════════════════════════════════════════════════════════════

async def ask_prix(message, type_transaction: str):
    if type_transaction == "vente":
        await message.reply_text(
            "💰 *Prix de vente*\n\n"
            "Indique ton prix avec la monnaie :\n"
            "_(ex: 5000 FCFA, 10 USD, 0.5 USDT)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")
            ]])
        )
    else:
        await message.reply_text(
            "🔄 *Contre-partie souhaitée*\n\n"
            "Qu'est-ce que tu veux en échange ?\n"
            "_(ex: Compte FIFA Ultimate, 2000 V-Bucks)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")
            ]])
        )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 7 — PHOTOS
# ══════════════════════════════════════════════════════════════

async def ask_photos(message):
    await message.reply_text(
        "📸 *Photos obligatoires*\n\n"
        "Envoie *au moins 1 photo* et *au maximum 5*\n"
        "qui prouvent ce que tu vends.\n\n"
        "💡 *Pour un compte :*\n"
        "• Screenshot du profil in-game\n"
        "• Screenshot des skins/objets\n\n"
        "💡 *Pour une monnaie :*\n"
        "• Screenshot du solde\n\n"
        "⚠️ _Les photos seront vérifiées par notre équipe._\n\n"
        "Envoie tes photos maintenant :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ J'ai tout envoyé", callback_data="ann_photos_ok"),
            InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")
        ]])
    )

# ══════════════════════════════════════════════════════════════
#  ÉTAPE 8 — RÉCAPITULATIF + CONFIRMATION
# ══════════════════════════════════════════════════════════════

async def show_recapitulatif(message, ctx, user_id: int):
    d = ctx.user_data.get("ann_data", {})
    type_label = dict(TYPES_TRANSACTION).get(d.get("type_transaction",""), "?")
    article_label = dict(TYPES_ARTICLE).get(d.get("type_article",""), "?")
    nb_photos = len(d.get("photos", []))

    msg = (
        f"📋 *Récapitulatif de ton annonce*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Type : *{type_label}*\n"
        f"🎮 Jeu : *{d.get('jeu','?')}*\n"
        f"📦 Article : *{article_label}*\n"
        f"📝 Titre : *{d.get('titre','?')}*\n"
        f"💰 Prix/Échange : *{d.get('prix','?')}*\n"
        f"📸 Photos : *{nb_photos}*\n\n"
        f"📄 *Description :*\n_{d.get('description','?')}_\n\n"
        f"⚠️ _Ton annonce sera vérifiée avant publication._"
    )

    kb = [
        [
            InlineKeyboardButton("✅ Soumettre", callback_data="ann_soumettre"),
            InlineKeyboardButton("🔄 Recommencer", callback_data="ann_recommencer")
        ],
        [InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")]
    ]
    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  SOUMISSION DE L'ANNONCE
# ══════════════════════════════════════════════════════════════

async def soumettre_annonce(message, ctx, user, super_admin_id: int, bot):
    d = ctx.user_data.get("ann_data", {})
    config = mdb_config()
    ann_id = next_annonce_id()

    annonce = {
        "id": ann_id,
        "vendeur_id": user.id,
        "vendeur_username": user.username or user.first_name,
        "type_transaction": d.get("type_transaction"),
        "type_article": d.get("type_article"),
        "jeu": d.get("jeu"),
        "titre": d.get("titre"),
        "description": d.get("description"),
        "prix": d.get("prix"),
        "photos": d.get("photos", []),
        "statut": "en_attente",
        "date_creation": format_date(),
        "date_soumission": format_date(),
        "expiration": date_expiration(config.get("duree_annonce_jours", 30)),
        "vues": 0,
        "contacts": 0,
        "signalements": 0,
        "booste": False,
        "boost_expiration": None,
        "refus_raison": None,
        "confirmation_vendeur": False,
        "confirmation_acheteur": False,
        "acheteur_id": None,
        "modifications": []
    }

    save_annonce(ann_id, annonce)
    update_stat("total_annonces")
    update_stat_jeu(d.get("jeu", "Autre"))
    add_log("ANNONCE_SOUMISE", f"{ann_id} par {user.id}", user.id)

    # Notifier l'équipe de modération
    await notifier_equipe_annonce(bot, ann_id, annonce, super_admin_id)

    await message.reply_text(
        f"✅ *Annonce soumise !*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎫 Référence : *{ann_id}*\n\n"
        f"Ton annonce est en cours de vérification.\n"
        f"Tu seras notifié dès qu'elle sera validée ou refusée.\n\n"
        f"⏱️ Délai habituel : quelques heures",
        parse_mode="Markdown"
    )

    ctx.user_data.pop("ann_state", None)
    ctx.user_data.pop("ann_data", None)

async def notifier_equipe_annonce(bot, ann_id: str, annonce: dict, super_admin_id: int):
    """Notifie les modérateurs d'annonces d'une nouvelle annonce à valider."""
    type_label = dict(TYPES_TRANSACTION).get(annonce.get("type_transaction",""), "?")
    article_label = dict(TYPES_ARTICLE).get(annonce.get("type_article",""), "?")

    msg = (
        f"📋 *Nouvelle annonce à valider — {ann_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Vendeur : @{annonce['vendeur_username']} (`{annonce['vendeur_id']}`)\n"
        f"📌 Type : {type_label}\n"
        f"🎮 Jeu : {annonce['jeu']}\n"
        f"📦 Article : {article_label}\n"
        f"📝 Titre : {annonce['titre']}\n"
        f"💰 Prix : {annonce['prix']}\n"
        f"📸 Photos : {len(annonce['photos'])}\n\n"
        f"📄 _{annonce['description'][:200]}{'...' if len(annonce['description']) > 200 else ''}_"
    )

    kb = [
        [
            InlineKeyboardButton("✅ Valider", callback_data=f"adm_valider_{ann_id}"),
            InlineKeyboardButton("❌ Refuser", callback_data=f"adm_refuser_{ann_id}")
        ],
        [InlineKeyboardButton("👤 Voir profil vendeur", callback_data=f"voir_profil_{annonce['vendeur_id']}")]
    ]

    # Envoyer au super admin
    try:
        await bot.send_message(super_admin_id, msg, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(kb))
        # Envoyer les photos
        for photo_id in annonce.get("photos", [])[:5]:
            try:
                await bot.send_photo(super_admin_id, photo_id,
                                     caption=f"📸 Photo annonce {ann_id}")
            except: pass
    except: pass

    # Envoyer aux modérateurs annonces
    mod_ids = get_team_ids_by_role("mod_annonces")
    for mod_id in mod_ids:
        try:
            await bot.send_message(mod_id, msg, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))
        except: pass

# ══════════════════════════════════════════════════════════════
#  VALIDATION / REFUS D'ANNONCE
# ══════════════════════════════════════════════════════════════

async def valider_annonce(query, ctx, bot, super_admin_id: int):
    """Admin valide une annonce."""
    ann_id = query.data.replace("adm_valider_", "")
    annonce = get_annonce(ann_id)
    if not annonce:
        await query.message.reply_text("❌ Annonce introuvable.")
        return

    annonce["statut"] = "active"
    annonce["date_validation"] = format_date()
    annonce["validee_par"] = query.from_user.id
    save_annonce(ann_id, annonce)

    # Mettre à jour stats vendeur
    user = get_user(annonce["vendeur_id"])
    user["stats"]["annonces_publiees"] = user["stats"].get("annonces_publiees", 0) + 1
    if not user.get("est_vendeur"):
        user["est_vendeur"] = True
        user["vendeur_verifie"] = True
    save_user(annonce["vendeur_id"], user)

    add_log("ANNONCE_VALIDEE", ann_id, query.from_user.id)

    # Notifier le vendeur
    try:
        await bot.send_message(
            annonce["vendeur_id"],
            f"✅ *Annonce validée !*\n\n"
            f"🎫 *{ann_id}* — {annonce['titre']}\n\n"
            f"Ton annonce est maintenant *en ligne* ! 🎉\n"
            f"Elle sera visible par tous les membres.",
            parse_mode="Markdown"
        )
    except: pass

    # Publier dans le canal
    canal_id = mdb_config().get("canal_id")
    if canal_id:
        await publier_dans_canal(bot, ann_id, annonce, canal_id)

    # Notifier les abonnés aux alertes
    await notifier_alertes_annonce(bot, annonce)

    await query.message.reply_text(
        f"✅ Annonce *{ann_id}* validée et publiée !", parse_mode="Markdown"
    )

async def refuser_annonce_init(query, ctx):
    """Demande la raison du refus."""
    ann_id = query.data.replace("adm_refuser_", "")
    ctx.user_data["adm_state"] = "refus_annonce"
    ctx.user_data["adm_data"] = {"ann_id": ann_id}
    await query.message.reply_text(
        f"❌ *Refus annonce {ann_id}*\n\n"
        f"Indique la raison du refus\n"
        f"(sera envoyée au vendeur) :",
        parse_mode="Markdown"
    )

async def refuser_annonce_confirm(message, ctx, bot, ann_id: str, raison: str):
    """Finalise le refus."""
    annonce = get_annonce(ann_id)
    if not annonce:
        await message.reply_text("❌ Annonce introuvable.")
        return

    annonce["statut"] = "refusee"
    annonce["refus_raison"] = raison
    annonce["date_refus"] = format_date()
    save_annonce(ann_id, annonce)
    add_log("ANNONCE_REFUSEE", f"{ann_id} — {raison}", message.from_user.id if hasattr(message, 'from_user') else 0)

    try:
        await bot.send_message(
            annonce["vendeur_id"],
            f"❌ *Annonce refusée*\n\n"
            f"🎫 *{ann_id}* — {annonce['titre']}\n\n"
            f"📋 *Raison :*\n_{raison}_\n\n"
            f"💡 Corrige les problèmes et republie une nouvelle annonce.",
            parse_mode="Markdown"
        )
    except: pass

    await message.reply_text(f"❌ Annonce *{ann_id}* refusée.", parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  PUBLICATION DANS LE CANAL
# ══════════════════════════════════════════════════════════════

async def publier_dans_canal(bot, ann_id: str, annonce: dict, canal_id: str):
    """Publie une annonce formatée dans le canal Telegram."""
    type_label = dict(TYPES_TRANSACTION).get(annonce.get("type_transaction",""), "?")
    article_label = dict(TYPES_ARTICLE).get(annonce.get("type_article",""), "?")

    booste = "🚀 " if annonce.get("booste") else ""
    msg = (
        f"{booste}{'━'*20}\n"
        f"🎫 *{ann_id}* — {type_label.upper()}\n"
        f"{'━'*20}\n\n"
        f"📝 *{annonce['titre']}*\n\n"
        f"🎮 Jeu : *{annonce['jeu']}*\n"
        f"📦 Type : *{article_label}*\n"
        f"💰 Prix : *{annonce['prix']}*\n\n"
        f"📋 _{annonce['description'][:300]}{'...' if len(annonce['description']) > 300 else ''}_\n\n"
        f"👤 Vendeur : @{annonce['vendeur_username']}\n"
        f"📅 Expire le : {annonce['expiration']}\n"
        f"{'━'*20}"
    )

    kb = [[InlineKeyboardButton(
        "🔍 Voir l'annonce complète",
        url=f"https://t.me/{(await bot.get_me()).username}?start=ann_{ann_id}"
    )]]

    try:
        if annonce.get("photos"):
            await bot.send_photo(
                canal_id,
                annonce["photos"][0],
                caption=msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await bot.send_message(
                canal_id, msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
    except Exception as e:
        print(f"Erreur publication canal : {e}")

# ══════════════════════════════════════════════════════════════
#  AFFICHAGE D'UNE ANNONCE
# ══════════════════════════════════════════════════════════════

async def afficher_annonce(message, ann_id: str, viewer_id: int):
    """Affiche une annonce complète."""
    annonce = get_annonce(ann_id)
    if not annonce or annonce.get("statut") not in ["active", "boostee"]:
        await message.reply_text("❌ Annonce introuvable ou inactive.")
        return

    # Incrémenter les vues
    annonce["vues"] = annonce.get("vues", 0) + 1
    save_annonce(ann_id, annonce)

    vendeur = get_user(annonce["vendeur_id"])
    rep = mdb_read("reputation.json").get(str(annonce["vendeur_id"]), {})
    note = rep.get("note_moyenne", 0)
    nb_avis = rep.get("nb_avis", 0)
    type_label = dict(TYPES_TRANSACTION).get(annonce.get("type_transaction",""), "?")
    article_label = dict(TYPES_ARTICLE).get(annonce.get("type_article",""), "?")

    booste = "🚀 *ANNONCE BOOSTÉE*\n\n" if annonce.get("booste") else ""
    msg = (
        f"{booste}"
        f"🎫 *{ann_id}* — {type_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 *{annonce['titre']}*\n\n"
        f"🎮 Jeu : *{annonce['jeu']}*\n"
        f"📦 Type : *{article_label}*\n"
        f"💰 Prix/Échange : *{annonce['prix']}*\n\n"
        f"📋 *Description :*\n_{annonce['description']}_\n\n"
        f"👤 *Vendeur :* @{annonce['vendeur_username']}\n"
        f"⭐ Note : {stars(note) if nb_avis > 0 else 'Aucun avis'}\n"
        f"📊 Niveau : {niveau_label(vendeur.get('niveau','bronze'))}\n"
        f"👁️ Vues : {annonce.get('vues',0)}\n"
        f"📅 Expire : {annonce['expiration']}"
    )

    kb = []
    if viewer_id != annonce["vendeur_id"]:
        kb.append([InlineKeyboardButton(
            "🤝 Je suis intéressé(e)", callback_data=f"interesse_{ann_id}"
        )])
        kb.append([InlineKeyboardButton(
            "👤 Voir profil vendeur", callback_data=f"voir_profil_{annonce['vendeur_id']}"
        )])
        kb.append([InlineKeyboardButton(
            "🚩 Signaler cette annonce", callback_data=f"signaler_ann_{ann_id}"
        )])
    else:
        kb.append([InlineKeyboardButton(
            "✏️ Modifier", callback_data=f"ann_modifier_{ann_id}"
        )])
        kb.append([InlineKeyboardButton(
            "🏷️ Marquer comme vendue", callback_data=f"ann_vendue_{ann_id}"
        )])
        kb.append([InlineKeyboardButton(
            "🗑️ Supprimer", callback_data=f"ann_supprimer_{ann_id}"
        )])

    if annonce.get("photos"):
        try:
            await message.reply_photo(
                annonce["photos"][0],
                caption=msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            await message.reply_text(msg, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(kb))
    else:
        await message.reply_text(msg, parse_mode="Markdown",
                                 reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  MES ANNONCES
# ══════════════════════════════════════════════════════════════

async def show_mes_annonces(message, user_id: int):
    """Affiche les annonces du vendeur."""
    annonces = get_annonces_user(user_id)

    if not annonces:
        await message.reply_text(
            "📋 *Mes annonces*\n\nTu n'as aucune annonce pour le moment.\n"
            "Tape /vendre pour en créer une !",
            parse_mode="Markdown"
        )
        return

    msg = f"📋 *Mes annonces* ({len(annonces)})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    kb = []
    for ann_id, ann in annonces[-10:]:
        statut = STATUTS_ANNONCE.get(ann.get("statut"), "?")
        msg += (
            f"🎫 *{ann_id}* — {ann.get('titre','?')[:30]}\n"
            f"  {statut} | 👁️ {ann.get('vues',0)} vues\n"
            f"  📅 Expire : {ann.get('expiration','?')}\n\n"
        )
        kb.append([InlineKeyboardButton(
            f"👁️ {ann_id} — {ann.get('titre','?')[:25]}",
            callback_data=f"voir_ann_{ann_id}"
        )])

    kb.append([InlineKeyboardButton("➕ Nouvelle annonce", callback_data="menu_vendre")])
    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  SIGNALEMENT D'ANNONCE
# ══════════════════════════════════════════════════════════════

async def signaler_annonce(query, ctx, bot, super_admin_id: int):
    """Un membre signale une annonce suspecte."""
    ann_id = query.data.replace("signaler_ann_", "")
    annonce = get_annonce(ann_id)
    if not annonce:
        await query.message.reply_text("❌ Annonce introuvable.")
        return

    annonce["signalements"] = annonce.get("signalements", 0) + 1
    save_annonce(ann_id, annonce)

    config = mdb_config()
    seuil = config.get("signalements_avant_suspension", 3)

    # Notifier les modérateurs sécurité
    msg_equipe = (
        f"🚩 *Annonce signalée — {ann_id}*\n"
        f"Signalements : {annonce['signalements']}/{seuil}\n"
        f"Titre : {annonce['titre']}\n"
        f"Vendeur : @{annonce['vendeur_username']}"
    )

    mod_ids = get_team_ids_by_role("mod_securite")
    for mod_id in [super_admin_id] + mod_ids:
        try:
            await bot.send_message(mod_id, msg_equipe, parse_mode="Markdown")
        except: pass

    add_log("ANNONCE_SIGNALEE", ann_id, query.from_user.id)
    await query.message.reply_text(
        "🚩 Signalement enregistré. Merci !\nNotre équipe va examiner cette annonce."
    )

# ══════════════════════════════════════════════════════════════
#  BOOST D'ANNONCE
# ══════════════════════════════════════════════════════════════

async def booster_annonce(ann_id: str, admin_id: int, bot):
    """Admin booste une annonce."""
    annonce = get_annonce(ann_id)
    if not annonce:
        return False

    config = mdb_config()
    boost_jours = config.get("boost_duree_jours", 7)
    annonce["booste"] = True
    annonce["statut"] = "boostee"
    annonce["boost_expiration"] = date_expiration(boost_jours)
    save_annonce(ann_id, annonce)
    add_log("ANNONCE_BOOSTEE", ann_id, admin_id)

    try:
        await bot.send_message(
            annonce["vendeur_id"],
            f"🚀 *Ton annonce est boostée !*\n\n"
            f"🎫 *{ann_id}* — {annonce['titre']}\n\n"
            f"Elle sera épinglée pendant *{boost_jours} jours* ! 🎉",
            parse_mode="Markdown"
        )
    except: pass
    return True

# ══════════════════════════════════════════════════════════════
#  ALERTES NOUVELLES ANNONCES
# ══════════════════════════════════════════════════════════════

async def notifier_alertes_annonce(bot, annonce: dict):
    """Notifie les membres abonnés aux alertes pour ce jeu."""
    alertes = mdb_read("alertes.json")
    jeu = annonce.get("jeu", "")

    for user_id_str, user_alertes in alertes.items():
        for alerte in user_alertes:
            if (alerte.get("jeu", "").lower() in jeu.lower() or
                jeu.lower() in alerte.get("jeu", "").lower()):
                try:
                    await bot.send_message(
                        int(user_id_str),
                        f"🔔 *Nouvelle annonce — {jeu}*\n\n"
                        f"📝 {annonce['titre']}\n"
                        f"💰 {annonce['prix']}\n\n"
                        f"Tape /ann_{annonce['id']} pour voir l'annonce.",
                        parse_mode="Markdown"
                    )
                except: pass

# ══════════════════════════════════════════════════════════════
#  RENOUVELLEMENT ANNONCE
# ══════════════════════════════════════════════════════════════

async def renouveler_annonce(query, user_id: int):
    """Vendeur renouvelle une annonce expirée."""
    ann_id = query.data.replace("ann_renouveler_", "")
    annonce = get_annonce(ann_id)

    if not annonce or annonce["vendeur_id"] != user_id:
        await query.message.reply_text("❌ Annonce introuvable.")
        return

    config = mdb_config()
    annonce["statut"] = "en_attente"
    annonce["expiration"] = date_expiration(config.get("duree_annonce_jours", 30))
    annonce["date_renouvellement"] = format_date()
    save_annonce(ann_id, annonce)

    await query.message.reply_text(
        f"✅ *Annonce {ann_id} renouvelée !*\n"
        f"Elle repassera en validation avant publication.",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_annonces_callbacks(query, ctx, user, bot, super_admin_id: int) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data == "menu_vendre":
        await start_creation_annonce(msg, uid)
        return True

    if data.startswith("ann_type_"):
        type_t = data.replace("ann_type_", "")
        ctx.user_data["ann_state"] = "type_article"
        ctx.user_data["ann_data"] = {"type_transaction": type_t}
        await ask_type_article(msg, type_t)
        return True

    if data.startswith("ann_article_"):
        article = data.replace("ann_article_", "")
        ctx.user_data["ann_data"]["type_article"] = article
        ctx.user_data["ann_state"] = "jeu"
        await ask_jeu(msg, article)
        return True

    if data.startswith("ann_jeu_"):
        jeu = data.replace("ann_jeu_", "")
        ctx.user_data["ann_data"]["jeu"] = jeu
        ctx.user_data["ann_state"] = "titre"
        await ask_titre(msg, jeu)
        return True

    if data == "ann_photos_ok":
        photos = ctx.user_data.get("ann_data", {}).get("photos", [])
        if not photos:
            await msg.reply_text("⚠️ Envoie au moins *1 photo* avant de continuer.",
                                 parse_mode="Markdown")
            return True
        ctx.user_data["ann_state"] = "recapitulatif"
        await show_recapitulatif(msg, ctx, uid)
        return True

    if data == "ann_soumettre":
        await soumettre_annonce(msg, ctx, user, super_admin_id, bot)
        return True

    if data == "ann_recommencer":
        ctx.user_data.pop("ann_state", None)
        ctx.user_data.pop("ann_data", None)
        await start_creation_annonce(msg, uid)
        return True

    if data == "ann_annuler":
        ctx.user_data.pop("ann_state", None)
        ctx.user_data.pop("ann_data", None)
        await msg.reply_text("❌ Création d'annonce annulée.")
        return True

    if data.startswith("voir_ann_"):
        ann_id = data.replace("voir_ann_", "")
        await afficher_annonce(msg, ann_id, uid)
        return True

    if data == "menu_mes_annonces":
        await show_mes_annonces(msg, uid)
        return True

    if data.startswith("signaler_ann_"):
        await signaler_annonce(query, ctx, bot, super_admin_id)
        return True

    if data.startswith("adm_valider_"):
        await valider_annonce(query, ctx, bot, super_admin_id)
        return True

    if data.startswith("adm_refuser_"):
        await refuser_annonce_init(query, ctx)
        return True

    if data.startswith("ann_renouveler_"):
        await renouveler_annonce(query, uid)
        return True

    return False

# ══════════════════════════════════════════════════════════════
#  HANDLER MESSAGES TEXTE
# ══════════════════════════════════════════════════════════════

async def handle_annonces_input(update, ctx, user, bot, super_admin_id: int) -> bool:
    state = ctx.user_data.get("ann_state")
    if not state:
        return False

    text = update.message.text.strip() if update.message and update.message.text else ""
    d = ctx.user_data.get("ann_data", {})

    if state == "titre":
        if len(text) < 5:
            await update.message.reply_text("⚠️ Titre trop court (min 5 caractères).")
            return True
        d["titre"] = text
        ctx.user_data["ann_data"] = d
        ctx.user_data["ann_state"] = "description"
        await ask_description(update.message)
        return True

    if state == "description":
        if len(text) < 20:
            await update.message.reply_text("⚠️ Description trop courte (min 20 caractères).")
            return True
        d["description"] = text
        ctx.user_data["ann_data"] = d
        ctx.user_data["ann_state"] = "prix"
        await ask_prix(update.message, d.get("type_transaction", "vente"))
        return True

    if state == "prix":
        d["prix"] = text
        ctx.user_data["ann_data"] = d
        ctx.user_data["ann_state"] = "photos"
        d["photos"] = []
        await ask_photos(update.message)
        return True

    # Raison de refus admin
    adm_state = ctx.user_data.get("adm_state")
    if adm_state == "refus_annonce":
        ann_id = ctx.user_data.get("adm_data", {}).get("ann_id")
        await refuser_annonce_confirm(update.message, ctx, bot, ann_id, text)
        ctx.user_data.pop("adm_state", None)
        ctx.user_data.pop("adm_data", None)
        return True

    return False

async def handle_annonces_photos(update, ctx) -> bool:
    """Gère la réception des photos pour une annonce."""
    state = ctx.user_data.get("ann_state")
    if state != "photos":
        return False

    if not update.message.photo:
        return False

    d = ctx.user_data.get("ann_data", {})
    photos = d.get("photos", [])

    if len(photos) >= 5:
        await update.message.reply_text(
            "⚠️ Maximum 5 photos atteint.\nAppuie sur *'J'ai tout envoyé'*.",
            parse_mode="Markdown"
        )
        return True

    photo_id = update.message.photo[-1].file_id
    photos.append(photo_id)
    d["photos"] = photos
    ctx.user_data["ann_data"] = d

    await update.message.reply_text(
        f"✅ Photo {len(photos)}/5 reçue !\n"
        f"{'Envoie une autre ou appuie sur ' + chr(39) + 'J' + chr(39) + 'ai tout envoyé' + chr(39) if len(photos) < 5 else 'Maximum atteint.'}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ J'ai tout envoyé", callback_data="ann_photos_ok"),
            InlineKeyboardButton("❌ Annuler", callback_data="ann_annuler")
        ]])
    )
    return True
