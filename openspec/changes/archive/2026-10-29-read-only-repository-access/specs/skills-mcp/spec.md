## MODIFIED Requirements

### Requirement: MCP Tool Surface
The server SHALL expose exactly five MCP tools — `list_skills`, `get_skill`,
`get_registry_source`, `list_repo_entries` and `read_repo_text_file` —
and one MCP resource template — `skill://{registry}/{+skill}{?file}` — over a
stdio transport using FastMCP. Each tool SHALL carry an explicit `description=`
parameter (not a docstring) as its only contract with the calling model.

#### Scenario: Tool list is stable
- **WHEN** an MCP client connects to the server
- **THEN** exactly the five named tools are advertised, with repository tool descriptions identifying returned data as untrusted and not authorisation to execute commands

#### Scenario: Resource template is advertised
- **WHEN** an MCP client calls `list_resource_templates`
- **THEN** exactly one template is returned with URI pattern `skill://{registry}/{+skill}{?file}`

## ADDED Requirements

### Requirement: Configured Repository Source
`get_registry_source(registry)` SHALL return only the configured GitHub source fields `registry`, `type`, `url`, `owner`, `repo`, `ref` and `skills_dir`, without upstream discovery or authentication data.

#### Scenario: Reports configured source without credentials
- **WHEN** source information is requested after an operator changes the repository configuration and restarts the server
- **THEN** the response reports the new configured identity and constructed HTTPS GitHub URL, without credentials, authentication configuration or upstream requests

### Requirement: Repository Operation Registry Boundary
Repository operations SHALL accept only configured GitHub registry names; unknown names and HTTP registries produce actionable model-recoverable errors.

#### Scenario: Rejects unknown repository registry
- **WHEN** any repository operation names an unconfigured registry
- **THEN** an `is_error=True` result identifies the unknown registry without an upstream request

#### Scenario: Rejects HTTP repository operations
- **WHEN** any repository operation names an HTTP registry
- **THEN** an `is_error=True` result explains that repository access requires a GitHub registry, without fetching the HTTP URL

### Requirement: Repository Directory Listing
`list_repo_entries(registry, path="")` SHALL return `{source,path,commit_sha,entries}` for one directory, including outside `skills_dir`; entries are sorted repository-relative paths with type `file`, `directory`, `symlink` or `submodule` and optional byte size. Empty path selects the root.

#### Scenario: Lists repository directories with provenance
- **WHEN** the root or a nested directory outside the skill root is listed
- **THEN** only immediate children are returned with source identity, requested path and resolved commit SHA, including unsupported symlinks/submodules labelled without following them

#### Scenario: Rejects missing or wrong-kind repository targets
- **WHEN** a safe path is absent, a file is listed as a directory, or a directory is read as a file
- **THEN** an actionable model-recoverable error identifies the target without attempting an unrelated blob read

### Requirement: Repository Snapshot Consistency
Repository browsing and reading SHALL use one immutable snapshot of the configured ref per operation, with all selected path components and file bytes belonging to that snapshot.

#### Scenario: Keeps moving-ref operations on one snapshot
- **WHEN** the configured branch moves while a nested repository file is being read
- **THEN** every selected directory and blob belongs to the initially resolved commit, which is included in the response

### Requirement: Repository Path Boundary
Repository paths SHALL be literal POSIX repository-relative paths of at most 32 components. Absolute paths, dot/dotdot components, empty components, backslashes and control characters are rejected before I/O; only directory listing accepts an empty root path. Percent sequences are literal filename data, not decoded path syntax.

#### Scenario: Rejects unsafe repository paths before I/O
- **WHEN** listing or reading receives an invalid path, including an over-depth path
- **THEN** a model-recoverable path error is returned without upstream requests

### Requirement: Repository Git Entry Boundary
Repository access SHALL follow only directory entries and read only regular or executable file entries, never symlinks or submodules, including in intermediate path components.

#### Scenario: Rejects symlink and submodule targets
- **WHEN** a requested path traverses or selects a symlink or submodule
- **THEN** a model-recoverable unsupported-operation error is returned without following the target

### Requirement: Repository Text Reading
`read_repo_text_file(registry, path)` SHALL return `{source,path,commit_sha,content}` for UTF-8 regular/executable files without NUL bytes, including files outside `skills_dir`, empty files and files of exactly 1 MiB. No local filesystem access or command execution occurs.

#### Scenario: Reads repository text with provenance
- **WHEN** a supported text file is requested
- **THEN** the complete strictly decoded text, configured source, requested path and snapshot commit SHA are returned

#### Scenario: Rejects non-text repository files
- **WHEN** file bytes are invalid UTF-8 or contain NUL
- **THEN** a model-recoverable unsupported-file error is returned without partial content

### Requirement: Bounded Repository File Retrieval
Repository file reading SHALL reject advertised or actual file bytes exceeding 1 MiB, bounding actual retrieval even when advertised metadata is incorrect and closing responses on success, failure and cancellation.

#### Scenario: Rejects advertised oversized files before download
- **WHEN** a regular file advertises more than 1 MiB
- **THEN** a model-recoverable size error is returned without requesting its blob

#### Scenario: Stops oversized downloads and closes streams
- **WHEN** a file download exceeds 1 MiB despite its metadata
- **THEN** retrieval stops at the limit check, the response closes and a model-recoverable size error is returned without partial content

### Requirement: Complete Bounded Repository Metadata
Repository operations SHALL reject truncated or malformed metadata rather than return apparently complete results. Tree responses are limited to 10,000 entries and 2 MiB each; cumulative metadata including retries is limited to 8 MiB and serialized listing output to 2 MiB.

#### Scenario: Rejects incomplete or malformed repository metadata
- **WHEN** metadata is truncated, invalid, missing required fields, contains unsupported modes or exceeds a response/entry/output limit
- **THEN** an infrastructure error identifies incomplete or invalid upstream data without returning partial entries

#### Scenario: Stops operations exceeding cumulative metadata budget
- **WHEN** metadata retrieval across an operation, including retries, exceeds 8 MiB
- **THEN** further traversal stops with an infrastructure error and all opened responses close

### Requirement: Repository Operation Deadline
Repository browsing and reading SHALL enforce a 60-second total operation deadline covering upstream activity, retry waiting and cancellation-safe response cleanup. A cleanup attempt that cannot finish within the deadline prevents success or further retries and produces an infrastructure error unless preserving an existing failure or caller cancellation; an uncooperative transport cannot be forcibly closed.

#### Scenario: Stops repository operations at deadline
- **WHEN** upstream activity, retry waiting or response cleanup stalls
- **THEN** the operation returns an infrastructure error without partial content within the total deadline, after a bounded cleanup attempt

#### Scenario: Preserves caller cancellation after bounded cleanup
- **WHEN** a caller cancels an active repository operation, including one whose response close stalls
- **THEN** cancellation propagates after a bounded shielded cleanup attempt without extending the total operation deadline

### Requirement: Repository Upstream Failures
Repository operations SHALL preserve existing error classification and bounded rate-limit retry behaviour, reject redirects, and exclude credentials, raw upstream bodies and exception details from diagnostics. Missing configured refs or snapshot objects are infrastructure failures; missing user-selected paths are model-recoverable.

#### Scenario: Retries repository rate limits after closing response
- **WHEN** a repository request returns 429 or 403 with Retry-After
- **THEN** the response closes before one capped retry, and exhaustion produces an infrastructure error

#### Scenario: Reports sanitized repository infrastructure errors
- **WHEN** repository requests encounter redirects, missing refs/objects, HTTP errors or transport failures
- **THEN** an infrastructure error is returned without raw body or credential-bearing exception details, responses close and other registries remain usable

### Requirement: Uncached Repository Operations
New repository operations SHALL bypass existing disk-cache entries and writes, leaving skill caching unchanged.

#### Scenario: Repository operations bypass disk cache
- **WHEN** source, listing or text-reading operations are repeated with disk caching enabled, including SHA-locked registries
- **THEN** source information comes from current loaded configuration and each listing/read reaches upstream without accessing or writing disk cache entries
