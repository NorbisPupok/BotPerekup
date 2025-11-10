import logging
import os
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
                          ConversationHandler, ContextTypes, CallbackQueryHandler)
from dotenv import load_dotenv

# --- НАСТРОЙКА И КОНСТАНТЫ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_CHAT_ID = int(os.getenv("CHANNEL_CHAT_ID"))  # Все еще нужен для публикации в канал
WEBSITE_API_URL = os.getenv("WEBSITE_API_URL", "http://localhost:3001")
WEB_API_KEY = os.getenv("WEB_API_KEY")

if not all([TELEGRAM_TOKEN, CHANNEL_CHAT_ID, WEBSITE_API_URL, WEB_API_KEY]):
    raise ValueError("Одна из переменных (TOKEN, CHANNEL_ID, WEBSITE_API_URL, WEB_API_KEY) не найдена в .env файле!")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

reply_keyboard = [['📝 Сделать пост']]
persistent_keyboard = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=False, resize_keyboard=True)

# --- СОСТОЯНИЯ ДИАЛОГА ---
PHOTO, SERVER_SELECTION, CAR, PRICE, CONFIRMATION = range(5)


# --- ФУНКЦИЯ ДЛЯ ОТПРАВКИ НА САЙТ (НОВАЯ ВЕРСИЯ) ---
async def send_to_website(data: dict):
    """
    Отправляет данные заявки напрямую на сайт.
    """
    try:
        logger.info(f"Отправка данных на сайт: {data}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{WEBSITE_API_URL}/api/submissions"
            response = await client.post(url, json=data, headers={"Authorization": f"Bearer {WEB_API_KEY}"})

            if response.status_code == 201:  # 201 - статус "Created"
                logger.info(f"Заявка от пользователя {data['user_name']} успешно отправлена на сайт.")
                return True
            else:
                logger.error(f"Ошибка отправки на сайт. Статус: {response.status_code}, Ответ: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Критическая ошибка в send_to_website: {e}")
        return False


# --- ФУНКЦИИ БОТА ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Нажмите кнопку '📝 Сделать пост', чтобы отправить информацию о покупке.",
        reply_markup=persistent_keyboard
    )


async def submit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("📸 Отлично! Для начала, отправьте мне фотографию покупки",
                                    reply_markup=ReplyKeyboardRemove())
    return PHOTO


async def photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo = update.message.photo[-1]  # Берем фото самого большого размера
    photo_file_id = photo.file_id

    file_object = await context.bot.get_file(photo_file_id)

    context.user_data['photo_file_id'] = photo_file_id
    context.user_data['file_path'] = file_object.file_path

    await update.message.reply_text("Теперь напишите название сервера.")
    return SERVER_SELECTION


async def server_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['server'] = update.message.text
    await update.message.reply_text("🚗 Сервер выбран! Какую машину вы купили?")
    return CAR


async def car_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['car'] = update.message.text
    await update.message.reply_text("💰 На какую сумму? (только число)")
    return PRICE


async def price_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price = int(update.message.text)
        context.user_data['price'] = price
    except ValueError:
        await update.message.reply_text("Ошибка! Введите число.")
        return PRICE

    user = update.effective_user
    photo_file_id = context.user_data.get('photo_file_id')
    server = context.user_data.get('server', 'Не указано')
    car = context.user_data.get('car', 'Не указано')

    confirmation_text = (f"Пожалуйста, проверьте все ли верно:\n\n"
                         f"🌐 Сервер: {server}\n"
                         f"🚗 Автомобиль: {car}\n"
                         f"💰 Цена покупки: {price}")

    keyboard = [[InlineKeyboardButton("✅ Все верно, отправить", callback_data='confirm_submit')],
                [InlineKeyboardButton("❌ Заполнить заново", callback_data='restart_submit')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_file_id, caption=confirmation_text,
                                 reply_markup=reply_markup)
    return CONFIRMATION


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == 'confirm_submit':
        user = update.effective_user

        submission_data = {
            "user_id": user.id,
            "user_name": user.full_name,
            "photo_file_id": context.user_data['photo_file_id'],
            "file_path": context.user_data['file_path'],
            "server": context.user_data['server'],
            "car": context.user_data['car'],
            "price": context.user_data['price']
        }

        # Отправляем данные на сайт и ЖДЕМ МОДЕРАЦИИ
        success = await send_to_website(submission_data)

        if success:
            await query.edit_message_caption(caption="✅ Спасибо! Ваша заявка отправлена на модерацию.",
                                             reply_markup=None)
        else:
            await query.edit_message_caption(caption="❌ Произошла ошибка. Пожалуйста, попробуйте позже.",
                                             reply_markup=None)

        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text="Вы можете создать новый пост, нажав на кнопку '📝 Сделать пост'.",
                                       reply_markup=persistent_keyboard)
        context.user_data.clear()
        return ConversationHandler.END

    elif query.data == 'restart_submit':
        # ... (код не меняется)
        context.user_data.clear()
        await query.edit_message_caption(caption="Хорошо, давайте начнем заново.", reply_markup=None)
        await query.message.reply_text("📸 Отлично! Для начала, отправьте мне фотографию покупки",
                                       reply_markup=ReplyKeyboardRemove())
        return PHOTO


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Операция отменена.", reply_markup=persistent_keyboard)
    return ConversationHandler.END


def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    start_handler = CommandHandler('start', start)
    cancel_handler = CommandHandler('cancel', cancel)

    conv_handler_user = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📝 Сделать пост$'), submit_start)],
        states={
            PHOTO: [MessageHandler(filters.PHOTO, photo_received)],
            SERVER_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, server_text_received)],
            CAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_received)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_received)],
            CONFIRMATION: [CallbackQueryHandler(handle_confirmation, pattern='^(confirm_submit|restart_submit)$')]
        },
        fallbacks=[cancel_handler],
        per_message=False,
        name="user_conversation",
        allow_reentry=True
    )

    application.add_handler(start_handler)
    application.add_handler(conv_handler_user)

    print("✅ Бот запускается...")
    application.run_polling()


if __name__ == '__main__':
    main()