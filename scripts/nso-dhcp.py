#!/usr/bin/env python3

"""
About this script:
1. Get the information on site subnet,
2. reserve new pool for site dhcp server
3. Configure router as dhcp server
The script is run from the environment where NSO is installed
"""


import ncs
import requests
import json

device_name = "router1-ams"

site = device_name.split("-")[1]
print(f"site: {site}")
pool_name = f"{site}-office-dhcp"


netbox = "NETBOX_IP_ADDRESS:PORT/api/"
token = "0123456789abcdef0123456789abcdef01234567"
headers = {
    'Authorization': f'Token {token}',
    'Content-Type': 'application/json',
}


def get_subnet():
    url = f"{netbox}ipam/prefixes/?site={site}"
    response = requests.request("GET", url, headers=headers, data={}).json()
    subnet = response["results"][0]["prefix"]
    print(f"subnet: {subnet}")
    return subnet


def reserve_dhcp_pool(subnet):
    start_address = subnet.replace(".0/24", ".129/24")
    end_address = subnet.replace(".0/24", ".254/24")

    url = f"{netbox}ipam/ip-ranges/"
    payload = json.dumps({
        "start_address": start_address,
        "end_address": end_address,
        "description": pool_name
    })
    return requests.request("POST", url, headers=headers, data=payload)


def configure_device(subnet):
    with ncs.maapi.single_write_trans('admin', 'python', groups=['ncsadmin']) as t:
        network_number = subnet.replace(".0/24", ".128")
        default_router = subnet.replace(".0/24", ".1")

        root = ncs.maagic.get_root(t)
        device_cdb = root.devices.device[device_name]

        print("Syncing configuration...")
        output = device_cdb.sync_from()
        print(f"Result: {output.result}")
        if not output.result:
            print(f"Error: {output.info}")
        device_cdb.config.ios__ip.dhcp.pool.create(pool_name)
        device_cdb.config.ios__ip.dhcp.pool[pool_name].default_router.create(default_router)
        device_cdb.config.ios__ip.dhcp.pool[pool_name].network.network_number = network_number
        device_cdb.config.ios__ip.dhcp.pool[pool_name].network.mask = "255.255.255.128"
        params = t.get_params()
        params.dry_run_native()
        result = t.apply_params(True, params)
        print(f"Configuration applied on device {device_name}: ")
        print(result['device'][device_name])
        t.apply_params(True, t.get_params())


def main():
    subnet = get_subnet()
    reserve_dhcp_pool(subnet)
    configure_device(subnet)


if __name__ == "__main__":
    main()