"""Arabic Telegram tutor for mathematics and physics. Run: python bot.py"""
import asyncio
import base64
import io
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from dotenv import load_dotenv

from questions import BY_ID, select_question
from storage import Storage
from tutor import LEVEL_NAMES, SUBJECT_NAMES, Tutor

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

store: Storage
teacher: Tutor | None = None
DAILY_AI_LIMIT = max(1, int(os.getenv('DAILY_AI_LIMIT', '25')))
TOPICS = {
    'math': {
        'beginner': 'الجمع والطرح', 'intermediate': 'المعادلات الخطية',
        'highschool': 'الدوال التربيعية', 'university': 'أساسيات التفاضل والتكامل',
    },
    'physics': {
        'beginner': 'الحركة والسرعة', 'intermediate': 'القوة وقوانين نيوتن',
        'highschool': 'الطاقة والشغل', 'university': 'قوانين الديناميكا الحرارية',
    },
    'software': {
        'beginner': 'أساسيات Python', 'intermediate': 'الخوارزميات وهياكل البيانات',
        'highschool': 'تصميم البرمجيات والاختبارات', 'university': 'هندسة الأنظمة الموزعة',
    },
    'electronics': {
        'beginner': 'المقاومة والجهد والتيار', 'intermediate': 'قوانين كيرشوف',
        'highschool': 'دوائر المنطق الرقمي', 'university': 'الأنظمة المدمجة والمتحكمات الدقيقة',
    },
}


def button(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=data)


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button('📐 الرياضيات', 'subject:math'), button('⚛️ الفيزياء', 'subject:physics')],
        [button('💻 البرمجيات', 'subject:software'), button('🔌 الإلكترونيات', 'subject:electronics')],
        [button('📚 اشرح لي درسًا', 'action:lesson'), button('🧠 اختبرني', 'action:quiz')],
        [button('🎓 مستواي', 'action:level'), button('📊 تقدمي', 'action:progress')],
    ])


def level_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button('🌱 مبتدئ', 'level:beginner'), button('📘 متوسط', 'level:intermediate')],
        [button('🎓 ثانوي', 'level:highschool'), button('🏛️ جامعي', 'level:university')],
    ])


def next_quiz_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button('🧠 سؤال آخر', 'action:quiz'), button('🏠 القائمة', 'action:home')],
    ])


def profile_text(user_id: int) -> str:
    profile = store.profile(user_id)
    total = profile['attempted']
    correct = profile['correct']
    accuracy = f'{correct / total:.0%}' if total else '—'
    return (f'📊 تقرير تقدمك\n\n'
            f'المادة: {SUBJECT_NAMES[profile["subject"]]}\n'
            f'المستوى: {LEVEL_NAMES[profile["level"]]}\n'
            f'إجابات صحيحة: {correct}\n'
            f'الأسئلة التي أجبت عنها: {total}\n'
            f'نسبة النجاح: {accuracy}\n\n'
            'يمكنك تغيير المادة أو المستوى من القائمة.')


async def send_chunks(message: Message, text: str):
    """Telegram limits message length. Send text as plain text, which is safe for formulas."""
    remaining = text.strip()
    while remaining:
        if len(remaining) <= 3800:
            await message.answer(remaining)
            break
        split = remaining.rfind('\n', 0, 3800)
        if split < 1000:
            split = 3800
        await message.answer(remaining[:split])
        remaining = remaining[split:].strip()


async def ask_ai(message: Message, prompt: str, image_data_url: str | None = None,
                 user_id: int | None = None):
    # Callback buttons carry the bot-authored message, not the student author.
    if user_id is None:
        if not message.from_user:
            return
        user_id = message.from_user.id
    if not store.claim_quota(user_id, DAILY_AI_LIMIT):
        await message.answer(f'⏳ وصلت إلى الحد اليومي ({DAILY_AI_LIMIT} طلبًا ذكيًا). يمكنك متابعة /quiz، ويُعاد ضبط الحد في منتصف الليل بتوقيت UTC.')
        return
    profile = store.profile(user_id)
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        response = await teacher.ask(
            level=profile['level'], subject=profile['subject'], question=prompt,
            history=store.recent_history(user_id), image_data_url=image_data_url,
        )
    except Exception:
        store.release_quota(user_id)
        log.exception('AI request failed for user %s', user_id)
        await message.answer('تعذر الاتصال بنموذج Ollama المحلي. تحقق من تشغيل الحاويات وتنزيل النموذج: docker compose logs ollama model-init tutor.')
        return
    store.add_exchange(user_id, prompt if not image_data_url else f'{prompt} [صورة أرسلها الطالب]', response)
    await send_chunks(message, response)


async def send_quiz(message: Message, user_id: int):
    p = store.profile(user_id)
    if p['subject'] not in ('math', 'physics'):
        await message.answer('🧠 بنك الأسئلة الحالي مخصص للرياضيات والفيزياء. في البرمجيات والإلكترونيات اطلب: «اختبرني بسؤال عن الموضوع» ليطرح النموذج المحلي سؤالًا.')
        return
    q = select_question(p['subject'], p['level'], p['last_question'])
    store.set_active_quiz(user_id, q.id)
    opts = [[button(f'{i+1}. {option}', f'answer:{q.id}:{i}')]
            for i, option in enumerate(q.options)]
    await message.answer(
        f'🧠 اختبار {SUBJECT_NAMES[q.subject]} — {LEVEL_NAMES[q.level]}\n\n{q.prompt}\n\nاختر إجابة واحدة:',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=opts),
    )


@router.message(CommandStart())
async def on_start(message: Message):
    assert message.from_user
    p = store.profile(message.from_user.id)
    await message.answer(
        'أهلًا بك في أستاذ الرياضيات والفيزياء! 👋\n\n'
        'نتعلم معًا خطوة بخطوة، ونراجع المفاهيم بالأسئلة والتمارين.\n'
        f'مستواك الحالي: {LEVEL_NAMES[p["level"]]}، المادة: {SUBJECT_NAMES[p["subject"]]}.\n\n'
        'اختر مادة، ثم اضغط «اشرح لي درسًا» أو «اختبرني».\n'
        'ويمكنك إرسال سؤالك مباشرة، (حاليًا الأسئلة النصية فقط).', reply_markup=menu(),
    )


@router.message(Command('help'))
async def on_help(message: Message):
    await message.answer(
        '📖 الأوامر:\n'
        '/start — القائمة الرئيسية\n'
        '/math — اختيار الرياضيات\n'
        '/physics — اختيار الفيزياء\n'
        '/software — هندسة البرمجيات\n'
        '/electronics — هندسة الإلكترونيات\n'
        '/level — تغيير المستوى\n'
        '/lesson موضوع — شرح موضوع تختاره (مثل /lesson الكسور)\n'
        '/quiz — اختبار قصير من بنك الأسئلة\n'
        '/progress — عرض تقدمك\n'
        '/new — بدء محادثة جديدة مع المعلم\n'
        '/delete_data — حذف كل بياناتك المسجلة\n\n'
        'يمكنك إرسال سؤالك النصي. النموذج الحالي نصي محلي ولا يدعم تحليل الصور.\n'
        f'حد الشرح الذكي اليومي: {DAILY_AI_LIMIT} طلبًا لكل مستخدم.', reply_markup=menu(),
    )


@router.message(Command('math'))
async def on_math(message: Message):
    assert message.from_user
    store.set_subject(message.from_user.id, 'math')
    store.clear_history(message.from_user.id)
    await message.answer('📐 اخترنا الرياضيات. اسأل عن أي مسألة، أو ابدأ درسًا أو اختبارًا.', reply_markup=menu())


@router.message(Command('physics'))
async def on_physics(message: Message):
    assert message.from_user
    store.set_subject(message.from_user.id, 'physics')
    store.clear_history(message.from_user.id)
    await message.answer('⚛️ اخترنا الفيزياء. اسأل عن الحركة أو الكهرباء أو أي موضوع آخر.', reply_markup=menu())


@router.message(Command('software'))
async def on_software(message: Message):
    assert message.from_user
    store.set_subject(message.from_user.id, 'software')
    store.clear_history(message.from_user.id)
    await message.answer('💻 اخترنا هندسة البرمجيات.', reply_markup=menu())


@router.message(Command('electronics'))
async def on_electronics(message: Message):
    assert message.from_user
    store.set_subject(message.from_user.id, 'electronics')
    store.clear_history(message.from_user.id)
    await message.answer('🔌 اخترنا هندسة الإلكترونيات.', reply_markup=menu())


@router.message(Command('level'))
async def on_level(message: Message):
    await message.answer('اختر مستواك الدراسي:', reply_markup=level_menu())


@router.message(Command('progress'))
async def on_progress(message: Message):
    assert message.from_user
    await message.answer(profile_text(message.from_user.id), reply_markup=menu())


@router.message(Command('quiz'))
async def on_quiz(message: Message):
    assert message.from_user
    await send_quiz(message, message.from_user.id)


@router.message(Command('lesson'))
async def on_lesson(message: Message):
    assert message.from_user
    p = store.profile(message.from_user.id)
    topic = (message.text or '').partition(' ')[2].strip() or TOPICS[p['subject']][p['level']]
    await ask_ai(message, f'اشرح درس «{topic}» من الصفر بما يناسب مستواي، ثم أعطني تمرينًا قصيرًا.')


@router.message(Command('new'))
async def on_new(message: Message):
    assert message.from_user
    store.clear_history(message.from_user.id)
    await message.answer('✅ بدأت محادثة جديدة. تذكرت مستواك ونتائج اختباراتك، ومسحت سياق الحوار السابق.', reply_markup=menu())


@router.message(Command('delete_data'))
async def on_delete_data(message: Message):
    await message.answer('⚠️ هل تريد حذف مستواك، تقدمك، سجل محادثاتك وعدادات الاستعمال نهائيًا؟',
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [button('نعم، احذف بياناتي', 'delete:confirm'), button('إلغاء', 'delete:cancel')],
                         ]))


@router.callback_query(F.data.startswith('subject:'))
async def select_subject_cb(call: CallbackQuery):
    assert call.from_user
    choice = (call.data or '').split(':', 1)[1]
    if choice not in SUBJECT_NAMES:
        await call.answer('اختيار غير معروف')
        return
    store.set_subject(call.from_user.id, choice)
    store.clear_history(call.from_user.id)
    await call.answer('تم تغيير المادة')
    if call.message:
        await call.message.answer(f'✅ المادة الحالية: {SUBJECT_NAMES[choice]}.', reply_markup=menu())


@router.callback_query(F.data.startswith('level:'))
async def select_level_cb(call: CallbackQuery):
    choice = (call.data or '').split(':', 1)[1]
    if choice not in LEVEL_NAMES:
        await call.answer('اختيار غير معروف')
        return
    store.set_level(call.from_user.id, choice)
    store.clear_history(call.from_user.id)
    await call.answer('تم تغيير المستوى')
    if call.message:
        await call.message.answer(f'✅ مستواك الآن: {LEVEL_NAMES[choice]}.', reply_markup=menu())


@router.callback_query(F.data.startswith('answer:'))
async def answer_cb(call: CallbackQuery):
    payload = (call.data or '').split(':')
    if len(payload) != 3 or payload[1] not in BY_ID or not payload[2].isdigit():
        await call.answer('إجابة غير صالحة')
        return
    q = BY_ID[payload[1]]
    selected = int(payload[2])
    if selected not in range(4):
        await call.answer('اختيار غير صالح')
        return
    accepted = store.grade_quiz(call.from_user.id, q.id, selected == q.correct)
    if not accepted:
        await call.answer('انتهى هذا السؤال، أو ظهر سؤال أحدث. اختر «سؤال آخر».', show_alert=True)
        return
    await call.answer('تم التصحيح')
    if call.message:
        verdict = '✅ أحسنت! إجابة صحيحة.' if selected == q.correct else '❌ إجابة غير صحيحة. لا بأس، نتعلم من الخطأ.'
        await call.message.edit_text(
            f'{verdict}\n\nالسؤال: {q.prompt}\n'
            f'إجابتك: {q.options[selected]}\n'
            f'الإجابة الصحيحة: {q.options[q.correct]}\n\n'
            f'💡 الشرح: {q.explanation}', reply_markup=next_quiz_menu(),
        )


@router.callback_query(F.data.startswith('action:'))
async def action_cb(call: CallbackQuery):
    action = (call.data or '').partition(':')[2]
    await call.answer()
    if not call.message:
        return
    if action == 'home':
        await call.message.answer('🏠 القائمة الرئيسية:', reply_markup=menu())
    elif action == 'level':
        await call.message.answer('اختر مستواك:', reply_markup=level_menu())
    elif action == 'progress':
        await call.message.answer(profile_text(call.from_user.id), reply_markup=menu())
    elif action == 'quiz':
        await send_quiz(call.message, call.from_user.id)
    elif action == 'lesson':
        p = store.profile(call.from_user.id)
        await ask_ai(call.message, f'اشرح درس «{TOPICS[p["subject"]][p["level"]]}» ثم ضع تمرينًا لي.',
                     user_id=call.from_user.id)


@router.callback_query(F.data.startswith('delete:'))
async def delete_cb(call: CallbackQuery):
    choice = (call.data or '').partition(':')[2]
    await call.answer()
    if choice == 'confirm':
        store.delete_user(call.from_user.id)
        if call.message:
            await call.message.edit_text('🗑️ حُذفت بياناتك المسجلة في قاعدة بيانات البوت. يمكنك البدء من جديد باستخدام /start.')
    elif call.message:
        await call.message.edit_text('أُلغي الحذف. بياناتك ما زالت محفوظة.')


@router.message(F.photo)
async def on_photo(message: Message):
    await message.answer('🖼️ النموذج المحلي المختار نصي فقط. اكتب نص المسألة لإعطائك شرحًا هندسيًا. يمكن إضافة نموذج بصري محلي لاحقًا.')


@router.message(F.text)
async def on_text(message: Message):
    text = (message.text or '').strip()
    if text.startswith('/'):
        await message.answer('لا أعرف هذا الأمر. أرسل /help لعرض الأوامر.')
        return
    if len(text) > 1200:
        await message.answer('سؤالك طويل جدًا. يرجى اختصاره إلى 1200 حرف أو أقل.')
        return
    await ask_ai(message, text)


@router.message()
async def on_other(message: Message):
    await message.answer('أرسل سؤالًا نصيًا أو صورة لمسألة، أو استخدم /quiz. الصوت والملفات غير مدعومة في هذه النسخة.')


async def main():
    global store, teacher
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token or token.startswith('YOUR_'):
        raise SystemExit('Missing TELEGRAM_BOT_TOKEN in .env. Create a bot using @BotFather.')
    database_url = os.getenv('DATABASE_URL', '').strip()
    if not database_url:
        raise SystemExit('DATABASE_URL is required for PostgreSQL.')
    store = Storage(database_url)
    model = os.getenv('OLLAMA_MODEL', 'qwen2.5:3b')
    teacher = Tutor(model=model, base_url=os.getenv('OLLAMA_URL', 'http://ollama:11434'))
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await bot.set_my_commands([
            BotCommand(command='start', description='ابدأ التعلم'),
            BotCommand(command='math', description='اختر الرياضيات'),
            BotCommand(command='physics', description='اختر الفيزياء'),
            BotCommand(command='software', description='هندسة البرمجيات'),
            BotCommand(command='electronics', description='هندسة الإلكترونيات'),
            BotCommand(command='level', description='اختر مستواك'),
            BotCommand(command='lesson', description='درس جديد'),
            BotCommand(command='quiz', description='اختبرني'),
            BotCommand(command='progress', description='تقدمي'),
            BotCommand(command='new', description='محادثة جديدة'),
            BotCommand(command='help', description='المساعدة'),
        ])
        log.info('Bot started using long polling. Model=%s; Local Ollama enabled=%s', model, teacher is not None)
        await dp.start_polling(bot, tasks_concurrency_limit=25)
    finally:
        await bot.session.close()
        if teacher:
            await teacher.close()


if __name__ == '__main__':
    asyncio.run(main())
