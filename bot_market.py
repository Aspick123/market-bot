import os
import time
import logging
from threading import Thread
from flask import Flask

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
    get_user,
    save_user,
    get_role_label,
    is_flooded,
    is_mode_urgence,
    create_annonce
)
from menus import get_main_menu_keyboard, get_back_to_start_keyboard

# États de la conversation pour la création d'une annonce (Tunnel Avancé)
(
    CHOIX_CATEGORIE,
    ATTENTE_AUTRE_JEU,
    CHOIX_PLATEFORME,      # Elle doit être présente ici
    CHOIX_SPECIFICITES,
    ATTENTE_VALEURS_SPECS,
    ATTENTE_PHOTOS,
    ATTENTE_DESCRIPTION,
    CHOIX_DEVISE,
    ATTENTE_AUTRE_DEVISE,
    ATTENTE_PRIX,
    CHOIX_CRYPTO,
    ATTENTE_CONTACT,
    ATTENTE_DISPO,
    CONFIRMATION
) = range(14)              # On l'augmente à 14

app = Flask("")

@app.route("/")
def home():
    return "Le Marketplace Bot est opérationnel !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "8549692419:AAFxtyQig1cNZDvYF1PnTTbOlDOW1POlrx4")
SUPER_ADMIN_ID = int(os.environ.get("SUPER_ADMIN_ID", "5117004360"))

async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    
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
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    return ConversationHandler.END

# ---------------- LOGIQUE DU MODULE VENTE ----------------

# Modifie la fonction debut_vente pour ajouter le bouton "Autre"
async def debut_vente(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # On nettoie la mémoire et on prépare les tiroirs pour la suite
    ctx.user_data.clear()
    ctx.user_data["specs_choisies"] = []
    ctx.user_data["specs_valeurs"] = {}
    ctx.user_data["photos"] = []
    
    # On demande directement d'écrire le nom du jeu
    await query.message.edit_text(
        "🎮 **Étape 1 : Quel est le jeu concerné ?**\n\n"
        "Veuillez écrire et envoyer le **nom exact** du jeu vidéo (ex: *Genshin Impact, eFootball, Brawl Stars...*).",
        parse_mode="Markdown"
    )
    return ATTENTE_AUTRE_JEU


async def description_recue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vente_description"] = update.message.text
    
    # Nouvelle transition : On propose d'abord de choisir la devise
    kb = [
        [InlineKeyboardButton("💵 FCFA (XOF)", callback_data="devise:FCFA")],
        [InlineKeyboardButton("💵 Dollar ($)", callback_data="devise:USD")],
        [InlineKeyboardButton("💶 Euro (€)", callback_data="devise:EUR")]
    ]
    
    await update.message.reply_text(
        "💱 **Étape 3 : Choix de la devise**\n\nDans quelle devise souhaitez-vous fixer le prix de votre compte ?",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return ATTENTE_PRIX  # On réutilise le même état, mais on intercepte d'abord le callback

async def prix_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # 1. Si c'est le clic sur la devise
    if query and query.data.startswith("devise:"):
        await query.answer()
        choix_devise = query.data.split(":")[1]
        ctx.user_data["vente_devise"] = choix_devise
        
        await query.message.edit_text(
            f"💰 **Étape 3.5 : Fixer le montant ({choix_devise})**\n\n"
            f"Entrez le prix de vente souhaité en **{choix_devise}**.\n"
            "*(Entrez uniquement un nombre entier, sans texte ni symboles)*",
            parse_mode="Markdown"
        )
        return ATTENTE_PRIX

    # 2. Si c'est le texte contenant le montant numérique
    if update.message:
        texte_prix = update.message.text.strip()
        if not texte_prix.isdigit():
            await update.message.reply_text("❌ Veuillez entrer un montant valide (uniquement des chiffres) :")
            return ATTENTE_PRIX
            
        ctx.user_data["vente_prix"] = int(texte_prix)
        ctx.user_data["vente_paiements"] = []
        
        # On passe à l'affichage des moyens de paiement
        return await afficher_choix_paiement(update.message.reply_text, ctx)

async def afficher_choix_paiement(reply_func, ctx):
    choix = ctx.user_data.get("vente_paiements", [])
    check = lambda m: "☑️" if m in choix else "⬜"
    
    # Nettoyage complet des parenthèses comme demandé 
    kb = [
        [InlineKeyboardButton(f"{check('FCFA')} 💵 FCFA", callback_data="pay:FCFA")],
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (Binance TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    
    await reply_func(
        "💳 **Étape 4 : Moyens de paiement acceptés**\n\n"
        "Sélectionnez les méthodes de paiement que vous acceptez pour cette vente.\n"
        "*(Cochez/décochez les options, puis validez)*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_PAIEMENT

async def paiement_choisi_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    choix = ctx.user_data.get("vente_paiements", [])
    
    if data == "pay:valider":
        if not choix:
            kb = [[InlineKeyboardButton("🔄 Réessayer", callback_data="pay:refresh")]]
            await query.message.edit_text("⚠️ Vous devez sélectionner au moins un moyen de paiement.", reply_markup=InlineKeyboardMarkup(kb))
            return CHOIX_PAIEMENT
            
        cat = ctx.user_data["vente_categorie"]
        desc = ctx.user_data["vente_description"]
        prix = ctx.user_data["vente_prix"]
        devise = ctx.user_data.get("vente_devise", "XOF")
        methodes = ", ".join(choix)
        
        recap = (
            "🧐 **VÉRIFICATION DE VOTRE ANNONCE**\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"📦 **Jeu :** `{cat}`\n"
            f"📝 **Description :**\n{desc}\n\n"
            f"💰 **Prix demandé :** `{prix} {devise}`\n"
            f"💳 **Paiements acceptés :** `{methodes}`\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "Souhaitez-vous valider et publier cette annonce ?"
        )
        kb = [
            [InlineKeyboardButton("✅ Valider et Publier", callback_data="publier:oui")],
            [InlineKeyboardButton("❌ Tout annuler", callback_data="publier:non")]
        ]
        await query.message.edit_text(recap, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return CONFIRMATION

    methode = data.replace("pay:", "")
    if methode in choix:
        choix.remove(methode)
    else:
        choix.append(methode)
        
    ctx.user_data["vente_paiements"] = choix
    
    check = lambda m: "☑️" if m in choix else "⬜"
    kb = [
        [InlineKeyboardButton(f"{check('FCFA')} 💵 FCFA", callback_data="pay:FCFA")],
        [InlineKeyboardButton(f"{check('USDT')} 🪙 USDT (Binance TRC20)", callback_data="pay:USDT")],
        [InlineKeyboardButton(f"{check('PayPal')} 💳 PayPal", callback_data="pay:PayPal")],
        [InlineKeyboardButton("✅ Confirmer la sélection", callback_data="pay:valider")]
    ]
    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
    return CHOIX_PAIEMENT

async def confirmation_finale(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if query.data == "publier:oui":
        cat = ctx.user_data.get("vente_categorie")
        desc = ctx.user_data.get("vente_description")
        prix = ctx.user_data.get("vente_prix")
        from database_market import create_annonce
        else:
        # Si ce n'est pas "Genshin", on passe directement à la suite
        pass

    return CONFIRMATION

async def confirmation_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    # Vérification du mode urgence/maintenance
    from database_market import db
    config = db.config.find_one({"_id": "mode_urgence"})
    
    if config and config.get("actif", False):
        if query:
            await query.message.edit_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return

    # Initialisation des variables pour le récapitulatif
    choix = ctx.user_data.get("specs_choisies", [])
    valeurs = ctx.user_data.get("specs_valeurs", {})

        # 1. On récupère les données stockées
    jeu = ctx.user_data.get("vente_jeu", "Inconnu")
    plateforme = ctx.user_data.get("vente_plateforme", "Non spécifiée")
    description = ctx.user_data.get("vente_description", "Aucune description")
    
    # 2. Traduction de la plateforme pour l'affichage propre
    noms_plateformes = {
        "Android": "📱 Android",
        "iOS": "🍏 iOS (Apple)",
        "PC": "💻 PC",
        "Console": "🎮 Console (PS/Xbox/Switch)",
        "Multi": "🌐 Multiplateforme"
    }
    plateforme_propre = noms_plateformes.get(plateforme, plateforme)

    # 3. Construction du texte récapitulatif mis à jour
    texte = (
        "✨ **RÉCAPITULATIF DE VOTRE OFFRE** ✨\n\n"
        f"🎮 **Jeu :** {jeu}\n"
        f"🔌 **Plateforme :** {plateforme_propre}\n"
        f"📝 **Description :** {description}\n"
    )
            await query.message.edit_text(profil_text, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
            
        elif data == "menu:cgu":
            cgu_text = (
                "📜 **Conditions Générales d'Utilisation (CGU)**\n\n"
                "1. Tout acte de fraude entraînera un bannissement irrévocable.\n"
                "2. Les transactions doivent respecter le système d'arbitrage sécurisé du bot.\n"
                "3. La plateforme décline toute responsabilité hors du système d'arbitrage."
            )
            await query.message.edit_text(cgu_text, reply_markup=get_back_to_start_keyboard(), parse_mode="Markdown")
            
        elif data == "menu:admin_panel":
            if uid != SUPER_ADMIN_ID:
                await query.message.edit_text("⛔ Accès refusé. Vous n'êtes pas administrateur.", reply_markup=get_back_to_start_keyboard())
                return
                
            # Récupération des statistiques réelles dans MongoDB
            total_users = db.users.count_documents({}) if hasattr(db, 'users') else 0
            total_annonces = db.annonces.count_documents({}) if hasattr(db, 'annonces') else 0
            statut_urgence = "🚨 ACTIF (Maintenance)" if is_mode_urgence() else "✅ INACTIF (En ligne)"

            admin_text = (
                "⚡ **PANNEAU D'ADMINISTRATION** ⚡\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"📊 **Statistiques du Marketplace :**\n"
                f"👤 Utilisateurs inscrits : `{total_users}`\n"
                f"📦 Annonces créées : `{total_annonces}`\n\n"
                f"⚙️ **Statut du Bot :** {statut_urgence}\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                "Utilisez les boutons ci-dessous pour piloter la plateforme :"
            )

            # Boutons de contrôle
            kb = [
                [InlineKeyboardButton("🚨 Basculer Mode Urgence", callback_data="admin:toggle_urgence")],
                [InlineKeyboardButton("🔙 Retour au Menu", callback_data="menu:retour_start")]
            ]
            await query.message.edit_text(admin_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

        elif data == "admin:toggle_urgence":
            if uid != SUPER_ADMIN_ID: return
            
            from database_market import db
            # On cherche ou crée la config du mode urgence
            config = db.config.find_one({"_id": "mode_urgence"})
            actuel = config.get("actif", False) if config else False
            nouveau_statut = not actuel
            
            db.config.update_one({"_id": "mode_urgence"}, {"$set": {"actif": nouveau_statut}}, upsert=True)
            
            texte_confirmation = f"🚨 **Mode Urgence modifié !**\nLe mode maintenance est maintenant : {'🔴 ACTIF' if nouveau_statut else '🟢 INACTIF'}."
            kb = [[InlineKeyboardButton("🔄 Rafraîchir le Panel", callback_data="menu:admin_panel")]]
            await query.message.edit_text(texte_confirmation, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

        # Reste des modules en chantier (sans admin_panel)
        elif data in ["menu:recherche", "menu:mes_annonces", "menu:historique", 
                      "menu:parrainage", "menu:defis", "menu:leaderboard", "menu:litige", 
                      "menu:alertes", "menu:blacklist"]:
            feature_name = data.replace("menu:", "").replace("_", " ").title()
            await query.message.edit_text(
                f"🚧 **Module [{feature_name}]**\n\nCe module est propre et prêt à recevoir sa logique métier.",
                reply_markup=get_back_to_start_keyboard(),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Erreur callback {data}: {str(e)}")
        await query.message.reply_text(f"❌ Erreur : {str(e)}")


async def autre_jeu_recu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # On enregistre proprement le nom du jeu tapé par l'utilisateur
    ctx.user_data["vente_jeu"] = update.message.text.strip()
    
    # On prépare les boutons des plateformes
    kb = [
        [InlineKeyboardButton("📱 Android", callback_data="plat:Android")],
        [InlineKeyboardButton("🍏 iOS (Apple)", callback_data="plat:iOS")],
        [InlineKeyboardButton("💻 PC", callback_data="plat:PC")],
        [InlineKeyboardButton("🎮 Console (PS/Xbox/Switch)", callback_data="plat:Console")],
        [InlineKeyboardButton("🌐 Multiplateforme (Partout)", callback_data="plat:Multi")]
    ]
    
    await update.message.reply_text(
        "🔌 **Sur quelle plateforme se trouve votre compte ?**\n\n"
        "Sélectionnez le support principal de votre compte :",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    # On redirige vers notre nouvel état intermédiaire
    return CHOIX_PLATEFORME
    ]
    
    kb = []
    for nom, callback in specs_disponibles:
        id_spec = callback.replace("spec:", "")
        # Si la caractéristique est déjà cochée, on met un carré plein, sinon un carré vide
        check = "☑️" if id_spec in choix else "⬜"
        kb.append([InlineKeyboardButton(f"{check} {nom}", callback_data=callback)])
        
    # Bouton de validation final
    kb.append([InlineKeyboardButton("✅ Valider la sélection", callback_data="spec:valider")])
    
    await reply_func(
        "📊 **Étape 2 : Spécificités du compte**\n\n"
        "Qu'est-ce qu'on collectionne principalement dans votre jeu ?\n"
        "*(Cochez ou décochez les options, puis cliquez sur Valider)*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )
    return CHOIX_SPECIFICITES

async def specificite_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    choix = ctx.user_data.get("specs_choisies", [])
    
    # 1. Si l'utilisateur clique TRÈS PRÉCISÉMENT sur le bouton de validation
    if data == "spec:valider":
        if not choix:
            # Si aucune case n'est cochée, on passe direct aux photos
            await query.message.edit_text(
                "📸 **Étape 3 : Preuves en images**\n\n"
                "Veuillez envoyer entre **1 et 5 photos** de votre compte (captures d'écran).\n\n"
                "👉 *Une fois que vous avez fini d'envoyer vos photos, écrivez le mot* **'FIN'** *pour passer à la suite.*",
                parse_mode="Markdown"
            )
            return ATTENTE_PHOTOS
            
        # Si des cases sont cochées, on démarre la boucle des nombres
        ctx.user_data["index_spec_actuelle"] = 0
        premiere_spec = choix[0]
        
        # Traduction propre pour l'affichage à l'utilisateur
        noms_affichage = {"Persos": "Personnages", "Skins": "Skins", "Armes": "Armes", "Artefacts": "Artefacts", "Objets": "Objets Rares"}
        nom_propre = noms_affichage.get(premiere_spec, premiere_spec)
        
        await query.message.edit_text(
            f"🔢 **Configuration des quantités**\n\n"
            f"Combien de **{nom_propre}** possédez-vous exactement sur votre compte ?\n"
            f"*(Entrez un nombre entier uniquement)*",
            parse_mode="Markdown"
        )
        return ATTENTE_VALEURS_SPECS

    # 2. Si l'utilisateur clique sur une case (Persos, Skins, etc.)
    id_spec = data.replace("spec:", "")
    if id_spec in choix:
        choix.remove(id_spec)
    else:
        choix.append(id_spec)
        
    ctx.user_data["specs_choisies"] = choix
    return await afficher_choix_specificites(query.message.edit_reply_markup, ctx)
async def confirmation_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    # Vérification du mode urgence/maintenance
    from database_market import db
    config = db.config.find_one({"_id": "mode_urgence"})
    
    if config and config.get("actif", False):
        if query:
            await query.message.edit_text("🚨 Le Marketplace est temporairement suspendu pour maintenance.")
        return

    # Initialisation des variables pour le récapitulatif
    choix = ctx.user_data.get("specs_choisies", [])
    valeurs = ctx.user_data.get("specs_valeurs", {})

    

async def valeurs_specs_recues(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texte = update.message.text.strip()
    
    if not texte.isdigit():
        await update.message.reply_text("❌ Veuillez entrer un nombre valide (uniquement des chiffres) :")
        return ATTENTE_VALEURS_SPECS
        
    choix = ctx.user_data.get("specs_choisies", [])
    index = ctx.user_data.get("index_spec_actuelle", 0)
    
    # Enregistrement de la valeur pour la spec actuelle
    spec_actuelle = choix[index]
    ctx.user_data["specs_valeurs"][spec_actuelle] = int(texte)
    
    # Passage à la caractéristique suivante s'il y en a une
    index += 1
    ctx.user_data["index_spec_actuelle"] = index
    
    if index < len(choix):
        prochaine_spec = choix[index]
        noms_affichage = {"Persos": "Personnages", "Skins": "Skins", "Armes": "Armes", "Artefacts": "Artefacts", "Objets": "Objets Rares"}
        nom_propre = noms_affichage.get(prochaine_spec, prochaine_spec)
        
        await update.message.reply_text(
            f"🔢 **Prochaine quantité**\n\n"
            f"Combien de **{nom_propre}** possédez-vous au total ?",
            parse_mode="Markdown"
        )
        return ATTENTE_VALEURS_SPECS
    else:
        # Si toutes les quantités sont remplies, on passe aux photos !
        await update.message.reply_text(
            "📸 **Étape 3 : Preuves en images**\n\n"
            "Veuillez envoyer entre **1 et 5 photos** de votre compte (captures d'écran).\n\n"
            "👉 *Une fois que vous avez fini d'envoyer vos photos, écrivez le mot* **'FIN'** *pour passer à la suite.*",
            parse_mode="Markdown"
        )
        return ATTENTE_PHOTOS
        
# Mettre la fonction complètement en dehors de main() (alignée tout à gauche)
async def plateforme_choisie_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # On récupère la plateforme sélectionnée
    plateforme = query.data.replace("plat:", "")
    ctx.user_data["vente_plateforme"] = plateforme
    
    # On passe enfin à l'affichage des cases à cocher
    return await afficher_choix_specificites(query.message.edit_text, ctx)


def main():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    vente_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(debut_vente, pattern="^menu:vendre$")],
        states={
            # 1. Enregistrement du nom du jeu tapé
            ATTENTE_AUTRE_JEU: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_jeu_recu)],
            
            # 2. Enregistrement de la plateforme choisie
            CHOIX_PLATEFORME: [CallbackQueryHandler(plateforme_choisie_handler, pattern="^plat:")],
            
            # 3. Menu des cases à cocher
            CHOIX_SPECIFICITES: [CallbackQueryHandler(specificite_choisie_handler, pattern="^spec:")],
            
            # 4. Enregistrement des quantités numériques
            ATTENTE_VALEURS_SPECS: [MessageHandler(filters.TEXT & ~filters.COMMAND, valeurs_specs_recues)],
            
            # --- Suite et fin logique du tunnel de vente ---
            ATTENTE_PHOTOS: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), photos_recues)],
            ATTENTE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description_recue)],
            CHOIX_DEVISE: [CallbackQueryHandler(devise_choisie_handler, pattern="^devise:")],
            ATTENTE_AUTRE_DEVISE: [MessageHandler(filters.TEXT & ~filters.COMMAND, autre_devise_recue)],
            ATTENTE_PRIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, prix_recu)],
            CHOIX_CRYPTO: [CallbackQueryHandler(crypto_choisie_handler, pattern="^crypto:")],
            ATTENTE_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, contact_recu)],
            ATTENTE_DISPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, dispo_recue)],
            CONFIRMATION: [CallbackQueryHandler(confirmation_handler, pattern="^(publier:|annuler$)")]
        },
        fallbacks=[CallbackQueryHandler(start_command, pattern="^menu:retour_start")],
        allow_reentry=True
    )
    
    application.add_handler(vente_conv)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🚀 Bot démarré avec le module Vente actif !")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

