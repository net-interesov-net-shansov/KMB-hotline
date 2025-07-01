import asyncio
import logging
import smtplib
import os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, List, Optional
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
import textwrap

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.media_group import MediaGroupBuilder
from dotenv_vault import load_dotenv

# Загрузка переменных окружения
load_dotenv("~/KMB-hotline/.env")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ротирующий файл для логов
file_handler = RotatingFileHandler(
    'bot.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(file_handler)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPERATOR_ID = int(os.getenv("OPERATOR_ID"))
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
CORPORATE_EMAIL = os.getenv("CORPORATE_EMAIL")

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM
class AppealStates(StatesGroup):
    waiting_for_agreement = State()
    selecting_instance = State()
    entering_topic = State()
    entering_text = State()
    uploading_media = State()
    entering_personal_data = State()
    entering_contact_method = State()
    confirming_appeal = State()

# Структура обращения
@dataclass
class Appeal:
    instance: str
    topic: str
    text: str
    full_name: str
    contact_method: str
    media_files: List[Dict] = None
    doc_files: List[Dict] = None
    created_at: datetime = None
    
    def __post_init__(self):
        if self.media_files is None:
            self.media_files = []
        if self.doc_files is None:
            self.doc_files = []
        if self.created_at is None:
            self.created_at = datetime.now()

# Функция для экранирования символов MarkdownV2
"""
def escape_markdown(text: str) -> str:
    # Список символов, которые нужно экранировать в MarkdownV2
    escape_chars = ['\\', '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    # Сначала экранируем обратный слеш, чтобы избежать двойного экранирования
    text = text.replace('\\', '\\\\')
    
    # Затем экранируем остальные символы
    for char in escape_chars[1:]:  # пропускаем первый элемент (обратный слеш)
        text = text.replace(char, f'\\{char}')
    
    return text
"""


# Список инстанций
INSTANCES = [
    "Санитарно-бытовое состояние помещений",
    "Материально-техническое оснащение",
    "Организация учебного процесса",
    "Взаимодействие с педагогами",
    "Нарушение прав обучающихся",
    "Конфликтные ситуации с обучающимися",
    "Организация питания",
    "Обращение по фактам коррупции"
]

# Текст соглашения
AGREEMENT_TEXT = """
🎓 <b>Уважаемые студенты!</b>

Здесь вы можете направить свое обращение по вопросам состояния помещений, работы педагогов и иным вопросам, возникающим в ходе обучения.

⚖️ <b>Согласие на обработку персональных данных:</b>
<u>Продолжая использование чат-бота, вы даете свое согласие на обработку персональных данных в соответствии с Федеральным законом «О персональных данных» от 27.07.2006 г. № 152-ФЗ.</u>

Нажмите "Принять", чтобы продолжить.
"""

# Клавиатуры
def get_agreement_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data="accept_agreement")]
    ])
    return keyboard

def get_main_menu_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Написать обращение", callback_data="new_appeal")]
    ])
    return keyboard

def get_instances_keyboard():
    keyboard = []
    for i, instance in enumerate(INSTANCES):
        keyboard.append([InlineKeyboardButton(text=f"{i+1}. {textwrap.fill(instance)}", callback_data=f"instance_{i}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_next_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Далее", callback_data="next_step")]
    ])
    return keyboard

def get_skip_media_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_media")],
        [InlineKeyboardButton(text="✅ Завершить загрузку", callback_data="finish_media")]
    ])
    return keyboard

def get_confirm_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить обращение", callback_data="send_appeal")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_appeal")]
    ])
    return keyboard

# Утилиты для работы с медиа
def is_valid_media_format(file_name: str) -> bool:
    """Проверка допустимого формата файла"""
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf']
    return any(file_name.lower().endswith(ext) for ext in allowed_extensions)

def format_file_size(size_bytes: int) -> str:
    """Форматирование размера файла"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.1f} KB"
    else:
        return f"{size_bytes/(1024**2):.1f} MB"

# Функция отправки email
async def send_email(appeal: Appeal) -> bool:
    """Отправка обращения на корпоративную почту"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = CORPORATE_EMAIL
        msg['Subject'] = f"[{appeal.instance}] {appeal.topic}"
        
        # Тело письма
        body = f"""
Новое обращение от студента

Инстанция: {appeal.instance}
Тема: {appeal.topic}
Дата: {appeal.created_at.strftime('%d.%m.%Y %H:%M')}

ФИО студента: {appeal.full_name}
Способ связи: {appeal.contact_method}

Текст обращения:
{appeal.text}

---
Отправлено через Telegram-бот "Горячая линия обращений студентов"
        """
        
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # Прикрепление медиа-файлов
        for media_file in appeal.media_files:
            for doc_file in appeal.doc_files:
                try:
                    file_info = await bot.get_file(doc_file['file_id'])
                    file_data = await bot.download_file(file_info.file_path)
                    
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(file_data.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {doc_file["file_name"]}'
                    )
                    msg.attach(part)
                except Exception as e:
                    logger.error(f"Ошибка прикрепления файла {doc_file['file_name']}: {e}")
            try:
                file_info = await bot.get_file(media_file['file_id'])
                file_data = await bot.download_file(file_info.file_path)
                
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(file_data.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {media_file["file_name"]}'
                )
                msg.attach(part)
            except Exception as e:
                logger.error(f"Ошибка прикрепления файла {media_file['file_name']}: {e}")
        
        # Отправка письма
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        text = msg.as_string()
        server.sendmail(SMTP_USER, CORPORATE_EMAIL, text)
        server.quit()
        
        logger.info(f"Email отправлен для обращения: {appeal.topic}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка отправки email: {e}")
        return False

# Функция отправки обращения оператору
async def send_to_operator(appeal: Appeal) -> bool:
    """Отправка обращения оператору в Telegram"""
    try:
        # Формирование сообщения для оператора
        operator_message = f"""
🔔 <b>НОВОЕ ОБРАЩЕНИЕ</b>

📋 <b>Инстанция:</b> {appeal.instance}
📝 <b>Тема:</b> {appeal.topic}
📅 <b>Дата:</b> {appeal.created_at.strftime('%d.%m.%Y %H:%M')}

👤 <b>ФИО:</b> {appeal.full_name}
📞 <b>Связь:</b> {appeal.contact_method}

💬 <b>Текст обращения:</b>
    {appeal.text}
        """
        
        # Отправка текстового сообщения
        sent_message = await bot.send_message(
            chat_id=OPERATOR_ID,
            text=operator_message,
            parse_mode='HTML'
        )
        
        # Отправка медиа-файлов, если есть
        if appeal.media_files:
            if len(appeal.media_files) == 1:
                # Один файл
                media_file = appeal.media_files[0]
                if media_file['type'] == 'photo':
                    await bot.send_photo(
                        chat_id=OPERATOR_ID,
                        photo=media_file['file_id'],
                        caption=f"📎 Вложение к обращению: {appeal.topic}"
                    )
                elif media_file['type'] == 'document':
                    await bot.send_document(
                        chat_id=OPERATOR_ID,
                        document=media_file['file_id'],
                        caption=f"📎 Вложение к обращению: {appeal.topic}"
                    )
            else:
                # Группа файлов
                media_group = MediaGroupBuilder(caption=f"📎 Вложения к обращению: {appeal.topic}")
                
                for media_file in appeal.media_files:
                    if media_file['type'] == 'photo':
                        media_group.add_photo(media=media_file['file_id'])
                    elif media_file['type'] == 'document':
                        media_group.add_document(media=media_file['file_id'])
                
                await bot.send_media_group(
                    chat_id=OPERATOR_ID,
                    media=media_group.build()
                )

        if appeal.doc_files:
            if len(appeal.doc_files) == 1:
                # Один файл
                doc_file = appeal.doc_files[0]
                if doc_file['type'] == 'photo':
                    await bot.send_photo(
                        chat_id=OPERATOR_ID,
                        photo=doc_file['file_id'],
                        caption=f"📎 Вложение к обращению: {appeal.topic}"
                    )
                elif doc_file['type'] == 'document':
                    await bot.send_document(
                        chat_id=OPERATOR_ID,
                        document=doc_file['file_id'],
                        caption=f"📎 Вложение к обращению: {appeal.topic}"
                    )
            else:
                # Группа файлов
                media_group = MediaGroupBuilder(caption=f"📎 Вложения к обращению: {appeal.topic}")
                
                for doc_file in appeal.doc_files:
                    if doc_file['type'] == 'photo':
                        media_group.add_photo(media=doc_file['file_id'])
                    elif doc_file['type'] == 'document':
                        media_group.add_document(media=doc_file['file_id'])
                
                await bot.send_media_group(
                    chat_id=OPERATOR_ID,
                    media=media_group.build()
                )
        
        logger.info(f"Обращение отправлено оператору: {appeal.topic}")
        return sent_message
        
    except Exception as e:
        logger.error(f"Ошибка отправки оператору: {e}")
        return False

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Обработчик команды /start"""
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    
    await state.clear()
    await message.answer(
        text=AGREEMENT_TEXT,
        reply_markup=get_agreement_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.waiting_for_agreement)

@dp.callback_query(F.data == "accept_agreement")
async def accept_agreement(callback: types.CallbackQuery, state: FSMContext):
    """Принятие соглашения"""
    await callback.message.edit_text(
        text="✅ Соглашение принято!\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard()
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "new_appeal")
async def start_new_appeal(callback: types.CallbackQuery, state: FSMContext):
    """Начало создания нового обращения"""
    logger.info(f"Пользователь {callback.from_user.id} начал создание обращения")
    
    await callback.message.edit_text(
        text="📋 <b>Выберите, по какому вопросу ваше обращение:</b>",
        reply_markup=get_instances_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.selecting_instance)
    await callback.answer()

@dp.callback_query(F.data.startswith("instance_"))
async def select_instance(callback: types.CallbackQuery, state: FSMContext):
    """Выбор инстанции"""
    instance_index = int(callback.data.split("_")[1])
    selected_instance = INSTANCES[instance_index]
    
    await state.update_data(instance=selected_instance)
    
    await callback.message.edit_text(
        text=f"✅ Выбрана инстанция: <b>{selected_instance}</b>",
        reply_markup=get_next_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.entering_topic)
    await callback.answer()

@dp.callback_query(F.data == "next_step", StateFilter(AppealStates.entering_topic))
async def ask_for_topic(callback: types.CallbackQuery, state: FSMContext):
    """Запрос темы обращения"""
    await callback.message.edit_text(
        text="📝 <b>Введите тему обращения</b> (краткий заголовок):",
        parse_mode='HTML'
    )
    await callback.answer()

@dp.message(StateFilter(AppealStates.entering_topic))
async def receive_topic(message: types.Message, state: FSMContext):
    """Получение темы обращения"""
    if len(message.text) < 5:
        await message.answer("❌ Тема обращения не может быть короче 5 символов:")
        return

    if len(message.text) > 100:
        await message.answer("❌ Тема слишком длинная. Введите тему до 100 символов:")
        return
    
    await state.update_data(topic=message.text)
    
    await message.answer(
        text=f"✅ Тема: <b>{message.text}</b>",
        reply_markup=get_next_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.entering_text)

@dp.callback_query(F.data == "next_step", StateFilter(AppealStates.entering_text))
async def ask_for_text(callback: types.CallbackQuery, state: FSMContext):
    """Запрос текста обращения"""
    await callback.message.edit_text(
        text="📄 <b>Введите подробное описание вашего обращения:</b>",
        parse_mode='HTML'
    )
    await callback.answer()

@dp.message(StateFilter(AppealStates.entering_text))
async def receive_text(message: types.Message, state: FSMContext):
    """Получение текста обращения"""

    if len(message.text) < 20:
        await message.answer("❌ Текст слишком короткий. Введите не менее 20 символов:")
        return

    if len(message.text) > 4000:
        await message.answer("❌ Текст слишком длинный. Введите текст до 4000 символов:")
        return
    
    await state.update_data(text=message.text)
    await state.update_data(media_files=[])         # Инициализируем пустой список для фото
    await state.update_data(doc_files=[])      # Такой же список для документов
    
    await message.answer(
        text="📎 <b>Прикрепите медиа-файлы</b> (фото, документы)\n\n"
             "• Допустимые форматы: JPG, JPEG, PNG, PDF\n"
             "• Максимальный размер: 10 МБ\n"
             "• Можно прикрепить несколько файлов\n\n"
             "Если файлы не нужны, нажмите «Пропустить»",        
        reply_markup=get_skip_media_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.uploading_media)

@dp.message(StateFilter(AppealStates.uploading_media), F.content_type.in_({'photo', 'document'}))
async def receive_media(message: types.Message, state: FSMContext):
    """Получение медиа-файлов"""
    data = await state.get_data()
    media_files = data.get('media_files', [])
    doc_files = data.get('doc_files', [])
    
    # Проверка лимита файлов
    if len(media_files) > 10:
        return  # Молча игнорируем лишние файлы
    
    if message.content_type == 'photo':
        file_id = message.photo[-1].file_id
        file_info = await bot.get_file(file_id)
        file_name = f"photo_{len(media_files)+1}.jpg"
        file_size = file_info.file_size
        
        # Проверка размера файла
        if file_size > 10 * 1024 * 1024:  # 10 МБ
            return  # Молча игнорируем слишком большие файлы
        
        media_files.append({
            'type': 'photo',
            'file_id': file_id,
            'file_name': file_name,
            'file_size': file_size
        })
        
    elif message.content_type == 'document':
        document = message.document
        file_id = document.file_id
        file_name = document.file_name
        file_size = document.file_size
        
        # Проверка размера файла
        if file_size > 10 * 1024 * 1024:  # 10 МБ
            return  # Молча игнорируем слишком большие файлы
        
        # Проверка формата файла
        if not is_valid_media_format(file_name):
            return  # Молча игнорируем неподдерживаемые форматы
        
        doc_files.append({
            'type': 'document',
            'file_id': file_id,
            'file_name': file_name,
            'file_size': file_size
        })
    
    await state.update_data(media_files=media_files, doc_files=doc_files)

# @dp.message(StateFilter(AppealStates.uploading_media))
# async def handle_wrong_media_format(message: types.Message, state: FSMContext):
#     """Обработка неправильного формата данных во время загрузки медиа"""
#     await message.answer(
#         "⚠️ Пожалуйста, отправьте только медиа-файлы (фото, документы) или используйте кнопки ниже для продолжения.",
#         reply_markup=get_skip_media_keyboard()
#     )

@dp.callback_query(F.data == "skip_media", StateFilter(AppealStates.uploading_media))
async def skip_media_upload(callback: types.CallbackQuery, state: FSMContext):
    """Пропуск загрузки медиа"""
    await callback.message.edit_text(
        text="⏭️ Загрузка файлов пропущена.",
        reply_markup=get_next_keyboard()
    )
    await state.set_state(AppealStates.entering_personal_data)
    await callback.answer()

@dp.callback_query(F.data == "finish_media", StateFilter(AppealStates.uploading_media))
async def finish_media_upload(callback: types.CallbackQuery, state: FSMContext):
    """Завершение загрузки медиа"""
    data = await state.get_data()
    media_files = data.get('media_files', [])
    doc_files = data.get('doc_files', [])
    
    if len(media_files) == 0 and len(doc_files) == 0:
        report_text = "📎 Файлы не загружены."
    else:
        report_text = f"📎 <b>Отчет о загрузке файлов:</b>\n\n"
        report_text += f"✅ Успешно загружено: {len(media_files)} фото и {len(doc_files)} документов\n\n"
        
        for i, file in enumerate(media_files, 1):
            report_text += f"{i}. {file['file_name']} ({format_file_size(file['file_size'])})\n"
        for i, file in enumerate(doc_files, 1):
            report_text += f"{i}. {file['file_name']} ({format_file_size(file['file_size'])})\n"


    
    await callback.message.edit_text(
        text=report_text,
        reply_markup=get_next_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.entering_personal_data)
    await callback.answer()

@dp.callback_query(F.data == "next_step", StateFilter(AppealStates.entering_personal_data))
async def ask_for_personal_data(callback: types.CallbackQuery, state: FSMContext):
    """Запрос персональных данных"""
    await callback.message.answer(
        text="👤 <b>Введите ваши ФИО полностью:</b>",
        parse_mode='HTML'
    )
    await callback.answer()


@dp.message(StateFilter(AppealStates.entering_personal_data))
async def receive_personal_data(message: types.Message, state: FSMContext):
    """Получение ФИО"""
    full_name = message.text.strip()
    space = " "

    if space not in full_name:
        await message.answer("❌ Введите Имя, Фамилию и Отчество (при наличии):")
        return
    
    await state.update_data(full_name=full_name)
    
    await message.answer(
        text=f"✅ ФИО: <b>{full_name}</b>",
        reply_markup=get_next_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.entering_contact_method)

@dp.callback_query(F.data == "next_step", StateFilter(AppealStates.entering_contact_method))
async def ask_for_contact_method(callback: types.CallbackQuery, state: FSMContext):
    """Запрос способа связи"""
    await callback.message.edit_text(
        text="📞 <b>Укажите предпочтительный способ обратной связи:</b>\n\n"
             "Например:\n"
             "• Username Telegram (для ответа через этого бота)\n"
             "• Email: example@mail.com\n"
             "• Телефон: +7 (xxx) xxx-xx-xx\n"
             "• Другой способ",
        parse_mode='HTML'
    )
    await callback.answer()

@dp.message(StateFilter(AppealStates.entering_contact_method))
async def receive_contact_method(message: types.Message, state: FSMContext):
    """Получение способа связи"""
    contact_method = message.text.strip()
    
    if len(contact_method) < 3:
        await message.answer("❌ Укажите способ связи (минимум 3 символа):")
        return
    
    await state.update_data(contact_method=contact_method)
    
    # Формирование итогового сообщения
    data = await state.get_data()
    
    summary = f"""
📋 <b>ПРОВЕРЬТЕ ОБРАЩЕНИЕ ПЕРЕД ОТПРАВКОЙ</b>

🏢 <b>Инстанция:</b> {data['instance']}
📝 <b>Тема:</b> {data['topic']}
👤 <b>ФИО:</b> {data['full_name']}
📞 <b>Связь:</b> {data['contact_method']}
📎 <b>Файлов:</b> {len(data.get('media_files', []))}

💬 <b>Текст:</b>
{data['text']}
    """
    
    await message.answer(
        text=summary,
        reply_markup=get_confirm_keyboard(),
        parse_mode='HTML'
    )
    await state.set_state(AppealStates.confirming_appeal)

@dp.callback_query(F.data == "send_appeal", StateFilter(AppealStates.confirming_appeal))
async def send_appeal(callback: types.CallbackQuery, state: FSMContext):
    """Отправка обращения"""
    data = await state.get_data()
    
    # Создание объекта обращения
    appeal = Appeal(
        instance=data['instance'],
        topic=data['topic'],
        text=data['text'],
        full_name=data['full_name'],
        contact_method=data['contact_method'],
        media_files=data.get('media_files', []),
        doc_files=data.get('doc_files', [])
    )
    
    await callback.message.edit_text("⏳ Отправляем ваше обращение...")
    
    # Отправка оператору
    operator_success = await send_to_operator(appeal)
    
    # Отправка на почту
    email_success = await send_email(appeal)
    
    if operator_success and email_success:
        success_message = """
✅ <b>Ваше обращение успешно направлено администрации Колледжа!</b>

⏰ <b>С вами свяжутся как можно скорее.</b>

Используйте /start для подачи нового обращения.
        """
        
        logger.info(f"Обращение успешно отправлено: {appeal.topic} от {appeal.full_name}")
        
    else:
        success_message = """
✅ <b>Ваше обращение успешно направлено администрации Колледжа!</b>

⏰ <b>В ближайшие время с Вами свяжутся.</b>

Используйте /start для подачи нового обращения.
        """
        
        logger.warning(f"Частичная отправка обращения: {appeal.topic}")
    
    await callback.message.edit_text(
        text=success_message,
        reply_markup=get_main_menu_keyboard(),
        parse_mode='HTML'
    )
    
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "cancel_appeal")
async def cancel_appeal(callback: types.CallbackQuery, state: FSMContext):
    """Отмена обращения"""
    await callback.message.edit_text(
        text="❌ Обращение отменено.\n\nВыберите действие:",
        reply_markup=get_main_menu_keyboard()
    )
    await state.clear()
    await callback.answer()

# Обработчик неизвестных сообщений
@dp.message()
async def unknown_message(message: types.Message):
    """Обработка неизвестных сообщений"""
    await message.answer(
        "❓ Команда не распознана.\n\n"
        "Используйте /start для начала работы с ботом.",
        reply_markup=get_main_menu_keyboard()
    )

# Основная функция запуска
async def main():
    """Запуск бота"""
    logger.info("Запуск Telegram-бота 'Горячая линия обращений студентов'")
    
    # Проверка конфигурации
    if not all([BOT_TOKEN, OPERATOR_ID, SMTP_USER, SMTP_PASSWORD, CORPORATE_EMAIL]):
        logger.error("Не все обязательные переменные окружения установлены!")
        return
    
    logger.info(f"Бот настроен для оператора ID: {OPERATOR_ID}")
    logger.info(f"Корпоративная почта: {CORPORATE_EMAIL}")
    
    try:
        # Запуск поллинга
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())