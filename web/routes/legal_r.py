"""Роуты публичных страниц: terms, privacy, contacts, robots.txt, sitemap.xml."""
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


TERMS_BODY = """
<h2>1. Общие положения</h2>
<p>Настоящие условия использования (далее — «Условия») регулируют отношения между сервисом MaxSurge (далее — «Сервис») и пользователем (далее — «Пользователь»), связанные с использованием функциональных возможностей Сервиса, размещённого по адресу <a href="https://maxsurge.ru">maxsurge.ru</a>.</p>
<p>Регистрируясь в Сервисе и используя его функции, Пользователь подтверждает, что прочёл, понял и полностью согласен с настоящими Условиями.</p>

<h2>2. Описание Сервиса</h2>
<p>MaxSurge предоставляет Пользователю набор инструментов для работы с мессенджером MAX, включая:</p>
<ul>
  <li>Управление аккаунтами мессенджера</li>
  <li>Ведение базы контактов (CRM)</li>
  <li>Сбор публичной информации об организациях из открытых источников</li>
  <li>Аналитику коммуникаций</li>
  <li>Настройку и запуск коммуникационных задач</li>
</ul>

<h2>3. Регистрация и аккаунт</h2>
<p>Для использования Сервиса необходимо создать учётную запись, указав действующий email и пароль. Пользователь обязуется:</p>
<ul>
  <li>Предоставлять достоверную информацию при регистрации</li>
  <li>Хранить в тайне пароль и не передавать его третьим лицам</li>
  <li>Незамедлительно уведомлять Сервис о несанкционированном доступе к учётной записи</li>
</ul>

<h2>4. Пробный период</h2>
<p>Новым пользователям предоставляется пробный период сроком 7 дней с полным доступом к функционалу Сервиса. По окончании пробного периода для продолжения работы требуется оформление платного тарифа.</p>

<h2>5. Правила использования</h2>
<p>Пользователь обязуется использовать Сервис в соответствии с:</p>
<ul>
  <li>Законодательством Российской Федерации</li>
  <li>Правилами использования мессенджера MAX</li>
  <li>Нормами деловой этики</li>
</ul>
<p><strong>Запрещается:</strong></p>
<ul>
  <li>Использовать Сервис для рассылки спама, фишинга, вредоносных ссылок</li>
  <li>Массово отправлять нежелательные сообщения пользователям без их согласия</li>
  <li>Нарушать законодательство о персональных данных</li>
  <li>Распространять противоправный контент</li>
</ul>

<h2>6. Ответственность</h2>
<p>Пользователь несёт полную ответственность за содержание отправляемых сообщений и соответствие своих действий законодательству. Сервис не несёт ответственности за действия Пользователя при использовании функций Сервиса.</p>
<p>Сервис предоставляется «как есть» без каких-либо явных или подразумеваемых гарантий.</p>

<h2>7. Изменение условий</h2>
<p>Сервис оставляет за собой право изменять настоящие Условия в любое время. Актуальная версия всегда доступна на странице <a href="/terms">/terms</a>. Продолжение использования Сервиса после внесения изменений означает согласие с новой редакцией.</p>

<h2>8. Контакты</h2>
<p>По всем вопросам, связанным с использованием Сервиса, обращайтесь через страницу <a href="/contacts">контактов</a>.</p>
"""

PRIVACY_BODY = """
<h2>1. Общие положения</h2>
<p>Настоящая Политика конфиденциальности (далее — «Политика») определяет порядок обработки персональных данных пользователей сервиса MaxSurge (далее — «Сервис»).</p>
<p>Используя Сервис, Пользователь даёт согласие на обработку своих персональных данных в соответствии с настоящей Политикой и Федеральным законом №152-ФЗ «О персональных данных».</p>

<h2>2. Какие данные мы собираем</h2>
<p>При регистрации и использовании Сервиса мы собираем следующую информацию:</p>
<ul>
  <li><strong>Email и пароль</strong> — для создания учётной записи и входа в Сервис</li>
  <li><strong>Имя</strong> — для персонализации интерфейса (опционально)</li>
  <li><strong>Дата регистрации и последнего входа</strong> — для обеспечения безопасности</li>
  <li><strong>IP-адрес и данные браузера</strong> — для защиты от злоупотреблений</li>
  <li><strong>Данные, загружаемые пользователем</strong> — контакты, списки, файлы, которые Пользователь добавляет сам</li>
</ul>

<h2>3. Цели обработки</h2>
<ul>
  <li>Предоставление функций Сервиса</li>
  <li>Авторизация и обеспечение безопасности аккаунта</li>
  <li>Связь с Пользователем по техническим вопросам</li>
  <li>Улучшение работы Сервиса</li>
  <li>Выполнение требований законодательства</li>
</ul>

<h2>4. Хранение данных</h2>
<p>Данные хранятся на защищённых серверах. Пароли хешируются с использованием алгоритма bcrypt. Данные не передаются третьим лицам, за исключением случаев, предусмотренных законодательством РФ.</p>

<h2>5. Cookie-файлы</h2>
<p>Сервис использует сессионные cookie для авторизации Пользователя. Отключение cookie в браузере приведёт к невозможности входа в Сервис.</p>

<h2>6. Права пользователя</h2>
<p>Пользователь имеет право:</p>
<ul>
  <li>Запросить информацию о своих персональных данных</li>
  <li>Требовать уточнения, блокировки или уничтожения своих данных</li>
  <li>Отозвать согласие на обработку данных</li>
  <li>Удалить свой аккаунт в любое время</li>
</ul>

<h2>7. Безопасность</h2>
<p>Мы применяем технические и организационные меры для защиты данных:</p>
<ul>
  <li>SSL/TLS-шифрование всех соединений</li>
  <li>Хеширование паролей bcrypt</li>
  <li>Регулярное резервное копирование</li>
  <li>Ограничение доступа к данным</li>
</ul>

<h2>8. Изменения политики</h2>
<p>Политика может обновляться. Актуальная версия публикуется на странице <a href="/privacy">/privacy</a>.</p>

<h2>9. Контакты</h2>
<p>По вопросам обработки персональных данных: см. <a href="/contacts">страницу контактов</a>.</p>
"""

CONTACTS_BODY = """
<h2>Связь с нами</h2>
<p>Мы всегда рады помочь вам с любыми вопросами об использовании сервиса MaxSurge.</p>

<h3>Техническая поддержка</h3>
<p>Если у вас возникли технические проблемы с работой сервиса, вопросы по функциональности или предложения по улучшению — напишите нам.</p>
<ul>
  <li><strong>Email поддержки:</strong> <a href="mailto:support@maxsurge.ru">support@maxsurge.ru</a></li>
  <li><strong>Режим работы:</strong> ежедневно с 10:00 до 22:00 МСК</li>
</ul>

<h3>Вопросы по оплате и подписке</h3>
<p>По вопросам оформления подписки, смены тарифа, возврата средств:</p>
<ul>
  <li><strong>Email:</strong> <a href="mailto:billing@maxsurge.ru">billing@maxsurge.ru</a></li>
</ul>

<h3>Юридические вопросы</h3>
<p>По вопросам условий использования, политики конфиденциальности, персональных данных:</p>
<ul>
  <li><strong>Email:</strong> <a href="mailto:legal@maxsurge.ru">legal@maxsurge.ru</a></li>
</ul>

<h3>Сотрудничество</h3>
<p>Предложения о партнёрстве, интеграциях, корпоративных тарифах:</p>
<ul>
  <li><strong>Email:</strong> <a href="mailto:hello@maxsurge.ru">hello@maxsurge.ru</a></li>
</ul>

<h2>Время ответа</h2>
<p>Мы стараемся отвечать на все обращения в течение 24 часов в рабочие дни. В выходные и праздничные дни время ответа может увеличиться.</p>

<h2>Обратная связь</h2>
<p>Ваши отзывы и предложения помогают нам делать сервис лучше. Мы внимательно читаем каждое сообщение.</p>
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


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return """User-agent: *
Allow: /
Allow: /login
Allow: /register
Allow: /terms
Allow: /privacy
Allow: /contacts
Allow: /about
Allow: /blog
Disallow: /app/
Disallow: /auth/
Disallow: /api/

Sitemap: https://maxsurge.ru/sitemap.xml
"""


@router.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://maxsurge.ru/</loc><priority>1.0</priority></url>
  <url><loc>https://maxsurge.ru/login</loc><priority>0.8</priority></url>
  <url><loc>https://maxsurge.ru/register</loc><priority>0.8</priority></url>
  <url><loc>https://maxsurge.ru/terms</loc><priority>0.5</priority></url>
  <url><loc>https://maxsurge.ru/privacy</loc><priority>0.5</priority></url>
  <url><loc>https://maxsurge.ru/contacts</loc><priority>0.5</priority></url>
  <url><loc>https://maxsurge.ru/about</loc><priority>0.7</priority></url>
  <url><loc>https://maxsurge.ru/blog/</loc><priority>0.8</priority></url>
  <url><loc>https://maxsurge.ru/blog/messenger-max-business-guide-2026</loc><priority>0.7</priority></url>
  <url><loc>https://maxsurge.ru/blog/lead-generation-crm-small-business</loc><priority>0.7</priority></url>
  <url><loc>https://maxsurge.ru/blog/2gis-parser-how-to</loc><priority>0.7</priority></url>
  <url><loc>https://maxsurge.ru/blog/ai-chatbot-customer-support</loc><priority>0.7</priority></url>
  <url><loc>https://maxsurge.ru/blog/account-warmup-messenger-security</loc><priority>0.7</priority></url>
</urlset>"""
    return PlainTextResponse(xml, media_type="application/xml")
