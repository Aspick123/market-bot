import os
import logging
import time
from bson.objectid import ObjectId
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database_market import db

logger = logging.getLogger(__name__)

# --- CONFIGURATION SÉCURISÉE DES VARIABLES D'ENVIRONNEMENT ---

# Récupération du Super Admin
try:
    SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))
except ValueError:
    SUPER_ADMIN_ID = 5117004360

# Récupération du Canal de vente public
CANAL_VENTE_ID = os.environ.get("CANAL_VENTE_ID", "@TonCanalDeVente")

# Récupération sécurisée du Groupe de Modération pour éviter le crash
groupe_mod_env = os.environ.get("GROUPE_MODERATION_ID", "")
if groupe_mod_env.replace("-", "").isdigit():
    GROUPE_MODERATION_ID = int(groupe_mod_env)
else:
    logger.warning("⚠️ GROUPE_MODERATION_ID n'est pas configuré ou est invalide sur Render. Pense à ajouter la variable d'environnement.")
    GROUPE_MODERATION_ID = 0  # Valeur temporaire pour éviter le crash au démarrage


# --- FONCTIONS DE MODÉRATION ---

async def soumettre_a_la_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Prend les données du tunnel de vente (ctx.user_data),
    crée l'annonce en statut 'en_attente' dans MongoDB,
    et envoie le ticket de modération dans le groupe des modérateurs.
    """
    query = update.callback_query
    uid = update.effective_user.id
    username_vendeur = update.effective_user.username or update.effective_user.first_name

    if GROUPE_MODERATION_ID == 0:
        await query.answer("❌ Configuration manquante. Le groupe de modération n'est pas configuré.", show_alert=True)
        return

    # 1. Préparation de l'objet Annonce pour MongoDB
    nouvelle_annonce = {
        "vendeur_id": uid,
        "categorie": ctx.user_data.get("vente_jeu"),
        "plateforme": ctx.user_data.get("vente_plateforme"),
        "description": ctx.user_data.get("vente_description"),
        "prix": ctx.user_data.get("vente_prix"),
        "devise": ctx.user_data.get("vente_devise"),
        "paiements": ctx.user_data.get("vente_paiements", []),
        "photos": ctx.user_data.get("photos", []),
        "statut": "en_attente",
        "date_creation": time.time()
    }

    # Insertion dans la base de données
    resultat = db.annonces.insert_one(nouvelle_annonce)
    annonce_id = resultat.inserted_id

    # 2. Construction du ticket destiné aux modérateurs
    paiements_txt = ", ".join(nouvelle_annonce["paiements"]) if nouvelle_annonce["paiements"] else "Non spécifié"
    texte_mod = (
        "🚨 **NOUVELLE ANNONCE À MODÉRER**\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        f"👤 **Vendeur :** @{username_vendeur} (`{uid}`)\n"
        f"🎮 **Jeu :** `{nouvelle_annonce['categorie']}`\n"
        f"💻 **Plateforme :** `{nouvelle_annonce['plateforme']}`\n"
        f"💰 **Prix demandé :** `{nouvelle_annonce['prix']} {nouvelle_annonce['devise']}`\n"
        f"💳 **Paiements :** `{paiements_txt}`\n"
        f"📝 **Description :**\n{nouvelle_annonce['description']}\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "👇 **Action de Modération :**"
    )

    kb_mod = [
        [
            InlineKeyboardButton("✅ Accepter & Publier", callback_data=f"mod:accepter:{annonce_id}"),
            InlineKeyboardButton("❌ Refuser / Supprimer", callback_data=f"mod:refuser:{annonce_id}")
        ]
    ]

    # Envoi du ticket (avec la première photo comme preuve si elle existe)
    try:
        if nouvelle_annonce["photos"]:
            await ctx.bot.send_photo(
                chat_id=GROUPE_MODERATION_ID,
                photo=nouvelle_annonce["photos"][0],
                caption=texte_mod,
                reply_markup=InlineKeyboardMarkup(kb_mod),
                parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                chat_id=GROUPE_MODERATION_ID,
                text=texte_mod,
                reply_markup=InlineKeyboardMarkup(kb_mod),
                parse_mode="Markdown"
            )
        
        await query.message.edit_text(
            "⏳ **Votre annonce a été soumise avec succès aux modérateurs.**\n"
            "Vous recevrez une notification dès qu'elle sera validée et publiée sur le canal public.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Principal", callback_data="menu:retour_start")]])
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi à la modération : {e}")
        await query.message.edit_text("❌ Erreur technique lors de la soumission. Contactez un administrateur.")


async def traitement_moderation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Gère les clics des modérateurs sur les boutons 'Accepter' et 'Refuser'.
    """
    query = update.callback_query
    data = query.data.split(":")
    action = data[1]  # 'accepter' ou 'refuser'
    annonce_id = data[2]

    # Récupération de l'annonce depuis MongoDB
    annonce = db.annonces.find_one({"_id": ObjectId(annonce_id)})
    if not annonce:
        await query.answer("❌ Cette annonce n'existe plus dans la base de données.")
        await query.message.delete()
        return

    vendeur_id = annonce["vendeur_id"]
    vendeur_data = db.users.find_one({"_id": vendeur_id})
    username_vendeur = vendeur_data.get("username", "Inconnu") if vendeur_data else "Inconnu"

    # --- ACTION : ACCEPTER L'ANNONCE ---
    if action == "accepter":
        if annonce["statut"] == "valide":
            await query.answer("⚠️ Cette annonce est déjà en ligne !", show_alert=True)
            return

        # 1. Génération du texte final destiné au canal public
        paiements_txt = ", ".join(annonce.get("paiements", [])) if annonce.get("paiements") else "Non spécifié"
        texte_canal = (
            "🛒 **ANNONCE EN LIGNE — MARKETPLACE**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"🎮 **Jeu :** `{annonce['categorie']}`\n"
            f"💻 **Plateforme :** `{annonce.get('plateforme', 'Non spécifiée')}`\n"
            f"💰 **Prix :** `{annonce['prix']} {annonce['devise']}`\n"
            f"💳 **Paiements acceptés :** `{paiements_txt}`\n"
            f"📝 **Description :**\n{annonce['description']}\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"👤 **Vendeur :** @{username_vendeur}\n\n"
            "💡 *Conseil : Contactez d'abord le vendeur en privé. En cas d'accord, utilisez le lien ci-dessous pour lancer une transaction sécurisée.*"
        )

        kb_canal = [
            [InlineKeyboardButton("💬 Contacter le Vendeur", url=f"https://t.me/{username_vendeur}")],
            [InlineKeyboardButton("⚡ Demander un Arbitrage", url=f"https://t.me/{ctx.bot.username}?start=arbitrage_{annonce_id}")]
        ]

        try:
            # 2. Envoi effectif sur le canal public
            if annonce.get("photos"):
                msg_canal = await ctx.bot.send_photo(
                    chat_id=CANAL_VENTE_ID,
                    photo=annonce["photos"][0],
                    caption=texte_canal,
                    reply_markup=InlineKeyboardMarkup(kb_canal),
                    parse_mode="Markdown"
                )
            else:
                msg_canal = await ctx.bot.send_message(
                    chat_id=CANAL_VENTE_ID,
                    text=texte_canal,
                    reply_markup=InlineKeyboardMarkup(kb_canal),
                    parse_mode="Markdown"
                )

            # 🔥 ENREGISTREMENT CRUCIAL : Sauvegarde du statut et du canal_message_id
            db.annonces.update_one(
                {"_id": ObjectId(annonce_id)},
                {"$set": {"statut": "valide", "canal_message_id": msg_canal.message_id}}
            )

            # 3. Notifier le vendeur en privé
            try:
                await ctx.bot.send_message(
                    chat_id=vendeur_id,
                    text=f"🎉 **Bonne nouvelle !** Votre annonce pour `{annonce['categorie']}` a été validée et publiée sur le canal public.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass 

            # Mettre à jour le ticket dans le groupe de modération
            await query.answer("✅ Annonce publiée sur le canal !")
            await query.message.edit_reply_markup(reply_markup=None)
            
            mod_username = update.effective_user.username or update.effective_user.first_name
            if query.message.caption:
                await query.message.edit_caption(caption=f"{query.message.caption}\n\n🟢 **ACCEPTEE par @{mod_username}**")
            else:
                await query.message.edit_text(text=f"{query.message.text}\n\n🟢 **ACCEPTEE par @{mod_username}**")

        except Exception as e:
            logger.error(f"Erreur lors de la publication sur le canal : {e}")
            await query.answer("❌ Erreur lors de la publication. Vérifie que le bot est Admin du canal.", show_alert=True)

    # --- ACTION : REFUSER L'ANNONCE ---
    elif action == "refuser":
        # Modification du statut en base de données
        db.annonces.update_one({"_id": ObjectId(annonce_id)}, {"$set": {"statut": "refuse"}})

        # Notifier le vendeur du refus
        try:
            await ctx.bot.send_message(
                chat_id=vendeur_id,
                text=f"❌ Votre annonce pour le jeu `{annonce['categorie']}` a été **refusée** par l'équipe de modération (Non conforme aux règles).",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        # Mettre à jour le ticket de modération
        await query.answer("❌ Annonce rejetée.")
        await query.message.edit_reply_markup(reply_markup=None)
        
        mod_username = update.effective_user.username or update.effective_user.first_name
        if query.message.caption:
            await query.message.edit_caption(caption=f"{query.message.caption}\n\n🔴 **REFUSEE par @{mod_username}**")
        else:
            await query.message.edit_text(text=f"{query.message.text}\n\n🔴 **REFUSEE par @{mod_username}**")
