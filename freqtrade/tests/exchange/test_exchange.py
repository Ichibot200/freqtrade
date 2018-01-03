# pragma pylint: disable=missing-docstring,C0103
from unittest.mock import MagicMock
from requests.exceptions import RequestException
from random import randint
import logging
import pytest

from freqtrade import OperationalException
from freqtrade.exchange import init, validate_pairs, buy, sell, get_balance, get_balances, \
    get_ticker, cancel_order, get_name, get_fee


def test_init(default_conf, mocker, caplog):
    mocker.patch('freqtrade.exchange.validate_pairs',
                 side_effect=lambda s: True)
    init(config=default_conf)
    assert ('freqtrade.exchange',
            logging.INFO,
            'Instance is running with dry_run enabled'
            ) in caplog.record_tuples


def test_init_exception(default_conf, mocker):
    default_conf['exchange']['name'] = 'wrong_exchange_name'

    with pytest.raises(
            OperationalException,
            match='Exchange {} is not supported'.format(default_conf['exchange']['name'])):
        init(config=default_conf)


def test_validate_pairs(default_conf, mocker):
    api_mock = MagicMock()
    api_mock.get_markets = MagicMock(return_value=[
        'BTC_ETH', 'BTC_TKN', 'BTC_TRST', 'BTC_SWT', 'BTC_BCC',
    ])
    mocker.patch('freqtrade.exchange._API', api_mock)
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)
    validate_pairs(default_conf['exchange']['pair_whitelist'])


def test_validate_pairs_not_available(default_conf, mocker):
    api_mock = MagicMock()
    api_mock.get_markets = MagicMock(return_value=[])
    mocker.patch('freqtrade.exchange._API', api_mock)
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)
    with pytest.raises(OperationalException, match=r'not available'):
        validate_pairs(default_conf['exchange']['pair_whitelist'])


def test_validate_pairs_not_compatible(default_conf, mocker):
    api_mock = MagicMock()
    api_mock.get_markets = MagicMock(
        return_value=['BTC_ETH', 'BTC_TKN', 'BTC_TRST', 'BTC_SWT'])
    default_conf['stake_currency'] = 'ETH'
    mocker.patch('freqtrade.exchange._API', api_mock)
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)
    with pytest.raises(OperationalException, match=r'not compatible'):
        validate_pairs(default_conf['exchange']['pair_whitelist'])


def test_validate_pairs_exception(default_conf, mocker, caplog):
    api_mock = MagicMock()
    api_mock.get_markets = MagicMock(side_effect=RequestException())
    mocker.patch('freqtrade.exchange._API', api_mock)

    # with pytest.raises(RequestException, match=r'Unable to validate pairs'):
    validate_pairs(default_conf['exchange']['pair_whitelist'])
    assert ('freqtrade.exchange',
            logging.WARNING,
            'Unable to validate pairs (assuming they are correct). Reason: '
            ) in caplog.record_tuples


def test_buy_dry_run(default_conf, mocker):
    default_conf['dry_run'] = True
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert 'dry_run_buy_' in buy(pair='BTC_ETH', rate=200, amount=1)


def test_buy_prod(default_conf, mocker):
    api_mock = MagicMock()
    api_mock.buy = MagicMock(
        return_value='dry_run_buy_{}'.format(randint(0, 10**6)))
    mocker.patch('freqtrade.exchange._API', api_mock)

    default_conf['dry_run'] = False
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert 'dry_run_buy_' in buy(pair='BTC_ETH', rate=200, amount=1)


def test_sell_dry_run(default_conf, mocker):
    default_conf['dry_run'] = True
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert 'dry_run_sell_' in sell(pair='BTC_ETH', rate=200, amount=1)


def test_sell_prod(default_conf, mocker):
    api_mock = MagicMock()
    api_mock.sell = MagicMock(
        return_value='dry_run_sell_{}'.format(randint(0, 10**6)))
    mocker.patch('freqtrade.exchange._API', api_mock)

    default_conf['dry_run'] = False
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert 'dry_run_sell_' in sell(pair='BTC_ETH', rate=200, amount=1)


def test_get_balance_dry_run(default_conf, mocker):
    default_conf['dry_run'] = True
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert get_balance(currency='BTC') == 999.9


def test_get_balance_prod(default_conf, mocker):
    api_mock = MagicMock()
    api_mock.get_balance = MagicMock(return_value=123.4)
    mocker.patch('freqtrade.exchange._API', api_mock)

    default_conf['dry_run'] = False
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert get_balance(currency='BTC') == 123.4


def test_get_balances_dry_run(default_conf, mocker):
    default_conf['dry_run'] = True
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert get_balances() == []


def test_get_balances_prod(default_conf, mocker):
    balance_item = {
        'Currency': '1ST',
        'Balance': 10.0,
        'Available': 10.0,
        'Pending': 0.0,
        'CryptoAddress': None
    }

    api_mock = MagicMock()
    api_mock.get_balances = MagicMock(
        return_value=[balance_item, balance_item, balance_item])
    mocker.patch('freqtrade.exchange._API', api_mock)

    default_conf['dry_run'] = False
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert len(get_balances()) == 3
    assert get_balances()[0]['Currency'] == '1ST'
    assert get_balances()[0]['Balance'] == 10.0
    assert get_balances()[0]['Available'] == 10.0
    assert get_balances()[0]['Pending'] == 0.0


def test_get_ticker(mocker, ticker):

    api_mock = MagicMock()
    api_mock.get_ticker = MagicMock(return_value=ticker())
    mocker.patch('freqtrade.exchange._API', api_mock)

    ticker = get_ticker(pair='BTC_ETH')
    assert ticker['bid'] == 0.00001098
    assert ticker['ask'] == 0.00001099

    # if not caching the result we should get the same ticker
    ticker = get_ticker(pair='BTC_ETH', refresh=False)
    assert ticker['bid'] == 0.00001098
    assert ticker['ask'] == 0.00001099

    # change the ticker
    api_mock.get_ticker = MagicMock(return_value={"bid": 0, "ask": 1})
    mocker.patch('freqtrade.exchange._API', api_mock)

    ticker = get_ticker(pair='BTC_ETH', refresh=True)
    assert ticker['bid'] == 0
    assert ticker['ask'] == 1


def test_cancel_order_dry_run(default_conf, mocker):
    default_conf['dry_run'] = True
    mocker.patch.dict('freqtrade.exchange._CONF', default_conf)

    assert cancel_order(order_id='123') is None


def test_get_name(default_conf, mocker):
    mocker.patch('freqtrade.exchange.validate_pairs',
                 side_effect=lambda s: True)
    default_conf['exchange']['name'] = 'bittrex'
    init(default_conf)

    assert get_name() == 'Bittrex'


def test_get_fee(default_conf, mocker):
    mocker.patch('freqtrade.exchange.validate_pairs',
                 side_effect=lambda s: True)
    init(default_conf)

    assert get_fee() == 0.0025
