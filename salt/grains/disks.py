# -*- coding: utf-8 -*-
'''
    Detect disks
'''
from __future__ import absolute_import

# Import python libs
import glob
import logging
import re

# Import salt libs
import salt.utils.files
import salt.utils.path
import salt.utils.platform

# Solve the Chicken and egg problem where grains need to run before any
# of the modules are loaded and are generally available for any usage.
import salt.modules.cmdmod

__salt__ = {
    'cmd.run': salt.modules.cmdmod._run_quiet,
    'cmd.run_all': salt.modules.cmdmod._run_all_quiet
}

log = logging.getLogger(__name__)


def disks():
    '''
    Return list of disk devices
    '''
    if salt.utils.platform.is_freebsd():
        return _freebsd_geom()
    elif salt.utils.platform.is_linux():
        return _linux_disks()
    elif salt.utils.is_windows():
        return _windows_disks()
    else:
        log.trace('Disk grain does not support OS')


class _geomconsts(object):
    GEOMNAME = 'Geom name'
    MEDIASIZE = 'Mediasize'
    SECTORSIZE = 'Sectorsize'
    STRIPESIZE = 'Stripesize'
    STRIPEOFFSET = 'Stripeoffset'
    DESCR = 'descr'  # model
    LUNID = 'lunid'
    LUNNAME = 'lunname'
    IDENT = 'ident'  # serial
    ROTATIONRATE = 'rotationrate'  # RPM or 0 for non-rotating

    # Preserve the API where possible with Salt < 2016.3
    _aliases = {
        DESCR: 'device_model',
        IDENT: 'serial_number',
        ROTATIONRATE: 'media_RPM',
        LUNID: 'WWN',
    }

    _datatypes = {
        MEDIASIZE: ('re_int', r'(\d+)'),
        SECTORSIZE: 'try_int',
        STRIPESIZE: 'try_int',
        STRIPEOFFSET: 'try_int',
        ROTATIONRATE: 'try_int',
    }


def _datavalue(datatype, data):
    if datatype == 'try_int':
        try:
            return int(data)
        except ValueError:
            return None
    elif datatype is tuple and datatype[0] == 're_int':
        search = re.search(datatype[1], data)
        if search:
            try:
                return int(search.group(1))
            except ValueError:
                return None
        return None
    else:
        return data


_geom_attribs = [_geomconsts.__dict__[key] for key in
                 _geomconsts.__dict__ if not key.startswith('_')]


def _freebsd_geom():
    geom = salt.utils.path.which('geom')
    ret = {'disks': {}, 'SSDs': []}

    devices = __salt__['cmd.run']('{0} disk list'.format(geom))
    devices = devices.split('\n\n')

    def parse_geom_attribs(device):
        tmp = {}
        for line in device.split('\n'):
            for attrib in _geom_attribs:
                search = re.search(r'{0}:\s(.*)'.format(attrib), line)
                if search:
                    value = _datavalue(_geomconsts._datatypes.get(attrib),
                                       search.group(1))
                    tmp[attrib] = value
                    if attrib in _geomconsts._aliases:
                        tmp[_geomconsts._aliases[attrib]] = value

        name = tmp.pop(_geomconsts.GEOMNAME)
        if name.startswith('cd'):
            return

        ret['disks'][name] = tmp
        if tmp.get(_geomconsts.ROTATIONRATE) == 0:
            log.trace('Device {0} reports itself as an SSD'.format(device))
            ret['SSDs'].append(name)

    for device in devices:
        parse_geom_attribs(device)

    return ret


def _linux_disks():
    '''
    Return list of disk devices and work out if they are SSD or HDD.
    '''
    ret = {'disks': [], 'SSDs': []}

    for entry in glob.glob('/sys/block/*/queue/rotational'):
        with salt.utils.files.fopen(entry) as entry_fp:
            device = entry.split('/')[3]
            flag = entry_fp.read(1)
            if flag == '0':
                ret['SSDs'].append(device)
                log.trace('Device {0} reports itself as an SSD'.format(device))
            elif flag == '1':
                ret['disks'].append(device)
                log.trace('Device {0} reports itself as an HDD'.format(device))
            else:
                log.trace('Unable to identify device {0} as an SSD or HDD.'
                          ' It does not report 0 or 1'.format(device))
    return ret


def _windows_disks():
    wmic = salt.utils.which('wmic')

    namespace = r'\\root\microsoft\windows\storage'
    path = 'MSFT_PhysicalDisk'
    where = '(MediaType=3 or MediaType=4)'
    get = 'DeviceID,MediaType'

    ret = {'disks': [], 'SSDs': []}

    cmdret = __salt__['cmd.run_all'](
        '{0} /namespace:{1} path {2} where {3} get {4} /format:table'.format(
            wmic, namespace, path, where, get))

    if cmdret['retcode'] != 0:
        log.trace('Disk grain does not support this version of Windows')
    else:
        for line in cmdret['stdout'].splitlines():
            info = line.split()
            if len(info) != 2 or not info[0].isdigit() or not info[1].isdigit():
                continue
            device = r'\\.\PhysicalDrive{0}'.format(info[0])
            mediatype = info[1]
            if mediatype == '3':
                log.trace('Device {0} reports itself as an HDD'.format(device))
                ret['disks'].append(device)
            elif mediatype == '4':
                log.trace('Device {0} reports itself as an SSD'.format(device))
                ret['SSDs'].append(device)
            else:
                log.trace('Unable to identify device {0} as an SSD or HDD.'
                          'It does not report 3 or 4'.format(device))

    return ret
