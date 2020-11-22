
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from sqlalchemy import and_, or_

from freqtrade.persistence import Trade
from freqtrade.plugins.protections import IProtection, ProtectionReturn
from freqtrade.strategy.interface import SellType


logger = logging.getLogger(__name__)


class StoplossGuard(IProtection):

    # Can globally stop the bot
    has_global_stop: bool = True
    # Can stop trading for one pair
    has_local_stop: bool = True

    def __init__(self, config: Dict[str, Any], protection_config: Dict[str, Any]) -> None:
        super().__init__(config, protection_config)

        self._lookback_period = protection_config.get('lookback_period', 60)
        self._trade_limit = protection_config.get('trade_limit', 10)
        self._stop_duration = protection_config.get('stop_duration', 60)

    def short_desc(self) -> str:
        """
        Short method description - used for startup-messages
        """
        return (f"{self.name} - Frequent Stoploss Guard, {self._trade_limit} stoplosses "
                f"within {self._lookback_period} minutes.")

    def _reason(self) -> str:
        """
        LockReason to use
        """
        return (f'{self._trade_limit} stoplosses in {self._lookback_period} min, '
                f'locking for {self._stop_duration} min.')

    def _stoploss_guard(self, date_now: datetime, pair: str = None) -> ProtectionReturn:
        """
        Evaluate recent trades
        """
        look_back_until = date_now - timedelta(minutes=self._lookback_period)
        filters = [
            Trade.is_open.is_(False),
            Trade.close_date > look_back_until,
            or_(Trade.sell_reason == SellType.STOP_LOSS.value,
                and_(Trade.sell_reason == SellType.TRAILING_STOP_LOSS.value,
                     Trade.close_profit < 0))
        ]
        if pair:
            filters.append(Trade.pair == pair)
        trades = Trade.get_trades(filters).all()

        if len(trades) > self._trade_limit:
            self.log_once(f"Trading stopped due to {self._trade_limit} "
                          f"stoplosses within {self._lookback_period} minutes.", logger.info)
            until = self.calculate_lock_end(trades, self._stop_duration)
            return True, until, self._reason()

        return False, None, None

    def global_stop(self, date_now: datetime) -> ProtectionReturn:
        """
        Stops trading (position entering) for all pairs
        This must evaluate to true for the whole period of the "cooldown period".
        :return: Tuple of [bool, until, reason].
            If true, all pairs will be locked with <reason> until <until>
        """
        return self._stoploss_guard(date_now, None)

    def stop_per_pair(self, pair: str, date_now: datetime) -> ProtectionReturn:
        """
        Stops trading (position entering) for this pair
        This must evaluate to true for the whole period of the "cooldown period".
        :return: Tuple of [bool, until, reason].
            If true, this pair will be locked with <reason> until <until>
        """
        return self._stoploss_guard(date_now, pair)
