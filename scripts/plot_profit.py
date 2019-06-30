#!/usr/bin/env python3
"""
Script to display profits

Use `python plot_profit.py --help` to display the command line arguments
"""
import logging
import sys
from typing import Any, Dict, List

from freqtrade.arguments import ARGS_PLOT_PROFIT, Arguments
from freqtrade.optimize import setup_configuration
from freqtrade.plot.plotting import FTPlots, generate_profit_graph
from freqtrade.state import RunMode

logger = logging.getLogger(__name__)


def plot_profit(config: Dict[str, Any]) -> None:
    """
    Plots the total profit for all pairs.
    Note, the profit calculation isn't realistic.
    But should be somewhat proportional, and therefor useful
    in helping out to find a good algorithm.
    """
    plot = FTPlots(config)

    trades = plot.trades[plot.trades['pair'].isin(plot.pairs)]

    # Create an average close price of all the pairs that were involved.
    # this could be useful to gauge the overall market trend
    generate_profit_graph(plot.pairs, plot.tickers, trades)


def plot_parse_args(args: List[str]) -> Dict[str, Any]:
    """
    Parse args passed to the script
    :param args: Cli arguments
    :return: args: Array with all arguments
    """
    arguments = Arguments(args, 'Graph profits')
    arguments.build_args(optionlist=ARGS_PLOT_PROFIT)

    parsed_args = arguments.parse_args()

    # Load the configuration
    config = setup_configuration(parsed_args, RunMode.OTHER)
    return config


def main(sysargv: List[str]) -> None:
    """
    This function will initiate the bot and start the trading loop.
    :return: None
    """
    logger.info('Starting Plot Dataframe')
    plot_profit(
        plot_parse_args(sysargv)
    )


if __name__ == '__main__':
    main(sys.argv[1:])
