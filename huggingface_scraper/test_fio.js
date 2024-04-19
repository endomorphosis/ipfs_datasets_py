import { execSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';

export class TestFio {
    constructor(resources, meta = null) {
    
    }

    call(method, kwargs) {
        if (method === 'test') {
            return this.test(kwargs);
        }
    }

    diskDeviceNameFromLocation(location) {
        let directoryTree = location.split('/');

        let df = execSync('df -h').toString().split('\n');
        for (let line of df) {
            if (line.includes(location)) {
            let device = line.split(' ')[0];
            return device;
            } else {
            while (directoryTree.length > 1) {
                directoryTree.pop();
                location = directoryTree.join('/');
                for (let line of df) {
                if (directoryTree.length === 1 && location === '') {
                    location = '/';
                }
                if (line.includes(location)) {
                    while (line.includes('  ')) {
                    line = line.replace('  ', ' ');
                    }
                    let mount = line.split(' ');
                    if (mount[5] === location) {
                    let device = mount[0];
                    return device;
                    }
                }
                }
            }
            }
        }
        return 'rootfs';
    }

    diskDeviceTotalCapacity(device) {
        let df = execSync('df -h').toString().split('\n');
        for (let line of df) {
            if (line.includes(device)) {
                while (line.includes('  ')) {
                    line = line.replace('  ', ' ');
                }
                let capacity = line.split(' ')[1];
                return capacity;
            }
        }
        return null;
    }

    diskDeviceUsedCapacity(device) {
        let df = execSync('df -h').toString().split('\n');
        for (let line of df) {
            if (line.includes(device)) {
                while (line.includes('  ')) {
                    line = line.replace('  ', ' ');
                }
                let capacity = line.split(' ')[2];
                return capacity;
            }
        }
        return null;
    }

    diskDeviceAvailCapacity(device) {
        let df = execSync('df -h').toString().split('\n');
        for (let line of df) {
            if (line.includes(device)) {
                while (line.includes('  ')) {
                    line = line.replace('  ', ' ');
                }
                let capacity = line.split(' ')[3];
                return capacity;
            }
        }
        return null;
    }

    diskSpeed4k(location) {
        let tempFile = path.join(os.tmpdir(), 'tempFile.iso');
        let timestamp0 = new Date();
        execSync(`dd if=/dev/zero of=${tempFile} bs=4k count=8k conv=fdatasync`);
        let timestamp1 = new Date();
        let writeSpeed = 32 / ((timestamp1 - timestamp0) / 1000);
        execSync(`dd if=${tempFile} of=/dev/null bs=4k`);
        let timestamp2 = new Date();
        let readSpeed = 32 / ((timestamp2 - timestamp1) / 1000);
        fs.unlinkSync(tempFile);
        return [readSpeed, writeSpeed];
    }

    stats(location) {
        let diskDevice = this.diskDeviceNameFromLocation(location);
        let diskCapacity = this.diskDeviceTotalCapacity(diskDevice);
        let diskUsed = this.diskDeviceUsedCapacity(diskDevice);
        let diskAvail = this.diskDeviceAvailCapacity(diskDevice);
        let [diskReadSpeed, diskWriteSpeed] = this.diskSpeed4k(location);
        let results = {
            "disk_device": diskDevice,
            "disk_capacity": diskCapacity,
            "disk_used": diskUsed,
            "disk_avail": diskAvail,
            "disk_write_speed": diskWriteSpeed,
            "disk_read_speed": diskReadSpeed
        };
        return results;
    }

}