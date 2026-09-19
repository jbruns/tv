"""Restricted one-document YAML parsing."""

import copy
from dataclasses import dataclass

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from coreelec_reconciler.domain.diagnostics import Diagnostic


class _RestrictedLoader(yaml.SafeLoader):
    pass


_RestrictedLoader.yaml_implicit_resolvers = copy.deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)


for first_character, resolvers in tuple(
    _RestrictedLoader.yaml_implicit_resolvers.items()
):
    _RestrictedLoader.yaml_implicit_resolvers[first_character] = [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]


def _construct_mapping(
    loader: _RestrictedLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConstructorError(
                None,
                None,
                "mapping keys must be strings",
                key_node.start_mark,
            )
        if key == "<<":
            raise ConstructorError(
                None,
                None,
                "merge keys are forbidden",
                key_node.start_mark,
            )
        if key in result:
            raise ConstructorError(
                None,
                None,
                f"duplicate mapping key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_RestrictedLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True, slots=True)
class ParsedYaml:
    value: dict[str, object] | None
    diagnostics: tuple[Diagnostic, ...]


def _diagnostic(
    source: str,
    code: str,
    message: str,
    line: int,
    column: int,
) -> ParsedYaml:
    return ParsedYaml(
        value=None,
        diagnostics=(
            Diagnostic(
                source=source,
                line=line,
                column=column,
                path=(),
                code=code,
                message=message,
            ),
        ),
    )


def parse_restricted_yaml(content: str, source: str) -> ParsedYaml:
    try:
        for token in yaml.scan(content, Loader=_RestrictedLoader):
            if isinstance(token, AnchorToken):
                return _diagnostic(
                    source,
                    "yaml.unsafe-anchor",
                    "YAML anchors are forbidden.",
                    token.start_mark.line + 1,
                    token.start_mark.column + 1,
                )
            if isinstance(token, AliasToken):
                return _diagnostic(
                    source,
                    "yaml.unsafe-alias",
                    "YAML aliases are forbidden.",
                    token.start_mark.line + 1,
                    token.start_mark.column + 1,
                )
            if isinstance(token, TagToken):
                return _diagnostic(
                    source,
                    "yaml.unsafe-tag",
                    "YAML tags are forbidden.",
                    token.start_mark.line + 1,
                    token.start_mark.column + 1,
                )
        documents = list(yaml.load_all(content, Loader=_RestrictedLoader))
    except ConstructorError as error:
        mark = error.problem_mark
        message = error.problem or "Invalid YAML mapping."
        if "duplicate mapping key" in message:
            code = "yaml.duplicate-key"
        elif "merge keys" in message:
            code = "yaml.merge-key"
        elif "strings" in message:
            code = "yaml.non-string-key"
        else:
            code = "yaml.syntax"
        return _diagnostic(
            source,
            code,
            message,
            (mark.line + 1) if mark is not None else 1,
            (mark.column + 1) if mark is not None else 1,
        )
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return _diagnostic(
            source,
            "yaml.syntax",
            "Invalid YAML syntax.",
            (mark.line + 1) if mark is not None else 1,
            (mark.column + 1) if mark is not None else 1,
        )
    if len(documents) != 1:
        return _diagnostic(
            source,
            "yaml.multiple-documents",
            "Exactly one YAML document is required.",
            1,
            1,
        )
    value = documents[0]
    if not isinstance(value, dict):
        return _diagnostic(
            source,
            "yaml.document-not-mapping",
            "The YAML document must be a mapping.",
            1,
            1,
        )
    return ParsedYaml(value=value, diagnostics=())
