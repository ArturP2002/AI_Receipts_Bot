# Развёртывание AI Receipts Bot на Ubuntu 22.04

Подробная инструкция: код берётся с **GitHub по HTTPS** (без SSH-ключа к GitHub — как при загрузке репозитория с Mac через браузер или HTTPS). На сервере бот работает под **long polling**; админская **Telegram Mini App** поднимается тем же процессом на **aiohttp** и проксируется через **nginx** с **HTTPS** (обязательно для Web App в Telegram).

---

## Содержание

1. [Что будет установлено](#1-что-будет-установлено)
2. [Требования](#2-требования)
3. [Доступ к серверу по SSH](#3-доступ-к-серверу-по-ssh)
4. [Подготовка Ubuntu](#4-подготовка-ubuntu-2204)
5. [Пользователь и каталог](#5-пользователь-и-каталог-проекта)
6. [Клонирование с GitHub по HTTPS](#6-клонирование-с-github-по-https)
7. [Python и зависимости](#7-python-и-зависимости)
8. [Файл `.env` на сервере](#8-файл-env-на-сервере)
9. [Домен, DNS, nginx и TLS](#9-домен-dns-nginx-и-tls)
10. [systemd: автозапуск](#10-systemd-автозапуск)
11. [Проверка и Telegram](#11-проверка-и-telegram)
12. [Обновление кода](#12-обновление-кода-с-github)
13. [Резервное копирование БД](#13-резервное-копирование-бд)
14. [Частые проблемы](#14-частые-проблемы)

---

## 1. Что будет установлено

| Компонент | Назначение |
|-----------|------------|
| **Python 3** + **venv** | Запуск бота (`main.py`) |
| Зависимости из `requirements.txt` | aiogram, aiohttp, peewee, openai и т.д. |
| **nginx** | Прокси HTTPS → локальный порт Mini App |
| **certbot** | Бесплатный сертификат Let's Encrypt |
| **ufw** | Файрвол (опционально, но рекомендуется) |

Бот **не** требует вебхуков: исходящие запросы к Telegram API и входящие обновления через polling. Наружу с интернета должен быть доступен только **HTTPS (443)** для Mini App; порт приложения для Mini App можно держать на `127.0.0.1`.

---

## 2. Требования

- VPS с **Ubuntu 22.04 LTS**.
- Права **sudo** на сервере.
- Репозиторий на GitHub (публичный или приватный), URL вида:  
  `https://github.com/<ваш_логин>/<имя_репозитория>.git`
- **Домен** (или поддомен), указывающий **A-записью** на IP сервера — для HTTPS Mini App.
- Токен бота от [@BotFather](https://t.me/BotFather).
- Для ИИ-функций — ключ **OpenAI** (переменная `OPENAI_API_KEY`).

---

## 3. Доступ к серверу по SSH

Это **отдельно** от доступа к GitHub. Вы подключаетесь к VPS по SSH.

### 3.1. Первый вход по паролю

Провайдер выдаёт **IP**, **логин** (часто `root` или `ubuntu`) и **пароль**.

С вашего компьютера:

```bash
ssh ubuntu@СЕРВЕР_IP
```

Подставьте свой логин и IP. Введите пароль.

### 3.2. Вход по SSH-ключу (рекомендуется для сервера)

На своём Mac (или ПК):

```bash
ssh-keygen -t ed25519 -C "vps" -f ~/.ssh/vps_ed25519
ssh-copy-id -i ~/.ssh/vps_ed25519.pub ubuntu@СЕРВЕР_IP
```

Дальше:

```bash
ssh -i ~/.ssh/vps_ed25519 ubuntu@СЕРВЕР_IP
```

Отключение входа по паролю — только после того, как убедились, что вход по ключу работает: в `/etc/ssh/sshd_config` параметр `PasswordAuthentication no`, затем `sudo systemctl reload sshd`.

---

## 4. Подготовка Ubuntu 22.04

Подключитесь по SSH и выполните:

```bash
sudo apt update
sudo apt upgrade -y
```

Установите пакеты:

```bash
sudo apt install -y git python3 python3-venv python3-pip nginx certbot python3-certbot-nginx ufw
```

Проверка версии Python (нужен 3.10+; на 22.04 обычно 3.10):

```bash
python3 --version
```

### Файрвол (рекомендуется)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status verbose
```

Убедитесь, что SSH не потеряете (сессия уже открыта — правило `OpenSSH` добавлено до `enable`).

---

## 5. Пользователь и каталог проекта

Не запускайте бота от **root**. Создайте пользователя (имя можно заменить):

```bash
sudo adduser --disabled-password botuser
sudo usermod -aG sudo botuser   # опционально, если нужен sudo для этого пользователя
```

Каталог приложения:

```bash
sudo mkdir -p /opt/ai_receipts_bot
sudo chown botuser:botuser /opt/ai_receipts_bot
```

Дальше команды клонирования и настройки выполняйте от `botuser` или через `sudo -u botuser bash -lc '...'`.

---

## 6. Клонирование с GitHub по HTTPS

Ниже предполагается, что вы **не** используете SSH URL вида `git@github.com:...`, а только **HTTPS**.

### 6.1. Публичный репозиторий

Достаточно:

```bash
sudo -u botuser git clone https://github.com/ВАШ_ЛОГИН/ИМЯ_РЕПО.git /opt/ai_receipts_bot
```

sudo -u botuser git clone https://github.com/ArturP2002/AI_Receipts_Bot.git /opt/ai_receipts_bot

Пароль не спросит — репозиторий открыт для чтения.

### 6.2. Приватный репозиторий

GitHub не отдаёт приватный репозиторий без аутентификации. Варианты:

#### Вариант A — Personal Access Token (PAT) при `git clone`

1. На GitHub: **Settings → Developer settings → Personal access tokens → Fine-grained tokens** (или classic).
2. Для **classic**: scope **`repo`** (полный доступ к приватным репозиториям).
3. Скопируйте токен один раз (потом его не покажут).

Клонирование (подставьте логин GitHub, репозиторий и токен):

```bash
sudo -u botuser git clone https://ВАШ_ЛОГИН:ВАШ_ТОКЕН@github.com/ВАШ_ЛОГИН/ИМЯ_РЕПО.git /opt/ai_receipts_bot
```

**Минус:** токен может попасть в историю команд shell. Безопаснее сразу после клонирования перейти к варианту B или очистить историю и сменить токен, если утёк.

#### Вариант B — `git clone` с запросом логина/пароля

```bash
sudo -u botuser git clone https://github.com/ВАШ_ЛОГИН/ИМЯ_РЕПО.git /opt/ai_receipts_bot
```

Когда спросит:

- **Username** — ваш логин GitHub.
- **Password** — **не пароль от аккаунта**, а **PAT** (Personal Access Token).

#### Вариант C — сохранить учётные данные на сервере (удобно для `git pull`)

После первого успешного ввода PAT:

```bash
sudo -u botuser bash -lc 'git config --global credential.helper store'
```

Следующий `git pull` подставит сохранённые данные из `~/.ssh` не используется — файл `~/.git-credentials` у пользователя `botuser`. **Права на домашний каталог и файл** должны быть строгими; токен = полный доступ к репо — храните сервер надёжно.

#### Вариант D — GitHub CLI (`gh`)

```bash
sudo apt install -y gh
sudo -u botuser gh auth login
```

Выберите GitHub.com → HTTPS → авторизация через браузер или токен. Затем:

```bash
sudo -u botuser gh repo clone ВАШ_ЛОГИН/ИМЯ_РЕПО /opt/ai_receipts_bot
```

---

## 7. Python и зависимости

Все команды от пользователя `botuser`, рабочий каталог — корень репозитория.

```bash
sudo -u botuser bash -lc 'cd /opt/ai_receipts_bot && python3 -m venv .venv'
sudo -u botuser bash -lc 'cd /opt/ai_receipts_bot && . .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt'
```

Проверка:

```bash
sudo -u botuser /opt/ai_receipts_bot/.venv/bin/python -c "import aiogram, aiohttp; print('ok')"
```

### Почему важен каталог запуска

SQLite база задаётся в `database.py` как файл **`AI_Receipts_Bot.db`** в **текущей рабочей директории** процесса. В **systemd** нужно явно указать `WorkingDirectory=/opt/ai_receipts_bot`, иначе база создастся не там, где вы ожидаете.

---

## 8. Файл `.env` на сервере

Файл **`.env` в Git не коммитится** (см. `.gitignore`). Создайте его только на сервере.

```bash
sudo -u botuser nano /opt/ai_receipts_bot/.env
sudo chmod 600 /opt/ai_receipts_bot/.env
```

Можно скопировать с локальной машины (пример):

```bash
scp .env botuser@СЕРВЕР_IP:/opt/ai_receipts_bot/.env
```

Затем на сервере: `chmod 600 /opt/ai_receipts_bot/.env`.

### 8.1. Обязательные переменные

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен от BotFather (**обязательно**). |

### 8.2. Админка и Mini App

| Переменная | Описание |
|------------|----------|
| `ADMIN_USER_IDS` | Telegram user id админов через запятую, например `123456789`. Без этого Mini App не авторизует вас как админа. |
| `ADMIN_WEBAPP_PUBLIC_URL` | Публичный **HTTPS** URL **без** слэша в конце, например `https://admin.example.com`. Именно он подставляется в кнопку Web App в боте (путь `/admin/` добавляется кодом). |
| `ADMIN_WEBAPP_HOST` | На проде с nginx: **`127.0.0.1`**, чтобы aiohttp слушал только localhost. |
| `ADMIN_WEBAPP_PORT` | Локальный порт, например **`8765`**. Должен совпадать с `proxy_pass` в nginx. |

Если `ADMIN_WEBAPP_PUBLIC_URL` пустой, команда `/admin` в боте не покажет кнопку Mini App (останется текстовая подсказка в сообщении).

### 8.3. OpenAI и поведение бота

См. `config.py` и `bot_secrets.py`. Кратко:

- `OPENAI_API_KEY` — для ИИ-рецептов и картинок.
- `BOT_USERNAME` — юзернейм бота без `@` (по умолчанию в коде есть placeholder).
- `RECIPE_STAR_PRICE`, `SHOW_MORE_STAR_PRICE`, `SUBSCRIPTION_STAR_PRICE`, `SUBSCRIPTION_DEFAULT_DAYS`, и др. — при необходимости переопределяют значения по умолчанию.
- `OPENAI_CHAT_MODEL`, `OPENAI_IMAGE_MODEL`, `RECIPE_IMAGES_MODE` (`sync` / `async` / `off`), `LOG_LEVEL` и т.д.

Минимальный рабочий набор для теста бота без Mini App: только `BOT_TOKEN`. Для полного функционала — ключ OpenAI и переменные админки выше.

---

## 9. Домен, DNS, nginx и TLS

Telegram **Web App** открывает только **HTTPS** с доверенным сертификатом (Let's Encrypt подходит).

### 9.1. DNS

У регистратора домена создайте запись:

- **Тип:** A  
- **Имя:** поддомен, например `admin` (будет `admin.example.com`) или `@` для корня.  
- **Значение:** публичный **IP** вашего VPS.

Проверка с вашего ПК:

```bash
dig +short admin.example.com

dig +short yadro.pro
```

Должен вернуться IP сервера.

### 9.2. Конфиг nginx до сертификата

Замените `admin.example.com` на свой хост.

```bash
sudo nano /etc/nginx/sites-available/ai-receipts-bot.conf
```

Содержимое:

```nginx
server {
    listen 80;
    server_name admin.example.com;

    location /admin/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```


server {
    listen 80;
    server_name Yadro.pro;

    location /admin/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}



Включите сайт и проверьте синтаксис:

```bash
sudo ln -sf /etc/nginx/sites-available/ai-receipts-bot.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Убедитесь, что в `.env` на сервере выставлено **`ADMIN_WEBAPP_HOST=127.0.0.1`** (не `0.0.0.0`, если снаружи доступ только через nginx). Порт **`8765`** совпадает с **`ADMIN_WEBAPP_PORT`**.

Временно можно запустить бота вручную (см. раздел 11) и проверить `curl -sI http://127.0.0.1:8765/admin/` с сервера — ответ **200**.

### 9.3. Сертификат Let's Encrypt

```bash
sudo certbot --nginx -d admin.example.com
```


sudo certbot --nginx -d Yadro.pro


Следуйте подсказкам (email, согласие с ToS). Certbot сам поправит конфиг nginx под HTTPS.

В `.env` укажите:

```env
ADMIN_WEBAPP_PUBLIC_URL=https://admin.example.com
```

https://Yadro.pro

Перезапустите сервис бота после правок `.env`.

### 9.4. BotFather (по необходимости)

Если Telegram ругается на домен Web App, в настройках бота в BotFather задайте домен / ссылку в соответствии с [документацией Telegram](https://core.telegram.org/bots/webapps) для вашего сценария.

---

## 10. systemd: автозапуск

Создайте unit-файл:

```bash
sudo nano /etc/systemd/system/ai-receipts-bot.service
```

Содержимое:

```ini
[Unit]
Description=AI Receipts Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
Group=botuser
WorkingDirectory=/opt/ai_receipts_bot
EnvironmentFile=/opt/ai_receipts_bot/.env
ExecStart=/opt/ai_receipts_bot/.venv/bin/python main.py
Restart=always
RestartSec=5

# Опционально: ограничения
# LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

**Замечание по `EnvironmentFile`:** строки должны быть в формате `KEY=value` без `export`. Значения с пробелами — в кавычках. Если какая-то переменная не подхватывается, проверьте кодировку файла (UTF-8) и отсутствие BOM.

Активация:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-receipts-bot.service
sudo systemctl start ai-receipts-bot.service
sudo systemctl status ai-receipts-bot.service
```

Логи:

```bash
journalctl -u ai-receipts-bot.service -f
```

В логах при успешном старте будет строка про админ mini app (хост/порт).

Остановка / перезапуск:

```bash
sudo systemctl stop ai-receipts-bot.service
sudo systemctl restart ai-receipts-bot.service
```


https://f905-72-56-111-110.ngrok-free.app

---

## 11. Проверка и Telegram

Чеклист:

1. **Сервис активен:**  
   `systemctl is-active ai-receipts-bot` → `active`

2. **Локальный Mini App:** на сервере  
   `curl -sI http://127.0.0.1:8765/admin/` → `HTTP/1.1 200`

3. **Снаружи по HTTPS:**  
   `curl -sI https://admin.example.com/admin/` → `200`, TLS без ошибок

4. В Telegram от пользователя из `ADMIN_USER_IDS`: команда **`/admin`** — должна быть кнопка **«Админ-панель (Mini App)»**, открывается интерфейс.

Если кнопки нет — проверьте `ADMIN_WEBAPP_PUBLIC_URL` и перезапуск сервиса.

---

## 12. Обновление кода с GitHub

На **Mac** (или где правите код): коммит и пуш в GitHub — тем способом, которым вы пользуетесь (HTTPS + PAT в Cursor/GitHub Desktop и т.д.).

На **сервере**:

```bash
sudo systemctl stop ai-receipts-bot.service
sudo -u botuser bash -lc 'cd /opt/ai_receipts_bot && git pull'
sudo -u botuser bash -lc 'cd /opt/ai_receipts_bot && . .venv/bin/activate && pip install -r requirements.txt'
sudo systemctl start ai-receipts-bot.service
```

Если `requirements.txt` не менялся, шаг с `pip install` можно пропустить.

Для **приватного** репозитория `git pull` попросит учётные данные, если не настроен `credential.helper` или `gh auth`.

---

## 13. Резервное копирование БД

Файл: `/opt/ai_receipts_bot/AI_Receipts_Bot.db`.

Копируйте его при остановке сервиса или используйте встроенную команду бота для админа **`/backup_db`** (если включена в вашей сборке) — см. обработчики админки.

Пример простого копирования:

```bash
sudo systemctl stop ai-receipts-bot.service
sudo cp /opt/ai_receipts_bot/AI_Receipts_Bot.db /opt/backups/AI_Receipts_Bot-$(date +%F).db
sudo systemctl start ai-receipts-bot.service
```

---

## 14. Частые проблемы

| Проблема | Что проверить |
|----------|----------------|
| `Permission denied (publickey)` при **git** на сервере | Вы используете SSH URL репозитория. Перейдите на `https://github.com/...git` или настройте SSH-ключ для GitHub. |
| `git clone` / `git pull` просит пароль, пароль не подходит | Для GitHub в поле пароля нужен **PAT**, не пароль аккаунта. |
| **502 Bad Gateway** в браузере на `/admin/` | Бот не запущен; неверный порт в nginx; `ADMIN_WEBAPP_HOST` не `127.0.0.1` при прокси на localhost; порт занят другим процессом. |
| Mini App пустой / ошибка в Telegram | Нет валидного HTTPS; неверный `ADMIN_WEBAPP_PUBLIC_URL`; домен не тот, что в сертификате. |
| Бот не стартует: нет `BOT_TOKEN` | `.env` и `EnvironmentFile` в systemd; перезапуск после правок. |
| Две разные базы данных | `WorkingDirectory` в systemd не тот каталог — процесс создаёт `AI_Receipts_Bot.db` в другом месте. |
| После обновления кода старые зависимости | Выполнить `pip install -r requirements.txt` в `.venv`. |

---

## Краткая шпаргалка команд

```bash
# Клон (публичный репо)
sudo -u botuser git clone https://github.com/USER/REPO.git /opt/ai_receipts_bot

# venv + deps
sudo -u botuser bash -lc 'cd /opt/ai_receipts_bot && python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements.txt'

# Права на секреты
sudo chmod 600 /opt/ai_receipts_bot/.env

# TLS
sudo certbot --nginx -d admin.example.com

# Сервис
sudo systemctl restart ai-receipts-bot.service
journalctl -u ai-receipts-bot.service -n 100 --no-pager
```

Если что-то из шагов отличается у вашего хостинга (другая ОС, панель, Docker), адаптируйте пути и способ запуска процесса, сохраняя смысл: **HTTPS → nginx → 127.0.0.1:порт**, **бот + aiohttp в одном процессе**, **`.env` только на сервере**, **код с GitHub по HTTPS**.
