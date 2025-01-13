""""
About this script:
1. Create a Netbox Form - collects input data in Netbox (site code, name, number of switches)
2. Creates new site
3. Selects next available IP prefix, reserves it for the site
4. DNS reservations for router and switches
5. Creates rack
6. Creates devices
7. Assigns IPs to interfaces
8. Adds devices to NSO and fetches their ssh host keys
"""

from django.utils.text import slugify
from extras.scripts import *
from dcim.choices import *
from dcim.models import Device, DeviceRole, DeviceType, Rack, Site, Interface
from ipam.models import Prefix, IPAddress

import requests
import json


class NewSiteScript(Script):
    # Here we create a Netbox form
    class Meta:
        name = "New Site"
        description = "Provision a new site"
        field_order = ['site_codename', 'site_name', 'switch_count', 'switch_model', 'router_model', 'add_to_nso']

    site_codename = StringVar(
        description="Short name of the new site"
    )
    site_name = StringVar(
        description="Full name of the new site"
    )
    switch_count = IntegerVar(
        description="Number of access switches in the site"
    )
    switch_model = ObjectVar(
        description="Switch model",
        model=DeviceType
    )
    router_model = ObjectVar(
        description="Router model",
        model=DeviceType
    )
    add_to_nso = BooleanVar(
        description="Add devices to NSO inventory"
    )

    def create_new_site(self, site_codename, site_name):
        site = Site(
            name=site_codename,
            slug=slugify(site_codename),
            description=site_name,
            status=SiteStatusChoices.STATUS_ACTIVE
        )
        site.save()
        self.log_success(f"New site {site_codename} ({site_name}) created")
        return site

    def find_next_free_mgmt_id(self):
        # We should have a management prefix allocated in Netbox before (For the demo purpose I used 172.20.0.0/16).
        # We return mgmt_id, which we will use later as 3rd octet of our IP subnet
        mgmt_prefix = Prefix.objects.get(description="Management")        
        avail_pfxs = mgmt_prefix.get_first_available_prefix()
        self.log_info(f"First available prefix: {avail_pfxs}")
        mgmt_id = int(str(avail_pfxs).split("/")[0].split(".")[2])
        self.log_info("Selected site ID: %d" % mgmt_id)
        return mgmt_id

    def create_mgmt_prefix(self, site, mgmt_id):
        # creating /24 subnet
        prefix_cidr = "172.20.%d.0/24" % mgmt_id
        prefix = Prefix(
            prefix=prefix_cidr,
            description=f"{site.description} subnet",
        )
        prefix.save()
        site.prefixes.set([prefix])
        prefix.save()
        self.log_success(f"Subnet {prefix} assigned to the site")
        return prefix

    def dns_allocations(self, site, mgmt_id, number_of_switches):
        router_name = f"router1-{site.slug}"
        router_domain = f"{router_name}.lab"
        router_ip = f"172.20.{mgmt_id}.1/24"
        r1_mgmt_ip = IPAddress(
            address=router_ip,
            dns_name=router_domain,
            description=f"{site.description} router management IP",
        )
        r1_mgmt_ip.save()
        dns_results = {
            "router": {
                "ip": router_ip,
                "name": router_name,
                "domain": router_domain,
            }
        }
        self.log_info(f"IP and domain reserved for site router: {router_ip} - {router_name}")

        # switches
        for i in range(number_of_switches):
            switch_name = f"switch{str(i + 1)}-{site.slug}"
            switch_domain = f"{switch_name}.lab"
            switch_ip = f"172.20.{mgmt_id}.{str(i + 2)}/24"
            sw_num = f"switch{str(i + 1)}"
            sw_mgmt_ip = IPAddress(
                address=switch_ip,
                dns_name=switch_domain,
                description=f"{site.description} {sw_num} management IP",
            )
            sw_mgmt_ip.save()
            dns_results[sw_num] = {"ip": switch_ip, "name": switch_name, "domain": switch_domain}
            self.log_info(f"IP and domain reserved for site switch: {switch_ip} - {switch_name}")
        return dns_results

    def create_rack(self, site):
        rack_name = f"{site.name.lower()}-rack1"
        rack = Rack(
            width=RackWidthChoices.WIDTH_19IN,
            u_height=16,
            status=RackStatusChoices.STATUS_ACTIVE,
            name=rack_name,
            site=site
        )
        rack.save()
        self.log_success(f"Rack created: {rack}")
        return rack

    def create_router(self, site, router_model, mgmt_id, rack):
        # We should have "router" device role, as well as router model in Netbox before with interfaces assigned to the model
        # In my demo I created CSR-1000 router with GigabitEthernet1-6

        router_role = DeviceRole.objects.get(name='router')
        router_name = f"router1-{site.slug}"

        router = Device(
            name=router_name,
            role=router_role,
            device_type=router_model,
            site=site,
            rack=rack,
            face=DeviceFaceChoices.FACE_FRONT,
            position=rack.u_height - 2,
            status=DeviceStatusChoices.STATUS_ACTIVE,
        )
        router.save()
        self.log_info(f"Created new router: {router}")

        router_mgmt_int = Interface.objects.get(device=router, name="GigabitEthernet2")
        router_ip = "172.20.%d.1/24" % mgmt_id
        router_mgmt_ip = IPAddress.objects.get(address=router_ip)
        router_mgmt_int.ip_addresses.add(router_mgmt_ip)
        router_mgmt_int.save()
        router.primary_ip4 = router_mgmt_ip
        router.save()
        self.log_success(f"Router - {router} created with mgmt IP: {router_mgmt_ip}")

        return router

    def create_switch(self, site, switch_model, number_of_switches, mgmt_id, rack):
        # We should have "switch" device role, as well as switch model in Netbox before with interfaces assigned to the model
        # In my demo I created Catalyst3850 switch  with GigabitEthernet1-6
        list_of_switches = []
        switch_role = DeviceRole.objects.get(name='switch')

        for i in range(number_of_switches):
            switch_name = f"switch{str(i + 1)}-{site.slug}"
            switch = Device(
                name=switch_name,
                role=switch_role,
                device_type=switch_model,
                site=site,
                rack=rack,
                face=DeviceFaceChoices.FACE_FRONT,
                position=rack.u_height - (3 + i),
                status=DeviceStatusChoices.STATUS_ACTIVE,
            )
            switch.save()
            self.log_info(f"Created new switch: {switch}")

            switch_ip = f"172.20.{mgmt_id}.{str(i + 2)}/24"
            switch_mgmt_port = Interface.objects.get(device=switch, name="GigabitEthernet2")
            switch_mgmt_ip = IPAddress.objects.get(address=switch_ip)
            switch_mgmt_port.ip_addresses.add(switch_mgmt_ip)
            switch_mgmt_port.save()
            switch.primary_ip4 = switch_mgmt_ip
            switch.save()
            self.log_success(f"Switch - {switch} created with mgmt IP: {switch_mgmt_ip}")
            list_of_switches.append(switch)
        return list_of_switches

    def add_devices_to_nso(self, site, dns_results):
        # Here we specify NSO IP and port, basic admin/admin authentication in headers
        nso = "NSO_IP_ADDRESS:PORT"
        url = f"{nso}/restconf/data/tailf-ncs:devices/"
        ned_id = "cisco-ios-cli-6.107"
        for device in dns_results:
            ip = dns_results[device]["ip"].split("/")[0]
            name = dns_results[device]["name"]

            headers = {
                'Accept': 'application/yang-data+json',
                'Content-Type': 'application/yang-data+json',
                'Authorization': 'Basic YWRtaW46YWRtaW4='
            }

            payload = json.dumps(
                {
                    "tailf-ncs:device": [
                        {
                            "name": name,
                            "address": ip,
                            "port": 22,
                            "authgroup": "mygroup",
                            "device-type": {
                                "cli": {"ned-id": f"{ned_id}:{ned_id}"}
                            },
                            "state": {"admin-state": "unlocked"},
                        }
                    ]
                }
            )

            response = requests.request("POST", url, headers=headers, data=payload)
            resp = response.status_code

            if resp == 201:
                self.log_success(f"Device {name} added to NSO (response code: {resp})")
                url2 = f"{nso}/restconf/operations/devices/device={name}/ssh/fetch-host-keys"
                response = requests.request("POST", url2, headers=headers, data="")

            else:
                self.log_failure(f"NSO transaction resulted with code: {resp}")

    def run(self, data, commit):
        # data from form
        site_codename = data['site_codename']
        site_name = data['site_name']
        switch_count = data['switch_count']
        switch_model = data['switch_model']
        router_model = data['router_model']
        add_to_nso = data['add_to_nso']

        site = self.create_new_site(site_codename, site_name)
        mgmt_id = self.find_next_free_mgmt_id()
        self.create_mgmt_prefix(site, mgmt_id)
        dns_results = self.dns_allocations(site, mgmt_id, switch_count)
        rack = self.create_rack(site)
        router = self.create_router(site, router_model, mgmt_id, rack)
        list_of_switches = self.create_switch(site, switch_model, switch_count, mgmt_id, rack)
        if add_to_nso:
            self.add_devices_to_nso(site, dns_results)