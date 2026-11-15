"""Клавиатуры и экраны: главное меню, приветствие, помощь.

Здесь же — общие кнопки навигации, чтобы названия действий были
согласованы во всех сценариях.
"""

from __future__ import annotations

from bot.states import Screen
from bot.utils.ui.keyboards import Keyboard, callback_button, link_button
from bot.utils.ui.screen import ScreenView


def main_menu_keyboard() -> Keyboard:
    """Главное меню (ТЗ п. 3.2)."""
    return (
        Keyboard()
        .row(
            callback_button("💸 Добавить расход", "tx:new", "expense"),
            callback_button("💰 Добавить доход", "tx:new", "income"),
        )
        .row(
            callback_button("📊 Мой баланс", "balance:show"),
            callback_button("🕘 История", "history:open"),
        )
        .row(
            callback_button("📈 Статистика", "stats:open"),
            callback_button("🎯 Мой бюджет", "budget:open"),
        )
        .row(
            callback_button("🏦 Цели накопления", "goals:open"),
            callback_button("🤖 AI-помощник", "ai:open"),
        )
        .row(
            callback_button("⚙️ Настройки", "settings:open"),
            callback_button("❓ Помощь", "help:show"),
        )
        .row(
            callback_button("👤 О проекте", "about:show"),
        )
    )


def back_to_menu_keyboard(text: str = "🏠 Главное меню") -> Keyboard:
    return Keyboard().row(callback_button(text, "menu:main"))


def cancel_keyboard() -> Keyboard:
    """Кнопка отмены текущего действия."""
    return Keyboard().row(
        callback_button("✖️ Отмена", "menu:main"),
    )


WELCOME_TEXT = (
    "<b>Умный кошелёк</b> — бот для учёта личных финансов в MAX.\n\n"
    "Я помогу:\n"
    "• записывать расходы и доходы — кнопками или обычным сообщением;\n"
    "• «Потратил 1250 на продукты» — и операция уже в истории;\n"
    "• следить за балансом, историей и статистикой;\n"
    "• ставить месячный бюджет и лимиты по категориям;\n"
    "• копить на цели и видеть прогресс.\n\n"
    "Базовые функции бесплатны и без ограничений. "
    "AI-функции (разбор свободного текста, голосовой ввод и AI-помощник) "
    "доступны в бесплатном лимите, дальше — по подписке."
)

MAIN_MENU_TEXT = (
    "<b>Главное меню</b>\n\n"
    "Выберите действие или просто напишите операцию, например:\n"
    "<i>«Потратил 1250 на продукты»</i>"
)

HELP_TEXT = (
    "<b>Помощь</b>\n\n"
    "<b>1. Как записывать операции</b>\n"
    "Кнопками: «Добавить расход» → сумма → категория → подтверждение.\n"
    "Текстом: напишите фразу, и я пойму тип, сумму и категорию:\n"
    "  • «Кофе 320»\n"
    "  • «Зарплата 85000»\n"
    "  • «Такси 450 вчера»\n"
    "Голосом: отправьте голосовое сообщение — я распознаю речь. "
    "Голосовой ввод использует тот же лимит AI-запросов.\n\n"
    "<b>2. Что я умею бесплатно</b>\n"
    "Учёт доходов и расходов, категории, баланс, история, статистика, "
    "бюджеты, цели, экспорт в CSV и Excel.\n\n"
    "<b>3. AI-функции</b>\n"
    "Разбор свободного текста, несколько операций в одном сообщении, "
    "голосовой ввод и AI-помощник. Бесплатный лимит запросов указан в разделе "
    "«AI-помощник».\n\n"
    "<b>4. Команды</b>\n"
    "/start — начать или вернуться в меню\n"
    "/menu — главное меню\n"
    "/balance — баланс\n"
    "/help — эта справка\n\n"
    "Все ваши данные видны только вам."
)


ABOUT_TEXT = (
    "<b>О проекте</b>\n\n"
    "Здравствуйте! Меня зовут <b>Михаил</b>, я программист-разработчик "
    "интеллектуальных чат-ботов с искусственным интеллектом. Рад представить "
    "вам свой новый проект — <b>«Умный кошелёк»</b>!\n\n"
    "Это ваш персональный финансовый помощник, который поможет контролировать "
    "доходы и расходы, планировать бюджет, анализировать финансовые привычки "
    "и разумнее распоряжаться деньгами. Моя цель — сделать управление личными "
    "финансами простым, понятным и доступным каждому. Проект постоянно "
    "развивается, и ваши идеи помогут сделать его ещё лучше!\n\n"
    "Если у вас есть вопросы, предложения и пожелания — напишите мне.\n\n"
    "Также принимаю заказы на разработку чат-ботов любой сложности "
    "для Telegram, MAX и ВКонтакте. Воплотим в жизнь ваши идеи и создадим бота, "
    "который решит именно ваши задачи. Всё ограничивается только вашей фантазией!"
)

#: Ссылка для связи (голосовая ссылка-визитка, работает везде).
ABOUT_CONTACT_URL = "https://golnk.ru/pbB0G"


def welcome_screen() -> ScreenView:
    """Приветствие для нового пользователя перед онбордингом."""
    view = ScreenView(text=WELCOME_TEXT)
    view.keyboard.row(callback_button("▶️ Начать настройку", "onboarding:start"))
    return view


def main_menu_screen(text: str = MAIN_MENU_TEXT) -> ScreenView:
    """Главное меню с сохранением экрана."""
    view = ScreenView(text=text, keyboard=main_menu_keyboard())
    view.next_screen = Screen.MAIN_MENU
    view.state_data = {}
    return view


def help_screen() -> ScreenView:
    view = ScreenView(text=HELP_TEXT, keyboard=back_to_menu_keyboard())
    view.next_screen = Screen.HELP
    return view


def about_screen() -> ScreenView:
    """Экран «О проекте» с кликабельной ссылкой на связь.

    MAX делает ссылку в тексте кликабельной автоматически (HTML-разметка),
    но дополнительно добавляем кнопку-ссылку — так надёжнее на всех клиентах.
    """
    keyboard = Keyboard()
    keyboard.row(link_button("💬 Написать Михаилу", ABOUT_CONTACT_URL))
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))
    view = ScreenView(text=ABOUT_TEXT, keyboard=keyboard)
    view.next_screen = Screen.ABOUT
    return view

