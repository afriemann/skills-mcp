# registry-instructions Specification

## Purpose
TBD - created by archiving change registry-instructions-field. Update Purpose after archive.
## Requirements
### Requirement: Registry Instructions Field
Both `GithubRegistry` and `HttpRegistry` configuration entries SHALL support an
optional `instructions` field. When present and non-empty, its value SHALL be a
non-empty string stored on the registry model. When absent or empty, the field
SHALL default to `None`. The field is operator-supplied config and is never
settable by an agent.

#### Scenario: GitHub registry with instructions parses correctly
- **WHEN** a GitHub registry entry in the config contains `"instructions": "Call list_skills('my-reg') at the start of every session"`
- **THEN** the parsed `GithubRegistry` has `instructions == "Call list_skills('my-reg') at the start of every session"`

#### Scenario: HTTP registry with instructions parses correctly
- **WHEN** an HTTP registry entry in the config contains a non-empty `instructions` string
- **THEN** the parsed `HttpRegistry` has `instructions` equal to that string

#### Scenario: Registry without instructions defaults to None
- **WHEN** a registry entry contains no `instructions` field
- **THEN** the parsed registry dataclass has `instructions == None`

#### Scenario: Empty string instructions treated as None
- **WHEN** a registry entry contains `"instructions": ""`
- **THEN** the parsed registry dataclass has `instructions == None`

### Requirement: Config-Assembled list_registries Description
The server SHALL expose a module-level pure function
`_build_list_skills_description(cfg: Config) -> str` that assembles the
`list_skills` tool description from the loaded configuration. The assembled
string SHALL begin with the current static introductory text for `list_skills`,
then append one entry per configured registry in config order. Each entry SHALL
include the registry name. When the registry has a non-None `description`, it
SHALL be included. When the registry has a non-None `instructions`, it SHALL be
appended to that registry's entry. Registries with no `instructions` SHALL appear
without a call-to-action. The `list_skills` tool SHALL be registered using the
result of this function as its `description=` parameter. The `get_skill` tool
description SHALL remain unchanged.

#### Scenario: Description with no registries configured
- **WHEN** `_build_list_skills_description` is called with a config containing no registries
- **THEN** the result contains the static intro text and no registry-specific lines

#### Scenario: Description with registry having description and instructions
- **WHEN** `_build_list_skills_description` is called with a registry that has both `description` and `instructions` set
- **THEN** the result contains the registry name, its description text, and its instructions text

#### Scenario: Description with registry having description only
- **WHEN** `_build_list_skills_description` is called with a registry that has `description` set but `instructions == None`
- **THEN** the result contains the registry name and description but no instructions line for that registry

#### Scenario: Description with registry having neither description nor instructions
- **WHEN** `_build_list_skills_description` is called with a registry where both `description` and `instructions` are `None`
- **THEN** the result contains the registry name only, with no description or instructions lines

#### Scenario: Description with instructions only (no description)
- **WHEN** `_build_list_skills_description` is called with a registry that has `instructions` set but `description == None`
- **THEN** the result contains the registry name and instructions text but no description line

#### Scenario: Multiple registries appear in config order
- **WHEN** `_build_list_skills_description` is called with two registries
- **THEN** both appear in the result in the order they are defined in the config
