from sqlalchemy.inspection import inspect

def record(obj):
    out = {}
    for column in inspect(obj).mapper.column_attrs:
        value = getattr(obj, column.key)
        out[column.key] = value.isoformat() if hasattr(value, 'isoformat') else value
    return out
