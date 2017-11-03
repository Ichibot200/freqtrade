import logging
from datetime import timedelta
from typing import Callable, Any

import arrow
from sqlalchemy import and_, func, text
from telegram import ParseMode, Bot, Update
from telegram.error import NetworkError
from telegram.ext import CommandHandler, Updater

from freqtrade import exchange
from freqtrade.misc import get_state, State, update_state
from freqtrade.persistence import Trade

# Remove noisy log messages
logging.getLogger('requests.packages.urllib3').setLevel(logging.INFO)
logging.getLogger('telegram').setLevel(logging.INFO)
logger = logging.getLogger(__name__)

_updater: Updater = None
_CONF = {}


def init(config: dict) -> None:
    """
    Initializes this module with the given config,
    registers all known command handlers
    and starts polling for message updates
    :param config: config to use
    :return: None
    """
    global _updater

    _CONF.update(config)
    if not is_enabled():
        return

    _updater = Updater(token=config['telegram']['token'], workers=0)

    # Register command handler and start telegram message polling
    handles = [
        CommandHandler('status', _status),
        CommandHandler('profit', _profit),
        CommandHandler('balance', _balance),
        CommandHandler('start', _start),
        CommandHandler('stop', _stop),
        CommandHandler('forcesell', _forcesell),
        CommandHandler('performance', _performance),
        CommandHandler('help', _help),
    ]
    for handle in handles:
        _updater.dispatcher.add_handler(handle)
    _updater.start_polling(
        clean=True,
        bootstrap_retries=3,
        timeout=30,
        read_latency=60,
    )
    logger.info(
        'rpc.telegram is listening for following commands: %s',
        [h.command for h in handles]
    )


def cleanup() -> None:
    """
    Stops all running telegram threads.
    :return: None
    """
    if not is_enabled():
        return
    _updater.stop()


def is_enabled() -> bool:
    """
    Returns True if the telegram module is activated, False otherwise
    """
    return bool(_CONF['telegram'].get('enabled', False))


def authorized_only(command_handler: Callable[[Bot, Update], None]) -> Callable[..., Any]:
    """
    Decorator to check if the message comes from the correct chat_id
    :param command_handler: Telegram CommandHandler
    :return: decorated function
    """
    def wrapper(*args, **kwargs):
        bot, update = kwargs.get('bot') or args[0], kwargs.get('update') or args[1]

        if not isinstance(bot, Bot) or not isinstance(update, Update):
            raise ValueError('Received invalid Arguments: {}'.format(*args))

        chat_id = int(_CONF['telegram']['chat_id'])
        if int(update.message.chat_id) == chat_id:
            logger.info('Executing handler: %s for chat_id: %s', command_handler.__name__, chat_id)
            return command_handler(*args, **kwargs)
        else:
            logger.info('Rejected unauthorized message from: %s', update.message.chat_id)
    return wrapper


@authorized_only
def _status(bot: Bot, update: Update) -> None:
    """
    Handler for /status.
    Returns the current TradeThread status
    :param bot: telegram bot
    :param update: message update
    :return: None
    """
    # Fetch open trade
    trades = Trade.query.filter(Trade.is_open.is_(True)).all()
    if get_state() != State.RUNNING:
        send_msg('*Status:* `trader is not running`', bot=bot)
    elif not trades:
        send_msg('*Status:* `no active trade`', bot=bot)
    else:
        for trade in trades:
            order = exchange.get_order(trade.open_order_id)
            # calculate profit and send message to user
            current_rate = exchange.get_ticker(trade.pair)['bid']
            current_profit = trade.calc_profit(current_rate)
            fmt_close_profit = '{:.2f}%'.format(
                round(trade.close_profit * 100, 2)
            ) if trade.close_profit else None
            message = """
*Trade ID:* `{trade_id}`
*Current Pair:* [{pair}]({market_url})
*Open Since:* `{date}`
*Amount:* `{amount}`
*Open Rate:* `{open_rate}`
*Close Rate:* `{close_rate}`
*Current Rate:* `{current_rate}`
*Close Profit:* `{close_profit}`
*Current Profit:* `{current_profit:.2f}%`
*Open Order:* `{open_order}`
            """.format(
                trade_id=trade.id,
                pair=trade.pair,
                market_url=exchange.get_pair_detail_url(trade.pair),
                date=arrow.get(trade.open_date).humanize(),
                open_rate=trade.open_rate,
                close_rate=trade.close_rate,
                current_rate=current_rate,
                amount=round(trade.amount, 8),
                close_profit=fmt_close_profit,
                current_profit=round(current_profit * 100, 2),
                open_order='{} ({})'.format(
                    order['remaining'], order['type']
                ) if order else None,
            )
            send_msg(message, bot=bot)


@authorized_only
def _profit(bot: Bot, update: Update) -> None:
    """
    Handler for /profit.
    Returns a cumulative profit statistics.
    :param bot: telegram bot
    :param update: message update
    :return: None
    """
    trades = Trade.query.order_by(Trade.id).all()

    profit_amounts = []
    profits = []
    durations = []
    for trade in trades:
        if not trade.open_rate:
            continue
        if trade.close_date:
            durations.append((trade.close_date - trade.open_date).total_seconds())
        if trade.close_profit:
            profit = trade.close_profit
        else:
            # Get current rate
            current_rate = exchange.get_ticker(trade.pair)['bid']
            profit = trade.calc_profit(current_rate)

        profit_amounts.append(profit * trade.stake_amount)
        profits.append(profit)

    best_pair = Trade.session.query(Trade.pair, func.sum(Trade.close_profit).label('profit_sum')) \
        .filter(Trade.is_open.is_(False)) \
        .group_by(Trade.pair) \
        .order_by(text('profit_sum DESC')) \
        .first()

    if not best_pair:
        send_msg('*Status:* `no closed trade`', bot=bot)
        return

    bp_pair, bp_rate = best_pair
    markdown_msg = """
*ROI:* `{profit_btc:.6f} ({profit:.2f}%)`
*Trade Count:* `{trade_count}`
*First Trade opened:* `{first_trade_date}`
*Latest Trade opened:* `{latest_trade_date}`
*Avg. Duration:* `{avg_duration}`
*Best Performing:* `{best_pair}: {best_rate:.2f}%`
{dry_run_info}
    """.format(
        profit_btc=round(sum(profit_amounts), 8),
        profit=round(sum(profits) * 100, 2),
        trade_count=len(trades),
        first_trade_date=arrow.get(trades[0].open_date).humanize(),
        latest_trade_date=arrow.get(trades[-1].open_date).humanize(),
        avg_duration=str(timedelta(seconds=sum(durations) / float(len(durations)))).split('.')[0],
        best_pair=bp_pair,
        best_rate=round(bp_rate * 100, 2),
        dry_run_info='\n*NOTE:* These values are mocked because *dry_run* is enabled!'
        if _CONF['dry_run'] else ''
    )
    send_msg(markdown_msg, bot=bot)


@authorized_only
def _balance(bot: Bot, update: Update) -> None:
    """
    Handler for /balance
    Returns current account balance per crypto
    """
    output = ""
    balances = exchange.get_balances()
    for currency in balances:
        if not currency['Balance'] and not currency['Available'] and not currency['Pending']:
            continue
        output += """*Currency*: {Currency}
*Available*: {Available}
*Balance*: {Balance}
*Pending*: {Pending}

""".format(**currency)

    send_msg(output)


@authorized_only
def _start(bot: Bot, update: Update) -> None:
    """
    Handler for /start.
    Starts TradeThread
    :param bot: telegram bot
    :param update: message update
    :return: None
    """
    if get_state() == State.RUNNING:
        send_msg('*Status:* `already running`', bot=bot)
    else:
        update_state(State.RUNNING)


@authorized_only
def _stop(bot: Bot, update: Update) -> None:
    """
    Handler for /stop.
    Stops TradeThread
    :param bot: telegram bot
    :param update: message update
    :return: None
    """
    if get_state() == State.RUNNING:
        send_msg('`Stopping trader ...`', bot=bot)
        update_state(State.STOPPED)
    else:
        send_msg('*Status:* `already stopped`', bot=bot)


@authorized_only
def _forcesell(bot: Bot, update: Update) -> None:
    """
    Handler for /forcesell <id>.
    Sells the given trade at current price
    :param bot: telegram bot
    :param update: message update
    :return: None
    """
    if get_state() != State.RUNNING:
        send_msg('`trader is not running`', bot=bot)
        return

    try:
        trade_id = int(update.message.text
                       .replace('/forcesell', '')
                       .strip())
        # Query for trade
        trade = Trade.query.filter(and_(
            Trade.id == trade_id,
            Trade.is_open.is_(True)
        )).first()
        if not trade:
            send_msg('There is no open trade with ID: `{}`'.format(trade_id))
            return
        # Get current rate
        current_rate = exchange.get_ticker(trade.pair)['bid']
        from freqtrade.main import execute_sell
        execute_sell(trade, current_rate)

    except ValueError:
        send_msg('Invalid argument. Usage: `/forcesell <trade_id>`')
        logger.warning('/forcesell: Invalid argument received')


@authorized_only
def _performance(bot: Bot, update: Update) -> None:
    """
    Handler for /performance.
    Shows a performance statistic from finished trades
    :param bot: telegram bot
    :param update: message update
    :return: None
    """
    if get_state() != State.RUNNING:
        send_msg('`trader is not running`', bot=bot)
        return

    pair_rates = Trade.session.query(Trade.pair, func.sum(Trade.close_profit).label('profit_sum')) \
        .filter(Trade.is_open.is_(False)) \
        .group_by(Trade.pair) \
        .order_by(text('profit_sum DESC')) \
        .all()

    stats = '\n'.join('{index}. <code>{pair}\t{profit:.2f}%</code>'.format(
        index=i + 1,
        pair=pair,
        profit=round(rate * 100, 2)
    ) for i, (pair, rate) in enumerate(pair_rates))

    message = '<b>Performance:</b>\n{}\n{}'.format(
        stats,
        '<b>NOTE:</b> These values are mocked because <b>dry_run</b> is enabled.'
        if _CONF['dry_run'] else ''
    )
    logger.debug(message)
    send_msg(message, parse_mode=ParseMode.HTML)


@authorized_only
def _help(bot: Bot, update: Update) -> None:
    """
    Handler for /help.
    Show commands of the bot
    :param bot: telegram bot
    :param update: message update
    :return: None
    """
    message = """
*/start:* `Starts the trader`
*/stop:* `Stops the trader`
*/status:* `Lists all open trades`
*/profit:* `Lists cumulative profit from all finished trades`
*/forcesell <trade_id>:* `Instantly sells the given trade, regardless of profit`
*/performance:* `Show performance of each finished trade grouped by pair`
*/balance:* `Show account balance per currency`
*/help:* `This help message`
    """
    send_msg(message, bot=bot)


def send_msg(msg: str, bot: Bot = None, parse_mode: ParseMode = ParseMode.MARKDOWN) -> None:
    """
    Send given markdown message
    :param msg: message
    :param bot: alternative bot
    :param parse_mode: telegram parse mode
    :return: None
    """
    if not is_enabled():
        return
    try:
        bot = bot or _updater.bot
        try:
            bot.send_message(_CONF['telegram']['chat_id'], msg, parse_mode=parse_mode)
        except NetworkError as error:
            # Sometimes the telegram server resets the current connection,
            # if this is the case we send the message again.
            logger.warning(
                'Got Telegram NetworkError: %s! Trying one more time.',
                error.message
            )
            bot.send_message(_CONF['telegram']['chat_id'], msg, parse_mode=parse_mode)
    except Exception:
        logger.exception('Exception occurred within Telegram API')
