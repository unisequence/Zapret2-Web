# Наблюдения по LuCI zapret2 на OpenWrt

Снимок настроек тестового роутера, просмотренный 23.09.2026 через LuCI без
изменения конфигурации. Версия пакета zapret2: `1.0.4-r11`, OpenWrt: `25.12.4`.
Пароли и адрес устройства здесь не сохраняются.

## Служба и стратегии

- Состояние: `main + 2 custom scripts`; автозапуск включён.
- Активные стратегии в порядке LuCI: `Discord_circular`, `discord_media`,
  `discord_udp`, `Youtube_UDP`, `Yv08`, `V_circular`, `games_tcp`, `games_udp`.
- Остальные варианты (`Youtube_circular`, `Yv_circular`, `Routerich_circular`,
  `DoH_*`, `v1`–`v10`, `Yv01`–`Yv11` и др.) выключены, но сохранены для выбора.
- У стратегии есть имя, состояние, порт, фильтры L3/L7, TCP/UDP, списки
  доменов и IP, исключения, автолист и текст опций `nfqws2`.
- Порядок стратегий важен: zapret2 выбирает первый подходящий профиль.
- Порядок опций внутри `script` тоже важен: `--in-range` может стоять между
  действиями `--lua-desync` и влиять лишь на последующие действия. Общий формат
  должен сохранять исходную последовательность.

Полный каталог из 34 карточек перенесён без перестановки опций в
`app/zapret2_webcontrol/strategy_catalog.py`.

| Семейство | Количество | Назначение |
| --- | ---: | --- |
| Активные прикладные | 8 | Discord TCP/UDP, YouTube TCP/QUIC, общий circular, игровые TCP/UDP |
| `v1`–`v10` | 10 | Атомарные TLS-варианты общего профиля |
| `Yv01`–`Yv11` без `Yv08` | 10 | Выключенные атомарные YouTube-варианты; `Yv08` активен выше |
| Circular | 3 выключенных + 2 активных | Адаптивная ротация действий с `strategy=N` |
| DoH | 2 | DNS/53 UDP и TLS/853 |
| `alt11` | 1 | Общий TCP/80,443 без L7-фильтра |

### Что означает circular

`circular` реализован в базовом `zapret-auto.lua`. Он считает неудачи для
хоста и переключает последующие действия, помеченные `strategy=1`,
`strategy=2` и так далее. Это не Linux firewall-функция и не отдельный
формат стратегии: та же Lua-механика доступна в `winws2`, если загружены
`zapret-lib.lua`, `zapret-antidpi.lua` и `zapret-auto.lua`.

### Проверка blob-зависимостей

В LuCI реально включена загрузка только следующих внешних blob-файлов:
`blob_stun`, `blob_tls_clienthello_gosuslugi_ru`,
`blob_tls_clienthello_t2_ru`, `blob_tls_clienthello_vk_com`,
`blob_tls_clienthello_www_4pda_to` и
`blob_tls_clienthello_www_google_com`.

Несколько включённых профилей ссылаются на имена, отсутствующие в этом списке:
`blob_quic_initial_steamcommunity_com`, `blob_stun2`,
`blob_tls_clienthello_www_onetrust_com` и
`blob_quic_initial_4pda_to`. На самом роутере это висячие ссылки, а не проблема
конвертера. Windows-бэкенд блокирует запуск, если соответствующие `.bin` не
добавлены в `runtime/blobs`.

Проверка через SSH подтвердила: этих четырёх файлов нет в
`/opt/zapret2/files/fake`, а рекурсивный поиск находит имена только в
сгенерированном `/opt/zapret2/config` и UCI-конфиге. То есть это реальные
висячие ссылки исходной конфигурации. Недостающие payload найдены в проектах,
которые используют Windows/OpenWrt-стратегии zapret v1:

- `quic_initial_steamcommunity_com.bin`, `stun2.bin` и
  `quic_initial_4pda_to.bin` —
  [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube),
  commit `865da4f4c3659523bf79bc6edf0446e7d7969614`;
- `tls_clienthello_www_onetrust_com.bin` —
  [remittor/zapret-openwrt](https://github.com/remittor/zapret-openwrt),
  commit `1b04a87558ec7965bfed0ef7fb557997872dd699`.

Полная история официальных `bol-van/zapret` (v1) и
`bol-van/zapret-win-bundle` также была проверена по именам. Точных четырёх
файлов там нет, поэтому подмена похожими payload не выполнялась. Источники выше
закреплены по commit, а bootstrap проверяет содержимое по SHA-256.

Контрольные суммы SHA-256:

| Файл | SHA-256 |
| --- | --- |
| `quic_initial_steamcommunity_com.bin` | `2FE18B3BD20807D36704D0B072092EE49AE84EDCA907A4420AB9A0F0F28FDDCF` |
| `stun2.bin` | `B7C2497496039C541F7337AC8536813F0A1CF52363AB2FAA5213B7816D458813` |
| `quic_initial_4pda_to.bin` | `E065870CB0D13152E6132807BBF42218A9E7CD8D96F5602B61674CC540F3A56E` |
| `tls_clienthello_www_onetrust_com.bin` | `4EE0870ABE0A0128600B0095189987BA1D210DAE8BF963BC725AFF49CF922624` |

Все эти файлы, доступные роутерные blob и Discord hostlist скопированы в
локальный `runtime` для Windows-проверок; этот каталог намеренно исключён из
Git. После подключения ресурсов все 34 профиля отдельно и полная активная
конфигурация успешно проходят `winws2 --dry-run`.

Воспроизводимая установка этих ресурсов реализована в
`scripts/bootstrap_windows.ps1`; бинарные payload не коммитятся в проект.

## Основные настройки роутера

| Параметр | Значение |
| --- | --- |
| Debug / IPv6 | выключены |
| POSTNAT / Filter TTL Expired ICMP | включены |
| Flow Offloading | Don't touch |
| Desync Mark / Postnat | `0x40000000` / `0x20000000` |
| Общие TCP / UDP порты NFQUEUE | `80,443,853,1024-65535` / `53,80,88,443,1024-65535` |
| Исходящие / входящие TCP пакеты | `25` / `5` |
| Lua GC | `600` |
| Conntrack timeouts | `60:300:60:60` |

Это параметры Linux/OpenWrt-бэкенда; общая веб-панель должна показывать только
возможности выбранной платформы. В Windows перехват строится через WinDivert,
а не через NFQUEUE, nftables и packet marks.

## Дополнительные скрипты

Включены `50-discord_media.sh` и `50-stun4all.sh`. Каждый создаёт отдельный
`nfqws2` daemon/queue и свои правила firewall.

- Discord media: UDP `19294-19344` и `50000-50099`, проверка QUIC Initial
  через `u32` либо `nft @ih`, `--payload discord_ip_discovery`, внешний blob
  `quic_initial_dbankcloud_ru.bin`, Lua `fake:blob=dbank:repeats=6`.
- STUN: сигнатура magic cookie `0x2112A442`, также `u32`/`nft @ih`,
  `--payload stun` и тот же внешний blob.

Для Windows нужно отдельно описать эквивалентный WinDivert raw filter или
проверенную схему захвата. Сам текст `.sh` исполнять на Windows нельзя.

В официальном `zapret-win-bundle` уже есть
`windivert_part.discord_media.txt` и `windivert_part.stun.txt`. Поэтому
Windows-бэкенд подключает эти фильтры через `--wf-raw-part=@...` вместо
переноса правил `u32`/nftables. Сам `winws2` из локального бандла проверен:
версия `v1.0.5.2`, Lua compatibility `6`; базовый перенесённый профиль
успешно проходит `--dry-run`.

## Списки, автолист и диагностика

В LuCI определены доменные списки `auto`, `user`, `user_exclude`, `youtube`,
`discord` в каталоге `/opt/zapret2/ipset/`. Содержимое Discord-списка
редактируется прямо в модальном окне; он не входит в официальный Windows-бандл.

Режим автолиста сейчас «Отсутствует». Параметры: порог ретрансляций `3`, порог
ошибок `3`, окно `60`, incoming maxseq `4096`, retrans maxseq `32768`,
retrans reset `1`, UDP in/out `1`/`4`. Список обнаруженных хостов пуст.

Blockcheck2 настроен на HTTPS TLS 1.2, IPv4, тайм-аут `1.5s`, один повтор,
уровень `standard`, автосбор максимум пяти стратегий и параллельное выполнение.
Журнал автолиста находится в `/opt/zapret2/ipset/zapret_hosts_auto_debug.log`;
режим отладки выключен.
