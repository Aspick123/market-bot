"""
╔══════════════════════════════════════════════════════════════╗
║           MODULE 11 — ADMIN_MARKET.PY                        ║
║  • Panel admin complet                                       ║
║  • Gestion équipe + rôles                                    ║
║  • Profils vendeurs (accès téléphone)                        ║
║  • Configuration générale                                    ║
║  • Blacklist publique                                        ║
╚══════════════════════════════════════════════════════════════╝
"""

import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database_market import (
    mdb_read, mdb_write, mdb_config, get_user, save_user,
    get_annonce, save_annonce, get_litige, get_all_users,
    add_to_blacklist, get_blacklist, add_log, format_date,
    set_role, get_role, has_perm, ROLES_EQUIPE, PERMISSIONS,
    get_team_ids_by_role, get_all_team_ids
)

# ══════════════════════════════════════════════════════════════
#  PANEL ADMIN PRINCIPAL
# ══════════════════════════════════════════════════════════════

async def show_admin_panel(message, user_id: int, super_admin_id: int):
    role = get_role(user_id, super_admin_id)
    role_label = ROLES_EQUIPE.get(role, "?")

    kb = []
    if has_perm(user_id, "valider_annonces", super_admin_id):
        annonces = mdb_read("annonces.json")
        nb_attente = sum(1 for a in annonces.values() if a.get("statut") == "en_attente")
        label = f"📋 Annonces en attente ({nb_attente})" if nb_attente else "📋 Annonces"
        kb.append([InlineKeyboardButton(label, callback_data="adm_annonces_attente")])

    if has_perm(user_id, "gerer_litiges", super_admin_id):
        litiges = mdb_read("litiges.json")
        nb_lit = sum(1 for l in litiges.values() if l.get("statut") in ["ouvert","en_cours"])
        label = f"⚖️ Litiges ({nb_lit})" if nb_lit else "⚖️ Litiges"
        kb.append([InlineKeyboardButton(label, callback_data="adm_litiges")])

    if has_perm(user_id, "aider_membres", super_admin_id):
        kb.append([InlineKeyboardButton("🎧 Support membres", callback_data="adm_support")])

    if has_perm(user_id, "gerer_securite", super_admin_id):
        kb.append([InlineKeyboardButton("🔒 Sécurité & Blacklist", callback_data="adm_securite")])

    if has_perm(user_id, "voir_stats", super_admin_id):
        kb.append([InlineKeyboardButton("📊 Dashboard stats", callback_data="adm_dashboard")])

    if has_perm(user_id, "modifier_cgu", super_admin_id):
        kb.append([InlineKeyboardButton("📋 Gérer CGU", callback_data="adm_cgu")])

    if has_perm(user_id, "nommer_moderateur", super_admin_id):
        kb.append([InlineKeyboardButton("👥 Gérer l'équipe", callback_data="adm_equipe")])

    if has_perm(user_id, "configurer", super_admin_id):
        kb.append([InlineKeyboardButton("⚙️ Configuration", callback_data="adm_config")])

    if has_perm(user_id, "exporter_donnees", super_admin_id):
        kb.append([InlineKeyboardButton("📤 Exporter données", callback_data="adm_exporter")])

    if has_perm(user_id, "mode_urgence", super_admin_id):
        kb.append([InlineKeyboardButton("🚨 Mode urgence", callback_data="adm_urgence")])

    kb.append([InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard")])
    kb.append([InlineKeyboardButton("❌ Fermer", callback_data="adm_close")])

    await message.reply_text(
        f"🔐 *Panel Admin — Marketplace*\n"
        f"Rôle : {role_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ══════════════════════════════════════════════════════════════
#  GESTION ANNONCES EN ATTENTE
# ══════════════════════════════════════════════════════════════

async def show_annonces_attente(message):
    annonces = mdb_read("annonces.json")
    en_attente = [(aid, a) for aid, a in annonces.items() if a.get("statut") == "en_attente"]

    if not en_attente:
        await message.reply_text(
            "✅ Aucune annonce en attente de validation.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Retour", callback_data="adm_market_panel")
            ]])
        )
        return

    msg = f"📋 *Annonces en attente* ({len(en_attente)})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    kb = []
    for aid, ann in en_attente[:10]:
        msg += (
            f"🎫 *{aid}*\n"
            f"👤 @{ann.get('vendeur_username','?')}\n"
            f"🎮 {ann.get('jeu','?')} | {ann.get('titre','?')[:25]}\n"
            f"💰 {ann.get('prix','?')}\n\n"
        )
        kb.append([
            InlineKeyboardButton(f"✅ {aid}", callback_data=f"adm_valider_{aid}"),
            InlineKeyboardButton(f"❌ {aid}", callback_data=f"adm_refuser_{aid}")
        ])

    kb.append([InlineKeyboardButton("🔙 Retour", callback_data="adm_market_panel")])
    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  GESTION SÉCURITÉ
# ══════════════════════════════════════════════════════════════

async def show_securite_menu(message):
    bl = get_blacklist()
    kb = [
        [InlineKeyboardButton(f"🚫 Blacklist ({len(bl)})", callback_data="adm_voir_blacklist")],
        [InlineKeyboardButton("➕ Blacklister un user", callback_data="adm_blacklister")],
        [InlineKeyboardButton("➖ Retirer de la blacklist", callback_data="adm_unblacklister")],
        [InlineKeyboardButton("⚠️ Avertir un user", callback_data="adm_avertir")],
        [InlineKeyboardButton("🔴 Suspendre un user", callback_data="adm_suspendre")],
        [InlineKeyboardButton("🔙 Retour", callback_data="adm_market_panel")],
    ]
    await message.reply_text(
        "🔒 *Sécurité & Modération*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_blacklist(message):
    bl = get_blacklist()
    if not bl:
        await message.reply_text("✅ Blacklist vide.")
        return

    msg = f"🚫 *Blacklist publique* ({len(bl)})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for entry in bl[-20:]:
        msg += (
            f"🆔 `{entry['user_id']}`\n"
            f"📋 {entry.get('raison','?')}\n"
            f"📅 {entry.get('date','?')}\n\n"
        )
    await message.reply_text(msg, parse_mode="Markdown")

async def show_blacklist_publique(message):
    """Version publique de la blacklist — sans les détails."""
    bl = get_blacklist()
    if not bl:
        await message.reply_text(
            "✅ *Blacklist*\n\nAucun arnaqueur signalé pour le moment.",
            parse_mode="Markdown"
        )
        return

    msg = f"🚫 *Arnaqueurs connus* ({len(bl)})\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for entry in bl:
        user = get_user(entry["user_id"])
        nom = user.get("profil",{}).get("nom","") or f"User{str(entry['user_id'])[-4:]}"
        msg += f"🚫 *{nom}* — {entry.get('raison','Arnaque')}\n"

    await message.reply_text(msg, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  GESTION ÉQUIPE
# ══════════════════════════════════════════════════════════════

async def show_equipe_menu(message, super_admin_id: int):
    team = mdb_read("team.json")
    kb = [
        [InlineKeyboardButton("➕ Ajouter un membre", callback_data="adm_equipe_ajouter")],
        [InlineKeyboardButton("📋 Voir l'équipe", callback_data="adm_equipe_liste")],
        [InlineKeyboardButton("➖ Révoquer un rôle", callback_data="adm_equipe_revoquer")],
        [InlineKeyboardButton("📊 Rapport équipe", callback_data="adm_equipe_rapport")],
        [InlineKeyboardButton("🔙 Retour", callback_data="adm_market_panel")],
    ]
    await message.reply_text(
        f"👥 *Gestion Équipe* ({len(team)} membres)\n━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_equipe_liste(message, super_admin_id: int):
    team = mdb_read("team.json")
    msg = f"👥 *Équipe Marketplace*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"👑 Super Admin : `{super_admin_id}`\n\n"

    roles_order = ["admin", "mod_annonces", "mod_litiges", "support", "mod_securite"]
    for role_key in roles_order:
        membres = [(uid, d) for uid, d in team.items() if d.get("role") == role_key]
        if membres:
            msg += f"*{ROLES_EQUIPE.get(role_key,'?')}*\n"
            for uid, d in membres:
                msg += f"  • `{uid}` — depuis {d.get('date','?')}\n"
            msg += "\n"

    await message.reply_text(msg, parse_mode="Markdown")

async def show_rapport_equipe(message, bot, super_admin_id: int):
    """Génère le rapport d'activité de l'équipe."""
    logs = mdb_read("logs.json")
    team = mdb_read("team.json")
    now = datetime.datetime.now()
    une_semaine = now - datetime.timedelta(days=7)

    stats_equipe = {}
    for log in logs:
        try:
            date_log = datetime.datetime.strptime(log["date"], "%d/%m/%Y %H:%M")
            if date_log < une_semaine:
                continue
            uid = str(log.get("user_id", ""))
            if uid in team or int(uid) == super_admin_id if uid.isdigit() else False:
                stats_equipe.setdefault(uid, {"actions": 0, "types": {}})
                stats_equipe[uid]["actions"] += 1
                action = log.get("action", "?")
                stats_equipe[uid]["types"][action] = stats_equipe[uid]["types"].get(action, 0) + 1
        except: pass

    msg = f"📊 *Rapport Équipe — 7 derniers jours*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if not stats_equipe:
        msg += "Aucune activité enregistrée."
    else:
        for uid, stats in stats_equipe.items():
            role = get_role(int(uid) if uid.isdigit() else 0, super_admin_id)
            role_label = ROLES_EQUIPE.get(role, "?")
            msg += f"👤 `{uid}` — {role_label}\n"
            msg += f"  ⚡ Actions : {stats['actions']}\n"
            top_actions = sorted(stats["types"].items(), key=lambda x: x[1], reverse=True)[:3]
            for action, nb in top_actions:
                msg += f"  • {action} : {nb}x\n"
            msg += "\n"

    await message.reply_text(msg, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION GÉNÉRALE
# ══════════════════════════════════════════════════════════════

async def show_config_menu(message):
    config = mdb_config()
    kb = [
        [InlineKeyboardButton(f"📋 Max annonces/user ({config.get('max_annonces_par_user',3)})",
                              callback_data="adm_config_max_ann")],
        [InlineKeyboardButton(f"⏰ Durée annonce ({config.get('duree_annonce_jours',30)}j)",
                              callback_data="adm_config_duree")],
        [InlineKeyboardButton(f"🚀 Durée boost ({config.get('boost_duree_jours',7)}j)",
                              callback_data="adm_config_boost")],
        [InlineKeyboardButton(f"⏱️ Délai anti-arnaque ({config.get('delai_anti_arnaque_minutes',5)}min)",
                              callback_data="adm_config_delai")],
        [InlineKeyboardButton(f"🚩 Signalements avant suspension ({config.get('signalements_avant_suspension',3)})",
                              callback_data="adm_config_signalements")],
        [InlineKeyboardButton("📢 Définir canal ID", callback_data="adm_config_canal")],
        [InlineKeyboardButton("🔙 Retour", callback_data="adm_market_panel")],
    ]
    await message.reply_text(
        "⚙️ *Configuration Marketplace*\n━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def modifier_config(message, ctx, cle: str, valeur):
    config = mdb_config()
    config[cle] = valeur
    mdb_write("config.json", config)
    await message.reply_text(f"✅ *{cle}* → `{valeur}`", parse_mode="Markdown")
    ctx.user_data.pop("adm_config_state", None)
    add_log(f"CONFIG_{cle.upper()}", str(valeur), message.from_user.id)

# ══════════════════════════════════════════════════════════════
#  VOIR PROFIL COMPLET (ADMIN)
# ══════════════════════════════════════════════════════════════

async def show_profil_complet_admin(message, target_id: int):
    """Affiche le profil complet d'un utilisateur (avec infos privées)."""
    user = get_user(target_id)
    profil = user.get("profil", {})
    stats = user.get("stats", {})

    from database_market import get_reputation
    rep = mdb_read("reputation.json").get(str(target_id), {})

    msg = (
        f"👤 *Profil Admin — {target_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌍 Nationalité : {profil.get('nationalite','?')}\n"
        f"📱 Téléphone : `{profil.get('telephone','Non renseigné')}`\n"
        f"💬 WhatsApp : {profil.get('whatsapp','?')}\n"
        f"📸 Instagram : {profil.get('instagram','?')}\n\n"
        f"📊 *Stats :*\n"
        f"  Ventes : {stats.get('ventes',0)}\n"
        f"  Achats : {stats.get('achats',0)}\n"
        f"  Litiges : {stats.get('litiges_ouverts',0)}\n"
        f"  Avertissements : {user.get('avertissements',0)}\n"
        f"  Suspendu : {'⛔ Oui' if user.get('suspendu') else '✅ Non'}\n"
        f"  Blacklisté : {'🚫 Oui' if user.get('blackliste') else '✅ Non'}\n\n"
        f"⭐ Note : {rep.get('note_moyenne',0):.1f} ({rep.get('nb_avis',0)} avis)\n"
        f"📅 Membre depuis : {user.get('joined','?')}\n"
        f"✅ CGU acceptée : {'Oui' if user.get('cgu_acceptee') else 'Non'}\n"
        f"📋 Version CGU : {user.get('cgu_version_acceptee','?')}"
    )

    kb = [
        [InlineKeyboardButton("⚠️ Avertir", callback_data=f"adm_avertir_user_{target_id}"),
         InlineKeyboardButton("🚫 Blacklister", callback_data=f"adm_bl_user_{target_id}")],
        [InlineKeyboardButton("📋 Ses annonces", callback_data=f"annonces_user_{target_id}")],
    ]
    await message.reply_text(msg, parse_mode="Markdown",
                             reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_admin_market_callbacks(query, ctx, bot, super_admin_id: int) -> bool:
    data = query.data
    msg = query.message
    uid = query.from_user.id

    if data == "adm_market_panel":
        await show_admin_panel(msg, uid, super_admin_id)
        return True

    if data == "adm_annonces_attente":
        if not has_perm(uid, "valider_annonces", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        await show_annonces_attente(msg)
        return True

    if data == "adm_securite":
        if not has_perm(uid, "gerer_securite", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        await show_securite_menu(msg)
        return True

    if data == "adm_voir_blacklist":
        await show_blacklist(msg)
        return True

    if data == "menu_blacklist_publique":
        await show_blacklist_publique(msg)
        return True

    if data == "adm_blacklister":
        if not has_perm(uid, "blacklister", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        ctx.user_data["adm_state"] = "blacklister_id"
        await msg.reply_text("🚫 ID Telegram à blacklister :")
        return True

    if data.startswith("adm_bl_user_"):
        target_id = int(data.replace("adm_bl_user_", ""))
        ctx.user_data["adm_state"] = "blacklister_raison"
        ctx.user_data["adm_data"] = {"target_id": target_id}
        await msg.reply_text(f"🚫 Raison du blacklist pour `{target_id}` :", parse_mode="Markdown")
        return True

    if data == "adm_unblacklister":
        ctx.user_data["adm_state"] = "unblacklister"
        await msg.reply_text("➖ ID Telegram à retirer de la blacklist :")
        return True

    if data == "adm_avertir":
        if not has_perm(uid, "avertir", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        ctx.user_data["adm_state"] = "avertir_id"
        ctx.user_data["adm_data"] = {}
        await msg.reply_text("⚠️ ID Telegram à avertir :")
        return True

    if data.startswith("adm_avertir_user_"):
        target_id = int(data.replace("adm_avertir_user_", ""))
        ctx.user_data["adm_state"] = "avertir_message"
        ctx.user_data["adm_data"] = {"target_id": target_id}
        await msg.reply_text(f"⚠️ Message d'avertissement pour `{target_id}` :", parse_mode="Markdown")
        return True

    if data == "adm_suspendre":
        if not has_perm(uid, "suspendre", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        ctx.user_data["adm_state"] = "suspendre_id"
        ctx.user_data["adm_data"] = {}
        await msg.reply_text("🔴 ID Telegram à suspendre :")
        return True

    if data == "adm_equipe":
        if not has_perm(uid, "nommer_moderateur", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        await show_equipe_menu(msg, super_admin_id)
        return True

    if data == "adm_equipe_liste":
        await show_equipe_liste(msg, super_admin_id)
        return True

    if data == "adm_equipe_rapport":
        await show_rapport_equipe(msg, bot, super_admin_id)
        return True

    if data == "adm_equipe_ajouter":
        ctx.user_data["adm_state"] = "ajouter_membre_id"
        ctx.user_data["adm_data"] = {}
        await msg.reply_text("👤 ID Telegram du nouveau membre :")
        return True

    if data.startswith("adm_equipe_role_"):
        parts = data.replace("adm_equipe_role_", "").split("_")
        role_key = parts[-1]
        target_id = int("_".join(parts[:-1]))
        set_role(target_id, role_key, uid)
        add_log(f"ROLE_{role_key.upper()}", str(target_id), uid)
        await msg.reply_text(
            f"✅ `{target_id}` → {ROLES_EQUIPE.get(role_key,'?')}",
            parse_mode="Markdown"
        )
        try:
            await bot.send_message(
                target_id,
                f"🎉 Tu as été nommé *{ROLES_EQUIPE.get(role_key,'?')}*\n"
                f"sur le Marketplace ! Tape /admin pour accéder.",
                parse_mode="Markdown"
            )
        except: pass
        ctx.user_data.pop("adm_state", None)
        return True

    if data == "adm_equipe_revoquer":
        if uid != super_admin_id:
            await msg.reply_text("🚫 Seul le Super Admin peut révoquer.")
            return True
        ctx.user_data["adm_state"] = "revoquer_id"
        await msg.reply_text("➖ ID Telegram à révoquer :")
        return True

    if data == "adm_config":
        if not has_perm(uid, "configurer", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        await show_config_menu(msg)
        return True

    if data.startswith("adm_config_"):
        cle_map = {
            "adm_config_max_ann": ("max_annonces_par_user", "Nouveau max annonces (nombre entier) :"),
            "adm_config_duree": ("duree_annonce_jours", "Nouvelle durée en jours :"),
            "adm_config_boost": ("boost_duree_jours", "Durée du boost en jours :"),
            "adm_config_delai": ("delai_anti_arnaque_minutes", "Délai anti-arnaque en minutes :"),
            "adm_config_signalements": ("signalements_avant_suspension", "Nb signalements avant suspension :"),
            "adm_config_canal": ("canal_id", "ID du canal Telegram (ex: -1001234567890) :"),
        }
        if data in cle_map:
            cle, question = cle_map[data]
            ctx.user_data["adm_config_state"] = cle
            await msg.reply_text(question)
            return True

    if data == "adm_exporter":
        if not has_perm(uid, "exporter_donnees", super_admin_id):
            await msg.reply_text("🚫 Permission refusée.")
            return True
        import io, json
        users = mdb_read("users.json")
        bio = io.BytesIO(json.dumps(users, ensure_ascii=False, indent=2).encode())
        bio.name = f"users_market_{datetime.date.today()}.json"
        await msg.reply_document(document=bio, caption="📤 Export utilisateurs marketplace")
        return True

    if data == "adm_urgence":
        if not has_perm(uid, "mode_urgence", super_admin_id):
            await msg.reply_text("🚫 Seul le Super Admin peut activer le mode urgence.")
            return True
        kb = [[
            InlineKeyboardButton("🚨 CONFIRMER MODE URGENCE", callback_data="adm_urgence_confirmer"),
            InlineKeyboardButton("❌ Annuler", callback_data="adm_market_panel")
        ]]
        await msg.reply_text(
            "🚨 *Mode Urgence*\n\n"
            "Cela va suspendre TOUTES les nouvelles\n"
            "transactions. Confirmer ?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return True

    if data == "adm_urgence_confirmer":
        config = mdb_config()
        config["mode_urgence"] = True
        mdb_write("config.json", config)
        add_log("MODE_URGENCE_ACTIVE", "Toutes transactions suspendues", uid)
        await msg.reply_text(
            "🚨 *Mode urgence activé !*\n"
            "Toutes les nouvelles transactions sont suspendues.",
            parse_mode="Markdown"
        )
        return True

    if data == "adm_close":
        try:
            await msg.delete()
        except: pass
        return True

    if data == "adm_support":
        tickets = mdb_read("tickets.json") if hasattr(mdb_read, '__call__') else []
        await msg.reply_text(
            "🎧 *Support Membres*\n\nGestion des tickets d'aide.",
            parse_mode="Markdown"
        )
        return True

    return False

# ══════════════════════════════════════════════════════════════
#  HANDLER MESSAGES TEXTE ADMIN
# ══════════════════════════════════════════════════════════════

async def handle_admin_market_input(update, ctx, bot, super_admin_id: int) -> bool:
    state = ctx.user_data.get("adm_state")
    config_state = ctx.user_data.get("adm_config_state")
    text = update.message.text.strip() if update.message and update.message.text else ""
    uid = update.effective_user.id
    d = ctx.user_data.get("adm_data", {})

    # Config
    if config_state:
        try:
            if config_state == "canal_id":
                valeur = text
            else:
                valeur = int(text)
            await modifier_config(update.message, ctx, config_state, valeur)
        except ValueError:
            await update.message.reply_text("⚠️ Valeur invalide.")
        ctx.user_data.pop("adm_config_state", None)
        return True

    if not state:
        return False

    if state == "blacklister_id":
        try:
            d["target_id"] = int(text)
            ctx.user_data["adm_data"] = d
            ctx.user_data["adm_state"] = "blacklister_raison"
            await update.message.reply_text("📋 Raison du blacklist :")
        except:
            await update.message.reply_text("⚠️ ID invalide.")
        return True

    if state == "blacklister_raison":
        target_id = d.get("target_id")
        if target_id:
            add_to_blacklist(target_id, text, uid)
            add_log("BLACKLIST", f"{target_id} — {text}", uid)
            await update.message.reply_text(f"🚫 `{target_id}` blacklisté.", parse_mode="Markdown")
            try:
                await bot.send_message(
                    target_id,
                    "🚫 *Ton compte a été blacklisté.*\n\nRaison : " + text,
                    parse_mode="Markdown"
                )
            except: pass
        ctx.user_data.pop("adm_state", None)
        ctx.user_data.pop("adm_data", None)
        return True

    if state == "unblacklister":
        try:
            target_id = int(text)
            bl = get_blacklist()
            new_bl = [b for b in bl if b["user_id"] != target_id]
            mdb_write("blacklist.json", new_bl)
            user = get_user(target_id)
            user["blackliste"] = False
            save_user(target_id, user)
            add_log("UNBLACKLIST", str(target_id), uid)
            await update.message.reply_text(f"✅ `{target_id}` retiré de la blacklist.", parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ ID invalide.")
        ctx.user_data.pop("adm_state", None)
        return True

    if state == "avertir_id":
        try:
            d["target_id"] = int(text)
            ctx.user_data["adm_data"] = d
            ctx.user_data["adm_state"] = "avertir_message"
            await update.message.reply_text("✉️ Message d'avertissement :")
        except:
            await update.message.reply_text("⚠️ ID invalide.")
        return True

    if state == "avertir_message":
        target_id = d.get("target_id")
        if target_id:
            user = get_user(target_id)
            user["avertissements"] = user.get("avertissements", 0) + 1
            save_user(target_id, user)
            add_log("AVERTISSEMENT", f"{target_id} — {text}", uid)
            try:
                await bot.send_message(
                    target_id,
                    f"⚠️ *Avertissement officiel*\n\n{text}\n\n"
                    f"_Avertissements : {user['avertissements']}_",
                    parse_mode="Markdown"
                )
            except: pass
            await update.message.reply_text(f"✅ Avertissement envoyé à `{target_id}`.", parse_mode="Markdown")
        ctx.user_data.pop("adm_state", None)
        ctx.user_data.pop("adm_data", None)
        return True

    if state == "suspendre_id":
        try:
            d["target_id"] = int(text)
            ctx.user_data["adm_data"] = d
            ctx.user_data["adm_state"] = "suspendre_jours"
            await update.message.reply_text("⏰ Durée de suspension en jours :")
        except:
            await update.message.reply_text("⚠️ ID invalide.")
        return True

    if state == "suspendre_jours":
        target_id = d.get("target_id")
        try:
            jours = int(text)
            user = get_user(target_id)
            user["suspendu"] = True
            user["suspension_fin"] = (datetime.datetime.now() + datetime.timedelta(days=jours)).strftime("%d/%m/%Y")
            save_user(target_id, user)
            add_log("SUSPENSION", f"{target_id} — {jours}j", uid)
            await update.message.reply_text(f"🔴 `{target_id}` suspendu pour {jours} jours.", parse_mode="Markdown")
            try:
                await bot.send_message(target_id,
                    f"🔴 *Compte suspendu {jours} jours.*\nFin : {user['suspension_fin']}",
                    parse_mode="Markdown")
            except: pass
        except:
            await update.message.reply_text("⚠️ Durée invalide.")
        ctx.user_data.pop("adm_state", None)
        ctx.user_data.pop("adm_data", None)
        return True

    if state == "ajouter_membre_id":
        try:
            d["target_id"] = int(text)
            ctx.user_data["adm_data"] = d
            ctx.user_data["adm_state"] = "ajouter_membre_role"
            roles_dispo = ["mod_annonces","mod_litiges","support","mod_securite"]
            if has_perm(uid, "nommer_admin", super_admin_id):
                roles_dispo.insert(0, "admin")
            kb = [[InlineKeyboardButton(ROLES_EQUIPE.get(r,"?"),
                   callback_data=f"adm_equipe_role_{d['target_id']}_{r}")] for r in roles_dispo]
            await update.message.reply_text("🎭 Quel rôle ?",
                                            reply_markup=InlineKeyboardMarkup(kb))
        except:
            await update.message.reply_text("⚠️ ID invalide.")
        return True

    if state == "revoquer_id":
        try:
            target_id = int(text)
            team = mdb_read("team.json")
            if str(target_id) in team:
                del team[str(target_id)]
                mdb_write("team.json", team)
                add_log("REVOCATION", str(target_id), uid)
                await update.message.reply_text(f"✅ Rôle de `{target_id}` révoqué.", parse_mode="Markdown")
                try:
                    await bot.send_message(target_id, "ℹ️ Ton rôle dans le marketplace a été révoqué.")
                except: pass
            else:
                await update.message.reply_text("❌ Membre introuvable.")
        except:
            await update.message.reply_text("⚠️ ID invalide.")
        ctx.user_data.pop("adm_state", None)
        return True

    return False
