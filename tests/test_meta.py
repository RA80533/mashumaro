import collections
import collections.abc
import typing
from dataclasses import dataclass
from datetime import datetime

import pytest
import typing_extensions

from mashumaro import DataClassDictMixin
from mashumaro.core.const import (
    PEP_585_COMPATIBLE,
    PY_37,
    PY_38,
    PY_38_MIN,
    PY_310_MIN,
)
from mashumaro.core.meta.code.builder import CodeBuilder

# noinspection PyProtectedMember
from mashumaro.core.meta.helpers import (
    collect_type_params,
    get_args,
    get_class_that_defines_field,
    get_class_that_defines_method,
    get_function_arg_annotation,
    get_function_return_annotation,
    get_generic_name,
    get_literal_values,
    get_type_origin,
    hash_type_args,
    is_annotated,
    is_dataclass_dict_mixin,
    is_dataclass_dict_mixin_subclass,
    is_dialect_subclass,
    is_generic,
    is_init_var,
    is_literal,
    is_new_type,
    is_optional,
    is_self,
    is_type_var_any,
    is_union,
    not_none_type_arg,
    resolve_type_params,
    type_name,
)
from mashumaro.core.meta.types.common import (
    FieldContext,
    ValueSpec,
    ensure_generic_collection,
)
from mashumaro.dialect import Dialect
from mashumaro.exceptions import UnserializableField
from mashumaro.mixins.json import DataClassJSONMixin

from .entities import (
    MyDataClass,
    MyDatetimeNewType,
    MyEnum,
    MyFlag,
    MyGenericDataClass,
    MyGenericList,
    MyIntEnum,
    MyIntFlag,
    MyNativeStrEnum,
    MyStrEnum,
    T,
    TAny,
    TInt,
    TIntStr,
)

NoneType = type(None)

TMyDataClass = typing.TypeVar("TMyDataClass", bound=MyDataClass)


def test_is_generic_unsupported_python(mocker):
    mocker.patch("mashumaro.core.meta.helpers.PY_37", False)
    mocker.patch("mashumaro.core.meta.helpers.PY_38", False)
    mocker.patch("mashumaro.core.meta.helpers.PY_39_MIN", False)
    with pytest.raises(NotImplementedError):
        is_generic(int)


def test_is_init_var_unsupported_python(mocker):
    mocker.patch("mashumaro.core.meta.helpers.PY_37", False)
    mocker.patch("mashumaro.core.meta.helpers.PY_38_MIN", False)
    with pytest.raises(NotImplementedError):
        is_init_var(int)


def test_is_literal_unsupported_python(mocker):
    mocker.patch("mashumaro.core.meta.helpers.PY_37", False)
    mocker.patch("mashumaro.core.meta.helpers.PY_38", False)
    mocker.patch("mashumaro.core.meta.helpers.PY_39_MIN", False)
    assert not is_literal(typing_extensions.Literal[1])


def test_no_code_builder(mocker):
    mocker.patch(
        "mashumaro.mixins.dict.DataClassDictMixin.__init_subclass__",
        lambda: ...,
    )

    @dataclass
    class DataClass(DataClassDictMixin):
        pass

    assert DataClass.__pre_deserialize__({}) is None
    assert DataClass.__post_deserialize__(DataClass()) is None
    assert DataClass().__pre_serialize__() is None
    assert DataClass().__post_serialize__({}) is None


def test_get_class_that_defines_method():
    class A:
        def foo(self):
            pass  # pragma no cover

        @classmethod
        def bar(cls):
            pass  # pragma no cover

        def foobar(self):
            pass  # pragma no cover

    class B(A):
        def foobar(self):
            pass  # pragma no cover

    assert get_class_that_defines_method("foo", B) == A
    assert get_class_that_defines_method("bar", B) == A
    assert get_class_that_defines_method("foobar", B) == B


def test_get_class_that_defines_field():
    @dataclass
    class A:
        x: int
        y: int
        z: int

    @dataclass
    class B(A):
        y: float
        z: int

    assert get_class_that_defines_field("x", B) == A
    assert get_class_that_defines_field("y", B) == B
    assert get_class_that_defines_field("z", B) == B


def test_get_unknown_declared_hook():
    builder = CodeBuilder(object)
    assert builder.get_declared_hook("unknown_name") is None


def test_is_dataclass_dict_mixin():
    assert is_dataclass_dict_mixin(DataClassDictMixin)
    assert not is_dataclass_dict_mixin(DataClassJSONMixin)


def test_is_dataclass_dict_mixin_subclass():
    assert is_dataclass_dict_mixin_subclass(DataClassDictMixin)
    assert is_dataclass_dict_mixin_subclass(DataClassJSONMixin)
    assert is_dataclass_dict_mixin_subclass(MyDataClass)


def test_is_type_var_any():
    assert is_type_var_any(TAny)
    assert not is_type_var_any(typing.Any)
    assert not is_type_var_any(TMyDataClass)


@pytest.mark.skipif(not (PY_37 or PY_38), reason="requires python 3.7..3.8")
def test_is_type_var_any_list_37_38():
    # noinspection PyProtectedMember
    # noinspection PyUnresolvedReferences
    assert is_type_var_any(typing.List.__args__[0])


def test_type_name():
    assert type_name(TAny) == "typing.Any"
    assert type_name(TInt) == "int"
    assert type_name(TMyDataClass) == "tests.entities.MyDataClass"
    assert type_name(TIntStr) == "typing.Union[int, str]"
    assert type_name(typing.List[TInt]) == "typing.List[int]"
    assert type_name(typing.Tuple[int]) == "typing.Tuple[int]"
    assert type_name(typing.Tuple[int, ...]) == "typing.Tuple[int, ...]"
    assert type_name(typing.Tuple[()]) == "typing.Tuple[()]"
    assert type_name(typing.Set[int]) == "typing.Set[int]"
    assert type_name(typing.FrozenSet[int]) == "typing.FrozenSet[int]"
    assert type_name(typing.Deque[int]) == "typing.Deque[int]"
    assert type_name(typing.Dict[int, int]) == "typing.Dict[int, int]"
    assert type_name(typing.Mapping[int, int]) == "typing.Mapping[int, int]"
    assert (
        type_name(typing.MutableMapping[int, int])
        == "typing.MutableMapping[int, int]"
    )
    assert type_name(typing.Counter[int]) == "typing.Counter[int]"
    assert type_name(typing.ChainMap[int, int]) == "typing.ChainMap[int, int]"
    assert type_name(typing.Sequence[int]) == "typing.Sequence[int]"
    assert type_name(typing.Union[int, str]) == "typing.Union[int, str]"
    assert (
        type_name(typing.Union[int, typing.Any])
        == "typing.Union[int, typing.Any]"
    )
    assert (
        type_name(typing_extensions.OrderedDict[int, int])
        == "typing.OrderedDict[int, int]"
    )
    assert (
        type_name(typing.DefaultDict[int, int])
        == "typing.DefaultDict[int, int]"
    )
    assert type_name(typing.Optional[int]) == "typing.Optional[int]"
    assert type_name(typing.Union[None, int]) == "typing.Optional[int]"
    assert type_name(typing.Union[int, None]) == "typing.Optional[int]"
    assert type_name(None) == "None"
    assert type_name(NoneType) == "NoneType"
    assert type_name(NoneType, none_type_as_none=True) == "None"
    assert type_name(typing.List[NoneType]) == "typing.List[NoneType]"
    assert (
        type_name(typing.Union[int, str, None])
        == "typing.Union[int, str, None]"
    )
    assert type_name(typing.Optional[NoneType]) == "NoneType"

    if PY_310_MIN:
        assert type_name(int | None) == "typing.Optional[int]"
        assert type_name(None | int) == "typing.Optional[int]"
        assert type_name(int | str) == "typing.Union[int, str]"
    if PY_310_MIN:
        assert (
            type_name(MyDatetimeNewType) == "tests.entities.MyDatetimeNewType"
        )
    else:
        assert type_name(MyDatetimeNewType) == type_name(datetime)
    assert (
        type_name(typing_extensions.Annotated[TMyDataClass, None])
        == "tests.entities.MyDataClass"
    )


@pytest.mark.skipif(not PEP_585_COMPATIBLE, reason="requires python 3.9+")
def test_type_name_pep_585():
    assert type_name(list[str]) == "list[str]"
    assert type_name(collections.deque[str]) == "collections.deque[str]"
    assert type_name(tuple[str]) == "tuple[str]"
    assert type_name(tuple[str, ...]) == "tuple[str, ...]"
    assert type_name(tuple[()]) == "tuple[()]"
    assert type_name(set[str]) == "set[str]"
    assert type_name(frozenset[str]) == "frozenset[str]"
    assert type_name(collections.abc.Set[str]) == "collections.abc.Set[str]"
    assert (
        type_name(collections.abc.MutableSet[str])
        == "collections.abc.MutableSet[str]"
    )
    assert type_name(collections.Counter[str]) == "collections.Counter[str]"
    assert (
        type_name(collections.abc.Sequence[str])
        == "collections.abc.Sequence[str]"
    )
    assert (
        type_name(collections.abc.MutableSequence[str])
        == "collections.abc.MutableSequence[str]"
    )
    assert (
        type_name(collections.ChainMap[str, str])
        == "collections.ChainMap[str, str]"
    )
    assert type_name(dict[str, str]) == "dict[str, str]"
    assert (
        type_name(collections.abc.Mapping[str, str])
        == "collections.abc.Mapping[str, str]"
    )
    assert (
        type_name(collections.OrderedDict[str, str])
        == "collections.OrderedDict[str, str]"
    )
    assert (
        type_name(collections.defaultdict[str, str])
        == "collections.defaultdict[str, str]"
    )


def test_type_name_short():
    assert type_name(TAny, short=True) == "Any"
    assert type_name(TInt, short=True) == "int"
    assert type_name(TMyDataClass, short=True) == "MyDataClass"
    assert type_name(TIntStr, short=True) == "Union[int, str]"
    assert type_name(typing.List[TInt], short=True) == "List[int]"
    assert type_name(typing.Tuple[int], short=True) == "Tuple[int]"
    assert type_name(typing.Tuple[int, ...], short=True) == "Tuple[int, ...]"
    assert type_name(typing.Tuple[()], short=True) == "Tuple[()]"
    assert type_name(typing.Set[int], short=True) == "Set[int]"
    assert type_name(typing.FrozenSet[int], short=True) == "FrozenSet[int]"
    assert type_name(typing.Deque[int], short=True) == "Deque[int]"
    assert type_name(typing.Dict[int, int], short=True) == "Dict[int, int]"
    assert (
        type_name(typing.Mapping[int, int], short=True) == "Mapping[int, int]"
    )
    assert (
        type_name(typing.MutableMapping[int, int], short=True)
        == "MutableMapping[int, int]"
    )
    assert type_name(typing.Counter[int], short=True) == "Counter[int]"
    assert (
        type_name(typing.ChainMap[int, int], short=True)
        == "ChainMap[int, int]"
    )
    assert type_name(typing.Sequence[int], short=True) == "Sequence[int]"
    assert type_name(typing.Union[int, str], short=True) == "Union[int, str]"
    assert (
        type_name(typing.Union[int, typing.Any], short=True)
        == "Union[int, Any]"
    )
    assert (
        type_name(typing_extensions.OrderedDict[int, int], short=True)
        == "OrderedDict[int, int]"
    )
    assert (
        type_name(typing.DefaultDict[int, int], short=True)
        == "DefaultDict[int, int]"
    )
    assert type_name(typing.Optional[int], short=True) == "Optional[int]"
    assert type_name(typing.Union[None, int], short=True) == "Optional[int]"
    assert type_name(typing.Union[int, None], short=True) == "Optional[int]"
    assert type_name(None, short=True) == "None"
    assert type_name(NoneType, short=True) == "NoneType"
    assert type_name(NoneType, short=True, none_type_as_none=True) == "None"
    assert type_name(typing.List[NoneType], short=True) == "List[NoneType]"
    assert (
        type_name(typing.Union[int, str, None], short=True)
        == "Union[int, str, None]"
    )
    assert type_name(typing.Optional[NoneType], short=True) == "NoneType"

    if PY_310_MIN:
        assert type_name(int | None, short=True) == "Optional[int]"
        assert type_name(None | int, short=True) == "Optional[int]"
        assert type_name(int | str, short=True) == "Union[int, str]"
    if PY_310_MIN:
        assert type_name(MyDatetimeNewType, short=True) == "MyDatetimeNewType"
    else:
        assert type_name(MyDatetimeNewType, short=True) == type_name(
            datetime, short=True
        )
    assert (
        type_name(typing_extensions.Annotated[TMyDataClass, None], short=True)
        == "MyDataClass"
    )


@pytest.mark.skipif(not PEP_585_COMPATIBLE, reason="requires python 3.9+")
def test_type_name_pep_585_short():
    assert type_name(list[str], short=True) == "list[str]"
    assert type_name(collections.deque[str], short=True) == "deque[str]"
    assert type_name(tuple[str], short=True) == "tuple[str]"
    assert type_name(tuple[str, ...], short=True) == "tuple[str, ...]"
    assert type_name(tuple[()], short=True) == "tuple[()]"
    assert type_name(set[str], short=True) == "set[str]"
    assert type_name(frozenset[str], short=True) == "frozenset[str]"
    assert type_name(collections.abc.Set[str], short=True) == "Set[str]"
    assert (
        type_name(collections.abc.MutableSet[str], short=True)
        == "MutableSet[str]"
    )
    assert type_name(collections.Counter[str], short=True) == "Counter[str]"
    assert (
        type_name(collections.abc.Sequence[str], short=True) == "Sequence[str]"
    )
    assert (
        type_name(collections.abc.MutableSequence[str], short=True)
        == "MutableSequence[str]"
    )
    assert (
        type_name(collections.ChainMap[str, str], short=True)
        == "ChainMap[str, str]"
    )
    assert type_name(dict[str, str], short=True) == "dict[str, str]"
    assert (
        type_name(collections.abc.Mapping[str, str], short=True)
        == "Mapping[str, str]"
    )
    assert (
        type_name(collections.OrderedDict[str, str], short=True)
        == "OrderedDict[str, str]"
    )
    assert (
        type_name(collections.defaultdict[str, str], short=True)
        == "defaultdict[str, str]"
    )


def test_get_type_origin():
    assert get_type_origin(typing.List[int]) == list
    assert get_type_origin(typing.List) == list
    assert get_type_origin(MyGenericDataClass[int]) == MyGenericDataClass
    assert get_type_origin(MyGenericDataClass) == MyGenericDataClass
    assert (
        get_type_origin(typing_extensions.Annotated[datetime, None])
        == datetime
    )
    assert (
        get_type_origin(typing_extensions.Required[int])
        == typing_extensions.Required
    )


def test_resolve_type_params():
    @dataclass
    class A(typing.Generic[T]):
        x: T

    @dataclass
    class B(A[int]):
        pass

    resolved = resolve_type_params(B)
    assert resolved[A] == {T: int}
    assert resolved[B] == {}


def test_get_generic_name():
    assert get_generic_name(typing.List[int]) == "typing.List"
    assert get_generic_name(typing.List[int], short=True) == "List"
    assert (
        get_generic_name(MyGenericDataClass[int])
        == "tests.entities.MyGenericDataClass"
    )
    assert (
        get_generic_name(MyGenericDataClass[int], short=True)
        == "MyGenericDataClass"
    )


def test_get_generic_collection_based_class_name():
    assert get_generic_name(MyGenericList, short=True) == "MyGenericList"
    assert get_generic_name(MyGenericList) == "tests.entities.MyGenericList"
    assert get_generic_name(MyGenericList[int], short=True) == "MyGenericList"
    assert (
        get_generic_name(MyGenericList[int]) == "tests.entities.MyGenericList"
    )


def test_is_dialect_subclass():
    class MyDialect(Dialect):
        pass

    assert is_dialect_subclass(Dialect)
    assert is_dialect_subclass(MyDialect)
    assert not is_dialect_subclass(123)


def test_is_union():
    t = typing.Optional[str]
    assert is_union(t)
    assert get_args(t) == (str, NoneType)
    t = typing.Union[str, None]
    assert is_union(t)
    assert get_args(t) == (str, NoneType)
    t = typing.Union[None, str]
    assert is_union(t)
    assert get_args(t) == (NoneType, str)


@pytest.mark.skipif(not PY_310_MIN, reason="requires python 3.10+")
def test_is_union_pep_604():
    t = str | None
    assert is_union(t)
    assert get_args(t) == (str, NoneType)
    t = None | str
    assert is_union(t)
    assert get_args(t) == (NoneType, str)


def test_is_optional():
    t = typing.Optional[str]
    assert is_optional(t)
    assert get_args(t) == (str, NoneType)
    t = typing.Union[str, None]
    assert is_optional(t)
    assert get_args(t) == (str, NoneType)
    t = typing.Union[None, str]
    assert is_optional(t)
    assert get_args(t) == (NoneType, str)


@pytest.mark.skipif(not PY_310_MIN, reason="requires python 3.10+")
def test_is_optional_pep_604():
    t = str | None
    assert is_optional(t)
    assert get_args(t) == (str, NoneType)
    t = None | str
    assert is_optional(t)
    assert get_args(t) == (NoneType, str)


def test_not_non_type_arg():
    assert not_none_type_arg((str, int)) == str
    assert not_none_type_arg((NoneType, int)) == int
    assert not_none_type_arg((str, NoneType)) == str
    assert not_none_type_arg((T, int), {T: NoneType}) == int
    assert not_none_type_arg((NoneType,)) is None


def test_is_new_type():
    assert is_new_type(typing.NewType("MyNewType", int))
    assert not is_new_type(int)


def test_is_annotated():
    assert is_annotated(typing_extensions.Annotated[datetime, None])
    assert not is_annotated(datetime)


def test_is_literal():
    assert is_literal(typing_extensions.Literal[1, 2, 3])
    assert not is_literal(typing_extensions.Literal)
    assert not is_literal([1, 2, 3])


def test_get_literal_values():
    assert get_literal_values(typing_extensions.Literal[1, 2, 3]) == (1, 2, 3)
    assert get_literal_values(
        typing_extensions.Literal[
            1, typing_extensions.Literal[typing_extensions.Literal[2], 3]
        ]
    ) == (1, 2, 3)


def test_type_name_literal():
    if PY_38_MIN:
        module_name = "typing"
    else:
        module_name = "typing_extensions"
    assert type_name(
        typing_extensions.Literal[
            1,
            "a",
            b"\x00",
            True,
            False,
            None,
            MyEnum.a,
            MyStrEnum.a,
            MyNativeStrEnum.a,
            MyIntEnum.a,
            MyFlag.a,
            MyIntFlag.a,
            typing_extensions.Literal[2, 3],
            typing_extensions.Literal[typing_extensions.Literal["b", "c"]],
        ]
    ) == (
        f"{module_name}.Literal[1, 'a', b'\\x00', True, False, None, "
        "tests.entities.MyEnum.a, tests.entities.MyStrEnum.a, "
        "tests.entities.MyNativeStrEnum.a, tests.entities.MyIntEnum.a, "
        "tests.entities.MyFlag.a, tests.entities.MyIntFlag.a, 2, 3, 'b', 'c']"
    )


def test_code_builder_get_pack_method_name():
    builder = CodeBuilder(object)
    type_args = (int,)
    type_args_hash = hash_type_args((int,))
    assert builder.get_pack_method_name() == "to_dict"
    assert (
        builder.get_pack_method_name(type_args=type_args)
        == f"to_dict_{type_args_hash}"
    )
    assert (
        builder.get_pack_method_name(type_args=type_args, format_name="yaml")
        == f"to_dict_yaml_{type_args_hash}"
    )
    assert builder.get_pack_method_name(format_name="yaml") == "to_dict_yaml"
    assert (
        builder.get_pack_method_name(format_name="yaml", encoder=object)
        == "to_yaml"
    )
    assert (
        builder.get_pack_method_name(type_args=type_args, encoder=object)
        == f"to_dict_{type_args_hash}"
    )
    assert builder.get_pack_method_name(encoder=object) == "to_dict"
    assert (
        builder.get_pack_method_name(
            type_args=type_args, format_name="yaml", encoder=object
        )
        == f"to_yaml"
    )


def test_code_builder_get_unpack_method_name():
    builder = CodeBuilder(object)
    type_args = (int,)
    type_args_hash = hash_type_args((int,))
    assert builder.get_unpack_method_name() == "from_dict"
    assert (
        builder.get_unpack_method_name(type_args=type_args)
        == f"from_dict_{type_args_hash}"
    )
    assert (
        builder.get_unpack_method_name(type_args=type_args, format_name="yaml")
        == f"from_dict_yaml_{type_args_hash}"
    )
    assert (
        builder.get_unpack_method_name(format_name="yaml") == "from_dict_yaml"
    )
    assert (
        builder.get_unpack_method_name(format_name="yaml", decoder=object)
        == "from_yaml"
    )
    assert (
        builder.get_unpack_method_name(type_args=type_args, decoder=object)
        == f"from_dict_{type_args_hash}"
    )
    assert builder.get_unpack_method_name(decoder=object) == "from_dict"
    assert (
        builder.get_unpack_method_name(
            type_args=type_args, format_name="yaml", decoder=object
        )
        == f"from_yaml"
    )


def test_is_self():
    assert is_self(typing_extensions.Self)
    assert not is_self(object)


@pytest.mark.skipif(PEP_585_COMPATIBLE, reason="requires python <3.9")
def test_ensure_generic_collection_not_pep_585():
    for t in (
        tuple,
        list,
        set,
        frozenset,
        dict,
        collections.deque,
        collections.ChainMap,
        collections.OrderedDict,
        collections.defaultdict,
        collections.Counter,
    ):
        with pytest.raises(UnserializableField):
            ensure_generic_collection(
                ValueSpec(t, "", CodeBuilder(None), FieldContext("", {}))
            )


def test_ensure_generic_collection_not_generic():
    assert not ensure_generic_collection(
        ValueSpec(int, "", CodeBuilder(None), FieldContext("", {}))
    )


def test_get_function_arg_annotation():
    def foo(x: int, y: Dialect) -> None:
        pass  # pragma no cover

    assert get_function_arg_annotation(foo, "x") == int
    assert get_function_arg_annotation(foo, "y") == Dialect
    assert get_function_arg_annotation(foo, arg_name="x") == int
    assert get_function_arg_annotation(foo, arg_name="y") == Dialect
    assert get_function_arg_annotation(foo, arg_pos=0) == int
    assert get_function_arg_annotation(foo, arg_pos=1) == Dialect
    with pytest.raises(ValueError):
        get_function_arg_annotation(foo)


def test_get_function_return_annotation():
    def foo(x: int, y: Dialect) -> Dialect:
        pass  # pragma no cover

    assert get_function_return_annotation(foo) == Dialect


def test_collect_type_params():
    T = typing.TypeVar("T")
    S = typing.TypeVar("S")

    class MyGeneric(typing.Generic[T, S], typing.Mapping[T, S]):
        pass

    assert collect_type_params(MyGeneric[T, T]) == [T]


def test_is_generic_like_with_class_getitem():
    class MyClass:
        def __class_getitem__(cls, item):
            return cls

    assert is_generic(MyClass)
    assert is_generic(MyClass[int])
