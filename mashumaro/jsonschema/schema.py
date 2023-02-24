import datetime
import ipaddress
import os
import typing
from base64 import encodebytes
from dataclasses import MISSING, dataclass, field, is_dataclass, replace
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    Union,
)
from uuid import UUID

from typing_extensions import TypeAlias, Unpack

from mashumaro.config import BaseConfig
from mashumaro.core.const import PY_311_MIN
from mashumaro.core.meta.code.builder import CodeBuilder
from mashumaro.core.meta.helpers import (
    get_args,
    get_literal_values,
    get_type_origin,
    is_annotated,
    is_generic,
    is_literal,
    is_named_tuple,
    is_new_type,
    is_not_required,
    is_required,
    is_self,
    is_special_typing_primitive,
    is_type_var,
    is_type_var_any,
    is_type_var_tuple,
    is_typed_dict,
    is_union,
    is_unpack,
    resolve_type_params,
    type_name,
)
from mashumaro.core.meta.types.common import NoneType
from mashumaro.helper import pass_through
from mashumaro.jsonschema.annotations import (
    Annotation,
    ExclusiveMaximum,
    ExclusiveMinimum,
    Maximum,
    Minimum,
)
from mashumaro.jsonschema.models import (
    DATETIME_FORMATS,
    IPADDRESS_FORMATS,
    Context,
    JSONArraySchema,
    JSONObjectSchema,
    JSONSchema,
    JSONSchemaInstanceFormatExtension,
    JSONSchemaInstanceType,
    JSONSchemaStringFormat,
)
from mashumaro.types import SerializationStrategy

try:
    from mashumaro.mixins.orjson import (
        DataClassORJSONMixin as DataClassJSONMixin,
    )
except ImportError:
    from mashumaro.mixins.json import DataClassJSONMixin  # type: ignore


@dataclass
class Instance:
    type: Type
    name: Optional[str] = None
    origin_type: Type = field(init=False)
    annotations: List[Annotation] = field(init=False, default_factory=list)
    __builder: Optional[CodeBuilder] = None

    def child(self, typ: Type) -> "Instance":
        child = self.copy(type=typ)
        return child

    @property
    def _builder(self) -> CodeBuilder:
        assert self.__builder
        return self.__builder

    @property
    def metadata(self) -> Mapping[str, Any]:
        if not self.name:
            return {}
        return self._builder.metadatas.get(self.name, {})

    @property
    def alias(self) -> Optional[str]:
        alias = self.metadata.get("alias")
        if alias is None:
            alias = self.get_config().aliases.get(self.name)  # type: ignore
        if alias is None:
            alias = self.name
        return alias

    @property
    def holder_class(self) -> Optional[Type]:
        if self.__builder:
            return self.__builder.cls
        return None

    def copy(self, **changes: Any) -> "Instance":
        return replace(self, **changes)

    def __post_init__(self) -> None:
        if self.__builder:
            self.type = self.__builder._get_real_type(
                field_name=self.name,  # type: ignore
                field_type=self.type,
            )
        self.origin_type = get_type_origin(self.type)
        if is_dataclass(self.origin_type):
            type_args = get_args(self.type)
            self.__builder = CodeBuilder(self.origin_type, type_args)
            self.__builder.reset()

        if is_annotated(self.type):
            self.annotations = getattr(self.type, "__metadata__", [])
            self.type = self.origin_type

    def fields(self) -> Iterable[Tuple[str, Type, Any]]:
        for f_name, f_type in self._builder.get_field_types(
            include_extras=True
        ).items():
            f = self._builder.dataclass_fields.get(f_name)  # type: ignore
            if f and not f.init:
                continue
            f_default = f.default
            if f_default is MISSING:
                f_default = self._builder.namespace.get(f_name, MISSING)
            if f_default is not MISSING:
                f_default = _default(f_type, f_default)
            yield f_name, f_type, f_default

    def get_resolved_type_params(self) -> Dict[Type, Type]:
        if not self.name:
            return {}
        return self._builder.get_field_resolved_type_params(self.name)

    def get_overridden_serialization_method(
        self,
    ) -> Optional[Union[Callable, str]]:
        if not self.__builder:
            return None
        serialize_option = self.metadata.get("serialize")
        if serialize_option is not None:
            return serialize_option
        for strategy in self.__builder.iter_serialization_strategies(
            self.metadata, self.type
        ):
            if strategy is pass_through:
                return pass_through
            elif isinstance(strategy, dict):
                serialize_option = strategy.get("serialize")
            elif isinstance(strategy, SerializationStrategy):
                serialize_option = strategy.serialize
            if serialize_option is not None:
                return serialize_option
        return None

    def get_config(self) -> Type[BaseConfig]:
        if self.__builder:
            return self.__builder.get_config()
        else:
            return BaseConfig


InstanceSchemaCreator: TypeAlias = Callable[
    [Instance, Context], Optional[JSONSchema]
]


@dataclass
class InstanceSchemaCreatorRegistry:
    _registry: List[InstanceSchemaCreator] = field(default_factory=list)

    def register(self, func: InstanceSchemaCreator) -> InstanceSchemaCreator:
        self._registry.append(func)
        return func

    def iter(self) -> Iterable[InstanceSchemaCreator]:
        yield from self._registry


def get_schema(instance: Instance, ctx: Context) -> JSONSchema:
    for schema_creator in Registry.iter():
        schema = schema_creator(instance, ctx)
        if schema is not None:
            return schema
    raise NotImplementedError(
        (
            f'Type {type_name(instance.type)} of field "{instance.name}" '
            f"in {instance.holder_class} isn't supported"
        )
    )


def _default(f_type: Type, f_value: Any) -> Any:
    @dataclass
    class CC(DataClassJSONMixin):
        x: f_type = f_value  # type: ignore

    return CC(f_value).to_dict()["x"]


Registry = InstanceSchemaCreatorRegistry()
register = Registry.register


@register
def on_dataclass(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    # TODO: Self references might not work
    if is_dataclass(instance.origin_type):
        schema = JSONObjectSchema(
            title=instance.origin_type.__name__,
            additionalProperties=False,
        )
        properties: Dict[str, JSONSchema] = {}
        required = []
        for f_name, f_type, f_default in instance.fields():
            f_instance = instance.copy(type=f_type, name=f_name)
            f_schema = get_schema(f_instance, ctx)
            if f_default is not MISSING:
                f_schema.default = f_default
            else:
                required.append(f_name)
            if f_instance.alias:
                properties[f_instance.alias] = f_schema
        if properties:
            schema.properties = properties
        if required:
            schema.required = required
        ctx.definitions[instance.origin_type.__name__] = schema
        return JSONSchema(
            reference=(
                f"{ctx.dialect.definitions_root_pointer}/"
                f"{instance.origin_type.__name__}"
            )
        )


@register
def on_any(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.type is Any:
        return JSONSchema()


def on_literal(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    enum_values = []
    for value in get_literal_values(instance.type):
        if isinstance(value, Enum):
            enum_values.append(value.value)
        elif isinstance(value, (int, str, bool, NoneType)):  # type: ignore
            enum_values.append(value)
        elif isinstance(value, bytes):
            enum_values.append(encodebytes(value).decode())
    return JSONSchema(enum=enum_values)


@register
def on_special_typing_primitive(
    instance: Instance, ctx: Context
) -> Optional[JSONSchema]:
    if not is_special_typing_primitive(instance.origin_type):
        return None

    args = get_args(instance.type)

    if is_union(instance.type):
        return JSONSchema(
            anyOf=[get_schema(instance.copy(type=arg), ctx) for arg in args]
        )
    elif is_type_var_any(instance.type):
        return JSONSchema()
    elif is_type_var(instance.type):
        constraints = getattr(instance.type, "__constraints__")
        if constraints:
            return JSONSchema(
                anyOf=[
                    get_schema(instance.copy(type=arg), ctx)
                    for arg in constraints
                ]
            )
        else:
            bound = getattr(instance.type, "__bound__")
            return get_schema(instance.copy(type=bound), ctx)
    elif is_new_type(instance.type):
        return get_schema(instance.copy(type=instance.type.__supertype__), ctx)
    elif is_literal(instance.type):
        return on_literal(instance, ctx)
    elif is_self(instance.type):
        raise NotImplementedError
    elif is_required(instance.type) or is_not_required(instance.type):
        return get_schema(instance.copy(type=args[0]), ctx)
    elif is_unpack(instance.type):
        return get_schema(instance.copy(type=get_args(instance.type)[0]), ctx)
    elif is_type_var_tuple(instance.type):
        return get_schema(instance.copy(type=Tuple[Any, ...]), ctx)


@register
def on_number(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type is int:
        schema = JSONSchema(type=JSONSchemaInstanceType.INTEGER)
    elif instance.origin_type is float:
        schema = JSONSchema(type=JSONSchemaInstanceType.NUMBER)
    else:
        return None
    for annotation in instance.annotations:
        if isinstance(annotation, Minimum):
            schema.minimum = annotation.value  # type: ignore
        elif isinstance(annotation, Maximum):
            schema.maximum = annotation.value  # type: ignore
        elif isinstance(annotation, ExclusiveMinimum):
            schema.exclusiveMinimum = annotation.value  # type: ignore
        elif isinstance(annotation, ExclusiveMaximum):
            schema.exclusiveMaximum = annotation.value  # type: ignore
    return schema


@register
def on_bool(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type is bool:
        return JSONSchema(type=JSONSchemaInstanceType.BOOLEAN)


@register
def on_none(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type in (NoneType, None):
        return JSONSchema(type=JSONSchemaInstanceType.NULL)


@register
def on_date_objects(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type in (
        datetime.datetime,
        datetime.date,
        datetime.time,
    ):
        return JSONSchema(
            type=JSONSchemaInstanceType.STRING,
            format=DATETIME_FORMATS[instance.origin_type],
        )


@register
def on_timedelta(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type is datetime.timedelta:
        if instance.origin_type is datetime.datetime:
            return JSONSchema(
                type=JSONSchemaInstanceType.NUMBER,
                format=JSONSchemaInstanceFormatExtension.TIMEDELTA,
            )


@register
def on_uuid(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type is UUID:
        return JSONSchema(
            type=JSONSchemaInstanceType.STRING,
            format=JSONSchemaStringFormat.UUID,
        )


@register
def on_ipaddress(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type in (
        ipaddress.IPv4Address,
        ipaddress.IPv6Address,
        ipaddress.IPv4Network,
        ipaddress.IPv6Network,
        ipaddress.IPv4Interface,
        ipaddress.IPv6Interface,
    ):
        return JSONSchema(
            type=JSONSchemaInstanceType.STRING,
            format=IPADDRESS_FORMATS[instance.origin_type],  # type: ignore
        )


@register
def on_decimal(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type is Decimal:
        return JSONSchema(
            type=JSONSchemaInstanceType.STRING,
            format=JSONSchemaInstanceFormatExtension.DECIMAL,
        )


@register
def on_fraction(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if instance.origin_type is Fraction:
        return JSONSchema(
            type=JSONSchemaInstanceType.STRING,
            format=JSONSchemaInstanceFormatExtension.FRACTION,
        )


def on_tuple(instance: Instance, ctx: Context) -> JSONArraySchema:
    args = get_args(instance.type)
    if not args:
        if instance.type in (Tuple, tuple):
            args = [typing.Any, ...]  # type: ignore
        else:
            return JSONArraySchema(maxItems=0)
    elif len(args) == 1 and args[0] == ():
        if not PY_311_MIN:
            return JSONArraySchema(maxItems=0)
    if len(args) == 2 and args[1] is Ellipsis:
        return JSONArraySchema(
            items=get_schema(instance.copy(type=args[0]), ctx)
        )
    else:
        min_items: Optional[int] = 0
        max_items: Optional[int] = 0
        prefix_items = []
        items: Optional[JSONSchema] = None
        unpack_schema: Optional[JSONSchema] = None
        unpack_idx = 0
        for arg_idx, arg in enumerate(args, start=1):
            if not is_unpack(arg):
                min_items += 1  # type: ignore
                if not unpack_schema:
                    prefix_items.append(
                        get_schema(instance.copy(type=arg), ctx)
                    )
            else:
                unpack_schema = get_schema(instance.copy(type=arg), ctx)
                unpack_idx = arg_idx
        if unpack_schema:
            prefix_items.extend(unpack_schema.prefixItems or [])
            min_items += unpack_schema.minItems or 0  # type: ignore
            max_items += unpack_schema.maxItems or 0  # type: ignore
            if unpack_idx == len(args):
                items = unpack_schema.items
        else:
            min_items = None
            max_items = len(args)
        if min_items and min_items == len(prefix_items):
            min_items = None
        return JSONArraySchema(
            prefixItems=prefix_items or None,
            items=items,
            minItems=min_items or None,
            maxItems=max_items or None,
        )


def on_named_tuple(instance: Instance, ctx: Context) -> JSONSchema:
    resolved = resolve_type_params(
        instance.origin_type, get_args(instance.type)
    )[instance.origin_type]
    annotations = {
        k: resolved.get(v, v)
        for k, v in getattr(
            instance.origin_type, "__annotations__", {}
        ).items()
    }
    fields = getattr(instance.type, "_fields", ())
    defaults = getattr(instance.type, "_field_defaults", {})
    as_dict = instance.get_config().namedtuple_as_dict
    serialize_option = instance.get_overridden_serialization_method()
    if serialize_option == "as_dict":
        as_dict = True
    elif serialize_option == "as_list":
        as_dict = False
    properties = {}
    for f_name in fields:
        f_type = annotations.get(f_name, typing.Any)
        f_schema = get_schema(instance.copy(type=f_type), ctx)
        f_default = defaults.get(f_name, MISSING)
        if f_default is not MISSING:
            f_schema.default = _default(f_type, f_default)  # type: ignore
        properties[f_name] = f_schema
    if as_dict:
        return JSONObjectSchema(
            properties=properties or None,
            required=list(fields),
            additionalProperties=False,
        )
    else:
        return JSONArraySchema(
            prefixItems=list(properties.values()) or None,
            maxItems=len(properties) or None,
        )


def on_typed_dict(instance: Instance, ctx: Context) -> JSONObjectSchema:
    resolved = resolve_type_params(
        instance.origin_type, get_args(instance.type)
    )[instance.origin_type]
    annotations = {
        k: resolved.get(v, v)
        for k, v in instance.origin_type.__annotations__.items()
    }
    all_keys = list(annotations.keys())
    required_keys = getattr(instance.type, "__required_keys__", all_keys)
    return JSONObjectSchema(
        properties={
            key: get_schema(instance.copy(type=annotations[key]), ctx)
            for key in all_keys
        }
        or None,
        required=sorted(required_keys) or None,
        additionalProperties=False,
    )


@register
def on_collection(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if not issubclass(instance.origin_type, typing.Collection):
        return None
    elif issubclass(instance.origin_type, Enum):
        return None

    args = get_args(instance.type)

    if issubclass(instance.origin_type, typing.ByteString):
        return JSONSchema(
            type=JSONSchemaInstanceType.STRING,
            format=JSONSchemaInstanceFormatExtension.BASE64,
        )
    elif issubclass(instance.origin_type, str):
        return JSONSchema(type=JSONSchemaInstanceType.STRING)
    elif is_generic(instance.type) and issubclass(
        instance.origin_type, (List, typing.Deque)
    ):
        instance.child(args[0])
        return JSONArraySchema(
            items=get_schema(instance.copy(type=args[0]), ctx)
            if args
            else None
        )
    elif issubclass(instance.origin_type, Tuple):  # type: ignore
        if is_named_tuple(instance.origin_type):
            return on_named_tuple(instance, ctx)
        elif is_generic(instance.type):
            return on_tuple(instance, ctx)
    elif is_generic(instance.type) and issubclass(
        instance.origin_type, (typing.FrozenSet, typing.AbstractSet)
    ):
        return JSONArraySchema(
            items=get_schema(instance.copy(type=args[0]), ctx)
            if args
            else None,
            uniqueItems=True,
        )
    elif is_generic(instance.type) and issubclass(
        instance.origin_type, typing.ChainMap
    ):
        return JSONArraySchema(
            items=get_schema(
                instance.copy(type=Dict[Unpack[args[:2]]]), ctx  # type: ignore
            )
        )
    elif is_generic(instance.type) and issubclass(
        instance.origin_type, typing.Counter
    ):
        schema = JSONObjectSchema(
            additionalProperties=get_schema(instance.copy(type=int), ctx),
        )
        if args and args[0] is not str:
            schema.propertyNames = get_schema(instance.copy(type=args[0]), ctx)
        return schema
    elif is_typed_dict(instance.origin_type):
        return on_typed_dict(instance, ctx)
    elif is_generic(instance.type) and issubclass(
        instance.origin_type, typing.Mapping
    ):
        schema = JSONObjectSchema(
            additionalProperties=get_schema(instance.copy(type=args[1]), ctx)
        )
        if args[0] is not str:
            schema.propertyNames = get_schema(instance.copy(type=args[0]), ctx)
        return schema
    elif is_generic(instance.type) and issubclass(
        instance.origin_type, typing.Sequence
    ):
        return JSONArraySchema(
            items=get_schema(instance.copy(type=args[0]), ctx)
            if args
            else None
        )


@register
def on_pathlike(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if issubclass(instance.origin_type, os.PathLike):
        return JSONSchema(
            type=JSONSchemaInstanceType.STRING,
            format=JSONSchemaInstanceFormatExtension.PATH,
        )


@register
def on_enum(instance: Instance, ctx: Context) -> Optional[JSONSchema]:
    if issubclass(instance.origin_type, Enum):
        return JSONSchema(enum=[m.value for m in instance.origin_type])


__all__ = ["Instance", "get_schema"]
