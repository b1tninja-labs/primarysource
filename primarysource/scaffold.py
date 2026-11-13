"""The MCP scaffold: how a collection's tools are registered, and how `primarysource mcp` serves collections.

Three rules from PLAN.md §5, enforced here so no collection has to remember them:

- **Errors** (§5.10). `guard` turns a `LibError` into the SDK's `ToolError`, which reaches the client as an
  `isError` result. Its text is the `error:`, `hint:` and `action:` lines of `LibError.as_text`. The SDK puts
  `Error executing tool <name>:` in front of every tool error's text, so the lines start after a newline: each
  field is then at the start of its own line, where a reader or a regex finds it.
- **Text only** (§5.9). Every tool is registered with `structured_output=False`, so a result is never sent twice
  (as text and again as `structuredContent`) and no tool advertises an output schema.
- **Prefixed names** (§5.12). `compose` builds the server `primarysource mcp` runs, from one or more collections'
  own servers, naming every tool and prompt `<collection>_<name>` (a name that already carries the prefix keeps
  it). `bare=True` keeps each collection's own names, for the old single-collection commands. A name, resource
  URI or HTTP route that two collections both want is refused at startup, never silently shadowed.

This module imports only the standard library and the core at import time; `mcp` is imported when a server is
built, so the core and every collection import without the `[mcp]` extra (§5.13).
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from primarysource.errors import LibError


def tool_error(exc: LibError) -> Exception:
    """The SDK `ToolError` for `exc`: the fixed error lines, each at the start of a line of the result text."""
    from mcp.server.mcpserver.exceptions import ToolError

    error: Exception = ToolError("\n" + exc.as_text())
    return error


def guard[F: Callable[..., Any]](fn: F) -> F:
    """Wrap a tool so a `LibError` becomes `tool_error(exc)`. Sync and async tools both keep their signature,
    which the SDK reads to build the input schema."""
    if getattr(fn, "__primarysource_guarded__", False):
        return fn
    if inspect.iscoroutinefunction(fn):
        async_fn = cast(Callable[..., Awaitable[Any]], fn)

        @functools.wraps(fn)
        async def guarded_async(*args: Any, **kwargs: Any) -> Any:
            try:
                return await async_fn(*args, **kwargs)
            except LibError as exc:
                raise tool_error(exc) from None

        wrapped: Any = guarded_async
    else:

        @functools.wraps(fn)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except LibError as exc:
                raise tool_error(exc) from None

        wrapped = guarded
    wrapped.__primarysource_guarded__ = True
    return cast(F, wrapped)


def add_tools(server: Any, tools: Iterable[Callable[..., Any]], *, prefix: str = "", annotations: Any = None) -> None:
    """Register `tools` on an `MCPServer` the way every collection must: guarded, text only, and named
    `prefix + fn.__name__` unless the function's name already starts with `prefix`."""
    for fn in tools:
        name = fn.__name__ if fn.__name__.startswith(prefix) else prefix + fn.__name__
        server.add_tool(guard(fn), name=name, annotations=annotations, structured_output=False)


@dataclass(frozen=True, slots=True)
class Served:
    """One collection to serve: its registry name and title, and the `MCPServer` its own module built."""

    name: str
    title: str
    server: Any


def public_name(collection: str, name: str, *, bare: bool = False) -> str:
    """The name `primarysource mcp` gives a collection's tool or prompt: `<collection>_<name>`, or `name` as it
    is when it already starts with that prefix or when `bare` keeps the collection's own names."""
    prefix = f"{collection}_"
    return name if bare or name.startswith(prefix) else prefix + name


def _clash(kind: str, key: str, first: str, second: str, bare: bool) -> LibError:
    if first == second:
        return LibError(f"collection {first!r} defines the {kind} {key!r} twice", "")
    if bare:
        hint = "drop --bare-names, which suits one collection only, or serve them from separate processes"
    else:
        hint = "serve them from separate processes, or rename one of them in its collection"
    return LibError(f"the {kind} {key!r} is wanted by both {first!r} and {second!r}", hint)


def _instructions(served: Sequence[Served], bare: bool) -> str:
    if bare and len(served) == 1:
        return str(served[0].server.instructions or "")
    parts = []
    for item in served:
        text = str(item.server.instructions or "").strip()
        head = f"[{item.name}] {item.title}." + ("" if bare else f" Tools are named {item.name}_<tool>.")
        parts.append(f"{head} {text}" if text else head)
    return "\n\n".join(parts)


def compose(served: Sequence[Served], *, bare: bool = False) -> Any:
    """One `MCPServer` serving every tool, prompt, resource and HTTP route of `served`, renamed by `public_name`.

    Each tool is rebuilt from its function with `structured_output=False` and behind `guard`, so the contract
    holds whatever the collection registered. Each collection keeps its own state (database, home directory,
    loaded corpus): its functions are reused, not copied. A collection's completion handler is carried over: a
    request for a renamed prompt reaches it under the prompt's own name, and one for a resource template reaches
    the collection that owns the template. A clash raises `LibError` before anything runs.
    """
    if not served:
        raise LibError("no collection to serve", "primarysource mcp --collection <name>")
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.tools import Tool

    tools: dict[str, tuple[str, Any]] = {}
    prompts: dict[str, tuple[str, Any]] = {}
    prompt_names: dict[str, str] = {}  # public prompt name -> the name its collection gave it
    completers: dict[str, Any] = {}  # collection -> its own `completion/complete` handler
    resources: dict[str, tuple[str, Any]] = {}
    templates: dict[str, tuple[str, Any]] = {}
    routes: dict[str, tuple[str, Any]] = {}

    def claim(table: dict[str, tuple[str, Any]], kind: str, key: str, owner: str, value: Any) -> None:
        if key in table:
            raise _clash(kind, key, table[key][0], owner, bare)
        table[key] = (owner, value)

    for item in served:
        source = item.server
        for tool in source._tool_manager.list_tools():
            name = public_name(item.name, tool.name, bare=bare)
            rebuilt = Tool.from_function(
                guard(tool.fn),
                name=name,
                title=tool.title,
                description=tool.description,
                annotations=tool.annotations,
                icons=tool.icons,
                meta=tool.meta,
                structured_output=False,
            )
            claim(tools, "tool", name, item.name, rebuilt)
        for prompt in source._prompt_manager.list_prompts():
            name = public_name(item.name, prompt.name, bare=bare)
            claim(prompts, "prompt", name, item.name, prompt.model_copy(update={"name": name}))
            prompt_names[name] = prompt.name
        for resource in source._resource_manager.list_resources():
            claim(resources, "resource", str(resource.uri), item.name, resource)
        for template in source._resource_manager.list_templates():
            claim(templates, "resource template", template.uri_template, item.name, template)
        for route in source._custom_starlette_routes:
            claim(routes, "HTTP route", f"{route.path} {sorted(route.methods or ())}", item.name, route)
        entry = source._lowlevel_server.get_request_handler("completion/complete")
        if entry is not None:
            completers[item.name] = entry.handler

    name = served[0].server.name if len(served) == 1 else "primarysource"
    server = MCPServer(
        name,
        version=str(served[0].server.version or "") if len(served) == 1 else _version(),
        instructions=_instructions(served, bare),
        tools=[tool for _, tool in tools.values()],
    )
    for _, prompt in prompts.values():
        server.add_prompt(prompt)
    for _, resource in resources.values():
        server.add_resource(resource)
    for _, template in templates.values():
        server._resource_manager._templates[template.uri_template] = template
    server._custom_starlette_routes.extend(route for _, route in routes.values())
    if completers:
        _carry_completions(server, completers, prompts, prompt_names, templates)
    return server


def _carry_completions(
    server: Any,
    completers: dict[str, Any],
    prompts: dict[str, tuple[str, Any]],
    prompt_names: dict[str, str],
    templates: dict[str, tuple[str, Any]],
) -> None:
    """Register one `completion/complete` handler on `server` that hands each request to the collection owning
    the prompt or resource template it names, with the prompt's public name turned back into the collection's.
    A request for something no collection completes gets no values, as the SDK answers when a handler returns
    nothing."""
    from mcp.types import CompleteRequestParams, CompleteResult, Completion, PromptReference

    async def complete(ctx: Any, params: CompleteRequestParams) -> CompleteResult:
        ref = params.ref
        if isinstance(ref, PromptReference):
            owner = prompts.get(ref.name, ("", None))[0]
            if owner in completers:
                original = ref.model_copy(update={"name": prompt_names[ref.name]})
                params = params.model_copy(update={"ref": original})
        else:
            owner = templates.get(ref.uri, ("", None))[0]
        handler = completers.get(owner)
        if handler is None:
            return CompleteResult(completion=Completion(values=[]))
        result: CompleteResult = await handler(ctx, params)
        return result

    server._lowlevel_server.add_request_handler("completion/complete", CompleteRequestParams, complete)


def _version() -> str:
    from primarysource import __version__

    return __version__
