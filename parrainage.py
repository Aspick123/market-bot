"""
╔══════════════════════════════════════════════════════════════╗
║              MODULE 8 — PARRAINAGE.PY                        ║
║  • Système de parrainage avec lien unique                    ║
║  • Badge + avantages pour le parrain                         ║
║  • Classement des parrains actifs                            ╚══════════════════════════════════════════════════════════════╝
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, get_user, save_user,
    format_date, niveau_label
)

# ══════════════════════════════════════════════════════════════
#  UTILITAIRES PARRAINAGE
# ══════════════════════════════════════════════════════════════

def get_parrainage_user(user_id: int) -> dict:
    parrainage = mdb_read("parrainage.json")
    uid = str(user_id)
    if uid not in parrainage:
        parrainage[uid] = {
            "filleuls": [],
            "total_parraines": 0,
            "points_parrainage": 0,
            "date_premier": None
        }
        mdb_write("parrainage.json", parrainage)
    return parrainage[uid]

def save_parrainage_user(user_id: int, data: dict):
    parrainage = mdb_read("parrainage.json")
    parrainage[str(user_id)] = data
    mdb_write("parrainage.json", parrainage)

def enregistrer_parrainage(parrain_id: int, filleul_id: int) -> bool:
    """Enregistre un nouveau parrainage."""
    if parrain_id == filleul_id:
        return False

    parrainage = get_parrainage_user(parrain_id)
    if filleul_id in parrainage["filleuls"]:
        return False

    parrainage["filleuls"].append(filleul_id)
    parrainage["total_parraines"] += 1
    parrainage["points_parrainage"] = parrainage.get("points_parrainage", 0) + 10
    if not parrainage.get("date_premier"):
        parrainage["date_premier"] = format_date()
    save_parrainage_user(parrain_id, parrainage)

    # Mettre à jour le filleul
    filleul = get_user(filleul_id)
    filleul["parrain_id"] = parrain_id
    save_user(filleul_id, filleul)

    # Badge parrain si 3+ filleuls
    parrain_user = get_user(parrain_id)
    if parrainage["total_parraines"] >= 3:
        badges = parrain_user.get("badges", [])
        if "parrain" not in badges:
            badges.append("parrain")
            parrain_user["badges"] = badges
            save_user(parrain_id, parrain_user)

    # Points gamification
    gamif = mdb_read("gamification.json")
    uid = str(parrain_id)
    gamif.setdefault(uid, {"points": 0, "defis": {}})
    gamif[uid]["points"] = gamif[uid].get("points", 0) + 10
    mdb_write("gamification.json", gamif)

    return True

# ══════════════════════════════════════════════════════════════
#  MENU PARRAINAGE
# ══════════════════════════════════════════════════════════════

async def show_menu_parrainage(message, user_id: int, bot):
    parrainage = get_parrainage_user(user_id)
    bot_info = await bot.get_me()
    lien = f"https://t.me/{bot_info.username}?start=parrain_{user_id}"

    total = parrainage.get("total_parraines", 0)
    points = parrainage.get("points_parrainage", 0)

    kb = [
        [InlineKeyboardButton("📋 Mes filleuls", callback_data="parrain_mes_filleuls")],
        [InlineKeyboardButton("🏆 Classement parrains", callback_data="parrain_leaderboard")],
        [InlineKeyboardButton("🎁 Mes avantages", callback_data="parrain_avantages")],
    ]

    await message.reply_text(
        f"🎁 *Mon Parrainage*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Filleuls : *{total}*\n"
        f"⚡ Points gagnés : *{points}*\n\n"
        f"🔗 *Ton lien de parrainage :*\n"
        f"`{lien}`\n\n"
        f"💡 Partage ce lien — chaque ami\n"
        f"qui s'inscrit te rapporte *10 points* !",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_mes_filleuls(message, user_id: int):
    parrainage = get_parrainage_user(user_id)
    filleuls = parrainage.get("filleuls", [])

    if not filleuls:
        await message.reply_text(
            "👥 *Mes filleuls*\n\nAucun filleul pour le moment.\n"
            "Partage ton lien pour en avoir !",
            parse_mode="Markdown"
        )
        return

    msg = f"👥 *Mes filleuls* ({len(filleuls)})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for fid in filleuls[-20:]:
        fu = get_user(fid)
        nom = fu.get("profil",{}).get("nom","") or f"User{str(fid)[-4:]}"
        msg += f"• *{nom}* — depuis {fu.get('joined','?')}\n"

    await message.reply_text(msg, parse_mode="Markdown")

async def show_avantages_parrainage(message, user_id: int):
    parrainage = get_parrainage_user(user_id)
    total = parrainage.get("total_parraines", 0)
    points = parrainage.get("points_parrainage", 0)

    paliers = [
        (1,  "🎯 1 filleul",  "Badge Parrain débloqué"),
        (3,  "🥉 3 filleuls", "Badge Parrain Actif + 30 pts bonus"),
        (5,  "🥈 5 filleuls", "Annonce boostée offerte"),
        (10, "🥇 10 filleuls","Statut Premium + 100 pts bonus"),
        (20, "👑 20 filleuls","Top Parrain + avantages exclusifs"),
    ]

    msg = (
        f"🎁 *Avantages Parrainage*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Filleuls actuels : *{total}*\n"
        f"Points accumulés : *{points}*\n\n"
        f"*Paliers de récompenses :*\n\n"
    )
    for nb, label, avantage in paliers:
        etat = "✅" if total >= nb else "🔒"
        msg += f"{etat} *{label}*\n  → {avantage}\n\n"

    await message.reply_text(msg, parse_mode="Markdown")

async def show_leaderboard_parrainage(message):
    parrainage = mdb_read("parrainage.json")
    classement = []
    for uid, data in parrainage.items():
        total = data.get("total_parraines", 0)
        if total > 0:
            user = get_user(int(uid))
            nom = user.get("profil",{}).get("nom","") or f"User{uid[-4:]}"
            classement.append({"nom": nom, "total": total, "points": data.get("points_parrainage",0)})

    classement.sort(key=lambda x: x["total"], reverse=True)

    if not classement:
        await message.reply_text("🏆 Aucun parrain pour le moment.")
        return

    medailles = ["🥇","🥈","🥉"]
    msg = "🏆 *Classement Parrains*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, entry in enumerate(classement[:10]):
        med = medailles[i] if i < 3 else f"{i+1}."
        msg += f"{med} *{entry['nom']}* — {entry['total']} filleuls ({entry['points']} pts)\n"

    await message.reply_text(msg, parse_mode="Markdown")

async def handle_parrainage_start(update, ctx, bot, super_admin_id: int):
    """Gère le lien de parrainage au démarrage."""
    args = ctx.args
    if not args:
        return False

    arg = args[0]
    if not arg.startswith("parrain_"):
        return False

    try:
        parrain_id = int(arg.replace("parrain_", ""))
        filleul_id = update.effective_user.id

        if parrain_id == filleul_id:
            return False

        success = enregistrer_parrainage(parrain_id, filleul_id)
        if success:
            try:
                parrain_user = get_user(parrain_id)
                nom_parrain = parrain_user.get("profil",{}).get("nom","") or f"User{str(parrain_id)[-4:]}"
                await update.message.reply_text(
                    f"🎁 *Tu as été parrainé par {nom_parrain} !*\n\n"
                    f"Bienvenue sur le Marketplace ! 🎮",
                    parse_mode="Markdown"
                )
                await bot.send_message(
                    parrain_id,
                    f"🎉 *Nouveau filleul !*\n\n"
                    f"@{update.effective_user.username or update.effective_user.first_name}\n"
                    f"a rejoint via ton lien !\n\n"
                    f"+10 points de parrainage 🎁",
                    parse_mode="Markdown"
                )
            except: pass
    except: pass
    return False

async def handle_parrainage_callbacks(query, ctx, bot) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data == "menu_parrainage":
        await show_menu_parrainage(msg, uid, bot)
        return True

    if data == "parrain_mes_filleuls":
        await show_mes_filleuls(msg, uid)
        return True

    if data == "parrain_leaderboard":
        await show_leaderboard_parrainage(msg)
        return True

    if data == "parrain_avantages":
        await show_avantages_parrainage(msg, uid)
        return True

    return False
