import os, json
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def handle_transactions_callbacks(query, ctx, bot, admin_id):
    data = query.data
    uid = query.from_user.id
    
    # Gestion de l'acceptation du contact par le vendeur
    if data.startswith("trx_accepter_"):
        transaction_id = data.replace("trx_accepter_", "")
        
        # Simulation de récupération des données de l'acheteur et du vendeur
        vendeur_username = query.from_user.username or "Vendeur"
        acheteur_id = ctx.user_data.get("current_acheteur_id")
        
        # Message au vendeur
        await query.message.edit_text("✅ Tu as accepté la mise en relation ! Les coordonnées ont été partagées.")
        
        # Message automatique à l'acheteur s'il est connu
        if acheteur_id:
            try:
                text_acheteur = (
                    "🎉 *Bonne nouvelle !*\n"
                    f"Le vendeur a accepté ta demande de contact.\n"
                    f"💬 Tu peux le contacter directement ici : @{vendeur_username}"
                )
                await bot.send_message(chat_id=acheteur_id, text=text_acheteur, parse_mode="Markdown")
            except:
                pass
        return True
        
    return False
