import os, json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CONFIG_FILE = "config_market.json"

def get_canal_id():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("canal_vente_id", "@comptedejeux")
        except: pass
    return "@comptedejeux"

async def handle_annonces_callbacks(query, ctx, bot, admin_id):
    data = query.data
    uid = query.from_user.id
    
    if data.startswith("valid_"):
        annonce_id = data.replace("valid_", "")
        canal = get_canal_id()
        
        # Structure de l'annonce visuelle pro
        texte_canal = (
            f"📢 *NOUVELLE ANNONCE DISPONIBLE !*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 *Jeu :* FC 25\n"
            f"📝 *Titre :* {ctx.user_data.get('titre_annonce', 'Compte FC 25')}\n"
            f"💰 *Prix :* {ctx.user_data.get('prix_annonce', 'À débattre')} XOF\n"
            f"👤 *Vendeur :* @{query.from_user.username or 'Anonyme'}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Pour acheter, contactez le vendeur ou passez par le bot !_"
        )
        
        try:
            await bot.send_message(chat_id=canal, text=texte_canal, parse_mode="Markdown")
            await query.message.edit_text("✅ Annonce validée et publiée instantanément sur le Canal !")
        except Exception as e:
            await query.message.edit_text(f"❌ Erreur de publication sur le canal : {str(e)}\nVérifie que le bot y est bien Admin.")
        return True
    return False

async def start_creation_annonce(message, user_id):
    await message.edit_text("🎮 *Création d'une annonce*\n\nÉcris le titre de ton annonce directement en réponse à ce message (ex: _Compte FC 25 full Or_).", parse_mode="Markdown")

async def handle_annonces_input(update, ctx, bot):
    return False

async def handle_annonces_photos(update, ctx):
    return False

async def show_mes_annonces(query, ctx):
    await query.message.edit_text("📝 Tu n'as pas encore d'annonces actives.")
    return True
