import difflib
import re
from typing import Dict, Optional, Tuple


# ==============================================================================
# ПУНКТ 1.3 ТЗ v3.0: ВСТРОЕННЫЙ СЛОВАРЬ ИГРОВЫХ МЕНЮ И ТЕРМИНОВ (160+ СЛОВ, 0 МС)
# ==============================================================================
GAME_UI_DICT: Dict[str, str] = {
    # Горизонтальные вкладки игровых меню (из реальных скриншотов)
    "play": "ИГРАТЬ",
    "event": "СОБЫТИЕ",
    "events": "СОБЫТИЯ",
    "loadout": "СНАРЯЖЕНИЕ",
    "loadouts": "СНАРЯЖЕНИЕ",
    "battle pass": "БОЕВОЙ ПРОПУСК",
    "challenges": "ИСПЫТАНИЯ",
    "challenge": "ИСПЫТАНИЕ",
    "store": "МАГАЗИН",
    "shop": "МАГАЗИН",
    "profile": "ПРОФИЛЬ",
    "career": "КАРЬЕРА",
    "barracks": "КАЗАРМА",
    "armory": "ОРУЖЕЙНАЯ",
    "operators": "ОПЕРАТИВНИКИ",
    "operator": "ОПЕРАТИВНИК",
    "weapons": "ОРУЖИЕ",
    "weapon": "ОРУЖИЕ",
    "heroes": "ГЕРОИ",
    "hero": "ГЕРОЙ",
    "champions": "ЧЕМПИОНЫ",
    "agents": "АГЕНТЫ",
    "custom": "СВОЯ ИГРА",
    "customize": "КАСТОМИЗАЦИЯ",
    "customization": "ПЕРСОНАЛИЗАЦИЯ",
    "locker": "ШКАФЧИК",
    "collection": "КОЛЛЕКЦИЯ",
    "collections": "КОЛЛЕКЦИИ",
    "clans": "КЛАНЫ",
    "clan": "КЛАН",
    "guild": "ГИЛЬДИЯ",
    "social": "СОЦИАЛЬНОЕ",
    "friends": "ДРУЗЬЯ",
    "party": "ГРУППА",
    "squad": "ОТРЯД",
    "leaderboards": "ТАБЛИЦА ЛИДЕРОВ",
    "leaderboard": "ЛИДЕРЫ",
    "rankings": "РЕЙТИНГ",
    "ranked": "РЕЙТИНГОВАЯ",
    "unranked": "БЕЗ РЕЙТИНГА",
    "casual": "ОБЫЧНАЯ ИГРА",
    "competitive": "СОРЕВНОВАТЕЛЬНЫЙ",
    "tournament": "ТУРНИР",
    "tournaments": "ТУРНИРЫ",
    "replays": "ПОВТОРЫ",
    "watch": "ПРОСМОТР",
    "news": "НОВОСТИ",
    "patch notes": "СПИСОК ИЗМЕНЕНИЙ",
    # Системные разделы и настройки
    "settings": "НАСТРОЙКИ",
    "options": "ОПЦИИ",
    "controls": "УПРАВЛЕНИЕ",
    "keybinds": "КЛАВИШИ",
    "graphics": "ГРАФИКА",
    "video": "ВИДЕО",
    "display": "ЭКРАН",
    "audio": "ЗВУК",
    "sound": "ЗВУК",
    "voice chat": "ГОЛОСОВОЙ ЧАТ",
    "interface": "ИНТЕРФЕЙС",
    "gameplay": "ГЕЙМПЛЕЙ",
    "accessibility": "ДОСТУПНОСТЬ",
    "account": "АККАУНТ",
    "network": "СЕТЬ",
    "credits": "АВТОРЫ",
    "help": "ПОМОЩЬ",
    "tutorials": "ОБУЧЕНИЕ",
    "tutorial": "ОБУЧЕНИЕ",
    "training": "ТРЕНИРОВКА",
    "practice": "ПРАКТИКА",
    "shooting range": "СТРЕЛЬБИЩЕ",
    "campaign": "КАМПАНИЯ",
    "story": "СЮЖЕТ",
    "singleplayer": "ОДИНОЧНАЯ ИГРА",
    "multiplayer": "МУЛЬТИПЛЕЕР",
    "co-op": "КООПЕРАТИВ",
    "cooperative": "КООПЕРАТИВ",
    "custom games": "СВОИ ИГРЫ",
    "server browser": "СПИСОК СЕРВЕРОВ",
    "quick play": "БЫСТРАЯ ИГРА",
    "quick match": "БЫСТРЫЙ МАТЧ",
    "find match": "НАЙТИ МАТЧ",
    "matchmaking": "ПОИСК ИГРЫ",
    "searching": "ПОИСК...",
    "ready": "ГОТОВ",
    "not ready": "НЕ ГОТОВ",
    # Кнопки действий
    "start": "СТАРТ",
    "start game": "НАЧАТЬ ИГРУ",
    "continue": "ПРОДОЛЖИТЬ",
    "resume": "ПРОДОЛЖИТЬ",
    "new game": "НОВАЯ ИГРА",
    "load game": "ЗАГРУЗИТЬ ИГРУ",
    "save game": "СОХРАНИТЬ ИГРУ",
    "save": "СОХРАНИТЬ",
    "load": "ЗАГРУЗИТЬ",
    "back": "НАЗАД",
    "return": "ВЕРНУТЬСЯ",
    "close": "ЗАКРЫТЬ",
    "exit": "ВЫХОД",
    "exit to desktop": "ВЫЙТИ НА РАБОЧИЙ СТОЛ",
    "exit game": "ВЫЙТИ ИЗ ИГРЫ",
    "quit": "ВЫЙТИ",
    "quit game": "ВЫЙТИ ИЗ ИГРЫ",
    "apply": "ПРИМЕНИТЬ",
    "confirm": "ПОДТВЕРДИТЬ",
    "accept": "ПРИНЯТЬ",
    "decline": "ОТКЛОНИТЬ",
    "cancel": "ОТМЕНА",
    "reset": "СБРОСИТЬ",
    "default": "ПО УМОЛЧАНИЮ",
    "defaults": "ПО УМОЛЧАНИЮ",
    "select": "ВЫБРАТЬ",
    "equip": "ЭКИПИРОВАТЬ",
    "equipped": "ЭКИПИРОВАНО",
    "unequip": "СНЯТЬ",
    "equip item": "ЭКИПИРОВАТЬ",
    "drop item": "ВЫБРОСИТЬ",
    "upgrade": "Улучшение",
    "upgrades": "Улучшения",
    "craft": "СОЗДАТЬ",
    "dismantle": "РАЗОБРАТЬ",
    "buy": "КУПИТЬ",
    "purchase": "КУПИТЬ",
    "sell": "ПРОДАТЬ",
    "claim": "ЗАБРАТЬ",
    "claim reward": "ЗАБРАТЬ НАГРАДУ",
    "claim all": "ЗАБРАТЬ ВСЁ",
    "redeem": "АКТИВИРОВАТЬ",
    "unlock": "РАЗБЛОКИРОВАТЬ",
    "locked": "ЗАБЛОКИРОВАНО",
    "unlocked": "ОТКРЫТО",
    "inspect": "ОСМОТРЕТЬ",
    "preview": "ПРЕДПРОСМОТР",
    "next": "ДАЛЕЕ",
    "previous": "НАЗАД",
    "skip": "ПРОПУСТИТЬ",
    "retry": "ПОВТОРИТЬ",
    "respawn": "ВОЗРОДИТЬСЯ",
    "deploy": "ВЫСАДКА",
    "spectate": "НАБЛЮДАТЬ",
    "invite": "ПРИГЛАСИТЬ",
    "join": "ПРИСОЕДИНИТЬСЯ",
    "leave": "ПОКИНУТЬ",
    # RPG, стратегия, башни и интерфейс
    "inventory": "ИНВЕНТАРЬ",
    "character": "ПЕРСОНАЖ",
    "skills": "НАВЫКИ",
    "abilities": "СПОСОБНОСТИ",
    "talents": "ТАЛАНТЫ",
    "perks": "ПЕРКИ",
    "attributes": "ХАРАКТЕРИСТИКИ",
    "stats": "СТАТИСТИКА",
    "statistics": "СТАТИСТИКА",
    "quests": "ЗАДАНИЯ",
    "quest log": "ЖУРНАЛ ЗАДАНИЙ",
    "missions": "МИССИИ",
    "mission": "МИССИЯ",
    "objectives": "ЦЕЛИ",
    "map": "КАРТА",
    "world map": "КАРТА МИРА",
    "journal": "ЖУРНАЛ",
    "codex": "КОДЕКС",
    "bestiary": "БЕСТИАРИЙ",
    "achievements": "ДОСТИЖЕНИЯ",
    "trophies": "ТРОФЕИ",
    "rewards": "НАГРАДЫ",
    "daily challenges": "ЕЖЕДНЕВНЫЕ ИСПЫТАНИЯ",
    "weekly challenges": "ЕЖЕНЕДЕЛЬНЫЕ ИСПЫТАНИЯ",
    "season pass": "СЕЗОННЫЙ ПРОПУСК",
    "free": "БЕСПЛАТНО",
    "premium": "ПРЕМИУМ",
    "level": "УРОВЕНЬ",
    "rank": "РАНГ",
    "tier": "УРОВЕНЬ",
    "victory": "ПОБЕДА",
    "defeat": "ПОРАЖЕНИЕ",
    "draw": "НИЧЬЯ",
    "towers": "Башни",
    "tower": "Башня",
    "demons": "Демоны",
    "demon": "Демон",
    "blockade": "Блокада",
    "cost": "Стоимость",
    "constructs": "Постройки",
    "construct": "Постройка",
    "barricade": "Баррикада",
    "barricades": "Баррикады",
    "can't attack": "Не может атаковать",
    "cannot attack": "Не может атаковать",
    "respawn time": "Время возрождения",
    "cooldown": "Перезарядка",
    "attack speed": "Скорость атаки",
    "damage": "Урон",
    "health": "Здоровье",
    "range": "Дальность",
    "clients and partners": "Клиенты и партнеры",
    "contacts": "Контакты",
    "projects": "Проекты",
    "knowledge base": "База знаний",
    "meetings and calls": "Встречи и звонки",
    "create new project": "Создать проект",
    "export report": "Экспорт отчета",
    "active tasks": "Активные задачи",
    "team members": "Участники команды",
    "ai features": "ИИ-функции",
    "view changes": "Посмотреть изменения",
    # Быстрые реплики игрового чата и пинги (v3.6)
    "gg": "Хорошая игра",
    "gg wp": "Хорошая игра, отлично сыграно",
    "wp": "Отлично сыграно",
    "well played": "Отлично сыграно",
    "gl hf": "Удачи и приятной игры",
    "glhf": "Удачи и приятной игры",
    "gl": "Удачи",
    "hf": "Приятной игры",
    "nt": "Хорошая попытка",
    "nice try": "Хорошая попытка",
    "mb": "Моя ошибка",
    "my bad": "Моя ошибка",
    "no problem": "Без проблем",
    "np": "Без проблем",
    "thank you": "Спасибо",
    "thanks": "Спасибо",
    "thx": "Спасибо",
    "ty": "Спасибо",
    "tysm": "Огромное спасибо",
    "sorry": "Извините",
    "sry": "Извините",
    "wait": "Подождите",
    "wait for me": "Подождите меня",
    "follow me": "За мной",
    "need help": "Нужна помощь",
    "help me": "Помогите мне",
    "need ammo": "Нужны патроны",
    "need healing": "Нужно лечение",
    "need heal": "Нужно лечение",
    "need backup": "Нужна подмога",
    "enemy spotted": "Замечен враг",
    "enemy here": "Враг здесь",
    "enemies ahead": "Впереди враги",
    "on my way": "Уже иду",
    "omw": "Уже иду",
    "fall back": "Отступаем",
    "retreat": "Отступаем",
    "push": "Атакуем",
    "hold position": "Держать позицию",
    "hold the line": "Держать линию",
    "defend": "Защищайте",
    "attack": "Атакуйте",
    "cover me": "Прикройте меня",
    "group up": "Собраться вместе",
    "regroup": "Перегруппироваться",
    "spread out": "Рассредоточиться",
    "reloading": "Перезаряжаюсь",
    "out of mana": "Нет маны",
    "oom": "Нет маны",
    "out of ammo": "Нет патронов",
    "low hp": "Мало здоровья",
    "ult ready": "Ульта готова",
    "ultimate ready": "Ульта готова",
    "lfg": "Ищу группу",
    "lfm": "Ищу игроков в группу",
    "afk": "Отошел",
    "brb": "Скоро вернусь",
    "inv": "Пригласите",
    "invite me": "Пригласите меня",
    "ready check": "Проверка готовности",
    "nice shot": "Отличный выстрел",
    "ns": "Отличный выстрел",
    "good job": "Отличная работа",
    "gj": "Отличная работа",
}


def lookup_game_ui_dict(text: str) -> Optional[str]:
    """Мгновенный поиск по GAME_UI_DICT: точный, без окончания -s/-es и нечеткий (cutoff=0.82)."""
    if not text:
        return None
    low = " ".join(text.strip().lower().split())
    if not low:
        return None

    # 1. Точное совпадение
    if low in GAME_UI_DICT:
        return GAME_UI_DICT[low]

    words = low.split()
    # 2. Проверка единственного числа без окончания -s / -es для одиночных слов
    if len(words) == 1 and len(low) >= 4:
        if low.endswith("es") and low[:-2] in GAME_UI_DICT:
            return GAME_UI_DICT[low[:-2]]
        if low.endswith("s") and low[:-1] in GAME_UI_DICT:
            return GAME_UI_DICT[low[:-1]]

    # 3. Нечеткий поиск для строк из 1-2 слов длиной >= 5 символов (опечатки OCR в 1-2 буквах)
    if 1 <= len(words) <= 2 and len(low) >= 5:
        matches = difflib.get_close_matches(low, GAME_UI_DICT.keys(), n=3, cutoff=0.82)
        if matches:
            if low.endswith("s"):
                for cand in matches:
                    if cand.endswith("s"):
                        return GAME_UI_DICT[cand]
            return GAME_UI_DICT[matches[0]]
    return None


# ==============================================================================
# ШАБЛОНЫ С ЧИСЛАМИ: «35m ago», «471 upvotes», «16.0s Respawn Time», «Barricade x1».
# ==============================================================================
def russian_plural(count: int, one: str, few: str, many: str) -> str:
    tail100, tail10 = count % 100, count % 10
    if 11 <= tail100 <= 14:
        return many
    if tail10 == 1:
        return one
    if 2 <= tail10 <= 4:
        return few
    return many


AGO_UNITS: Dict[str, Tuple[str, str, str]] = {
    "s": ("секунду", "секунды", "секунд"),
    "sec": ("секунду", "секунды", "секунд"),
    "m": ("минуту", "минуты", "минут"),
    "min": ("минуту", "минуты", "минут"),
    "h": ("час", "часа", "часов"),
    "hr": ("час", "часа", "часов"),
    "d": ("день", "дня", "дней"),
    "w": ("неделю", "недели", "недель"),
    "mo": ("месяц", "месяца", "месяцев"),
    "y": ("год", "года", "лет"),
    "yr": ("год", "года", "лет"),
}
COUNT_NOUNS: Dict[str, Tuple[str, str, str]] = {
    "upvote": ("голос", "голоса", "голосов"),
    "vote": ("голос", "голоса", "голосов"),
    "comment": ("комментарий", "комментария", "комментариев"),
    "member": ("участник", "участника", "участников"),
    "view": ("просмотр", "просмотра", "просмотров"),
    "reply": ("ответ", "ответа", "ответов"),
}
AGO_REGEX = re.compile(r"(\d+)\s*(s|sec|m|min|h|hr|d|w|mo|y|yr)s?\s+ago", re.IGNORECASE)
COUNT_REGEX = re.compile(r"([\d.,]+[kKmM]?)\s+([a-zA-Z]+)")
RESPAWN_TIME_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*s\s+respawn\s+time", re.IGNORECASE)
COOLDOWN_TIME_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*s\s+cooldown", re.IGNORECASE)
BARRICADE_MULT_REGEX = re.compile(r"barricade\s+x\s*(\d+)", re.IGNORECASE)


def _singular(noun: str) -> str:
    noun = noun.lower()
    if noun.endswith("ies"):
        return noun[:-3] + "y"
    return noun[:-1] if noun.endswith("s") else noun


def translate_ui_pattern(text: str) -> Optional[str]:
    """Перевод счётчиков, таймеров перезарядки и «N ago» без модели; None, если не шаблон."""
    stripped = re.sub(r"^[@©®¤§°•·]+\s*(?=\d)", "", text.strip())
    match = RESPAWN_TIME_REGEX.fullmatch(stripped)
    if match:
        return f"{match.group(1)} с Время возрождения"
    match = COOLDOWN_TIME_REGEX.fullmatch(stripped)
    if match:
        return f"{match.group(1)} с Перезарядка"
    match = BARRICADE_MULT_REGEX.fullmatch(stripped)
    if match:
        return f"Баррикада x{match.group(1)}"
    match = AGO_REGEX.fullmatch(stripped)
    if match:
        count = int(match.group(1))
        unit = AGO_UNITS[match.group(2).lower()]
        return f"{count} {russian_plural(count, *unit)} назад"
    match = COUNT_REGEX.fullmatch(stripped)
    if match and _singular(match.group(2)) in COUNT_NOUNS:
        number = match.group(1)
        digits = number.replace(",", "").replace(".", "")
        # «1.2k» — дробное число тысяч: «голосов», как у любого большого числа.
        count = int(digits) if digits.isdigit() and number[-1].isdigit() else 5
        return f"{number} {russian_plural(count, *COUNT_NOUNS[_singular(match.group(2))])}"
    return None
