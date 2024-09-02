import os
import sys
import datetime
import subprocess
import tempfile
import json
import math
import subprocess
import tempfile

class test_fio:
    def __init__(self, resources, meta=None):
        pass

    def __call__(self, method, **kwargs):
        if method == "test":
            return self.test(self, **kwargs)

    def disk_device_name_from_location(self, location):
        directory_tree = location.split("/")

        command = "df -h"
        df = subprocess.check_output(command, shell=True)
        df = df.decode()
        df = df.split("\n")
        for line in df:
            if location in line:
                device = line.split(" ")[0]
                return device
            else:
                while directory_tree.__len__() > 1:
                    directory_tree.pop()
                    location = "/".join(directory_tree)
                    for line in df:
                        if len(directory_tree) == 1 and location == "":
                            location = "/"
                        if location in line:
                            while "  " in line:
                                line = line.replace("  ", " ")
                            mount = line.split(" ")
                            if mount[5] == location:
                                device = mount[0]
                                return device
        return "rootfs"
    
    def disk_device_total_capacity(self, device):
        command = "df -h"
        df = subprocess.check_output(command, shell=True)
        df = df.decode()
        df = df.split("\n")
        for line in df:
            if device in line:
                ## remove duplicate spaces in line
                while "  " in line:
                    line = line.replace("  ", " ")
                capacity = line.split(" ")[1]
                return capacity
        return None
    
    def disk_device_used_capacity(self, device):
        command = "df -h"
        df = subprocess.check_output(command, shell=True)
        df = df.decode()
        df = df.split("\n")
        for line in df:
            if device in line:
                ## remove duplicate spaces in line
                while "  " in line:
                    line = line.replace("  ", " ")
                capacity = line.split(" ")[2]
                return capacity
        return None


    def disk_device_avail_capacity(self, device):
        command = "df -h"
        df = subprocess.check_output(command, shell=True)
        df = df.decode()
        df = df.split("\n")
        for line in df:
            if device in line:
                ## remove duplicate spaces in line
                while "  " in line:
                    line = line.replace("  ", " ")
                capacity = line.split(" ")[3]
                return capacity
        return None

    def disk_speed_4k(self, location):
        with tempfile.NamedTemporaryFile(suffix=".iso", dir=location) as temp_file:
            timestamp_0 = datetime.datetime.now()
            command = "dd if=/dev/zero of=" + temp_file.name + " bs=4k count=8k conv=fdatasync"
            subprocess.check_output(command, shell=True)
            timestamp_1 = datetime.datetime.now()
            write_speed = 32 / (timestamp_1 - timestamp_0).total_seconds()
            command2 = "dd if=" + temp_file.name + " of=/dev/null bs=4k"
            subprocess.check_output(command2, shell=True)
            timestamp_2 = datetime.datetime.now()
            read_speed = 32 / (timestamp_2 - timestamp_1).total_seconds()
            command3 = "rm " + temp_file.name
            return read_speed, write_speed
            
    def stats(self,location, **kwargs):
        disk_device = self.disk_device_name_from_location(location)
        disk_capacity = self.disk_device_total_capacity(disk_device)
        disk_used = self.disk_device_used_capacity(disk_device)
        disk_avail = self.disk_device_avail_capacity(disk_device)
        disk_read_speed, disk_write_speed = self.disk_speed_4k(location)
        results = {
            "disk_device": disk_device,
            "disk_capacity": disk_capacity,
            "disk_used": disk_used,
            "disk_avail": disk_avail,
            "disk_write_speed": disk_write_speed,
            "disk_read_speed": disk_read_speed
        }
        return results

#if __name__ == "__main__":
#    this_test = test_fio(None)
#    results = this_test.test("/tmp/")
#    print(results)    
#    print("Test complete")
#    sys.exit(0)