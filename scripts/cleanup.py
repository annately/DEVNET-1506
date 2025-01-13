""""
Delete all data related to site
"""

from extras.scripts import *
from dcim.choices import *
from dcim.models import Device, Rack, Site



class CleanAll(Script):
    # Here we create a Netbox form
    class Meta:
        name = "Delete Site"
        description = "Delete site"
        field_order = ['site_codename']

    site_codename = StringVar(
        description="Short name of the new site",
        default="AMS"
    )
    
    def get_site_id(self, site_codename):
        self.log_info(f"Searching for site with name {site_codename}")
        try:
            site = Site.objects.get(name=site_codename)
            
            self.log_success(f"Site with ID {site.id} found")
            return site.id
        except Site.DoesNotExist:
            return None
        
    def get_rack_id(self, site_codename):
        rack_codename = f"{site_codename.lower()}-rack1"
        try:
            rack = Rack.objects.get(name=rack_codename)
            return rack.id
        except Rack.DoesNotExist:
            return None
        
    def delete_site(self, site_id):
        try:
            site = Site.objects.get(id=site_id)
            site.delete()
            self.log_success(f"Site with ID {site_id} deleted")
        except Site.DoesNotExist:
            self.log_failure(f"Site with ID {site_id} does not exist")

    def delete_rack(self, rack_id):
        try:
            rack = Rack.objects.get(id=rack_id)
            rack.delete()
            self.log_success(f"Rack with ID {rack_id} deleted")
        except Rack.DoesNotExist:
            self.log_failure(f"Rack with ID {rack_id} does not exist")

    def delete_devices(self, site_id):
        devices = Device.objects.filter(site_id=site_id)
        for device in devices:
            device.delete()
        self.log_success(f"All devices for site with ID {site_id} deleted")


    def run(self, data, commit):  
        # data from form
        site_codename = data['site_codename']
        site_id = self.get_site_id(site_codename)
        self.delete_devices(site_id)
        rack_id = self.get_rack_id(site_codename)
        self.delete_rack(rack_id)
        self.delete_site(site_id) 
