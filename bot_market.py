import os
import time
import logging
from threading import Thread
from flask import Flask
from bson.objectid import ObjectId

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

from database_market import (
    db,
    get_user,
    save_user,
    get_role_label,
    is_flooded,
    is_mode_urgence
)
from menus import get_main_menu_keyboard, get_back_to_start_keyboard
from moderation import soumettre_a_la_moderation, traitement_moderation
from profil import afficher_profil, gestion_candidature

# États de la conversation
(
    CHOIX_CATEGORIE, ATTENTE_AUTRE_JEU, CHOIX_PLATEFORME, CHOIX_SPECIFICITES,
    ATTENTE_VALEURS_SPECS, ATTENTE_PHOTOS, ATTENTE_DESCRIPTION, CHOIX_DEVISE,
    ATTENTE_AUTRE_DEVISE, ATTENTE_PRIX, CHOIX_PAIEMENT, CHOIX_CRYPTO,
    ATTENTE_CONTACT, ATTENTE_DISPO, CONFIRMATION
) = range(15)

ATTENTE_RECHERCHE_JEU = 99
ATTENTE_MODIF_PRIX = 100
ATTENTE_MODIF_DESC = 101

app = Flask("")

@app.route("/")
def home():
    return "Le Marketplace Bot est opérationnel !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAFxtyQig1cNZDvYF1PnTTbOlDOW1POlrx4")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
CANAL_VENTE_ID = os.environ.get("CANAL_VENTE_ID", "@TonCanalDeVente") 

# --- FONCTION DE VÉRIFICATION EN TEMPS RÉEL ---
async def verifier_abonnement_canal(ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        membre = await ctx.bot.get_chat_member(chat_id=CANAL_VENTE_ID, user_id=user_id)
        if membre.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception as e:
        logger.error(f"Erreur vérification canal : {e}")
        return False

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    
    # 🔐 SÉCURITÉ : Vérification d'abonnement immédiat
    est_abonne = await verifier_abonnement_canal(ctx, uid)
    if not est_abonne and uid != SUPER_ADMIN_ID:
        texte_bloque = (
            f"🚀 **Pour utiliser ce bot, vous devez d'ici là rejoindre notre canal officiel !**\n\n"
            f"👉 Rejoignez ici : {CANAL_VENTE_ID}\n\n"
            f"Une fois rejoint, réécrivez /start pour débloquer le Marketplace."
        )
        kb_rejoin = [[InlineKeyboardButton("📢 Rejoindre le Canal", url=f"https://t.me/{CANAL_VENTE_ID.replace('@','')}")]]
        
        if update.callback_query:
            await update.callback_query.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="Markdown")
        else:
            await update.message.reply_text(texte_bloque, reply_markup=InlineKeyboardMarkup(kb_rejoin), parse_mode="Markdown")
        return ConversationHandler.END

    if is_mode_urgence() and uid != SUPER_ADMIN_ID:
        await update.effective_message.reply_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return ConversationHandler.END
        
    if is_flooded(uid):
        await update.effective_message.reply_text("⏳ Trop de requêtes. Veuillez patienter.")
        return ConversationHandler.END

    user_data = get_user(uid)
    if not user_data.get("username") or user_data["username"] != user.username:
        user_data["username"] = user.username or user.first_name
        save_user(uid, user_data)

    role_label = get_role_label(uid, SUPER_ADMIN_ID)
    welcome_text = (
        f"🎮 **Bienvenue sur le Marketplace, {user.first_name} !**\n"
        f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🎖️ **Rang :** {role_label}\n\n"
        f"🤝 *Achetez, vendez et échangez vos comptes de jeux et monnaies virtuelles en toute sécurité.*\n\n"
        f"👇 **Sélectionnez une option ci-dessous :**"
    )
    
    reply_markup = get_main_menu_keyboard(uid, SUPER_ADMIN_ID)
    boutons_modifies = []
    for ligne in reply_markup.inline_keyboard:
        boutons_modifies.append(ligne)
        for bouton in ligne:
            if "recherche" in bouton.callback_data:
                boutons_modifies.append([InlineKeyboardButton("📋 Parcourir toutes les offres", callback_data="menu:liste_offres")])
                break

    reply_markup_modifie = InlineKeyboardMarkup(boutons_modifies)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup_modifie, parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup_modifie, parse_mode="Markdown")
    return ConversationHandler.END

# ==================== LOGIQUE DE RECHERCHE & TUNNEL DE VENTE ====================

async def debut_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.callback_query.answer("⚠️ Vous devez rester dans le canal pour utiliser le bot !", show_alert=True)
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🔍 **Moteur de Recherche Flash**\n\nEntrez le nom exact du jeu que vous recherchez :", parse_mode="Markdown")
    return ATTENTE_RECHERCHE_JEU

async def executer_recherche(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Action refusée. Vous avez quitté notre canal.")
        return ConversationHandler.END
    jeu_recherche = update.message.text.strip()
    annonce = db.annonces.find_one({"categorie": {"$regex": f"^{jeu_recherche}$", "$options": "i"}, "statut": "valide"})
    if annonce:
        await afficher_une_annonce(update.message.reply_text, annonce)
    else:
        await update.message.reply_text(f"🔴 **NON. Aucune annonce disponible** pour *{jeu_recherche}*.", reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
    return ConversationHandler.END

def generer_texte_annonce(annonce, username_vendeur):
    paiements = ", ".join(annonce.get("paiements", []))
    return (
        "🛒 **ANNONCE EN LIGNE — MARKETPLACE**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"🎮 **Jeu :** `{annonce['categorie']}`\n"
        f"💻 **Plateforme :** `{annonce.get('plateforme', 'Non spécifiée')}`\n"
        f"💰 **Prix :** `{annonce['prix']} {annonce['devise']}`\n"
        f"💳 **Paiements acceptés :** `{paiements}`\n"
        f"📝 **Description :**\n{annonce['description']}\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👤 **Vendeur :** @{username_vendeur}\n\n"
        "💡 *Conseil : Contactez d'abord le vendeur en privé.*"
    )

async def afficher_une_annonce(reply_func, annonce):
    vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
    username_vendeur = vendeur.get("username", "Inconnu") if vendeur else "Inconnu"
    texte_offre = generer_texte_annonce(annonce, username_vendeur)
    kb = [
        [InlineKeyboardButton("💬 Contacter le Vendeur", url=f"https://t.me/{username_vendeur}")],
        [InlineKeyboardButton("⚡ Sécuriser via un Gérant (Arbitrage)", callback_data=f"achat:arbitrage:{annonce['_id']}")],
        [InlineKeyboardButton("🔙 Menu Principal", callback_data="menu:retour_start")]
    ]
    await reply_func(texte_offre, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def synchroniser_modification_canal(ctx: ContextTypes.DEFAULT_TYPE, annonce_id):
    try:
        annonce = db.annonces.find_one({"_id": ObjectId(annonce_id)})
        if not annonce or "canal_message_id" not in annonce: return
        vendeur = db.users.find_one({"_id": annonce["vendeur_id"]})
        username_vendeur = vendeur.get("username", "Inconnu") if vendeur else "Inconnu"
        nouveau_texte = generer_texte_annonce(annonce, username_vendeur)
        kb_canal = [
            [InlineKeyboardButton("💬 Contacter le Vendeur", url=f"https://t.me/{username_vendeur}")],
            [InlineKeyboardButton("⚡ Demander un Arbitrage", url=f"https://t.me/{ctx.bot.username}?start=arbitrage_{annonce_id}")]
        ]
        await ctx.bot.edit_message_text(chat_id=CANAL_VENTE_ID, message_id=int(annonce["canal_message_id"]), text=nouveau_texte, reply_markup=InlineKeyboardMarkup(kb_canal), parse_mode="Markdown")
    except Exception as e: logger.error(f"Erreur synchro canal: {e}")

async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await verifier_abonnement_canal(ctx, update.effective_user.id) and update.effective_user.id != SUPER_ADMIN_ID:
        await update.callback_query.answer("⚠️ Vous devez rester dans le canal pour vendre !", show_alert=True)
        return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    ctx.user_data["photos"] = []
    ctx.user_data["vente_paiements"] = []
    await query.message.edit_text("🎮 **Étape 1 : Quel est le jeu concerné ?**\n\nEnvoyez le nom exact du jeu vidéo.", parse_mode="Markdown")
    return ATTENTE_AUTRE_JEU

async def autre_jeu_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_jeu"] = update.message.text.strip()
    kb = [
        [InlineKeyboardButton("📱 Android", callback_data="plat:Android")], [InlineKeyboardButton("🍏 iOS (Apple)", callback_data="plat:iOS")],
        [InlineKeyboardButton("💻 PC", callback_data="plat:PC")], [InlineKeyboardButton("🎮 Console (PS/Xbox)", callback_data="plat:Console")],
        [InlineKeyboardButton("🌐 Multiplateforme", callback_data="plat:Multi")]
    ]
    await update.message.reply_text("🎮 **Sur quelle plateforme se trouve votre compte ?**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return CHOIX_PLATEFORME

async def plateforme_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["vente_plateforme"] = query.data.replace("plat:", "")
    await query.message.edit_text("📸 **Étape 2 : Preuves en images**\n\nEnvoyez de 1 à 5 captures d'écran, puis écrivez **'FIN'**.", parse_mode="Markdown")
    return ATTENTE_PHOTOS

async def photos_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        if len(ctx.user_data["photos"]) < 5:
            ctx.user_data["photos"].append(photo_id)
            await update.message.reply_text(f"📸 Image reçue ({len(ctx.user_data['photos'])}/5). Continuez ou écrivez 'FIN'.")
        else: await update.message.reply_text("⚠️ Limite de 5 photos atteinte. Écrivez 'FIN'.")
        return ATTENTE_PHOTOS
    if update.message.text and update.message.text.upper() == "FIN":
        await update.message.reply_text("📝 **Veuillez entrer une description détaillée pour votre compte :**")
        return ATTENTE_DESCRIPTION
    return ATTENTE_PHOTOS

async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    kb = [[InlineKeyboardButton("💵 FCFA (XOF)", callback_data="devise:FCFA")], [InlineKeyboardButton("💵 Dollar ($)", callback_data="devise:USD")], [InlineKeyboardButton("💶 Euro (€)", callback_data="devise:EUR")]]
    await update.message.reply_text("💱 **Étape 3 : Choix de la devise**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ATTENTE_PRIX

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and query.data.startswith("devise:"):
        await query.answer()
        ctx.user_data["vente_devise"] = query.data.split(":")[1]
        await query.message.edit_text(f"💰 **Fixer le montant ({ctx.user_data['vente_devise']})**\n\nEntrez le prix (chiffres uniquement) :", parse_mode="Markdown")
        return ATTENTE_PRIX
    if update.message:
        texte_prix = update.message.text.strip()
        if not texte_prix.isdigit():
            await update.message.reply_text("❌ Chiffres uniquement :")
            return ATTENTE_PRIX
        ctx.user_data["vente_prix"] = int(texte_prix)
        return await afficher_choix_paiement(update.message.reply_text, ctx)

async def afficher_choix_paiement(reply_func, ctx):
    choix = ctx.user_data.get("vente_paiements", [])
    check = lambda m: "☑️" if m in choix else "⬜"
    kb = [[InlineKeyboardButton(f"{check('FCFA')} 💵 FCFA", callback_data="pay:FCFA")], [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (TRC20)", callback_data="pay:USDT")], [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")], [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]]
    await reply_func("💳 **Étape 4 : Moyens de paiement acceptés**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return CHOIX_PAIEMENT

async def paiement_choisi_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    choix = ctx.user_data.get("vente_paiements", [])
    if data == "pay:valider":
        if not choix:
            await query.message.edit_text("⚠️ Sélectionnez au moins un moyen de paiement.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Réessayer", callback_data="pay:refresh")]]))
            return CHOIX_PAIEMENT
        recap = f"🧐 **VÉRIFICATION DE VOTRE ANNONCE**\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n📦 **Jeu :** `{ctx.user_data.get('vente_jeu')}`\n💻 **Plateforme :** `{ctx.user_data.get('vente_plateforme')}`\n💰 **Prix :** `{ctx.user_data.get('vente_prix')} {ctx.user_data.get('vente_devise')}`\n💳 **Paiements :** `{', '.join(choix)}`\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\nSouhaitez-vous soumettre cette annonce ?"
        kb = [[InlineKeyboardButton("✅ Valider et Soumettre", callback_data="publier:oui")], [InlineKeyboardButton("❌ Tout annuler", callback_data="publier:non")]]
        await query.message.edit_text(recap, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return CONFIRMATION
    methode = data.replace("pay:", "")
    if methode in choix: choix.remove(methode)
    else: choix.append(methode)
    ctx.user_data["vente_paiements"] = choix
    check = lambda m: "☑️" if m in choix else "⬜"
    kb = [[InlineKeyboardButton(f"{check('FCFA')} 💵 FCFA", callback_data="pay:FCFA")], [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (TRC20)", callback_data="pay:USDT")], [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")], [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return CHOIX_PAIEMENT

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "publier:oui": await soumettre_a_la_moderation(update, ctx)
    else: await query.message.edit_text("❌ Création annulée.", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END

# ==================== MODIFICATIONS DE L'ESPACE VENDEUR ====================

async def executer_modification_prix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    nouveau_prix = update.message.text.strip()
    if not nouveau_prix.isdigit():
        await update.message.reply_text("❌ Veuillez entrer un montant valide :")
        return ATTENTE_MODIF_PRIX
    annonce_id = ctx.user_data.get("modif_annonce_id")
    if annonce_id:
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"prix": int(nouveau_prix)}})
        await synchroniser_modification_canal(ctx, annonce_id)
        await update.message.reply_text("✅ Prix mis à jour !", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END

async def executer_modification_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    nouvelle_desc = update.message.text.strip()
    annonce_id = ctx.user_data.get("modif_annonce_id")
    if annonce_id:
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"description": nouvelle_desc}})
        await synchroniser_modification_canal(ctx, annonce_id)
        await update.message.reply_text("✅ Description mise à jour !", reply_markup=get_back_to_start_keyboard())
    return ConversationHandler.END


# ==================== AIGUILLAGE CENTRAL DES INTERACTIONS (BOUTONS) ====================

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    # 🔒 BLOQUER TOUT LE MONDE SUR TOUS LES BOUTONS S'ILS ONT QUITTÉ LE CANAL
    if not await verifier_abonnement_canal(ctx, uid) and uid != SUPER_ADMIN_ID:
        await query.answer("🚨 Accès refusé ! Vous devez rejoindre notre canal pour interagir avec le bot.", show_alert=True)
        return

    if data == "menu:retour_start":
        await query.answer()
        await start_command(update, ctx)
        return

    if data == "menu:liste_offres":
        await query.answer()
        annonces_valides = list(db.annonces.find({"statut": "valide"}))
        if not annonces_valides:
            await query.message.edit_text("📦 Aucun compte en ligne pour le moment.", reply_markup=get_back_to_start_keyboard())
            return
        kb = []
        for index, anc in enumerate(annonces_valides):
            kb.append([InlineKeyboardButton(f"{index + 1}. {anc.get('categorie')} — {anc.get('prix')} {anc.get('devise')}", callback_data=f"voir_offre:{anc['_id']}")])
        kb.append([InlineKeyboardButton("🔙 Retour au Menu", callback_data="menu:retour_start")])
        await query.message.edit_text("📋 **LISTE DES OFFRES DISPONIBLES**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if data.startswith("voir_offre:"):
        await query.answer()
        annonce = db.annonces.find_one({"_id": ObjectId(data.split(":")[1])})
        if not annonce: return
        await query.message.delete()
        await afficher_une_annonce(query.message.reply_text, annonce)
        return

    if data == "menu:mes_annonces":
        await query.answer()
        mes_anc = list(db.annonces.find({"vendeur_id": uid, "statut": "valide"}))
        if not mes_anc:
            await query.message.edit_text("📦 Vous n'avez aucune annonce active.", reply_markup=get_back_to_start_keyboard())
            return
        kb = [[InlineKeyboardButton(f"⚙️ {anc['categorie']} — {anc['prix']} {anc['devise']}", callback_data=f"gerer_mon_annonce:{anc['_id']}")] for anc in mes_anc]
        kb.append([InlineKeyboardButton("🔙 Retour au Menu", callback_data="menu:retour_start")])
        await query.message.edit_text("⚙️ **GESTION DE VOS OFFRES**", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("gerer_mon_annonce:"):
        await query.answer()
        aid = data.split(":")[1]
        anc = db.annonces.find_one({"_id": ObjectId(aid)})
        if not anc: return
        texte_gestion = f"⚙️ **Gestion de votre annonce : {anc['categorie']}**\n\n💰 **Prix actuel :** `{anc['prix']} {anc['devise']}`\n📝 **Description :**\n{anc['description']}"
        kb = [
            [InlineKeyboardButton("💰 Modifier le Prix", callback_data=f"mon_annonce:modif_prix:{aid}")],
            [InlineKeyboardButton("📝 Modifier la Description", callback_data=f"mon_annonce:modif_desc:{aid}")],
            [InlineKeyboardButton("❌ Supprimer l'annonce", callback_data=f"mon_annonce:suppr:{aid}")],
            [InlineKeyboardButton("🔙 Annuler", callback_data="menu:mes_annonces")]
        ]
        await query.message.edit_text(texte_gestion, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if data.startswith("mon_annonce:suppr:"):
        await query.answer()
        aid = data.split(":")[2]
        try:
            anc = db.annonces.find_one({"_id": ObjectId(aid)})
            if anc and "canal_message_id" in anc:
                await ctx.bot.delete_message(chat_id=CANAL_VENTE_ID, message_id=int(anc["canal_message_id"]))
        except Exception as e: logger.error(e)
        db.annonces.delete_one({"_id": ObjectId(aid)})
        await query.message.edit_text("🗑️ Annonce supprimée avec succès !", reply_markup=get_back_to_start_keyboard())
        return

    if data.startswith("mon_annonce:modif_prix:"):
        await query.answer()
        ctx.user_data["modif_annonce_id"] = data.split(":")[2]
        await query.message.edit_text("💰 **Entrez le nouveau prix (chiffres uniquement) :**")
        return ATTENTE_MODIF_PRIX

    if data.startswith("mon_annonce:modif_desc:"):
        await query.answer()
        ctx.user_data["modif_annonce_id"] = data.split(":")[2]
        await query.message.edit_text("📝 **Envoyez la nouvelle description :**")
        return ATTENTE_MODIF_DESC

    if data.startswith("achat:arbitrage:"):
        await query.answer()
        annonce = db.annonces.find_one({"_id": ObjectId(data.split(":")[2])})
        if not annonce: return
        vendeur_data = db.users.find_one({"_id": annonce["vendeur_id"]})
        username_vendeur = vendeur_data.get("username", "Inconnu") if vendeur_data else "Inconnu"
        await query.message.reply_text("⏳ **Demande d'arbitrage transmise !**", parse_mode="Markdown")
        ticket = f"🚨 **DEMANDE D'ARBITRAGE**\n👤 Acheteur: @{update.effective_user.username or 'Sans_Pseudo'} (`{uid}`)\n📦 Jeu: `{annonce['categorie']}`\n👤 Vendeur: @{username_vendeur}"
        try: await ctx.bot.send_message(chat_id=SUPER_ADMIN_ID, text=ticket)
        except Exception as e: logger.error(e)
        return

    if data.startswith("mod:"): await traitement_moderation(update, ctx); return
    if data.startswith("staff:"): await gestion_candidature(update, ctx); return

    try:
        if "profil" in data: await afficher_profil(update, ctx); return
        elif data == "menu:cgu":
            await query.message.edit_text("📜 **CGU**\n\nToute fraude est passible de bannissement. Utilisez l'arbitrage.", reply_markup=get_back_to_start_keyboard())
    except Exception as e: logger.error(e)


def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    application = ApplicationBuilder().token(TOKEN).build()
    
    vente_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(debut_vente, pattern="^menu:vendre$"),
            CallbackQueryHandler(button_handler, pattern="^mon_annonce:modif_prix:"),
            CallbackQueryHandler(button_handler, pattern="^mon_annonce:modif_desc:")
        ],
        states={
            ATTENTE_AUTRE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_jeu_recu)],
            CHOIX_PLATEFORME: [CallbackQueryHandler(plateforme_choisie_handler, pattern="^plat:")],
            ATTENTE_PHOTOS: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), photos_recues)],
            ATTENTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_recue)],
            ATTENTE_PRIX: [CallbackQueryHandler(prix_recu, pattern="^devise:"), MessageHandler(filters.TEXT & ~filters.COMMAND, prix_recu)],
            CHOIX_PAIEMENT: [CallbackQueryHandler(paiement_choisi_handler, pattern="^pay:")],
            CONFIRMATION: [CallbackQueryHandler(confirmation_finale, pattern="^publier:")],
            ATTENTE_MODIF_PRIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, executer_modification_prix)],
            ATTENTE_MODIF_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, executer_modification_description)]
        },
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    recherche_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_recherche, pattern=".*recherche.*")],
        states={ATTENTE_RECHERCHE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, executer_recherche)]},
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    application.add_handler(vente_conv)
    application.add_handler(recherche_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🚀 Marketplace Bot Opérationnel avec Force-Join actif !")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
