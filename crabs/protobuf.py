"""Small strict wire reader for the documented Anki package/schema-18 messages.

Unknown fields fail closed. No Anki runtime is opened or imported.
Field definitions: https://github.com/ankitects/anki/tree/main/proto/anki
"""
class FormatError(ValueError):
    pass


def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise FormatError('Truncated protobuf varint')
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            if value >= 2**64:raise FormatError('Protobuf varint exceeds 64 bits')
            return value, pos
    raise FormatError('Invalid protobuf varint')


def message(data, allowed):
    result = {}
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field not in allowed:
            raise FormatError(f'Unsupported protobuf field {field}; update the format adapter before proceeding')
        if wire not in allowed[field]:
            raise FormatError(f'Unexpected wire type {wire} for protobuf field {field}')
        if wire == 0:
            value, pos = varint(data, pos)
        else:
            if wire == 2:
                size, pos = varint(data, pos)
            else:
                size = {1: 8, 5: 4}[wire]
            value = data[pos:pos + size]
            pos += size
            if len(value) != size:
                raise FormatError('Truncated protobuf field')
        result.setdefault(field, []).append(value)
    return result


def one(msg, key, default=None):
    values = msg.get(key, [])
    if len(values) > 1:
        raise FormatError(f'Duplicate scalar protobuf field {key}')
    return values[0] if values else default


def config(data, spec):
    """spec maps number to (output name, type, default); absent optional IDs stay null."""
    msg = message(data, {k: ({0} if t in ('int', 'int64', 'bool') else {2}) for k, (_, t, _) in spec.items()})
    result = {}
    for key, (name, typ, default) in spec.items():
        value = one(msg, key, default)
        if isinstance(value, bytes):
            if typ == 'text':
                value = value.decode('utf-8')
            elif typ == 'json':
                import json
                value = json.loads(value) if value else {}
        if typ == 'int64' and value is not None and value >= 2**63:
            value -= 2**64
        if typ == 'bool':
            value = bool(value)
        result[name] = value
    return result
