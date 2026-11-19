"""标准库下的最小 SQLAlchemy / FastAPI 替身，仅供服务层单测使用。

真实运行环境（docker compose 内）由 requirements.txt 的正式依赖接管；
替身只实现 capacity_service 实际用到的查询形态，保证排队、预留、检查点与
崩溃恢复的编排逻辑可以在无第三方依赖的环境里被完整执行和断言。
"""
import sys
import types


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


fastapi = types.ModuleType('fastapi')
fastapi.HTTPException = HTTPException
fastapi.APIRouter = lambda *a, **k: None
fastapi.Depends = lambda *a, **k: None
sys.modules.setdefault('fastapi', fastapi)
for name in ('fastapi.responses',):
    mod = types.ModuleType(name)
    mod.Response = object
    sys.modules.setdefault(name, mod)


class Field:
    def __init__(self, key, type_=None, nullable=True, default=None):
        self.key = key
        self.type = type_
        self.nullable = nullable
        self.default = default


def mapped_column(*args, **kwargs):
    key = kwargs.pop('__key', None)
    default = kwargs.get('default')
    return Field(key=key, nullable=kwargs.get('nullable', True), default=default)


class _Mapped:
    def __getitem__(self, item):
        return item


class _Column:
    def __init__(self, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return _Cond(self.name, 'col', None)
        return instance.__dict__[self.name]

    def __set__(self, instance, value):
        instance.__dict__[self.name] = value


class _Cond:
    def __init__(self, col, op, value):
        self.parts = (col, op, value)

    def __eq__(self, other):
        return _Cond(self.parts[0], '==', other)

    def __ne__(self, other):
        return _Cond(self.parts[0], '!=', other)

    def __lt__(self, other):
        return _Cond(self.parts[0], '<', other)

    def __le__(self, other):
        return _Cond(self.parts[0], '<=', other)

    def __gt__(self, other):
        return _Cond(self.parts[0], '>', other)

    def __ge__(self, other):
        return _Cond(self.parts[0], '>=', other)

    def in_(self, values):
        return _Cond(self.parts[0], 'in', tuple(values))

    def is_(self, other):
        return _Cond(self.parts[0], 'is', other)


class Registry:
    tables = {}


class Base:
    __tablename__ = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        table = cls.__dict__.get('__tablename__')
        if table:
            Registry.tables[table] = cls
            columns = {}
            for name, value in list(cls.__dict__.items()):
                if isinstance(value, Field):
                    value.key = name
                    columns[name] = value
                    setattr(cls, name, _Column(name))
            cls.__columns__ = columns

    def __init__(self, **kwargs):
        for name, col in type(self).__columns__.items():
            default = col.default
            value = kwargs.get(name, default() if callable(default) else default)
            self.__dict__[name] = value
        for key, value in kwargs.items():
            self.__dict__[key] = value


class _Mapper:
    def __init__(self, cls):
        self.column_attrs = [_Attr(name) for name in cls.__columns__]


class _Attr:
    def __init__(self, key):
        self.key = key


def inspect(obj):
    cls = obj if isinstance(obj, type) else type(obj)
    result = types.SimpleNamespace()
    result.mapper = _Mapper(cls)
    return result


class Select:
    def __init__(self, entity):
        self.entity = entity
        self.conds = []
        self.order = None
        self.limit_value = None

    def where(self, *conds):
        self.conds.extend(c.parts for c in conds)
        return self

    def order_by(self, col):
        self.order = col.parts[0] if isinstance(col, _Cond) else col
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def with_for_update(self, skip_locked=False):
        return self


def select(entity):
    return Select(entity)


class _Result:
    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class FakeSession:
    def __init__(self):
        self.store = {}
        self._ids = {}

    def _table(self, entity):
        return self.store.setdefault(entity.__tablename__, [])

    def _next_id(self, entity):
        current = self._ids.get(entity.__tablename__, 0) + 1
        self._ids[entity.__tablename__] = current
        return current

    def add(self, obj):
        if getattr(obj, 'id', None) is None:
            obj.id = self._next_id(type(obj))
        self._table(type(obj)).append(obj)

    def delete(self, obj):
        rows = self._table(type(obj))
        if obj in rows:
            rows.remove(obj)

    def get(self, entity, ident):
        return next((row for row in self._table(entity) if row.id == ident), None)

    def _match(self, row, parts):
        col, op, expected = parts
        value = row.__dict__.get(col)
        if op == '==':
            return value == expected
        if op == '!=':
            return value != expected
        if op == 'in':
            return value in expected
        if op == 'is':
            return value is expected
        if op == '<':
            return value is not None and value < expected
        if op == '<=':
            return value is not None and value <= expected
        if op == '>':
            return value is not None and value > expected
        if op == '>=':
            return value is not None and value >= expected
        raise AssertionError(f'unsupported operator {op}')

    def scalars(self, query):
        rows = [row for row in self._table(query.entity)
                if all(self._match(row, cond) for cond in query.conds)]
        if query.order:
            rows = sorted(rows, key=lambda row: row.__dict__.get(query.order))
        if query.limit_value is not None:
            rows = rows[:query.limit_value]
        return _Result(rows)

    def scalar(self, query):
        rows = self.scalars(query).all()
        return rows[0] if rows else None

    def flush(self):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


sqlalchemy = types.ModuleType('sqlalchemy')
sqlalchemy.String = lambda *a, **k: 'str'
sqlalchemy.Integer = lambda *a, **k: 'int'
sqlalchemy.JSON = lambda *a, **k: 'json'
sqlalchemy.DateTime = lambda *a, **k: 'dt'
sqlalchemy.ForeignKey = lambda *a, **k: 'fk'
sqlalchemy.select = select
sqlalchemy.inspect = inspect
sys.modules.setdefault('sqlalchemy', sqlalchemy)

orm = types.ModuleType('sqlalchemy.orm')
orm.Mapped = _Mapped()
orm.mapped_column = mapped_column
sys.modules.setdefault('sqlalchemy.orm', orm)

inspection = types.ModuleType('sqlalchemy.inspection')
inspection.inspect = inspect
sys.modules.setdefault('sqlalchemy.inspection', inspection)


# ---- 项目配置替身：避免真实数据库连接与环境变量依赖 ----
db_config = types.ModuleType('src.config.database')
db_config.Base = Base
db_config.engine = None
db_config.Session = FakeSession


def _get_db():
    yield FakeSession()


db_config.get_db = _get_db
sys.modules.setdefault('src.config.database', db_config)

settings = types.ModuleType('src.config.settings')
settings.DATABASE_URL = 'sqlite:///:memory:'
settings.REDIS_URL = 'redis://localhost:6379/0'
settings.JWT_SECRET = 'test-secret'
sys.modules.setdefault('src.config.settings', settings)
