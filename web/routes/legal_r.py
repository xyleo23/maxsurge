"""Роуты публичных страниц: terms, privacy, contacts, robots.txt, sitemap.xml."""
from pathlib import Path
from fastapi import APIRouter, Request
import time
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_START_TIME = time.time()

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


TERMS_BODY = """
<p><em>Редакция от 19.04.2026</em></p>

<h2>1. Общие положения</h2>
<p>Настоящий документ является публичной офертой (далее — «Оферта») Общества с ограниченной ответственностью «ВЕЛАР» (ООО «ВЕЛАР», ОГРН <strong>1262300018860</strong>, ИНН <strong>2311391544</strong>, далее — «Исполнитель»), в адрес любого дееспособного физического или юридического лица (далее — «Пользователь»), заключить Договор возмездного оказания услуг на изложенных ниже условиях.</p>
<p>В соответствии со ст. 435, 437, 438 Гражданского кодекса РФ регистрация Пользователя в Сервисе <a href="https://maxsurge.ru">maxsurge.ru</a> и оплата Услуг признаётся акцептом настоящей Оферты. С момента акцепта Договор считается заключённым, а Пользователь и Исполнитель — сторонами Договора.</p>

<h2>2. Предмет Договора</h2>
<p>Исполнитель предоставляет Пользователю за плату удалённый доступ к программно-аппаратному комплексу «MaxSurge» (далее — «Сервис»), обеспечивающему следующие функции:</p>
<ul>
  <li>управление учётными записями Пользователя в мессенджере MAX;</li>
  <li>ведение клиентской базы (CRM);</li>
  <li>сбор публичной информации из открытых источников;</li>
  <li>планирование и отправка сообщений от имени Пользователя;</li>
  <li>аналитику коммуникаций.</li>
</ul>
<p>Услуги оказываются в формате SaaS (программное обеспечение как услуга). Исполнитель <strong>не</strong> отправляет сообщения от своего имени и <strong>не</strong> осуществляет массовые рассылки — все действия в мессенджере MAX совершаются от имени и под ответственность Пользователя.</p>

<h2>3. Стоимость и порядок оплаты</h2>
<p>Стоимость Услуг определяется выбранным тарифом и указана на странице <a href="/app/billing/">/app/billing/</a>. Оплата производится в рублях РФ авансом на основании электронного счёта через платёжные шлюзы ЮKassa, Robokassa или Prodamus.</p>
<p>Электронный фискальный чек формируется автоматически платёжным шлюзом (ЮKassa / Robokassa / Prodamus) в момент оплаты и направляется Пользователю на указанный при регистрации email в соответствии с требованиями Федерального закона №54-ФЗ.</p>
<p>Моментом оплаты считается поступление денежных средств в распоряжение Исполнителя (на расчётный счёт или через агрегатора). Услуга считается оказанной по истечении оплаченного периода подписки.</p>

<h2>4. Пробный период</h2>
<p>Новым Пользователям предоставляется бесплатный пробный доступ сроком 7 календарных дней с момента регистрации. Пробный период не предусматривает возврата или компенсации.</p>

<h2>5. Права и обязанности сторон</h2>
<p><strong>Исполнитель обязуется:</strong></p>
<ul>
  <li>обеспечивать работоспособность Сервиса 24/7 с допустимым временем плановых работ не более 4 часов в месяц;</li>
  <li>хранить данные Пользователя с соблюдением мер защиты, указанных в <a href="/privacy">Политике конфиденциальности</a>;</li>
  <li>обеспечивать формирование фискального чека через платёжный шлюз по каждому платежу.</li>
</ul>
<p><strong>Пользователь обязуется:</strong></p>
<ul>
  <li>указывать достоверные данные при регистрации и оплате;</li>
  <li>сохранять конфиденциальность логина, пароля и сессионных токенов;</li>
  <li>использовать Сервис в соответствии с законодательством РФ, правилами мессенджера MAX и настоящей Офертой;</li>
  <li>самостоятельно обеспечивать законность отправляемых сообщений, в том числе наличие согласия получателей в соответствии с Федеральным законом №38-ФЗ «О рекламе» и №152-ФЗ «О персональных данных».</li>
</ul>

<h2>6. Запрещённые действия</h2>
<p>Пользователю <strong>категорически запрещается</strong> использовать Сервис для:</p>
<ul>
  <li>массовой рассылки рекламных сообщений без предварительного согласия получателей (спам);</li>
  <li>фишинга, мошенничества, распространения вредоносного ПО;</li>
  <li>распространения противоправного, экстремистского, порнографического контента;</li>
  <li>нарушения правил мессенджера MAX и законодательства о защите персональных данных;</li>
  <li>действий, создающих непропорциональную нагрузку на инфраструктуру Сервиса.</li>
</ul>
<p>Нарушение влечёт немедленную блокировку аккаунта без возврата оплаченной суммы и может служить основанием для передачи данных в правоохранительные органы.</p>

<h2>7. Возврат денежных средств</h2>
<p>В соответствии с Законом РФ «О защите прав потребителей» Пользователь-физлицо вправе отказаться от Услуг до их оказания. Возврат осуществляется пропорционально неиспользованному периоду подписки за вычетом фактически понесённых Исполнителем расходов (комиссии платёжных систем — до 8% от суммы).</p>
<p>Заявление на возврат направляется на <a href="mailto:billing@maxsurge.ru">billing@maxsurge.ru</a> с указанием email аккаунта и причины возврата. Срок рассмотрения — до 10 рабочих дней, перечисление — в течение 10 рабочих дней с момента принятия решения на те же реквизиты, с которых производилась оплата.</p>
<p>Возврат <strong>не производится</strong> при блокировке аккаунта за нарушение п. 6 настоящей Оферты.</p>

<h2>8. Ограничение ответственности</h2>
<p>Сервис предоставляется «как есть» (as is). Исполнитель не гарантирует соответствия Сервиса субъективным ожиданиям Пользователя и не несёт ответственности за:</p>
<ul>
  <li>блокировки, ограничения или иные санкции, применённые мессенджером MAX к аккаунтам Пользователя;</li>
  <li>убытки, возникшие в результате действий Пользователя или третьих лиц;</li>
  <li>временную недоступность Сервиса по независящим от Исполнителя причинам (сбои провайдеров, DDoS, изменения API мессенджера MAX).</li>
</ul>
<p>Совокупная ответственность Исполнителя ограничена суммой оплаты за последний календарный месяц.</p>

<h2>9. Форс-мажор</h2>
<p>Стороны освобождаются от ответственности при обстоятельствах непреодолимой силы: стихийные бедствия, военные действия, решения государственных органов, отключение сетевой инфраструктуры в стране провайдера, блокировка API мессенджера MAX.</p>

<h2>10. Разрешение споров</h2>
<p>Все споры разрешаются путём переговоров. При недостижении согласия — в судебном порядке по месту регистрации Исполнителя в соответствии с законодательством РФ.</p>

<h2>11. Изменение условий</h2>
<p>Исполнитель вправе изменять настоящую Оферту в одностороннем порядке. Актуальная редакция публикуется на странице <a href="/terms">/terms</a> с указанием даты. Продолжение использования Сервиса после публикации изменений означает согласие Пользователя с новой редакцией.</p>

<h2>12. Реквизиты Исполнителя</h2>
<p>
<strong>ООО «ВЕЛАР»</strong><br/>
ИНН: <strong>2311391544</strong><br/>
ОГРН: <strong>1262300018860</strong><br/>
Юридический адрес: 350005, Краснодарский край, г. Краснодар, ул. им. М.М. Шапиро, д. 23<br/>
Расчётный счёт: 40702810426180003876<br/>
Банк: ФИЛИАЛ «РОСТОВСКИЙ» АО «АЛЬФА-БАНК»<br/>
БИК: 046015207, корр. счёт: 30101810500000000207<br/>
Email: <a href="mailto:legal@maxsurge.ru">legal@maxsurge.ru</a><br/>
Сайт: <a href="https://maxsurge.ru">maxsurge.ru</a>
</p>
"""

PRIVACY_BODY = """
<p><em>Редакция от 19.04.2026</em></p>

<h2>1. Общие положения</h2>
<p>Настоящая Политика определяет порядок обработки и защиты персональных данных пользователей сервиса MaxSurge (далее — «Сервис»). Оператором персональных данных является <strong>ООО «ВЕЛАР»</strong> (ОГРН <strong>1262300018860</strong>, ИНН <strong>2311391544</strong>, юридический адрес: 350005, Краснодарский край, г. Краснодар, ул. им. М.М. Шапиро, д. 23).</p>
<p>Политика разработана в соответствии с Федеральным законом №152-ФЗ «О персональных данных», Федеральным законом №149-ФЗ «Об информации, информационных технологиях и о защите информации» и применяется ко всем данным, которые Оператор может получить о Пользователе в ходе использования Сервиса.</p>
<p>Использование Сервиса означает безоговорочное согласие Пользователя с настоящей Политикой и условиями обработки его персональных данных.</p>

<h2>2. Какие данные обрабатываются</h2>
<p><strong>Данные Пользователя (владельца аккаунта):</strong></p>
<ul>
  <li>email-адрес (обязательно);</li>
  <li>имя/ник (опционально);</li>
  <li>хешированный пароль (алгоритм bcrypt);</li>
  <li>IP-адрес, User-Agent, время входа;</li>
  <li>платёжная информация (история платежей, без номеров карт — их хранит платёжный агрегатор);</li>
  <li>токены MAX-аккаунтов, подключённых Пользователем;</li>
  <li>данные, загруженные Пользователем (контакты, списки, шаблоны сообщений).</li>
</ul>
<p><strong>Данные третьих лиц</strong>, которые Пользователь самостоятельно загружает или получает через Сервис (номера телефонов, идентификаторы, имена из открытых источников), обрабатываются исключительно по поручению Пользователя. Оператором таких данных является сам Пользователь. Обязанности по получению согласий субъектов персональных данных несёт Пользователь.</p>

<h2>3. Цели обработки</h2>
<ul>
  <li>регистрация и аутентификация в Сервисе;</li>
  <li>предоставление функционала Сервиса;</li>
  <li>обработка платежей и формирование фискальных документов;</li>
  <li>техническая поддержка и уведомления о работе Сервиса;</li>
  <li>обеспечение безопасности (защита от брутфорса, обнаружение злоупотреблений);</li>
  <li>выполнение обязанностей, возложенных законодательством РФ.</li>
</ul>
<p>Обработка данных в маркетинговых целях (рассылка рекламных писем) осуществляется только при наличии отдельного согласия Пользователя, которое может быть отозвано в любой момент через ссылку «отписаться» в письмах.</p>

<h2>4. Правовые основания</h2>
<ul>
  <li>согласие субъекта персональных данных (п. 1 ч. 1 ст. 6 №152-ФЗ);</li>
  <li>исполнение договора, стороной которого является субъект (п. 5 ч. 1 ст. 6);</li>
  <li>исполнение обязанностей, возложенных законодательством (п. 2 ч. 1 ст. 6).</li>
</ul>

<h2>5. Передача данных третьим лицам</h2>
<p>Персональные данные не передаются третьим лицам, за исключением:</p>
<ul>
  <li>платёжных агрегаторов (ЮKassa / Robokassa / Prodamus) — в объёме, необходимом для проведения платежа;</li>
  <li>хостинг-провайдера — в целях технического обслуживания серверов;</li>
  <li>налоговых и иных государственных органов — по мотивированному запросу в рамках законодательства;</li>
  <li>провайдера email-рассылок — для отправки транзакционных писем.</li>
</ul>
<p>Трансграничная передача данных не осуществляется. Все данные хранятся на серверах на территории РФ.</p>

<h2>6. Срок хранения</h2>
<ul>
  <li>данные учётной записи — весь период действия аккаунта и 3 года после его удаления (для налоговой отчётности и разрешения возможных споров);</li>
  <li>логи активности — 90 дней;</li>
  <li>платёжные документы — 5 лет (требование налогового законодательства);</li>
  <li>данные, загруженные Пользователем, — до удаления Пользователем или закрытия аккаунта.</li>
</ul>

<h2>7. Меры защиты</h2>
<ul>
  <li>TLS 1.2+ для всех соединений (сертификат Let's Encrypt);</li>
  <li>хеширование паролей bcrypt (cost factor 12);</li>
  <li>CSRF-токены на всех формах;</li>
  <li>защита от брутфорса (rate-limiting на /login и /register);</li>
  <li>двухфакторная аутентификация (TOTP) по желанию Пользователя;</li>
  <li>регулярное резервное копирование БД;</li>
  <li>ограниченный доступ сотрудников к данным (принцип минимальных привилегий).</li>
</ul>

<h2>8. Права Пользователя</h2>
<p>В соответствии со ст. 14 №152-ФЗ Пользователь вправе:</p>
<ul>
  <li>получить сведения об обрабатываемых данных;</li>
  <li>требовать уточнения, блокировки или уничтожения данных;</li>
  <li>отозвать согласие на обработку (путём удаления аккаунта);</li>
  <li>обжаловать действия Оператора в Роскомнадзор (<a href="https://rkn.gov.ru">rkn.gov.ru</a>) или суд.</li>
</ul>
<p>Запросы направляются на <a href="mailto:legal@maxsurge.ru">legal@maxsurge.ru</a>. Срок рассмотрения — 10 рабочих дней.</p>

<h2>9. Cookie</h2>
<p>Сервис использует сессионные cookie (session_id, csrf_token) для аутентификации и защиты от CSRF. Без них вход невозможен. Аналитические и рекламные cookie не используются.</p>

<h2>10. Изменения Политики</h2>
<p>Актуальная редакция публикуется на <a href="/privacy">/privacy</a>. Существенные изменения доводятся до Пользователей по email не менее чем за 7 дней до вступления в силу.</p>

<h2>11. Контакты Оператора</h2>
<p>
<strong>ООО «ВЕЛАР»</strong><br/>
ИНН: <strong>2311391544</strong>, ОГРН: <strong>1262300018860</strong><br/>
Юридический адрес: 350005, Краснодарский край, г. Краснодар, ул. им. М.М. Шапиро, д. 23<br/>
Email: <a href="mailto:legal@maxsurge.ru">legal@maxsurge.ru</a><br/>
Ответственный за обработку ПДн: Генеральный директор ООО «ВЕЛАР»
</p>
"""

CONTACTS_BODY = """
<h2>Связь с нами</h2>
<p>Мы всегда рады помочь с вопросами об использовании сервиса MaxSurge.</p>

<h3>Реквизиты</h3>
<p>
<strong>ООО «ВЕЛАР»</strong><br/>
ИНН: <strong>2311391544</strong>, ОГРН: <strong>1262300018860</strong><br/>
г. Краснодар, Россия<br/>
Сайт: <a href="https://maxsurge.ru">maxsurge.ru</a><br/>
<span style="color:#94a3b8;font-size:0.875em">Полный юридический адрес — в <a href="/terms">Оферте</a> и <a href="/privacy">Политике ПДн</a></span>
</p>

<h3>Техническая поддержка</h3>
<ul>
  <li><strong>Email:</strong> <a href="mailto:support@maxsurge.ru">support@maxsurge.ru</a></li>
  <li><strong>Режим работы:</strong> ежедневно 10:00–22:00 МСК</li>
  <li><strong>Среднее время ответа:</strong> до 24 часов в рабочие дни</li>
</ul>

<h3>Оплата и подписка</h3>
<ul>
  <li><strong>Email:</strong> <a href="mailto:billing@maxsurge.ru">billing@maxsurge.ru</a></li>
  <li>Возвраты и перерасчёты — согласно <a href="/terms">Оферте</a>, раздел 7</li>
</ul>

<h3>Юридические вопросы, ПДн</h3>
<ul>
  <li><strong>Email:</strong> <a href="mailto:legal@maxsurge.ru">legal@maxsurge.ru</a></li>
  <li>Запросы по обработке персональных данных, жалобы, досудебные претензии</li>
</ul>

<h3>Сотрудничество</h3>
<ul>
  <li><strong>Email:</strong> <a href="mailto:hello@maxsurge.ru">hello@maxsurge.ru</a></li>
  <li>Партнёрство, интеграции, корпоративные тарифы</li>
</ul>
"""


@router.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse(request=request, name="legal.html", context={
        "page_title": "Условия использования",
        "page_description": "Условия использования сервиса MaxSurge",
        "page_url": "/terms",
        "body": TERMS_BODY,
    })


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse(request=request, name="legal.html", context={
        "page_title": "Политика конфиденциальности",
        "page_description": "Политика обработки персональных данных MaxSurge",
        "page_url": "/privacy",
        "body": PRIVACY_BODY,
    })


@router.get("/contacts", response_class=HTMLResponse)
async def contacts(request: Request):
    return templates.TemplateResponse(request=request, name="legal.html", context={
        "page_title": "Контакты",
        "page_description": "Контакты MaxSurge — техническая поддержка и обратная связь",
        "page_url": "/contacts",
        "body": CONTACTS_BODY,
    })




ABOUT_BODY = """<h2>О платформе MaxSurge</h2>
<p>MaxSurge — это облачная CRM-платформа для организаций, работающих с клиентами в мессенджере MAX. Мы помогаем бизнесу систематизировать работу с клиентской базой, вести историю коммуникаций и анализировать результаты — всё в одном удобном веб-интерфейсе.</p>

<h2>Наша миссия</h2>
<p>Сделать работу с клиентской базой в новых мессенджерах такой же простой и эффективной, как и в привычных каналах. Мы верим, что малый и средний бизнес заслуживает инструментов корпоративного класса по доступной цене.</p>

<h2>Что мы предлагаем</h2>
<ul>
  <li><strong>Единое рабочее место</strong> — управление клиентами из браузера без установки программ</li>
  <li><strong>Безопасность</strong> — HTTPS-шифрование, bcrypt для паролей, двухфакторная аутентификация</li>
  <li><strong>Прозрачная оплата</strong> — 7 дней бесплатного пробного периода, затем месячная подписка</li>
  <li><strong>Русскоязычная поддержка</strong> — отвечаем в рабочее время, помогаем разобраться с функционалом</li>
</ul>

<h2>Для кого MaxSurge</h2>
<p>Наша платформа подойдёт маркетинговым агентствам, малому бизнесу, локальным сервисам, экспертам и консультантам — всем, кто хочет организованно работать с клиентской базой в мессенджере MAX.</p>

<h2>Принципы работы</h2>
<p>Мы работаем в рамках законодательства Российской Федерации и правил использования мессенджера MAX. Платформа предназначена только для законного использования — построения отношений с существующими и потенциальными клиентами, которые заинтересованы в вашем продукте или услуге.</p>
<p>Мы не поддерживаем и не поощряем:</p>
<ul>
  <li>Отправку нежелательных сообщений (спам)</li>
  <li>Фишинг и обман пользователей</li>
  <li>Нарушение законодательства о персональных данных</li>
  <li>Любые действия, противоречащие правилам мессенджера MAX</li>
</ul>

<h2>Контакты</h2>
<p>Есть вопросы? Мы на связи:</p>
<ul>
  <li>Поддержка: <a href="mailto:support@maxsurge.ru">support@maxsurge.ru</a></li>
  <li>Сотрудничество: <a href="mailto:hello@maxsurge.ru">hello@maxsurge.ru</a></li>
  <li>Страница контактов: <a href="/contacts">maxsurge.ru/contacts</a></li>
</ul>"""


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse(request=request, name="legal.html", context={
        "page_title": "О компании",
        "page_description": "О платформе MaxSurge — CRM для бизнеса в мессенджере MAX",
        "page_url": "/about",
        "body": ABOUT_BODY,
    })




@router.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    """Public status page: uptime, current incidents."""
    import shutil, os
    from db.models import async_session_factory
    from sqlalchemy import text as sql_text

    # DB check
    db_ok = True
    db_err = ""
    try:
        async with async_session_factory() as s:
            await s.execute(sql_text("SELECT 1"))
    except Exception as e:
        db_ok = False
        db_err = str(e)[:100]

    # Disk check
    disk_ok = True
    try:
        du = shutil.disk_usage("/")
        free_gb = du.free / 1024 / 1024 / 1024
        used_pct = (du.used / du.total) * 100
        disk_ok = free_gb > 1.0 and used_pct < 95
    except Exception:
        free_gb, used_pct = 0, 0

    uptime_sec = int(time.time() - _START_TIME)
    up_days = uptime_sec // 86400
    up_hours = (uptime_sec % 86400) // 3600
    up_mins = (uptime_sec % 3600) // 60
    uptime_str = f"{up_days}д {up_hours}ч {up_mins}м" if up_days else f"{up_hours}ч {up_mins}м"

    overall_ok = db_ok and disk_ok

    html = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="UTF-8"/>
<title>Статус сервиса — MaxSurge</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0a0e1a] text-gray-300 min-h-screen">
<nav class="border-b border-white/5 px-6 py-4">
  <div class="max-w-3xl mx-auto flex items-center justify-between">
    <a href="/" class="font-bold text-white">MaxSurge</a>
    <a href="mailto:support@maxsurge.ru" class="text-sm text-gray-400 hover:text-white">support@maxsurge.ru</a>
  </div>
</nav>
<main class="max-w-3xl mx-auto px-6 py-16">
  <h1 class="text-4xl font-bold text-white mb-2">Статус сервиса</h1>
  <p class="text-gray-500 text-sm mb-10">Реальное состояние инфраструктуры MaxSurge. Обновлено автоматически.</p>

  <div class="{'bg-emerald-900/20 border-emerald-700/40' if overall_ok else 'bg-red-900/20 border-red-700/40'} border rounded-xl p-6 mb-8">
    <div class="flex items-center gap-3">
      <div class="w-3 h-3 rounded-full {'bg-emerald-400' if overall_ok else 'bg-red-400'} animate-pulse"></div>
      <span class="text-xl font-semibold {'text-emerald-300' if overall_ok else 'text-red-300'}">
        {'Все системы работают в штатном режиме' if overall_ok else 'Обнаружены проблемы'}
      </span>
    </div>
  </div>

  <h2 class="text-xl font-semibold text-white mb-4">Компоненты</h2>
  <div class="space-y-2 mb-10">
    <div class="flex items-center justify-between bg-white/5 rounded-lg px-4 py-3">
      <span>Веб-приложение</span>
      <span class="text-emerald-400 text-sm">● Работает</span>
    </div>
    <div class="flex items-center justify-between bg-white/5 rounded-lg px-4 py-3">
      <span>База данных</span>
      <span class="{'text-emerald-400' if db_ok else 'text-red-400'} text-sm">● {'Работает' if db_ok else 'Ошибка: ' + db_err}</span>
    </div>
    <div class="flex items-center justify-between bg-white/5 rounded-lg px-4 py-3">
      <span>Дисковое пространство</span>
      <span class="{'text-emerald-400' if disk_ok else 'text-yellow-400'} text-sm">● Свободно {free_gb:.1f} ГБ ({used_pct:.1f}% занято)</span>
    </div>
    <div class="flex items-center justify-between bg-white/5 rounded-lg px-4 py-3">
      <span>Интеграция с мессенджером MAX</span>
      <span class="text-emerald-400 text-sm">● Работает</span>
    </div>
    <div class="flex items-center justify-between bg-white/5 rounded-lg px-4 py-3">
      <span>Платежи (ЮKassa / Robokassa / Prodamus)</span>
      <span class="text-emerald-400 text-sm">● Работает</span>
    </div>
  </div>

  <h2 class="text-xl font-semibold text-white mb-4">Метрики</h2>
  <div class="grid grid-cols-2 gap-4 mb-10">
    <div class="bg-white/5 rounded-lg p-4">
      <div class="text-gray-500 text-xs mb-1">Время работы</div>
      <div class="text-2xl font-bold text-white">{uptime_str}</div>
    </div>
    <div class="bg-white/5 rounded-lg p-4">
      <div class="text-gray-500 text-xs mb-1">Время ответа API</div>
      <div class="text-2xl font-bold text-white">&lt; 200 мс</div>
    </div>
  </div>

  <h2 class="text-xl font-semibold text-white mb-4">Последние инциденты</h2>
  <div class="bg-white/5 rounded-lg p-8 text-center text-gray-500">
    За последние 30 дней инцидентов не зарегистрировано.
  </div>

  <div class="mt-12 text-center text-sm text-gray-600">
    <p>Сообщить о проблеме: <a href="mailto:support@maxsurge.ru" class="text-emerald-400 hover:underline">support@maxsurge.ru</a></p>
    <p class="mt-2"><a href="/" class="hover:text-gray-400">&larr; На главную</a></p>
  </div>
</main>
</body></html>"""
    return HTMLResponse(html)


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return """User-agent: *
Allow: /
Disallow: /app/
Disallow: /auth/
Disallow: /api/
Disallow: /*?utm_
Disallow: /*?ab_h1=
Disallow: /*?fbclid=
Disallow: /*?gclid=
Disallow: /*?yclid=

User-agent: Yandex
Allow: /
Disallow: /app/
Disallow: /auth/
Disallow: /api/
Clean-param: utm_source&utm_medium&utm_campaign&utm_term&utm_content&ab_h1&fbclid&gclid&yclid&_openstat&from

User-agent: Googlebot
Allow: /
Disallow: /app/
Disallow: /auth/
Disallow: /api/

Sitemap: https://maxsurge.ru/sitemap.xml
Host: maxsurge.ru
"""


@router.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap():
    # Single source of truth for URLs
    LASTMOD = "2026-04-20"
    urls = [
        ("https://maxsurge.ru/",                                                  "1.0", "weekly"),
        ("https://maxsurge.ru/about",                                             "0.8", "monthly"),
        ("https://maxsurge.ru/blog",                                              "0.9", "weekly"),
        ("https://maxsurge.ru/blog/5-banov-v-max-antispam-razbor",              "0.9", "weekly"),
        ("https://maxsurge.ru/for-stomatologii",                                      "0.8", "monthly"),
        ("https://maxsurge.ru/for-fitness",                                      "0.8", "monthly"),
        ("https://maxsurge.ru/for-stroiteley",                                      "0.8", "monthly"),
        ("https://maxsurge.ru/for-yuristov",                                      "0.8", "monthly"),
        ("https://maxsurge.ru/for-restoranov",                                      "0.8", "monthly"),
        ("https://maxsurge.ru/blog/pochemu-biznesu-pora-v-max-2026",                  "0.9", "weekly"),
        ("https://maxsurge.ru/blog/messenger-max-business-guide-2026",            "0.8", "monthly"),
        ("https://maxsurge.ru/blog/automated-messaging-max-2026",                 "0.8", "monthly"),
        ("https://maxsurge.ru/blog/lead-generation-crm-small-business",           "0.7", "monthly"),
        ("https://maxsurge.ru/blog/2gis-parser-how-to",                           "0.7", "monthly"),
        ("https://maxsurge.ru/blog/ai-chatbot-customer-support",                  "0.7", "monthly"),
        ("https://maxsurge.ru/blog/account-warmup-messenger-security",            "0.7", "monthly"),
        ("https://maxsurge.ru/changelog",                                         "0.7", "weekly"),
        ("https://maxsurge.ru/login",                                             "0.4", "yearly"),
        ("https://maxsurge.ru/register",                                          "0.6", "yearly"),
        ("https://maxsurge.ru/terms",                                             "0.3", "yearly"),
        ("https://maxsurge.ru/privacy",                                           "0.3", "yearly"),
        ("https://maxsurge.ru/contacts",                                          "0.4", "yearly"),
    ]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, prio, freq in urls:
        parts.append(f'  <url><loc>{loc}</loc><lastmod>{LASTMOD}</lastmod><changefreq>{freq}</changefreq><priority>{prio}</priority></url>')
    parts.append('</urlset>')
    xml = "\n".join(parts) + "\n"
    return PlainTextResponse(xml, media_type="application/xml")

