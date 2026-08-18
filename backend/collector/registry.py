"""Code-first adapter registry (FR-1).

Adding a site type = one adapter module + one `@register` row;
reusing a registered adapter = registry row only, no code change.
"""

from .ports import AdapterNotFound, SourcePort

_ADAPTERS: dict[str, type] = {}


def register(key: str):
    """Decorator: register an adapter class under a kebab-case adapter_key.

    The class must implement the SourcePort protocol (fetch/parse).
    """

    def decorator(cls):
        if not isinstance(cls, SourcePort):
            raise TypeError(
                f'adapter class {cls.__name__} must implement SourcePort '
                '(fetch/parse)'
            )
        _ADAPTERS[key] = cls
        return cls

    return decorator


def clear():
    """Remove all registered adapters (test isolation)."""
    _ADAPTERS.clear()


def get_adapter(key: str) -> type:
    """Resolve an adapter_key to its class; unknown keys raise AdapterNotFound."""
    if not isinstance(key, str):
        raise AdapterNotFound(f'unknown adapter key: {key}')
    try:
        return _ADAPTERS[key]
    except KeyError:
        raise AdapterNotFound(f'unknown adapter key: {key}') from None