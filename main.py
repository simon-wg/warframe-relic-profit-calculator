import time
import json
import httpx

from tqdm import tqdm
from tqdm.asyncio import tqdm as tqdm_asyncio
from typing import Dict, Any

import asyncio

MARKET_API_ENDPOINT = "https://api.warframe.market/v1"
DROPS_API_ENDPOINT = "https://drops.warframestat.us/data"


def check_update() -> bool:
    """Check if the relic data needs to be updated

    This will return True if the data needs to be updated
    The data by default is updated every 24 hours
    """
    needs_update = False
    try:
        with open("relics.json", "r") as file:
            text = file.read()
            if text == "":
                needs_update = True
            else:
                relics = json.loads(text)
                if (
                    relics.get("timestamp")
                    and relics.get("timestamp") + 24 * 60 * 60 < time.time()
                ):
                    needs_update = True
    except FileNotFoundError:
        needs_update = True
    return needs_update


def get_relics(needs_update=False) -> bool:
    """Gets all relics from the API and saves them to a file

    The format of the file is as follows:
    {
        "relics": {
            "Lith A1 Intact": {
                "urlName": "lith_a1_relic",
                "relicName": "Lith A1 Intact",
                "rewards": [
                    {
                        "itemName": "Forma Blueprint",
                        "rarity": "Common",
                        "chance": 25.33
                    },
                    {
                        "itemName": "Paris Prime String",
                        "rarity": "Common",
                        "chance": 25.33
                    },
                    {
                        "itemName": "Paris Prime Upper Limb",
                        "rarity": "Common",
                        "chance": 25.33
                    },
                    {
                        "itemName": "Paris Prime Lower Limb",
                        "rarity": "Common",
                        "chance": 25.33
                    },
                "value": 0,
                "price": 0
                }
            }
        }
    }
    """

    url = f"{DROPS_API_ENDPOINT}/relics.json"
    try:
        with open("relics.json", "r") as file:
            text = file.read()
            if text == "":
                needs_update = True
    except FileNotFoundError:
        needs_update = True
    if needs_update:
        with httpx.Client() as client:
            response = client.get(url)
            relic_json = response.json()
            relics = {}
            for relic in tqdm(relic_json.get("relics"), desc="Parsing Relics..."):
                relic_name = (
                    f"{relic.get('tier')} {relic.get('relicName')} {relic.get('state')}"
                )
                relic_url_name = (
                    f"{relic.get('tier')}_{relic.get('relicName')}_relic".lower()
                )
                rewards = relic.get("rewards")
                relics[relic_name] = {
                    "urlName": relic_url_name,
                    "relicName": relic_name,
                    "rewards": rewards,
                    "value": 0,
                    "price": 0,
                }
            relic_json["relics"] = relics
            relic_json["timestamp"] = time.time()
        with open("relics.json", "w") as file:
            relic_json["timestamp"] = time.time()
            file.write(json.dumps(relic_json))


def get_items(needs_update=False) -> bool:
    """Parse the relics and get all items from them

    This will save the items to a file later to be used for calculating most valuable relics
    The format of the file is as follows:
    {
        "ItemName": {
            "rarity": "Common",
            "chance": 25.33,
            "urlName": "forma_blueprint",
            "itemName": "Forma Blueprint"
        }
    }
    """

    relics = {}
    with open("relics.json", "r") as file:
        relics = json.loads(file.read())

    try:
        with open("items.json", "r") as file:
            text = file.read()
            if text == "":
                needs_update = True
    except FileNotFoundError:
        needs_update = True

    if needs_update:
        items = {}
        relics = relics.get("relics")
        for relic in tqdm(relics, desc="Parsing Items from Relics..."):
            for reward in relics[relic]["rewards"]:
                if reward["itemName"] not in items.keys():
                    items[reward["itemName"]] = {
                        "rarity": reward["rarity"],
                        "chance": reward["chance"],
                        "urlName": reward["itemName"]
                        .replace(" ", "_")
                        .lower()
                        .replace("&", "and"),
                        "itemName": reward["itemName"],
                    }
        with open("items.json", "w") as file:
            file.write(json.dumps(items))

    else:
        with open("items.json", "r") as file:
            items = json.loads(file.read())


async def get_info(
    client: httpx.AsyncClient, item: str, item_url: str, item_api_uri: str
) -> Dict[str, Any]:
    """Get all orders for an item

    This will get all orders for an item and save them to a file
    The format of the file is as follows:
    [{
        "ItemName": [{
            "quantity": 1,
            "platinum": 10,
            "order_type": "sell",
            "user": {
                "status": "offline",
                "ingame_name": "User",
                "reputation_bonus": 0,
                "reputation": 0,
                "region": "en",
                "id": "1234567890",
                "avatar": "https://cdn.warframe.market/static/avatar/1234567890.png",
                "last_seen": "2021-05-20T18:00:00.000Z"
            },
            "platform": "pc",
            "visible": True,
            "region": "en",
            "creation_date": "2021-05-20T18:00:00.000Z",
            "last_update": "2021-05-20T18:00:00.000Z",
            "subtype": "intact"}]
    }]
    """
    url = f"{MARKET_API_ENDPOINT}/items/{item_url}/{item_api_uri}"
    response = await client.get(url)
    if response.status_code == 429:
        await asyncio.sleep(1)
        return await get_info(client, item, item_url, item_api_uri)
    elif response.status_code != 200:
        print(f"Error on {item}")
        return {}
    info = response.json()
    return {item: info["payload"]}


async def get_all_info(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    item_api_uri: str,
    needs_update=False,
) -> bool:
    # Helper function to make sure we don't make too many requests at once
    async def safe_get_info(
        client: httpx.AsyncClient, item: str, item_url: str, item_api_uri: str
    ):
        async with sem:
            return await get_info(client, item, item_url, item_api_uri)

    try:
        with open(f"{item_api_uri}.json", "r") as file:
            text = file.read()
            if text == "":
                needs_update = True
    except FileNotFoundError:
        needs_update = True
    if not needs_update:
        return

    with open("items.json", "r") as file:
        items = json.loads(file.read())

    with open("relics.json", "r") as file:
        relics = json.loads(file.read())
        relics = relics["relics"]

    tasks = []

    for relic in relics.items():
        if "Intact" in relic[0]:
            tasks.append(
                safe_get_info(client, relic[0], relic[1]["urlName"], item_api_uri)
            )
    for item in items.items():
        tasks.append(safe_get_info(client, item[0], item[1]["urlName"], item_api_uri))

    results = await tqdm_asyncio.gather(
        *tasks, desc=f"Getting {item_api_uri.capitalize()}..."
    )
    with open(f"{item_api_uri}.json", "w") as file:
        file.write(json.dumps(results))


def calculate_relic_values(live: bool = False):
    with open("orders.json", "r") as file:
        orders = json.loads(file.read())

    with open("statistics.json", "r") as file:
        statistics = json.loads(file.read())

    order_dict = {}
    for order in orders:
        order_dict.update(order)

    statistics_dict = {}
    for statistic in statistics:
        statistics_dict.update(statistic)
    median_plat = {}

    # This method looks at all live orders for an item and gets the median price for that item based on all current orders
    if live:
        for item, orders in tqdm(order_dict.items(), desc="Calculating Median Plat..."):
            median_plat[item] = 0
            all_plat = []
            for order in orders["orders"]:
                if order["order_type"] == "sell":
                    all_plat.append(order["platinum"])
            all_plat.sort()
            median_plat[item] = all_plat[len(all_plat) // 2]

    # Statistics based version of calculating median plat looking at the average of the median for the last week (7 days)
    else:
        for item in tqdm(
            statistics_dict, desc="Calculating Median Plat (Statistics)..."
        ):
            median_plat[item] = 0
            all_medians = []
            item_statistics = statistics_dict[item]["statistics_closed"]["90days"]
            item_statistics.sort(key=lambda x: x["datetime"])
            all_medians = [x["median"] for x in item_statistics[0:7]]
            try:
                median_plat[item] = round(sum(all_medians) / len(all_medians), 2)
            except ZeroDivisionError:
                median_plat[item] = float("inf")

    with open("relics.json", "r") as file:
        relics = json.loads(file.read())

    new_relics = dict()

    for name, data in relics["relics"].items():
        new_relics[name] = data
        for reward in data["rewards"]:
            if reward["itemName"] in median_plat:
                new_relics[name]["value"] += (
                    median_plat[reward["itemName"]] * reward["chance"] / 100
                )
    sorted_relics = [x for x in new_relics.items()]
    sorted_relics.sort(key=lambda x: x[1]["value"], reverse=True)
    print("Top 25 Relics by value: ")
    print("------------------------")
    for relic in sorted_relics[0:25]:
        print(f"{relic[0]}: {relic[1]['value']:.2f}p")
    with open("sorted_relics.json", "w") as file:
        file.write(json.dumps(sorted_relics))

    value_divided_by_price = []
    for relic in sorted_relics:
        price = median_plat[" ".join(relic[0].split(" ")[0:2]) + " Intact"]
        value_divided_by_price.append((relic[0], round(relic[1]["value"] / price, 2)))
    value_divided_by_price.sort(key=lambda x: x[1], reverse=True)
    print("\n")
    print("Top 25 Relics by profit (EV/Price): ")
    print("------------------------")
    for relic in value_divided_by_price[0:25]:
        print(f"{relic[0]}: {relic[1]:.2f}")
    with open("profit_relics.json", "w") as file:
        file.write(json.dumps(value_divided_by_price))
    # TODO Add a list of most plat gained by refining past intact


def open_menu():
    with open("sorted_relics.json", "r") as file:
        sorted_relics = json.loads(file.read())
    with open("profit_relics.json", "r") as file:
        profit_relics = json.loads(file.read())

    def handle_mode_input() -> str:
        mode = input("Select mode:\n1. Value\n2. Profit\nq. Quit\nEnter mode: ").strip()
        if mode == "1":
            return "value"
        elif mode == "2":
            return "profit"
        elif mode == "q":
            return "quit"
        else:
            return handle_mode_input()

    def handle_relic_input() -> str:
        relic = input("Enter relic (enter list for 25 best): ")
        if relic.lower() == "list":
            return "list"
        elif relic.lower() in [x[0].lower() for x in sorted_relics]:
            return relic
        elif relic == "q":
            return "quit"
        else:
            return handle_relic_input()

    mode = ""
    while mode != "quit":
        mode = handle_mode_input()
        if mode == "quit":
            break
        relic = handle_relic_input()
        if relic == "quit":
            mode = "quit"
            break
        if mode == "value":
            for relic_data in sorted_relics:
                if relic == "list":
                    for relic_data in sorted_relics[0:25]:
                        print(f"{relic_data[0]}: {relic_data[1]['value']:.2f}p")
                    break
                if relic.lower() == relic_data[0].lower():
                    print(f"{relic_data[0]}: {relic_data[1]['value']:.2f}p")
                    break
        elif mode == "profit":
            for relic_data in profit_relics:
                if relic == "list":
                    for relic_data in profit_relics[0:25]:
                        print(f"{relic_data[0]}: {relic_data[1]:.2f}")
                    break
                if relic.lower() == relic_data[0].lower():
                    print(f"{relic_data[0]}: {relic_data[1]:.2f}")
                    break


async def main(pool_size: int):
    """Main function"""

    sem = asyncio.Semaphore(pool_size)

    needs_update = check_update()
    if needs_update:
        print("Updating Relics...")
    else:
        print("Relics are up to date! (<24 hours old)")
    get_relics(needs_update)
    get_items(needs_update)
    async with httpx.AsyncClient() as client:
        await get_all_info(client, sem, "statistics", needs_update)
        await get_all_info(client, sem, "orders", needs_update)
    calculate_relic_values()
    
    open_menu()


if __name__ == "__main__":
    POOL_SIZE = 10
    asyncio.run(main(POOL_SIZE))
