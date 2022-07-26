"""Price oracle testing.

Tests are performed using BNB Chain mainnet fork and Ganache.

To run tests in this module:

.. code-block:: shell

    export BNB_CHAIN_JSON_RPC="https://bsc-dataseed.binance.org/"
    pytest -k test_price_oracle

"""
import datetime
import os
from decimal import Decimal

import pytest
from web3 import HTTPProvider, Web3
from web3.middleware import geth_poa_middleware

from eth_defi.event_reader.fast_json_rpc import patch_web3
from eth_defi.event_reader.web3factory import TunedWeb3Factory
from eth_defi.event_reader.web3worker import create_thread_pool_executor
from eth_defi.price_oracle.oracle import PriceOracle, time_weighted_average_price, NotEnoughData, DataTooOld, \
    DataPeriodTooShort
from eth_defi.uniswap_v2.oracle import update_price_oracle_with_sync_events, \
    update_price_oracle_with_sync_events_single_thread
from eth_defi.uniswap_v2.pair import fetch_pair_details


@pytest.fixture
def web3_factory() -> TunedWeb3Factory:
    """Set up a Web3 connection generation factury """
    # https://web3py.readthedocs.io/en/latest/web3.eth.account.html#read-a-private-key-from-an-environment-variable
    return TunedWeb3Factory(os.environ["BNB_CHAIN_JSON_RPC"])


@pytest.fixture
def web3() -> Web3:
    """Set up a Web3 connection generation factury """
    # https://web3py.readthedocs.io/en/latest/web3.eth.account.html#read-a-private-key-from-an-environment-variable
    web3 = Web3(HTTPProvider(os.environ["BNB_CHAIN_JSON_RPC"]))
    web3.middleware_onion.clear()
    web3.middleware_onion.inject(geth_poa_middleware, layer=0)
    return web3


@pytest.fixture
def bnb_busd_address():
    """https://tradingstrategy.ai/trading-view/binance/pancakeswap-v2/bnb-busd"""
    return "0x58F876857a02D6762E0101bb5C46A8c1ED44Dc16"


def test_oracle_no_data():
    """Price oracle cannot give price if there is no data."""

    oracle = PriceOracle(time_weighted_average_price)
    with pytest.raises(NotEnoughData):
        oracle.calculate_price()


def test_oracle_simple():
    """Calculate price over manually entered data."""

    price_data = {
        datetime.datetime(2021, 1, 1): Decimal(100),
        datetime.datetime(2021, 1, 2): Decimal(150),
        datetime.datetime(2021, 1, 3): Decimal(120),
    }

    oracle = PriceOracle(
        time_weighted_average_price,
        min_entries=1,
        max_age=PriceOracle.ANY_AGE,
    )

    oracle.feed_simple_data(price_data)

    # Heap is sorted oldest event first
    # Heap is sorted oldest event first
    assert oracle.get_newest().timestamp == datetime.datetime(2021, 1, 3)
    assert oracle.get_oldest().timestamp == datetime.datetime(2021, 1, 1)

    price = oracle.calculate_price()
    assert price == pytest.approx(Decimal("123.3333333333333333333333333"))


def test_oracle_feed_data_reverse():
    """Oracle heap is sorted the same even if we feed data in the reverse order."""

    price_data = {
        datetime.datetime(2021, 1, 3): Decimal(100),
        datetime.datetime(2021, 1, 2): Decimal(150),
        datetime.datetime(2021, 1, 1): Decimal(120),
    }

    oracle = PriceOracle(
        time_weighted_average_price,
    )

    oracle.feed_simple_data(price_data)

    # Heap is sorted oldest event first
    assert oracle.get_newest().timestamp == datetime.datetime(2021, 1, 3)
    assert oracle.get_oldest().timestamp == datetime.datetime(2021, 1, 1)


def test_oracle_too_old():
    """Price data is stale for real time."""

    price_data = {
        datetime.datetime(2021, 1, 1): Decimal(100),
        datetime.datetime(2021, 1, 2): Decimal(150),
        datetime.datetime(2021, 1, 3): Decimal(120),
    }

    oracle = PriceOracle(
        time_weighted_average_price,
        min_entries=1,
        max_age=datetime.timedelta(days=1),
    )

    oracle.feed_simple_data(price_data)

    with pytest.raises(DataTooOld):
        oracle.calculate_price()


def test_too_narrow_time_window():
    """We have data only over very short, manipulable, time window."""

    # Data for one second
    price_data = {
        datetime.datetime(2021, 1, 1): Decimal(100),
        datetime.datetime(2021, 1, 1, 0, 0, 1): Decimal(150),
    }

    oracle = PriceOracle(
        time_weighted_average_price,
        min_entries=1,
        max_age=datetime.timedelta(days=1),
    )

    oracle.feed_simple_data(price_data)

    with pytest.raises(DataPeriodTooShort):
        oracle.calculate_price()


pytest.mark.skipif(
    os.environ.get("BNB_CHAIN_JSON_RPC") is None,
    reason="Set BNB_CHAIN_JSON_RPC environment variable to Binance Smart Chain node to run this test",
)
def test_bnb_busd_price(web3, bnb_busd_address):
    """Calculate historical BNB price from PancakeSwap pool."""

    # Randomly chosen block range.
    # 100 blocks * 3 sec / block = ~300 seconds
    start_block = 14_000_000
    end_block = 14_000_100

    pair_details = fetch_pair_details(web3, bnb_busd_address)
    assert pair_details.token0.symbol == "WBNB"
    assert pair_details.token1.symbol == "BUSD"

    oracle = PriceOracle(
        time_weighted_average_price,
        max_age=PriceOracle.ANY_AGE,  # We are dealing with historical data
    )

    update_price_oracle_with_sync_events_single_thread(
        oracle,
        web3,
        bnb_busd_address,
        start_block,
        end_block
    )

    oldest = oracle.get_oldest()
    assert oldest.block_number == 14_000_000
    assert oldest.timestamp == datetime.datetime(2022, 1, 2, 1, 18, 40)
    assert oldest.price == 1000

    newest = oracle.get_newest()
    assert newest.block_number == 14_000_100
    assert newest.timestamp == datetime.datetime(2022, 1, 2, 1, 23, 40)
    assert newest.price == 1000

    # We have 6000 swaps for the duration
    assert len(oracle.buffer) == 5996
    assert oracle.get_buffer_duration() == datetime.timedelta(seconds=300)

    assert oracle.price()







