#!/usr/bin/env python3
"""Passive SteamOS discovery/checklist validation; never activates an accelerator.

The checklist references, but cannot replace, hardware-evidence.schema.json.
No installer, provider import, XRT workload, Vulkan probe or device-node open.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys

import docksr_detect
import npu_probe
from validate_gate0 import _finite, _pairs

ROOT = Path(__file__).resolve().parents[1]
AREAS = ('device_identity', 'steamos_build', 'kernel', 'npu_driver', 'firmware',
         'device_access', 'xrt', 'vitis_ep', 'model_execution', 'update_survival',
         'reversibility', 'gaming_impact')
STAGES = ('HOST_STAGING', 'VULKAN_DMA_BUF_EXPORTED', 'XRT_BO_IMPORTED',
          'ORT_IMPORTER_AVAILABLE', 'EXTERNAL_TENSOR_BOUND',
          'ACTUAL_NPU_CONSUMPTION_VERIFIED', 'SHARED_SYNCHRONIZATION_VERIFIED',
          'END_TO_END_PERFORMANCE_BENEFIT_VERIFIED')
SYSTEMD_COMMAND = ('systemctl', '--user', 'show', '--property=DefaultLimitMEMLOCK', '--property=DefaultLimitMEMLOCKSoft')
XRT_PACKAGES = ('xrt-base', 'xrt-npu', 'xrt-plugin-amdxdna', 'xrt-plugin-amdxdna-intree', 'amdxdna-driver')
PACMAN_COMMAND = ('pacman', '-Q', *XRT_PACKAGES)
COMMANDS = (('uname', '-r'), ('uname', '-m'), ('lspci', '-n'), SYSTEMD_COMMAND)
FAILURES = {
    'NPU_DEVICE_ABSENT': 'HOST', 'DRIVER_NOT_BOUND': 'HOST',
    'FIRMWARE_MISSING_OR_MISMATCHED': 'HOST', 'XRT_KERNEL_PLUGIN_INCOMPATIBLE': 'HOST_OR_USERSPACE',
    'MEMLOCK_INSUFFICIENT': 'HOST_POLICY', 'PROVIDER_MISSING': 'USERSPACE',
    'NO_NPU_OPERATOR_ASSIGNMENT': 'USERSPACE_OR_MODEL', 'ACTIVE_CONTEXT_MISSING': 'EVIDENCE',
    'MODEL_OUTPUT_MISMATCH': 'INFERENCE', 'INFERENCE_TIMEOUT': 'RUNTIME_OR_HOST',
    'GPU_NPU_CONTENTION': 'SYSTEM_BUDGET', 'IDLE_RESUME_INSTABILITY': 'HOST_OR_RUNTIME',
    'STEAMOS_UPDATE_REGRESSION': 'HOST_OR_USERSPACE',
}


def token(value, maximum=128):
    """Retain bounded public identifiers, never arbitrary command/error text."""
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.+-]{1,' + str(maximum) + '}', value) else None


def os_identity(fs):
    # Deliberately not `source /etc/os-release` and not uname -a (hostname).
    raw = fs.read_text('/etc/os-release')
    values = {}
    for line in raw.get('value', '').splitlines():
        key, sep, value = line.partition('=')
        if sep and key in ('ID', 'VERSION_ID', 'BUILD_ID', 'VARIANT_ID'):
            values[key] = token(value.strip().strip('"\''))
    return {'read_status': raw['status'], 'fields': values}


def command_log(runner, os_id=None):
    rows = []
    commands = (*COMMANDS, PACMAN_COMMAND) if os_id in ('steamos', 'arch', 'cachyos') else COMMANDS
    for argv in commands:
        raw = runner.run(list(argv))
        status = raw['status']
        status = status if status in ('ok', 'missing_tool', 'permission_denied', 'timeout', 'error', 'command_failed') else 'error'
        # Keep exit status, not stdout/stderr or resolved executable/home path.
        values = []
        if status == 'ok' or (argv == PACMAN_COMMAND and status == 'command_failed'):
            if argv[0] == 'uname':
                value = token(raw.get('stdout', '').strip())
                if value is not None:
                    values.append(value)
            elif argv == SYSTEMD_COMMAND:
                for line in raw.get('stdout', '').splitlines()[:16]:
                    key, sep, value = line.partition('=')
                    if sep and key in ('DefaultLimitMEMLOCK', 'DefaultLimitMEMLOCKSoft') and (
                            value == 'infinity' or re.fullmatch(r'[0-9]{1,20}', value) and int(value) < 2**64):
                        values.append(key + '=' + value)
            elif argv == PACMAN_COMMAND:
                for line in raw.get('stdout', '').splitlines()[:32]:
                    fields = line.split()
                    if len(fields) == 2 and fields[0] in XRT_PACKAGES and re.fullmatch(r'[A-Za-z0-9_.:+~-]{1,128}', fields[1]):
                        values.append(' '.join(fields))
            else:
                for line in raw.get('stdout', '').splitlines()[:512]:
                    match = re.fullmatch(r'([0-9a-fA-F:.]{7,12}) ([0-9a-fA-F]{4}): ([0-9a-fA-F]{4}):([0-9a-fA-F]{4})(?: \(rev [0-9a-fA-F]{2}\))?', line)
                    if match and match[3].lower() in ('1022', '1002'):
                        values.append(' '.join(match.groups()).lower())
        rows.append({'argv': list(argv), 'status': status,
                     'exit_status': raw.get('returncode') if status in ('ok', 'command_failed') else None,
                     'observations': values, 'raw_output_retained': False})
    return rows


def passive_runtime_limits(commands):
    """Manager defaults/package database only; never loads XRT or an EP."""
    manager = next(row for row in commands if row['argv'] == list(SYSTEMD_COMMAND))
    fields = dict(line.split('=', 1) for line in manager['observations'])
    result = {'status': manager['status'], 'scope': 'USER_MANAGER_DEFAULTS_NOT_RUNNING_UNIT_LIMITS',
              'unit': 'bytes', 'soft': None, 'hard': None, 'soft_unlimited': False, 'hard_unlimited': False}
    if len(fields) != len(manager['observations']):
        fields = {}  # Conflicting/duplicate properties are not reliable limits.
    for field, property_name in (('soft', 'DefaultLimitMEMLOCKSoft'), ('hard', 'DefaultLimitMEMLOCK')):
        if property_name in fields:
            result[field + '_unlimited'] = fields[property_name] == 'infinity'
            result[field] = None if result[field + '_unlimited'] else int(fields[property_name])
    if manager['status'] == 'ok' and len(fields) != 2:
        result['status'] = 'unavailable_properties'
    package = next((row for row in commands if row['argv'] == list(PACMAN_COMMAND)), None)
    metadata = {'status': package['status'] if package else 'not_queried_non_arch',
                'source': 'PACMAN_LOCAL_DATABASE', 'packages': [], 'vitis_python_packages': {},
                'loaded_runtime_verified': False}
    if package:
        metadata['packages'] = [{'name': line.split()[0], 'version': line.split()[1]} for line in package['observations']]
    for name in ('voe', 'vaip'):
        try: value = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: value = None
        metadata['vitis_python_packages'][name] = token(value)
    return result, metadata


def discover(*, fs=None, runner=None, timestamp=None, tool_lookup=None):
    fs = fs or docksr_detect.FileSystem()
    runner = runner or docksr_detect.CommandRunner()
    tool_lookup = tool_lookup or shutil.which
    identity = os_identity(fs)
    os_id = identity['fields'].get('ID')
    family = 'STEAMOS' if os_id == 'steamos' else 'UNKNOWN' if os_id is None else 'OTHER'
    nodes = []
    for directory, pattern in (('/dev/accel', r'accel[0-9]+'), ('/dev/dri', r'(card|renderD)[0-9]+')):
        listing = fs.entries(directory)
        group = {'path': directory, 'status': listing['status'], 'nodes': []}
        for name in listing.get('names', [])[:256]:
            if re.fullmatch(pattern, name):
                path = directory + '/' + name
                group['nodes'].append({'path': path, **fs.inspect(path),
                    'readable': os.access(fs.path(path), os.R_OK),
                    'writable': os.access(fs.path(path), os.W_OK)})
        nodes.append(group)
    cpu = {}
    for line in fs.read_text('/proc/cpuinfo').get('value', '').splitlines():
        key, sep, value = line.partition(':')
        key = key.strip()
        if sep and key in ('vendor_id', 'cpu family', 'model', 'stepping'):
            cpu.setdefault(key, token(value.strip()))
    pci = []
    for name in fs.entries('/sys/bus/pci/devices').get('names', [])[:512]:
        if not re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', name):
            continue
        base = '/sys/bus/pci/devices/' + name
        vendor = token(fs.read_text(base + '/vendor').get('value'))
        if vendor not in ('0x1022', '0x1002'):
            continue
        pci.append({'address': name, 'vendor': vendor,
                    'device': token(fs.read_text(base + '/device').get('value')),
                    'class': token(fs.read_text(base + '/class').get('value')),
                    'driver': token(fs.link_name(base + '/driver').get('value'))})
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    firmware = {}
    for name in fs.entries('/sys/class/accel').get('names', [])[:128]:
        if re.fullmatch(r'accel[0-9]+', name):
            firmware[name] = {key: token(fs.read_text('/sys/class/accel/' + name + '/device/' + key).get('value'))
                              for key in ('firmware_version', 'fw_version')}
    runtime = npu_probe.runtime_inventory(False)
    commands = command_log(runner, os_id)
    systemd_limits, installed_metadata = passive_runtime_limits(commands)
    inventory = {
        'os': identity, 'cpu': cpu, 'pci': pci, 'nodes': nodes,
        'kernel_release': token(fs.read_text('/proc/sys/kernel/osrelease').get('value')),
        'kernel_config': npu_probe.kernel_config(fs, fs.read_text('/proc/sys/kernel/osrelease')),
        'amdxdna': {key: token(fs.read_text('/sys/module/amdxdna/' + key).get('value'))
                    for key in ('version', 'srcversion')},
        'firmware_attributes': firmware,
        'firmware_directory_status': fs.entries('/usr/lib/firmware/amdnpu')['status'],
        'memlock_bytes': {'soft': None if soft == resource.RLIM_INFINITY else soft,
                          'hard': None if hard == resource.RLIM_INFINITY else hard},
        'user_systemd_memlock': systemd_limits,
        'installed_runtime_metadata': installed_metadata,
        'tools_available': {tool: tool_lookup(tool) is not None for tool in ('xrt-smi', 'python3', 'lspci', 'modinfo')},
        'runtime_packages': {key: token(value) for key, value in runtime['packages'].items()},
        'provider_query_status': 'NOT_TESTED',
        'commands': commands,
    }
    return {'schema_version': '1.0.0', 'document_type': 'docksr_steamos_readiness',
            'generated_at_utc': timestamp or datetime.now(timezone.utc).isoformat(),
            'evidence_class': 'DEVICE_INVENTORY', 'physical_test_status': 'NOT_TESTED',
            'os_family': family, 'compatibility_claim': 'NOT_ESTABLISHED',
            'npu_execution_claim': 'NOT_ATTESTED', 'hardware_execution_verified': False,
            'read_only': True, 'inventory': inventory, 'evidence': [], 'failures': [],
            'areas': {key: {'status': 'NOT_TESTED', 'evidence_refs': []} for key in AREAS},
            'gates': {key: {'status': 'NOT_TESTED', 'evidence_refs': []} for key in ('H0', 'H1', 'H2', 'H3')},
            'interop': {key: {'status': 'NOT_TESTED', 'evidence_refs': []} for key in STAGES}}


def validate(record):
    """Validate checklist consistency, not authenticity or accelerator execution."""
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads((ROOT / 'schemas/steamos-readiness.schema.json').read_text())
    _finite(record)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record))
    if errors:
        raise ValueError('Readiness schema violation at /' + '/'.join(map(str, errors[0].absolute_path)))
    timestamp = datetime.fromisoformat(record['generated_at_utc'].replace('Z', '+00:00'))
    if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
        raise ValueError('Readiness timestamp requires UTC')
    refs = {row['id']: row for row in record['evidence']}
    if len(refs) != len(record['evidence']):
        raise ValueError('Duplicate evidence ID')
    device = record['evidence_class'] == 'DEVICE_INVENTORY' and record['physical_test_status'] == 'OBSERVED_ON_DEVICE'
    if record['evidence_class'] != 'DEVICE_INVENTORY' and record['physical_test_status'] != 'NOT_TESTED':
        raise ValueError('Plans and examples are not device observations')
    inventory = record['inventory']
    if inventory is not None:
        os_id = inventory['os']['fields'].get('ID')
        family = 'STEAMOS' if os_id == 'steamos' else 'UNKNOWN' if os_id is None else 'OTHER'
        if record['os_family'] != family:
            raise ValueError('OS family contradicts collected identity')
        for command in inventory['commands']:
            if command['status'] == 'ok' and command['exit_status'] != 0:
                raise ValueError('Successful command needs exit status zero')
            if command['status'] == 'command_failed' and (command['exit_status'] is None or command['exit_status'] == 0):
                raise ValueError('Failed command needs nonzero exit status')
            if command['status'] not in ('ok', 'command_failed') and command['exit_status'] is not None:
                raise ValueError('Unexecuted or interrupted command has no exit status')
        limits = inventory.get('user_systemd_memlock')
        if limits:
            for field in ('soft', 'hard'):
                if limits[field + '_unlimited'] and limits[field] is not None:
                    raise ValueError('Unlimited memlock cannot also be a finite byte value')
                if limits['status'] == 'ok' and limits[field] is None and not limits[field + '_unlimited']:
                    raise ValueError('Observed memlock requires a finite value or explicit infinity')
    for failure in record['failures']:
        if not set(failure['evidence_refs']) <= refs.keys():
            raise ValueError('Unresolved failure evidence reference')
        if failure['status'] == 'CONFIRMED' and not device and record['evidence_class'] != 'SCHEMA_EXAMPLE':
            raise ValueError('Confirmed failure requires device evidence')
        if failure['status'] == 'CONFIRMED' and any(refs[key]['category'] != 'DEVICE_OBSERVATION' for key in failure['evidence_refs']):
            raise ValueError('Documentation cannot confirm a device failure')
    for group in ('areas', 'gates', 'interop'):
        for row in record[group].values():
            if not set(row['evidence_refs']) <= refs.keys():
                raise ValueError('Unresolved evidence reference')
            if row['status'] in ('PASS', 'OBSERVED_ON_DEVICE'):
                if not row['evidence_refs'] or (record['evidence_class'] != 'SCHEMA_EXAMPLE' and not device):
                    raise ValueError('Observed/pass state requires device evidence')
                if any(refs[key]['category'] != 'DEVICE_OBSERVATION' for key in row['evidence_refs']):
                    raise ValueError('Documentation alone cannot pass a device gate')
            if row['status'] == 'SUPPORTED_BY_DOCUMENTATION' and (not row['evidence_refs'] or
                    any(refs[key]['category'] != 'PRIMARY_DOCUMENTATION' for key in row['evidence_refs'])):
                raise ValueError('Documentation state requires primary documentation')
    gates = record['gates']
    for name, previous in (('H1', 'H0'), ('H2', 'H1'), ('H3', 'H2')):
        if gates[name]['status'] == 'PASS' and gates[previous]['status'] != 'PASS':
            raise ValueError('Gate prerequisite not passed')
    if gates['H0']['status'] == 'PASS' and any(record['areas'][key]['status'] != 'PASS' for key in AREAS[:7]):
        raise ValueError('H0 requires host readiness evidence')
    if gates['H1']['status'] == 'PASS' or record['areas']['model_execution']['status'] == 'PASS':
        row = gates['H1']
        kinds = {refs[key]['kind'] for key in row['evidence_refs']}
        required = {'HARDWARE_RECORD', 'MODEL_IDENTITY', 'OPERATOR_ASSIGNMENT', 'ACTIVE_CONTEXT', 'CPU_REFERENCE', 'OUTPUT_COMPARISON'}
        if row['status'] != 'PASS' or not required <= kinds or record['areas']['vitis_ep']['status'] != 'PASS':
            raise ValueError('H1 requires canonical hardware record, model, placement, context and CPU agreement')
    for index, name in enumerate(STAGES):
        if record['interop'][name]['status'] == 'PASS':
            if gates['H1']['status'] != 'PASS' or any(record['interop'][prior]['status'] != 'PASS' for prior in STAGES[:index]):
                raise ValueError('Interop ladder prerequisite not passed')
    if record['compatibility_claim'] == 'STEAMOS_VALIDATED':
        if (not device or record['os_family'] != 'STEAMOS' or inventory is None or
                any(not inventory['os']['fields'].get(key) for key in ('VERSION_ID', 'BUILD_ID')) or
                any(row['status'] != 'PASS' for row in record['areas'].values()) or gates['H3']['status'] != 'PASS'):
            raise ValueError('SteamOS acceptance requires SteamOS device evidence across all areas through H3')
    return {'status': 'VALID', 'hardware_execution_verified': False,
            'scope': 'Checklist structure and consistency only; artifacts require independent review.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path, help='NEW private JSON outside Git; existing parent mode0700')
    group.add_argument('--validate', type=Path, help='Validate checklist only; never execute referenced commands')
    args = parser.parse_args(argv)
    try:
        if args.validate:
            with args.validate.open('rb') as stream:
                raw = stream.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError('Readiness record exceeds 1 MiB')
            result = validate(json.loads(raw, object_pairs_hook=_pairs))
        else:
            if os.geteuid() == 0:
                raise ValueError('Run initial discovery as an ordinary user')
            record = discover()
            validate(record)
            npu_probe.write_new_private(args.output, record)
            result = {'status': 'WRITTEN', 'physical_test_status': 'NOT_TESTED', 'hardware_execution_verified': False}
        print(json.dumps(result, allow_nan=False, sort_keys=True))
        return 0
    except (OSError, ValueError, ImportError, RecursionError):
        # Paths, usernames and dependency exception text are intentionally excluded.
        print(json.dumps({'status': 'ERROR', 'reason': 'READINESS_INPUT_OR_OUTPUT_UNAVAILABLE_OR_INVALID', 'hardware_execution_verified': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
