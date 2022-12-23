import datetime
import json
import locale
import logging
import os
import time
import traceback

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (CallbackContext, CallbackQueryHandler,
                          CommandHandler, Updater)

CACHED_EVENT_TYPES = []
CACHED_EVENTS = {}

load_dotenv()

print(os.getenv('LOCALE'))

locale.setlocale(locale.LC_ALL, os.getenv('LOCALE'))


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_phrase(phrase: str) -> str:
    global PHRASES

    return PHRASES[phrase]


def start(update: Update, _: CallbackContext):
    day_date_format = '%d %b %Y'
    date_format = '%d %b %Y %H:%M'

    keyboard_buttons = []

    for i in range(0, 7):
        date = datetime.date.today() + datetime.timedelta(days=i)
        keyboard_buttons.append(InlineKeyboardButton(
            text=f"🗓️{date.strftime(day_date_format)}", callback_data=json.dumps({'date': repr(date)})))

    update.effective_message.reply_html(get_phrase('SELECT_SCHEDULE_DATE').replace("{0}", time.strftime(date_format)),
                                        reply_markup=InlineKeyboardMarkup.from_column(keyboard_buttons))

    logger.log(
        msg=f'[{get_formatted_user(update)}] started bot', level=logging.INFO)


def get_event_types_json():
    global CACHED_EVENT_TYPES

    if not CACHED_EVENT_TYPES:
        response = requests.get(os.getenv('EVENT_TYPES_URL'), headers={
            'User-Agent': os.getenv('USER_AGENT_HEADER_VALUE'),
            'Authorization': os.getenv('AUTHORIZATION_HEADER_VALUE'),
            'Referer': os.getenv('REFERER_HEADER_VALUE'),
            'Content-Type': 'application/json',
            'Cookie': os.getenv('COOKIE_HEADER_VALUE')
        })

        json = response.json()

        CACHED_EVENT_TYPES = json['_embedded']['event-types']

    return CACHED_EVENT_TYPES


def get_events_json(date):
    response = requests.post(os.getenv('EVENTS_URL'), headers={
        'User-Agent': os.getenv('USER_AGENT_HEADER_VALUE'),
        'Authorization': os.getenv('AUTHORIZATION_HEADER_VALUE'),
        'Referer': os.getenv('REFERER_HEADER_VALUE'),
        'Content-Type': 'application/json',
        'Cookie': os.getenv('COOKIE_HEADER_VALUE')
    }, data='{"size":500,"timeMin":"' + date.strftime('%Y-%m-%d') + 'T00:00:00Z","timeMax":"' + date.strftime('%Y-%m-%d') + 'T23:59:59Z","attendeePersonId":["' + os.getenv('ATTENDEE_PERSON_ID') + '"]}')

    json = response.json()

    return json['_embedded']


def sort_events(events):
    return sorted(events, key=lambda x: datetime.datetime.strptime(x['startsAt'], '%Y-%m-%dT%H:%M:%S'))


def get_formatted_events_text(events, day, all_events):
    hour_format = '%H:%M'

    sorted_events = sort_events(events)
    event_types = get_event_types_json()

    global_builder = []

    header = f'<b>{get_phrase("SCHEDULE_FOR_DATE").replace("{0}", str(day))}</b>'
    global_builder.append(header)

    for index, event in enumerate(sorted_events):
        local_builder = []

        startsAt = datetime.datetime.strptime(
            event['startsAt'], "%Y-%m-%dT%H:%M:%S").strftime(hour_format)
        endsAt = datetime.datetime.strptime(
            event['endsAt'], "%Y-%m-%dT%H:%M:%S").strftime(hour_format)
        room = get_event_room(event_id=event['id'], events=all_events)
        course_unit_realization = get_course_unit_realization(
            realization_id=event['_links']['course-unit-realization']['href'].replace('/', ''), events=all_events)
        lecturer = get_lecturer(event_id=event['id'], events=all_events)

        event_type_name = next(
            x for x in event_types if x['id'] == event['typeId'])['name']

        local_builder.append(f"🕒 {startsAt}-{endsAt}")

        is_online = False

        try:
            local_builder.append(
                f"📙 {index + 1}. <b>[{room['building']['nameShort']}]</b> - {course_unit_realization['name']} / {event['name']}")
            local_builder.append(
                f"{get_phrase('LECTURER')} {lecturer['fullName']}")
        except:
            local_builder.append(
                f"🖥️ {index + 1}. <b>[{get_phrase('ONLINE_EVENT')}]</b> - {course_unit_realization['name']} / {event['name']}")
            is_online = True
        local_builder.append(f"📖 <i>({event_type_name})</i>")

        if is_online:
            local_builder.append(f"🌏 {room['nameShort']}")
        else:
            local_builder.append(f"🚪 {room['nameShort']}")

        global_builder.append('\n'.join(local_builder))

    return '\n\n'.join(global_builder)


def get_event_room(event_id, events):
    try:
        locations = events['event-locations']
        location = next(x for x in locations if x['eventId'] == event_id)

        event_room_id = location['_links']['event-rooms']['href'].replace(
            '/', '')
        room_id = next(x for x in events['event-rooms'] if x['id'] == event_room_id)[
            '_links']['room']['href'].replace('/', '')
        rooms = events['rooms']
        room = next(x for x in rooms if x['id'] == room_id)

        return room
    except:
        return {
            'nameShort': 'Educon'
        }


def get_course_unit_realization(realization_id, events):
    realizations = events['course-unit-realizations']
    course_unit_realization = next(
        x for x in realizations if x['id'] == realization_id)

    return course_unit_realization


def get_lecturer(event_id, events):
    event_attendees_id = next(x for x in events['event-organizers'] if x['eventId'] == event_id)[
        '_links']['event-attendees']['href'].replace('/', '')
    person_id = next(x for x in events['event-attendees'] if x['id'] ==
                     event_attendees_id)['_links']['person']['href'].replace('/', '')
    person = next(x for x in events['persons'] if x['id'] == person_id)
    return person


def get_formatted_user(update: Update):
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name

    return f'{user_id} :: {full_name}'


def handle_callback_query(update: Update, _: CallbackContext):
    global logger
    global CACHED_EVENTS

    action = update.callback_query.data

    date = eval(json.loads(action)['date'])
    yesterday = date + datetime.timedelta(days=-1)
    tomorrow = date + datetime.timedelta(days=1)
    week_ago = date + datetime.timedelta(days=-7)
    after_week = date + datetime.timedelta(days=7)
    day = date.day

    formatted_user = get_formatted_user(update)

    try:
        if not CACHED_EVENTS.get(repr(date), None):
            events = get_events_json(date=date)
            formatted_schedule = get_formatted_events_text(
                events=events['events'], day=day, all_events=events)

            CACHED_EVENTS[repr(date)] = formatted_schedule

            logger.log(
                msg=f'[{formatted_user}] created cache for {repr(date)}', level=logging.INFO)
        else:
            logger.log(
                msg=f'[{formatted_user}] already cached for {repr(date)}', level=logging.INFO)
    except:
        traceback.print_exc()

        if not CACHED_EVENTS.get(repr(date), None):
            CACHED_EVENTS[repr(date)] = get_phrase('EVENTS_NOT_FOUND')

            logger.log(
                msg=f'[{formatted_user}] created 404 cache for {repr(date)}', level=logging.INFO)

    update.effective_message.reply_html(text=CACHED_EVENTS[repr(date)], reply_markup=InlineKeyboardMarkup([
        [
            InlineKeyboardButton(text=f'⬅ {yesterday.strftime("%d.%m %A")}', callback_data=json.dumps(
                {'type': 'yesterday', 'date': repr(yesterday)})),
            InlineKeyboardButton(text=f'➡️ {tomorrow.strftime("%d.%m %A")}', callback_data=json.dumps(
                {'type': 'tomorrow', 'date': repr(tomorrow)})),
        ],
        [
            InlineKeyboardButton(text=f'⏪ {week_ago.strftime("%d.%m %A")}', callback_data=json.dumps(
                {'type': 'week_ago', 'date': repr(week_ago)})),
            InlineKeyboardButton(text=f'⏩ {after_week.strftime("%d.%m %A")}', callback_data=json.dumps(
                {'type': 'after_week', 'date': repr(after_week)}))
        ]
    ]))
    logger.log(msg=f'[{formatted_user}] {action}', level=logging.INFO)


def main():
    global PHRASES

    with open('locales.json', mode='r', encoding='utf-8') as file:
        PHRASES = json.loads(file.read())

    updater = Updater(os.getenv('TOKEN'))

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CallbackQueryHandler(handle_callback_query))

    updater.start_polling()

    updater.idle()


if __name__ == '__main__':
    main()
