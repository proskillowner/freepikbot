import datetime as dt
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from telegram.error import BadRequest, NetworkError
from telegram.ext import Updater, CallbackContext, CommandHandler, Dispatcher, Filters, MessageHandler, \
    PicklePersistence, JobQueue, Defaults
from freepik import *
from flaticon import *
import logging
import pytz
from roles import roles
from ptbcontrib.postgres_persistence import PostgresPersistence


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
DEFAULT_TZINFO = pytz.FixedOffset(5 * 60 + 30)
freepik_client = Freepik(os.environ['FREEPIK_USERNAME'], os.environ['FREEPIK_PASSWORD'], os.environ['TWO_CAPTCHA_API_KEY'])


class InvalidURLError(Exception):
    pass


def inline_handler(msg: str):
    """returns a handler that sends message msg in response to any updates"""
    def handler(update: Update, ctx: CallbackContext):
        update.effective_chat.send_message(msg)
    return handler


def set_role_handler(update: Update, ctx: CallbackContext):
    # print('bot_data =', ctx.bot_data)
    print(update.message.text)
    if len(ctx.args) < 2:
        return update.message.reply_text('You have to specify the role and the username(s) like this: /set_role role_name username\n'
                                         'You can see all roles with /roles_list')
    role = ctx.args[0]
    usernames = [username if not username.startswith('@') else username[1:] for username in ctx.args[1:]]
    for username in usernames:
        ctx.bot_data['users'][username] = {}
        for k, v in default_user(role).items():
            ctx.bot_data['users'][username][k] = v
    update.message.reply_text(f'The following users have been promoted to {role}:\n' + "\n".join(usernames))
    # print('bot_data =', ctx.bot_data)
    # print('default_user =', default_user())


def roles_list_handler(update: Update, ctx: CallbackContext):
    lines = []
    indent = 2
    for role, params in roles.items():
        lines.append(role)
        lines.append('\n'.join(f'{" " * indent}{k} = {v}' for k, v in params.items()))
    msg = '\n'.join(lines)
    if not msg:
        msg = 'There are no roles'
    update.message.reply_text(msg)


def members_list_handler(update: Update, ctx: CallbackContext):
    lines = [f'{user_data["role"]} - {username}' for username, user_data in ctx.bot_data['users'].items() if user_data["role"] != 'regular']
    msg = '\n'.join(sorted(lines))
    if not msg:
        msg = 'There are no members'
    update.message.reply_text(msg)


def restrict_if_necessary(update: Update, ctx: CallbackContext):
    username = effective_username(update)
    # print(f'restrict_if_necessary(user={username})')
    user_data = ctx.bot_data['users'][username]
    if user_data['uses'] <= 0:
        print(f'retstricting user {username}')
        today_12am = dt.datetime.now(DEFAULT_TZINFO).replace(hour=0, minute=0, second=0, microsecond=0)
        user_data['unrestrict_date'] = (today_12am + dt.timedelta(days=user_data['restrict_days'])).isoformat()
        permissions = ChatPermissions(*([False] * 8))  # set all 8 arguments to False
        if user_data['restrict_days'] > 1:
            unlock_date = (today_12am + dt.timedelta(days=user_data['restrict_days'])).date().isoformat()
            update.effective_chat.send_message(f'[@{username}]\n'
                                               f'You will be unlocked on {unlock_date}')
        try:
            ctx.bot.restrict_chat_member(update.effective_chat.id, update.effective_user.id,
                                         permissions, today_12am + dt.timedelta(days=user_data['restrict_days']))
        except BadRequest as e:
            print(e)


def input_url2download_url(input_url: str):
    global freepik_client
    if 'freepik' in input_url:
        return freepik_client.get_download_url(input_url)
    # if 'flaticon' in input_url:
    #     return flaticon_input_url2download_url(input_url)
    raise InvalidURLError


def effective_username(update: Update):
    return update.effective_user.username if update.effective_user.username else update.effective_user.id


def url_handler(update: Update, ctx: CallbackContext):
    user_data = ctx.bot_data['users'].setdefault(effective_username(update), default_user())
    if user_data['role'] == 'regular' and ctx.bot_data.get('allow_members_only'):
        update.message.delete()
        return
    input_url = update.message.text
    # print('bot_data =', ctx.bot_data)
    print(f'url_handler(user={effective_username(update)}, url={input_url})')
    if user_data['uses'] > 0:
        download_url_sent = False
        try:
            download_url = input_url2download_url(input_url)
            try:
                update.message.reply_text(
                    'To download the file, use the button below',
                    reply_markup=InlineKeyboardMarkup.from_button(InlineKeyboardButton('Download', url=download_url)))
            except NetworkError:  # After some time idle this may happen
                update.message.reply_text(
                    'To download the file, use the button below',
                    reply_markup=InlineKeyboardMarkup.from_button(InlineKeyboardButton('Download', url=download_url)))
            download_url_sent = True
        except InvalidURLError as e:
            update.message.reply_text('This is not a valid url')
            print(e)
        except Exception as e:
            update.message.reply_text('Something went wrong with the request')
            print(e)
        if download_url_sent:
            user_data['uses'] -= 1
    else:
        update.message.delete()
    restrict_if_necessary(update, ctx)
    # print('bot_data =', ctx.bot_data)
    # print('default_user =', default_user())


def default_user(role: str = 'regular'):
    user_data = roles[role].copy()
    user_data['role'] = role
    today_12am = dt.datetime.now(DEFAULT_TZINFO).replace(hour=0, minute=0, second=0, microsecond=0)
    user_data['unrestrict_date'] = (today_12am + dt.timedelta(days=user_data['restrict_days'])).isoformat()
    return user_data.copy()


def unrestrict_everyone_necessary(ctx: CallbackContext):
    now = dt.datetime.now(DEFAULT_TZINFO)
    for username, user_data in ctx.bot_data['users'].items():
        if now >= dt.datetime.fromisoformat(user_data['unrestrict_date']):
            for k, v in default_user(user_data['role']).items():
                user_data[k] = v


def simulate_activity(ctx: CallbackContext):
    a = 0
    for i in range(19999999):
        a = i * 5 + 4


def allow_members_only_handler(update: Update, ctx: CallbackContext):
    ctx.bot_data['allow_members_only'] = True


def allow_all_handler(update: Update, ctx: CallbackContext):
    ctx.bot_data['allow_members_only'] = False


def main():
    global freepik_client
    if not os.path.exists('session.pickle'):
        print('creating new session')
        if freepik_client.sign_in():
            with open('session.pickle', 'wb') as file:
                pickle.dump(freepik_client.session, file)
    else:
        print('loading cached session')
        with open('session.pickle', 'rb') as file:
            freepik_client.session = pickle.load(file)
    defaults = Defaults(tzinfo=DEFAULT_TZINFO)
    persistence = PostgresPersistence(os.environ['DATABASE_URL'].replace('postgres://', 'postgresql://'))  # PicklePersistence('persistence.pickle')
    updater = Updater(token=os.environ['TELEGRAM_TOKEN'], use_context=True, persistence=persistence, defaults=defaults)
    dispatcher: Dispatcher = updater.dispatcher
    dispatcher.bot_data.setdefault('users', dict())

    logging.info(dispatcher.bot_data)
    logging.info(dispatcher.user_data)
    logging.info(dispatcher.chat_data)

    jq: JobQueue = dispatcher.job_queue
    jq.run_once(unrestrict_everyone_necessary, 1)
    jq.run_daily(unrestrict_everyone_necessary, dt.time(0, 0, 0, 0))
    jq.run_repeating(simulate_activity, interval=dt.timedelta(minutes=20))
    # jq.run_repeating(lambda ctx: print('bot_data =', ctx.bot_data), interval=dt.timedelta(seconds=5))  # for debug
    jq.start()

    admin_usernames = os.environ['ADMIN_USERNAMES'].split(' ')
    dispatcher.bot_data['admin_usernames'] = admin_usernames
    dispatcher.bot.set_my_commands([
        ('/set_role', 'assigns a role to user(s), usage: /set_role role username'),
        ('/roles_list', 'prints all roles and their perks'),
        ('/members_list', 'lists all members in the format role - username'),
        ('/allow_members_only', 'only lets members (bronze, silver, gold and diamond users) to send links'),
        ('/allow_all', 'allows all users to send links but maintaining their corresponding restrictions timings'),
    ])

    only_admins = Filters.user(username=admin_usernames)
    regular_users = ~only_admins
    private_chat = Filters.chat_type.private
    group_chat = Filters.chat_type.groups
    has_url = Filters.regex(r'^https?://')

    handlers = [
        MessageHandler(private_chat & regular_users, inline_handler('You are not an admin')),

        CommandHandler('start', inline_handler('start'), filters=private_chat & only_admins),
        CommandHandler('set_role', set_role_handler, filters=private_chat & only_admins, pass_args=True),
        CommandHandler('roles_list', roles_list_handler, filters=private_chat & only_admins, pass_args=True),
        CommandHandler('members_list', members_list_handler, filters=private_chat & only_admins, pass_args=True),
        CommandHandler('allow_members_only', allow_members_only_handler, filters=private_chat & only_admins),
        CommandHandler('allow_all', allow_all_handler, filters=private_chat & only_admins),

        MessageHandler(group_chat & Filters.forwarded, lambda upd, ctx: upd.message.delete()),
        MessageHandler(group_chat & has_url, url_handler),
        MessageHandler(group_chat & ~has_url & ~only_admins, lambda upd, ctx: upd.message.delete()),

        MessageHandler(Filters.all, lambda upd, ctx: print('unhandled message:', upd.message.text)),
    ]

    for handler in handlers:
        dispatcher.add_handler(handler)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
