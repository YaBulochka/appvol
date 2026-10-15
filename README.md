# appvol — громкость активного окна по хоткею

`appvol` меняет громкость **всех аудиопотоков приложения, окно которого сейчас
в фокусе**, и показывает штатный KDE OSD. Команда вешается на хоткей.

```
appvol up            # +5% приложению в фокусе
appvol down          # -5%
appvol mute          # тоггл mute
appvol list          # потоки, кэш фокуса, что сматчилось и почему
```

Рассчитано на KDE Plasma 6 на Wayland с PipeWire (pipewire-pulse). Root не нужен,
X11-инструменты не используются.

## Как это работает

```
KWin-скрипт  --SetFocus(pid, resourceClass, desktopFileName, caption)-->  appvold
                                                                             |
appvol up  --Adjust("up", 5)---------------------------------------------->  |
                                                                             v
                                                     pulsectl -> sink-input'ы -> OSD
```

* **`appvold`** — демон: держит соединение с pipewire-pulse через `pulsectl`,
  регистрирует на сессионной шине `org.appvol.Daemon`, кэширует последний фокус,
  сам загружает KWin-скрипт и перезагружает его после рестарта KWin. Второй
  инстанс не стартует (имя на шине занято).
* **KWin-скрипт** (`kwin/appvol.js`) — на старте и на каждый
  `workspace.windowActivated` пушит в демон `pid`, `resourceClass`,
  `desktopFileName`, `caption`. Если активного окна нет, отправляет пустой фокус.
* **`appvol`** — тонкий клиент: один вызов по D-Bus, фокус не спрашивает, в KWin не
  ходит. Полный цикл на нажатие — около 35 мс.

Сопоставление окна и потоков (первый шаг, давший результат, останавливает поиск):

1. `application.process.id` потока равен pid окна;
2. pid потока — потомок pid окна (цепочка `ppid` через `/proc/<pid>/stat`):
   Firefox, Chromium, Electron;
3. имя: `desktopFileName`/`resourceClass` окна против
   `pipewire.access.portal.app_id`, `application.id`,
   `application.process.binary`, `application.name` (без учёта регистра,
   `org.mozilla.firefox` ↔ `firefox`, суффикс `.desktop` отбрасывается).

Фокус на панели, рабочем столе или `plasmashell` игнорируется. Если потоков нет,
ничего не меняется, команда завершается с кодом 0.

## Зависимости

| Что | Имя для импорта | Пакет Arch | Зачем |
| --- | --- | --- | --- |
| Python 3.11+ | — | `python` | нужен `tomllib` для конфига |
| python-dbus | `dbus` | `python-dbus` | сессионная шина: API демона и OSD |
| PyGObject | `gi` | `python-gobject` | главный цикл GLib, в котором живёт демон |
| pulsectl | `pulsectl` | `python-pulsectl` | громкость потоков в pipewire-pulse |

Остальное — это сессия, в которой appvol запускается, и её ставит дистрибутив:

* KDE Plasma 6 на Wayland: `kwin` (источник фокуса) и `plasmashell` (OSD);
* `kglobalacceld` и System Settings — чтобы назначить хоткеи;
* PipeWire с `pipewire-pulse` — сервер, к которому подключается демон.

Root не нужен ни для установки, ни для работы; X11-инструменты не используются.
`install.sh` проверяет только Python-модули и подсказывает имена пакетов.

## Установка

### Пакет pacman (Arch)

```sh
bin/appvol-release --package    # собрать архив и пакет в dist/
cd packaging && makepkg -si     # или: sudo pacman -U ../dist/appvol-*.pkg.tar.zst
```

Пакет объявляет зависимости и ставит всё в `/usr`: пакет Python в site-packages,
`appvol` и `appvold` в `/usr/bin`, KWin-скрипт в `/usr/share/appvol`, запись хоткеев
в `/usr/share/applications`, пользовательский юнит в `/usr/lib/systemd/user`.
Клавиши назначаются вручную (см. «Хоткеи в KDE»), демон включается от имени
пользователя:

```sh
systemctl --user daemon-reload && systemctl --user enable --now appvold
```

### install.sh (любой дистрибутив, без root)

```sh
./install.sh --service     # без --service юнит только кладётся на место
./install.sh --uninstall   # убрать всё, что поставил скрипт
./install.sh --prefix DIR  # поставить не в ~/.local
```

Раскладка: `~/.local/share/appvol` — программа, KWin-скрипт и шаблоны,
`~/.local/bin/{appvol,appvold,appvol-shortcuts}` — симлинки на неё,
`~/.config/systemd/user/appvold.service` — юнит с абсолютным `ExecStart`,
`~/.local/share/applications/org.appvol.desktop` — запись хоткеев.

### Из каталога проекта

Ставить ничего не нужно: обёртки `bin/appvol` и `bin/appvold` сами находят пакет
рядом с собой (см. «Запуск»).

## Запуск

```sh
# из каталога проекта
bin/appvold            # демон, пишет логи в stderr
bin/appvol up          # в другом терминале
bin/appvol list        # состояние: фокус, потоки, шаг матчинга

# после install.sh или пакета
appvol up
journalctl --user -u appvold -f
```

Демон стартует вместе с сессией через пользовательский юнит. Его кладут `install.sh`
и пакет; при ручной установке шаблон нужно развернуть самому — в нём `@APPVOLD@` это
абсолютный путь к демону:

```sh
mkdir -p ~/.config/systemd/user
sed "s|@APPVOLD@|$PWD/bin/appvold|" systemd/appvold.service.in \
    > ~/.config/systemd/user/appvold.service
systemctl --user daemon-reload
systemctl --user enable --now appvold
```

KWin-скрипт демон ищет сам: сначала рядом с пакетом (`<проект>/kwin/appvol.js`), затем
в `$XDG_DATA_DIRS/appvol/appvol.js` — там его держит пакет. Переопределить путь можно
ключом `kwin_script` в конфиге или `bin/appvold --kwin-script FILE`.

## Хоткеи в KDE

appvol появляется в System Settings → Shortcuts сам, как приложения и системные
службы: KDE читает `.desktop`-файл с `X-KDE-Shortcuts` и действиями. Пакет для pacman
кладёт такой файл в `/usr/share/applications`, для каталога проекта и `install.sh`
запись ставится в `~/.local/share/applications`:

```sh
bin/appvol-shortcuts            # поставить или обновить запись
bin/appvol-shortcuts --remove   # убрать
```

Скрипт кладёт в `~/.local/share/applications/org.appvol.desktop` файл с
`Actions=VolumeUp;VolumeDown;Mute;`. KDE показывает такие файлы отдельной группой
**appvol** с действиями **Volume up**, **Volume down** и **Toggle mute**, а по нажатию
клавиши запускает `Exec` выбранного действия, то есть `bin/appvol up|down|mute`.
Путь в `Exec` абсолютный намеренно: у сервера хоткеев в PATH нет `~/.local/bin`,
поэтому добавленная руками команда `appvol up` не запускается и KDE отвечает
`Could not find the program "appvol"`. Записи от таких опытов (в том числе созданные
через Add → Command or Script) лучше удалить в том же разделе настроек.

Клавиш по умолчанию запись не занимает (`X-KDE-Shortcuts=none`): щёлкните по строке
действия в списке и назначьте свои. Путь к клиенту, который попадёт в файл, можно
переопределить переменной `APPVOL_BIN`.

Чтобы `appvol` был доступен в терминале, положите обёртку в `~/.local/bin` (это делает
`install.sh`) — но не копией, а симлинком: копия обёртки без самого пакета рядом модуль
не найдёт.

```sh
ln -sf ~/Projects/appvol/bin/appvol ~/.local/bin/appvol
```

Обёртка ищет пакет в таком порядке: `$APPVOL_ROOT`, каталог самого скрипта (симлинки
раскрываются через `readlink -f`), `~/.local/share/appvol`. Интерпретатор можно задать
через `PYTHON`.

## Конфиг

`~/.config/appvol/config.toml`, при отсутствии файла используются значения по умолчанию:

```toml
step = 5          # относительный шаг в процентах
max_volume = 100  # верхний предел, допускается до 150
osd = true        # показывать KDE OSD
# kwin_script = "/полный/путь/appvol.js"  # необязательное переопределение
```

Шаг применяется ко всем найденным потокам, баланс каналов сохраняется, значение
ограничивается диапазоном `0..max_volume`. Процент в OSD — максимум по изменённым
потокам.

## OSD и иконка приложения

При нажатии хоткея OSD показывает иконку приложения и полосу громкости с процентом.

Иконка берётся оттуда же, откуда её берёт микшер KDE (plasma-pa) — из свойств самого
звукового потока. Plasma перебирает свойства в таком порядке и берёт первое, которое
есть в текущей теме иконок:

1. `device.icon_name` / `media.icon_name` / `window.icon_name`;
2. `application.icon_name`;
3. `application.process.binary`;
4. `application.name`;
5. `pipewire.access.portal.app_id`.

Это ровно `PulseAudioQt::PulseObject::iconName()`. Свойства клиента-владельца потока
подмешиваются к свойствам потока — так же, как при матчинге; например, Spotify держит
`application.process.binary=spotify` только у клиента, а не у самого потока.

Если поток не сообщил ничего, что есть в теме, appvol откатывается на иконку окна:
`Icon=` файла `<desktopFileName>.desktop`, затем `<resourceClass>.desktop`, затем сам
идентификатор, если он не в reverse-DNS виде. Для приложений, которые себя никак не
афишируют (Node/Electron-плееры, обёртки), OSD покажет то же, что панель.

Проверка «есть ли такое имя в теме» сделана без Qt: тема читается из `kdeglobals`
(`[Icons] Theme=`), обходятся она сама, её `Inherits` и `hicolor`, а также
`XDG_*_DIRS/pixmaps`. Как и QIcon, имя пробуется ещё и без последнего сегмента после
дефиса (`spotify-launcher` рисуется как `spotify`). Найденное кешируется на время
работы демона, при повторных нажатиях диск не читается.

Расхождения с панелью ожидаемы и не считаются ошибкой: если приложение публикует
иконку, не совпадающую с иконкой окна, побеждает поток. Minecraft, например, отдаёт
`application.process.binary=java`, поэтому микшер и OSD показывают иконку Java, а не
иконку окна.

Технически используется штатный метод
`org.kde.osdService.mediaPlayerVolumeChanged(percent, name, icon)`, но аргумент
`name` отправляется пустым: подпись с именем приложения выглядела хуже, чем одна
иконка. Имя всё равно вычисляется — `appvol list` показывает его для диагностики,
а когда появится GUI, его можно будет вывести в OSD настройкой.

Если иконка неизвестна, OSD откатывается на штатный вид `volumeChanged(percent)`.
Что именно уйдёт в OSD, видно в `appvol list`:

```
match:  step=pid matched=1 (streams owned by pid 155358)
osd:    icon='spotify' (app 'Spotify')
```

При `mute` OSD показывает иконку приложения и короткое «Muted», при `unmute` —
иконку и полосу с текущей громкостью (или «Unmuted», если громкость нулевая).

## Диагностика

```sh
bin/appvol list          # фокус, потоки, шаг матчинга и причина отказа
bin/appvol -v list       # то же плюс отладочные сообщения клиента
APPVOL_VERBOSE=1 bin/appvold -v   # подробный лог демона
journalctl --user -u appvold -f   # логи при запуске через systemd
```

После `install.sh` или пакета те же команды короче: `appvol list`, `appvold -v`.

Проверка без окон (ручной фокус, как в отладке):

```sh
qdbus6 org.appvol.Daemon /org/appvol/Daemon org.appvol.Daemon.SetFocus \
    2952 spotify spotify "Spotify"
bin/appvol list
```

## Тесты

```sh
python3 -m unittest discover -s tests -t .
```

Покрыты чистые функции: матчинг (`tests/test_match.py`), расчёт громкости
(`tests/test_volume.py`), нормализация имён и обход дерева процессов
(`tests/test_focus.py`), выбор иконки для OSD — свойства потока, тема иконок,
.desktop-файлы (`tests/test_icon.py`), разбор конфига (`tests/test_config.py`),
соответствие записи хоткеев клиенту (`tests/test_shortcuts.py`), поведение обёртки
OSD при смене владельца имени (`tests/test_osd.py`), поиск KWin-скрипта в раскладках
репозитория и пакета (`tests/test_daemon.py`).

## Структура

```
appvol/focus.py    # цель (окно): pid, resourceClass, desktopFileName, дерево процессов
appvol/match.py    # чистая функция focus -> индексы sink-input'ов
appvol/volume.py   # чистая арифметика громкости (шаг, клэмп, баланс)
appvol/icon.py     # имя иконки для OSD: как в микшере, с откатом на панель
appvol/osd.py      # KDE OSD по D-Bus
appvol/config.py   # config.toml
appvol/daemon.py   # appvold: D-Bus сервис, pulsectl, автозагрузка KWin-скрипта
appvol/cli.py      # appvol
kwin/appvol.js     # KWin-скрипт (push фокуса)
desktop/           # шаблон записи хоткеев для KDE
systemd/           # шаблон пользовательского юнита
packaging/         # PKGBUILD и скриптлеты пакета pacman
install.sh         # установка в ~/.local без root
bin/               # обёртки appvol, appvold, appvol-shortcuts, appvol-release
bin/appvol-release # сборка архива релиза и пакета
tests/
```

## Релиз

Версия живёт в одном месте — `appvol/__init__.py`; из неё `bin/appvol-release`
синхронизирует `pkgver` в `packaging/PKGBUILD`.

```sh
$EDITOR appvol/__init__.py       # поднять версию
bin/appvol-release --package     # архив + пакет (в git-чекауте — из HEAD)
git tag -a v0.1.0 -m "appvol 0.1.0" && git push --tags
```

Что получается:

* `dist/appvol-<версия>.tar.gz` и `.sha256` рядом — архив релиза; в git-чекауте он
  собирается `git archive HEAD`, поэтому дерево должно быть чистым (иначе скрипт
  откажется работать, `--allow-dirty` снимает проверку);
* `packaging/appvol-<версия>.tar.gz` — тот же архив, потому что пакет собирается
  именно из него;
* `dist/appvol-<версия>-1-any.pkg.tar.zst` — пакет pacman.

Контрольная сумма не лежит в `PKGBUILD` намеренно: архив содержит сам `PKGBUILD`,
поэтому подходящей суммы для него не существует. `makepkg` работает с
`sha256sums=('SKIP')`, а сумма публикуется файлом `.sha256`.


## Что подтвердилось на KWin 6.7.5 (Plasma 6.7.5)

Разведка на живой системе, отличия от предположений ТЗ:

* `org.kde.KWin /Scripting` предоставляет `loadScript(path, name)` и
  `isScriptLoaded(name)`; метода `run()` у `/Scripting` нет. `loadScript`
  возвращает id, и `run()` вызывается у отдельного объекта
  `/Scripting/Script<id>` (интерфейс `org.kde.kwin.Script`). Повторная загрузка
  с занятым именем возвращает `-1`, поэтому демон сначала делает `unloadScript`.
* У `loadScript` две перегрузки; `dbus-python` видит только первую, поэтому
  вызов идёт с явной подписью `signature="ss"`.
* `workspace.activeWindow` отдаёт `pid`, `resourceClass`, `resourceName`,
  `desktopFileName`, `caption`, `windowType`. `callDBus` доступен из скрипта,
  целые числа из JS корректно маршалятся в D-Bus `i`, сигнал
  `workspace.windowActivated` существует.
* OSD: `org.kde.osdService.volumeChanged` перегружен как `(i)` и `(ii)`,
  поэтому вызов идёт с явной подписью `signature="i"`; `showText` доступен.
* Иконку приложения штатное `volumeChanged` показать не умеет. Для этого есть
  `mediaPlayerVolumeChanged(percent, name, icon)`; в `shell/osd.cpp` из
  plasma-workspace видно, что он вызывает `showProgress(icon, percent, 100, name)`,
  а при нулевом проценте — `showText(icon, "%1 Muted")`. appvol использует его,
  когда иконка известна, передавая пустое имя: в OSD остаётся только иконка.
* Прокси OSD нельзя держать «как есть»: `dbus-python` по умолчанию резолвит
  известное имя в уникальное имя текущего владельца и дальше шлёт вызовы именно
  туда. После перезапуска plasmashell закешированный прокси демона указывал на
  мёртвое `:1.x`, и каждый вызов OSD отвечал
  `ServiceUnknown: The name is not activatable`, хотя громкость менялась —
  заметно только по логу. Поэтому прокси создаётся с
  `follow_name_owner_changes=True` (вызов уходит на известное имя, владельца
  подставляет шина), а упавший вызов один раз повторяется на свежем прокси
  (`appvol/osd.py`, `tests/test_osd.py`).
* Иконку для потока микшер KDE (plasma-pa) ищет в свойствах самого потока
  (`PulseAudioQt::PulseObject::iconName()`): `device.icon_name`, `media.icon_name`,
  `window.icon_name`, `application.icon_name`, `application.process.binary`,
  `application.name`, `pipewire.access.portal.app_id` — берётся первое, что есть в
  теме иконок. Иконку окна plasmashell, наоборот, берёт из `Icon=`
  .desktop-файла. appvol использует первый источник, второй — как откат
  (`appvol/icon.py`).
* Свойства чувствительны к стилю записи: пульсовый слой отдаёт
  `application.icon_name`, PipeWire — `application.icon-name`, поэтому
  просматриваются оба варианта.
* `QIcon::hasThemeIcon()` в отрыве от сеанса отвечает неверно (тема Qt задаётся
  платформенной темой, а не вызовом `setThemeName` после старта), и в отрыве от
  Qt тоже: `QIcon::fromTheme()` умеет отбрасывать последний сегмент после дефиса
  (`spotify-launcher` → `spotify`). Поэтому проверка «есть ли имя в теме» сделана
  обходом каталогов темы вручную и сверена с `kiconfinder6` на 17 именах —
  расхождений нет.
* У Spotify нет `application.process.id` у sink-input'а — pid лежит у PulseAudio
  клиента (`client.id` → `application.process.id`). Матчинг поэтому сравнивает
  свойства sink-input'а, **объединённые** со свойствами его клиента.
* `pulsectl` даёт по индексу `PA_VOLUME_UI_MAX` (150%), что совпадает с
  допустимым `max_volume`.
* Spotify, запущенный через `spotify-launcher`, сообщает окну
  `desktopFileName = "spotify-launcher"`, но `resourceClass = "Spotify"`.
  Имя приложения совпадает именно по `resourceClass`, поэтому шаг «имя»
  сравнивает оба поля, а не только `desktopFileName`.
* Хоткеи: desktop-файл с `Actions=` и непустым `X-KDE-Shortcuts` (в любой группе —
  службы или действия) демон `kglobalacceld` превращает в компонент.
  `KServiceActionComponent::loadSettings` регистрирует хоткей на каждое действие,
  `emitGlobalShortcutEvent` по нажатию запускает `Exec` этого действия через
  `KIO::ApplicationLauncherJob`. Сканирование привязано к изменению sycoca, поэтому
  запись появляется в списке сразу, без перелогина.
* `X-KDE-GlobalShortcutType=Service` избавляет от лишнего действия «запустить сам
  файл», которое KDE добавляет по умолчанию. `X-KDE-Shortcuts=none` — это «клавиша не
  назначена»: пустое значение не подходит, демон ищет именно непустое.
* Флаг `X-KDE-GlobalAccel-CommandShortcut=true` (его ставит KCM в Add → Command or
  Script) заставляет KCM подписывать действия строкой `Exec` и относить компонент к
  разделу «Commands»; без флага действия подписаны своими `Name`, а файл из
  `~/.local/share/applications` KCM показывает как приложение. Запись appvol идёт по
  второму пути.
* Перезапуск `pipewire-pulse` (проверено на живой системе): первое обращение
  падает с `CallError`/`PulseDisconnected`, демон закрывает соединение, создаёт
  новое и повторяет операцию — команда доходит до результата без ручных действий.
  Сразу после рестарта потоков может ещё не быть: `stream-restore` восстанавливает
  их в течение пары секунд.

## Приложение: исходное техническое задание

Исходное ТЗ сохранено без изменений в `README.task.md`. Ключевые требования —
цель №1 (`up|down|mute` для активного окна + OSD), без GUI, правил, групп и portal.
