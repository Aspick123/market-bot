"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 3 — RECHERCHE.PY                         ║
║  • Recherche par jeu, type, prix                             ║
║  • Filtres combinés                                          ║
║  • Pagination des résultats                                  ║
║  • Affichage des annonces filtrées                           ║
╚══════════════════════════════════════════════════════════════╝
"""

import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, get_annonce, get_user,
    format_date, stars, niveau_label, is_expired
)

PER_PAGE = 5

TYPES_TRANSACTION = [
    ("vente",   "💰 Vente"),
    ("echange", "🔄 Échange"),
    ("tous",    "🔍 Tous"),
]

TYPES_ARTICLE = [
    ("compte",  "👤 Compte de jeu"),
    ("monnaie", "💎 Monnaie virtuelle"),
    ("tous",    "🔍 Tous types"),
]

FOURCHETTES_PRIX = [
    ("0-1000",   "Moins de 1 000"),
    ("1000-5000","1 000 — 5 000"),
    ("5000-10000","5 000 — 10 000"),
    ("10000+",   "Plus de 10 000"),
    ("echange",  "Échange uniquement"),
    ("tous",     "Tous les prix"),
]

# ══════════════════════════════════════════════════════════════
#  MENU PRINCIPAL RECHERCHE
# ══════════════════════════════════════════════════════════════

async def show_menu_recherche(message):
    kb = [
        [InlineKeyboardButton("🎮 Par jeu", callback_data="rech_par_jeu"),
         InlineKeyboardButton("📦 Par type", callback_data="rech_par_type")],
        [InlineKeyboardButton("💰 Par prix", callback_data="rech_par_prix"),
         InlineKeyboardButton("🔍 Recherche avancée", callback_data="rech_avancee")],
        [InlineKeyboardButton("📋 Toutes les annonces", callback_data="rech_toutes_0")],
        [InlineKeyboardButton("🚀 Annonces boostées", callback_data="rech_boostees_0")],
    ]
    await message.reply_text(
        "🔍 *Rechercher une annonce*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Comment veux-tu chercher ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  FILTRES PAR JEU
# ══════════════════════════════════════════════════════════════

async def show_filtre_jeu(message):
    jeux = mdb_read("jeux.json")
    kb = []
    row = []
    for jeu in jeux.keys():
        row.append(InlineKeyboardButton(jeu, callback_data=f"rech_jeu_{jeu}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🔙 Retour", callback_data="menu_recherche")])

    await message.reply_text(
        "🎮 *Choisir un jeu*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  FILTRES PAR TYPE
# ══════════════════════════════════════════════════════════════

async def show_filtre_type(message):
    kb = [[InlineKeyboardButton(label, callback_data=f"rech_type_{key}")]
          for key, label in TYPES_ARTICLE]
    kb.append([InlineKeyboardButton("🔙 Retour", callback_data="menu_recherche")])
    await message.reply_text(
        "📦 *Choisir un type d'article*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  FILTRES PAR PRIX
# ══════════════════════════════════════════════════════════════

async def show_filtre_prix(message):
    kb = [[InlineKeyboardButton(label, callback_data=f"rech_prix_{key}")]
          for key, label in FOURCHETTES_PRIX]
    kb.append([InlineKeyboardButton("🔙 Retour", callback_data="menu_recherche")])
    await message.reply_text(
        "💰 *Choisir une fourchette de prix*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  RECHERCHE AVANCÉE
# ══════════════════════════════════════════════════════════════

async def show_recherche_avancee(message, ctx):
    ctx.user_data["rech_filtres"] = {}
    kb = [
        [InlineKeyboardButton("🎮 Jeu", callback_data="rech_adv_jeu"),
         InlineKeyboardButton("📦 Type", callback_data="rech_adv_type")],
        [InlineKeyboardButton("💰 Prix", callback_data="rech_adv_prix"),
         InlineKeyboardButton("💳 Transaction", callback_data="rech_adv_transaction")],
        [InlineKeyboardButton("🔍 Lancer la recherche", callback_data="rech_adv_lancer_0")],
        [InlineKeyboardButton("🔙 Retour", callback_data="menu_recherche")],
    ]
    await message.reply_text(
        "🔍 *Recherche avancée*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Sélectionne tes filtres :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_adv_jeu(message):
    jeux = mdb_read("jeux.json")
    kb = []
    row = []
    for jeu in list(jeux.keys()) + ["Tous"]:
        row.append(InlineKeyboardButton(jeu, callback_data=f"rech_adv_set_jeu_{jeu}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    await message.reply_text("🎮 Choisir un jeu :",
                             reply_markup=InlineKeyboardMarkup(kb))

async def show_adv_type(message):
    kb = [[InlineKeyboardButton(label, callback_data=f"rech_adv_set_type_{key}")]
          for key, label in TYPES_ARTICLE]
    await message.reply_text("📦 Choisir un type :",
                             reply_markup=InlineKeyboardMarkup(kb))

async def show_adv_prix(message):
    kb = [[InlineKeyboardButton(label, callback_data=f"rech_adv_set_prix_{key}")]
          for key, label in FOURCHETTES_PRIX]
    await message.reply_text("💰 Choisir une fourchette :",
                             reply_markup=InlineKeyboardMarkup(kb))

async def show_adv_transaction(message):
    kb = [[InlineKeyboardButton(label, callback_data=f"rech_adv_set_trx_{key}")]
          for key, label in TYPES_TRANSACTION]
    await message.reply_text("💳 Type de transaction :",
                             reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  MOTEUR DE RECHERCHE
# ══════════════════════════════════════════════════════════════

def filter_annonces(filtres: dict) -> list:
    """Filtre les annonces selon les critères donnés."""
    annonces = mdb_read("annonces.json")
    resultats = []

    for ann_id, ann in annonces.items():
        # Statut actif uniquement
        if ann.get("statut") not in ["active", "boostee"]:
            continue

        # Vérifier expiration
        if is_expired(ann.get("expiration", "")):
            continue

        # Filtre jeu
        if filtres.get("jeu") and filtres["jeu"] != "Tous":
            if ann.get("jeu", "").lower() != filtres["jeu"].lower():
                continue

        # Filtre type article
        if filtres.get("type") and filtres["type"] != "tous":
            if ann.get("type_article") != filtres["type"]:
                continue

        # Filtre transaction
        if filtres.get("transaction") and filtres["transaction"] != "tous":
            if ann.get("type_transaction") != filtres["transaction"]:
                continue

        # Filtre prix (basique — cherche les chiffres dans le prix)
        if filtres.get("prix") and filtres["prix"] != "tous":
            prix_str = ann.get("prix", "")
            if filtres["prix"] == "echange":
                if ann.get("type_transaction") != "echange":
                    continue
            else:
                import re
                nombres = re.findall(r'\d+', prix_str.replace(" ", ""))
                if nombres:
                    prix_num = int(nombres[0])
                    fourchette = filtres["prix"]
                    if fourchette == "0-1000" and prix_num >= 1000:
                        continue
                    elif fourchette == "1000-5000" and not (1000 <= prix_num < 5000):
                        continue
                    elif fourchette == "5000-10000" and not (5000 <= prix_num < 10000):
                        continue
                    elif fourchette == "10000+" and prix_num < 10000:
                        continue

        # Filtre texte libre
        if filtres.get("texte"):
            texte = filtres["texte"].lower()
            if (texte not in ann.get("titre", "").lower() and
                texte not in ann.get("description", "").lower() and
                texte not in ann.get("jeu", "").lower()):
                continue

        resultats.append((ann_id, ann))

    # Trier : boostées en premier, puis par date
    resultats.sort(key=lambda x: (
        0 if x[1].get("statut") == "boostee" else 1,
        x[1].get("date_creation", "")
    ), reverse=False)

    return resultats

# ══════════════════════════════════════════════════════════════
#  AFFICHAGE DES RÉSULTATS
# ══════════════════════════════════════════════════════════════

async def afficher_resultats(message, resultats: list, page: int,
                              filtres: dict, callback_prefix: str):
    """Affiche une page de résultats."""
    total = len(resultats)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    slice_ = resultats[page * PER_PAGE:(page + 1) * PER_PAGE]

    if not slice_:
        await message.reply_text(
            "🔍 *Aucune annonce trouvée*\n\n"
            "Essaie d'autres filtres ou reviens plus tard.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Recherche", callback_data="menu_recherche")
            ]])
        )
        return

    # Résumé des filtres
    filtres_txt = ""
    if filtres.get("jeu") and filtres["jeu"] != "Tous":
        filtres_txt += f"🎮 {filtres['jeu']} "
    if filtres.get("type") and filtres["type"] != "tous":
        filtres_txt += f"📦 {filtres['type']} "
    if filtres.get("prix") and filtres["prix"] != "tous":
        filtres_txt += f"💰 {filtres['prix']} "

    msg = (
        f"🔍 *Résultats* — {total} annonce{'s' if total > 1 else ''}\n"
        f"{filtres_txt}\n"
        f"Page {page + 1}/{total_pages}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    kb = []
    for ann_id, ann in slice_:
        booste = "🚀 " if ann.get("statut") == "boostee" else ""
        type_label = "💰" if ann.get("type_transaction") == "vente" else "🔄"
        msg += (
            f"{booste}{type_label} *{ann.get('titre','?')[:35]}*\n"
            f"  🎮 {ann.get('jeu','?')} | 💰 {ann.get('prix','?')}\n"
            f"  👁️ {ann.get('vues',0)} vues\n\n"
        )
        kb.append([InlineKeyboardButton(
            f"{booste}{type_label} {ann_id} — {ann.get('titre','?')[:25]}",
            callback_data=f"voir_ann_{ann_id}"
        )])

    # Navigation
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"{callback_prefix}_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"{callback_prefix}_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 Recherche", callback_data="menu_recherche")])

    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

async def afficher_toutes(message, page: int):
    resultats = filter_annonces({})
    await afficher_resultats(message, resultats, page, {}, "rech_toutes")

async def afficher_boostees(message, page: int):
    annonces = mdb_read("annonces.json")
    resultats = [(aid, a) for aid, a in annonces.items()
                 if a.get("statut") == "boostee" and not is_expired(a.get("expiration",""))]
    await afficher_resultats(message, resultats, page, {"boost": True}, "rech_boostees")

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_recherche_callbacks(query, ctx) -> bool:
    data = query.data
    msg = query.message

    if data == "menu_recherche":
        await show_menu_recherche(msg)
        return True

    if data == "rech_par_jeu":
        await show_filtre_jeu(msg)
        return True

    if data == "rech_par_type":
        await show_filtre_type(msg)
        return True

    if data == "rech_par_prix":
        await show_filtre_prix(msg)
        return True

    if data == "rech_avancee":
        await show_recherche_avancee(msg, ctx)
        return True

    if data.startswith("rech_toutes_"):
        page = int(data.replace("rech_toutes_", ""))
        await afficher_toutes(msg, page)
        return True

    if data.startswith("rech_boostees_"):
        page = int(data.replace("rech_boostees_", ""))
        await afficher_boostees(msg, page)
        return True

    if data.startswith("rech_jeu_"):
        jeu = data.replace("rech_jeu_", "")
        resultats = filter_annonces({"jeu": jeu})
        await afficher_resultats(msg, resultats, 0, {"jeu": jeu}, f"rech_jeu_{jeu}_p")
        return True

    if data.startswith("rech_jeu_") and "_p" in data:
        parts = data.split("_p")
        jeu = parts[0].replace("rech_jeu_", "")
        page = int(parts[1])
        resultats = filter_annonces({"jeu": jeu})
        await afficher_resultats(msg, resultats, page, {"jeu": jeu}, f"rech_jeu_{jeu}_p")
        return True

    if data.startswith("rech_type_"):
        type_art = data.replace("rech_type_", "")
        resultats = filter_annonces({"type": type_art})
        await afficher_resultats(msg, resultats, 0, {"type": type_art}, f"rech_type_{type_art}_p")
        return True

    if data.startswith("rech_prix_"):
        prix = data.replace("rech_prix_", "")
        resultats = filter_annonces({"prix": prix})
        await afficher_resultats(msg, resultats, 0, {"prix": prix}, f"rech_prix_{prix}_p")
        return True

    # Recherche avancée
    if data == "rech_adv_jeu":
        await show_adv_jeu(msg)
        return True

    if data == "rech_adv_type":
        await show_adv_type(msg)
        return True

    if data == "rech_adv_prix":
        await show_adv_prix(msg)
        return True

    if data == "rech_adv_transaction":
        await show_adv_transaction(msg)
        return True

    if data.startswith("rech_adv_set_jeu_"):
        jeu = data.replace("rech_adv_set_jeu_", "")
        ctx.user_data.setdefault("rech_filtres", {})["jeu"] = jeu
        await msg.reply_text(f"✅ Jeu : *{jeu}*", parse_mode="Markdown")
        return True

    if data.startswith("rech_adv_set_type_"):
        type_art = data.replace("rech_adv_set_type_", "")
        ctx.user_data.setdefault("rech_filtres", {})["type"] = type_art
        await msg.reply_text(f"✅ Type : *{type_art}*", parse_mode="Markdown")
        return True

    if data.startswith("rech_adv_set_prix_"):
        prix = data.replace("rech_adv_set_prix_", "")
        ctx.user_data.setdefault("rech_filtres", {})["prix"] = prix
        await msg.reply_text(f"✅ Prix : *{prix}*", parse_mode="Markdown")
        return True

    if data.startswith("rech_adv_set_trx_"):
        trx = data.replace("rech_adv_set_trx_", "")
        ctx.user_data.setdefault("rech_filtres", {})["transaction"] = trx
        await msg.reply_text(f"✅ Transaction : *{trx}*", parse_mode="Markdown")
        return True

    if data.startswith("rech_adv_lancer_"):
        page = int(data.replace("rech_adv_lancer_", ""))
        filtres = ctx.user_data.get("rech_filtres", {})
        resultats = filter_annonces(filtres)
        await afficher_resultats(msg, resultats, page, filtres, "rech_adv_lancer")
        return True

    return False

async def handle_recherche_input(update, ctx) -> bool:
    """Gère la recherche par texte libre."""
    state = ctx.user_data.get("rech_state")
    if state != "texte_libre":
        return False

    texte = update.message.text.strip()
    resultats = filter_annonces({"texte": texte})
    await afficher_resultats(
        update.message, resultats, 0,
        {"texte": texte}, f"rech_texte_{texte[:10]}_p"
    )
    ctx.user_data.pop("rech_state", None)
    return True
