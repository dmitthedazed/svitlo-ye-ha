<p align="center">
  <img src="images/logo.svg" alt="СвітлоЄ?" width="160">
</p>

<h1 align="center">СвітлоЄ? для Home Assistant</h1>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=dmitthedazed&repository=svitlo-ye-ha&category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Додати в HACS"></a>
  <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=svitlo_ye"><img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Додати інтеграцію"></a>
</p>

<p align="center">
  <a href="https://github.com/dmitthedazed/svitlo-ye-ha/actions/workflows/tests.yml"><img src="https://github.com/dmitthedazed/svitlo-ye-ha/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/dmitthedazed/svitlo-ye-ha/actions/workflows/validate.yml"><img src="https://github.com/dmitthedazed/svitlo-ye-ha/actions/workflows/validate.yml/badge.svg" alt="Validate"></a>
</p>

Графіки відключень світла від «Житомиробленерго» прямо в Home Assistant. Дані
беруться з публічного сайту обленерго, тож ні акаунта, ні ключа не треба.

- Адресу обираєте по кроках: **РЕМ → населений пункт → вулиця → будинок**. Чергу й
  підчергу інтеграція визначить сама.
- Додати можна скільки завгодно адрес: кожна стане окремим пристроєм.
- Графік тягнеться раз на 15 хвилин (це налаштовується), а стани сутностей
  перераховуються щохвилини.
- Усе рахується за київським часом.

## Встановлення

Потрібен Home Assistant **2025.2** або новіший. Найпростіше натиснути «Додати в HACS»
вгорі (потрібен [My Home Assistant](https://my.home-assistant.io/)). Якщо не виходить:

1. HACS → ⋮ → **Custom repositories**.
2. Вставте `https://github.com/dmitthedazed/svitlo-ye-ha`, категорія **Integration**.
3. Знайдіть «СвітлоЄ? (Житомиробленерго)» і натисніть **Download**.
4. Перезапустіть Home Assistant.

<details>
<summary>Встановлення вручну</summary>

1. Скопіюйте папку `custom_components/svitlo_ye` у `<config>/custom_components/svitlo_ye`.
2. Перезапустіть Home Assistant.

</details>

## Налаштування

Натисніть «Додати інтеграцію» вгорі або відкрийте **Налаштування → Пристрої та служби →
Додати інтеграцію → «СвітлоЄ?»**.

1. **РЕМ**, наприклад «Житомирський».
2. **Населений пункт.**
3. **Вулиця.** Якщо їх понад 60, спершу з'явиться пошук за частиною назви
   (скажімо, «Київська»).
4. **Будинок.** Біля номера видно чергу, наприклад `12А — черга 3.1`. Юридичних
   споживачів позначено «(юридичні)». Тут же можна дати адресі назву: «Дім», «Робота».

Ще одна адреса додається тими самими кроками.

Інтервал оновлення (від 5 до 180 хвилин, типово 15) змінюється кнопкою
«Налаштувати» на записі інтеграції. Переїхали чи помилилися з будинком: ⋮ →
*Переналаштувати*, ідентифікатори сутностей при цьому не зміняться.

## Картка

Окремо нічого підключати не треба: картка `svitlo-ye-card` приїздить разом з
інтеграцією. Після перезапуску HA один раз оновіть сторінку (Ctrl+F5). Вона показує
статус, чергу, час найближчої зміни та 24-годинний таймлайн з маркером «зараз» на сьогодні
й завтра.

```yaml
type: custom:svitlo-ye-card
entity: sensor.dim_schedule
show_tomorrow: true    # необов'язково
show_messages: true    # необов'язково
```

## Сутності

Для прикладу взято адресу «Дім». Назви перекладені, а ідентифікатори HA будує з
англійських, наприклад `binary_sensor.dim_power` чи `sensor.dim_schedule`.

Найкорисніше:

- **Є світло** (`binary_sensor`): `on`, коли за графіком світло є. Можливе відключення
  теж рахується як `off`. Якщо графіка на цей час немає, стан `unknown`.
- **Графік** (`sensor`): `available`, `outage`, `probable` або `unknown`. В атрибутах
  `today` і `tomorrow` лежать інтервали для карток.
- **Наступне відключення** і **наступне вмикання** (`sensor`, timestamp).
- **Відключення** (`calendar`): події «Відключення світла» та «Можливе відключення світла».
- **Події графіка** (`event`): `power_off`, `power_on`, `schedule_changed`,
  `tomorrow_published`.

<details>
<summary>Усі сутності</summary>

| Сутність | Тип | Опис |
|---|---|---|
| **Є світло** | `binary_sensor` (`power`) | `on`: світло є. `off`: відключення або можливе відключення. `unknown`: графіка на цей час немає |
| **Графік** | `sensor` (enum) | Поточний статус. Атрибути: `today`, `tomorrow`, `current`, `messages` (оголошення обленерго), `queue` |
| **Наступна зміна стану** | `sensor` (timestamp) | Коли світло з'явиться або зникне. Атрибут `next_power_state`: `on` / `off` |
| **До відключення / увімкнення** | `sensor` (duration, хв) | Скільки хвилин до наступної зміни |
| **Наступне відключення / вмикання** | `sensor` (timestamp) | `next_power_off` і `next_power_on` |
| **Черга** | `sensor` | Черга й підчерга, наприклад `3.1` |
| **Відключень сьогодні** | `sensor` (duration, год) | Скільки годин гарантованих відключень заплановано. Атрибути: `probable_hours`, `available_hours`, `unknown_hours`, `outages`, `published` |
| **Відключень завтра** | `sensor` (duration, год) | Те саме на завтра, до публікації графіка `unknown` |
| **Графік на завтра опубліковано** | `binary_sensor` | `on`, коли графік на завтра вже виклали |
| **Відключення** | `calendar` | Відключення та можливі відключення |
| **Події графіка** | `event` | `power_off`, `power_on`, `schedule_changed`, `tomorrow_published` |
| **Оновити графік** | `button` | Завантажити графік просто зараз |
| **Останнє оновлення даних** | `sensor` (timestamp, діагностика) | Коли обленерго оновило графік |

Коли сервер недоступний, сутності стають `unavailable` до першого вдалого оновлення.
Якщо він мовчить близько трьох годин, у *Налаштування → Система → Відновлення*
з'явиться попередження, яке зникне саме після відновлення зв'язку.

</details>

<details>
<summary>Сервіс <code>svitlo_ye.get_schedule</code></summary>

Повертає графік у відповіді сервісу (`response_variable`): `queue`, `server_updated`
і `days` з інтервалами за датами. Параметр `days` від 1 до 7, типово 2. Ціль: будь-який
сенсор інтеграції.

</details>

## Приклади

<details>
<summary>Сповіщення за 15 хвилин до відключення (календар)</summary>

```yaml
alias: "Світло: за 15 хв відключення"
triggers:
  - trigger: calendar
    event: start
    offset: "-0:15:00"
    entity_id: calendar.dim_outages
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "⚡ Скоро відключення"
      message: >-
        {{ trigger.calendar_event.summary }} о
        {{ as_timestamp(trigger.calendar_event.start) | timestamp_custom('%H:%M') }}
        до {{ as_timestamp(trigger.calendar_event.end) | timestamp_custom('%H:%M') }}.
mode: queued
```

</details>

<details>
<summary>Сповіщення за 15 хвилин до відключення (сенсор)</summary>

```yaml
alias: "Світло: за 15 хв відключення (сенсор)"
triggers:
  - trigger: numeric_state
    entity_id: sensor.dim_time_to_power_change
    below: 16
conditions:
  - condition: state
    entity_id: sensor.dim_time_to_power_change
    attribute: next_power_state
    state: "off"
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: >-
        Світло вимкнуть о
        {{ states('sensor.dim_next_power_change') | as_datetime | as_local
           | as_timestamp | timestamp_custom('%H:%M') }}
```

</details>

<details>
<summary>Світло повернулося за графіком</summary>

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.dim_power
    from: "off"
    to: "on"
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: "За графіком світло вже має бути 💡"
```

</details>

<details>
<summary>Картка Entities</summary>

```yaml
type: entities
title: Дім — світло
entities:
  - entity: binary_sensor.dim_power
  - entity: sensor.dim_next_power_change
    format: time
  - entity: sensor.dim_time_to_power_change
  - entity: sensor.dim_queue
  - entity: sensor.dim_outages_today
  - entity: sensor.dim_outages_tomorrow
  - entity: sensor.dim_last_data_update
```

</details>

<details>
<summary>Картка Markdown з розкладом</summary>

```yaml
type: markdown
title: Графік відключень
content: >-
  {% set s = 'sensor.dim_schedule' %}
  {% set icons = {'available': '🟢', 'outage': '🔴', 'probable': '🟡', 'unknown': '⚪'} %}
  **Черга {{ state_attr(s, 'queue') }}**

  **Сьогодні**
  {% for i in state_attr(s, 'today') or [] %}
  {{ icons[i.status] }} {{ i.start_time }}–{{ i.end_time }}
  {% else %}
  _графік не опубліковано_
  {% endfor %}

  **Завтра**
  {% for i in state_attr(s, 'tomorrow') or [] %}
  {{ icons[i.status] }} {{ i.start_time }}–{{ i.end_time }}
  {% else %}
  _графік ще не опубліковано_
  {% endfor %}
```

</details>

<details>
<summary>Таймлайн в apexcharts-card</summary>

Потрібна [apexcharts-card](https://github.com/RomRider/apexcharts-card) з HACS.
На графіку `1`: світло є, `0`: відключення, `0.5`: можливе відключення.

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Світло сьогодні й завтра
graph_span: 2d
span:
  start: day
now:
  show: true
  label: зараз
yaxis:
  - min: 0
    max: 1
    decimals: 1
apex_config:
  chart:
    height: 160
  legend:
    show: false
series:
  - entity: sensor.dim_schedule
    name: Світло
    type: area
    curve: stepline
    color: "#FFB800"
    data_generator: |
      const level = { available: 1, probable: 0.5, outage: 0, unknown: null };
      const items = [...(entity.attributes.today || []), ...(entity.attributes.tomorrow || [])];
      const points = [];
      for (const i of items) {
        points.push([new Date(i.start).getTime(), level[i.status]]);
        points.push([new Date(i.end).getTime() - 1, level[i.status]]);
      }
      return points;
```

</details>

## Діагностика

**Налаштування → Пристрої та служби → СвітлоЄ? → ⋮ → Завантажити діагностику.**
У файл потрапляють графік, повідомлення й стан оновлень, а вулицю та номер будинку
замасковано.

## [📱 СвітлоЄ? для Android](https://github.com/dmitthedazed/SvitloYE)

Той самий графік у кишені: сповіщення, віджети, кілька адрес, без реклами.

## Ліцензія

MIT. Інтеграція неофіційна й ніяк не пов'язана з АТ «Житомиробленерго».
