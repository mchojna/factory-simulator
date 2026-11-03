# Operational record

The server records every HTTP operation, every startup and every shutdown in DuckDB,
beside the record of the factory. It keeps the exact bodies of requests and responses,
the times and what the transport reports. A running agent reads only the description,
the observation and the closed periods of its run. The export of a finished run and the
offline bundle hold the bodies of the operations.

## Operation rows

A database sequence gives each operation a position in `operation_identities`. A
position never changes. `operations` holds what the server observes about the operation
at each position. Requests that run at the same time can end in another order than
their positions. The positions can skip numbers, and a skipped number stays unused.

| Columns | Values |
| --- | --- |
| `position`, `request_id` | The position in the order of the database and the unique identifier of the request. |
| `kind`, `state` | `http`, `startup` or `shutdown`; `received`, `completed`, `failed` or `interrupted`. |
| `status_code` | The status of the response, or null. |
| `correlation_id` | The `x-correlation-id` the client sends, or null. |
| `method`, `path`, `route` | The HTTP method, the decoded path and the matched route template, when known. |
| `raw_path`, `query` | The bytes of the encoded path and of the query; the encoded path is null when ASGI gives none. |
| `requested_run_id` | The run identifier in the path, also an unknown one. |
| `run_id`, `created_run_id` | The run, when it exists, and the run the operation creates. A fork names the run it repeats and the new run. |
| `manifest_id`, `scenario_id` | The identifiers of the manifest and the scenario, when known, or null. |
| `started_at`, `generated_at`, `finished_at`, `recovered_at` | UTC times in ISO format. A time the server does not observe is null. |
| `duration_ns` | The time of the processing in nanoseconds, when observed. |
| `request_complete`, `response_generated` | Whether the record holds the complete request, and whether the complete response is generated. |
| `request_bytes`, `response_bytes` | The lengths of the complete bodies, when known; an empty complete body has length 0. |
| `headers_attempted`, `headers_sent` | Whether the send of the response headers starts, and whether it returns. |
| `attempted_bytes`, `sent_bytes` | The body bytes whose send starts, and the body bytes whose send returns. |
| `request_headers`, `response_headers` | The selected protocol headers, in their order. |
| `exception_type`, `exception_message`, `exception_traceback` | The type, the text and the traceback of an exception, when known. |

A handled 404, 409 or 422 ends its HTTP operation with state `completed`. An exception
the server does not handle gives state `failed`, and the record keeps the fixed 500 body
of its response. A receive or a send that is cut off gives state `interrupted`. An
operation still in `received` at a restart gets state `interrupted` and `recovered_at`;
its end time and its duration stay null.

The record writes the names and values of headers as Latin-1 text in JSON pairs, so
the bytes can be rebuilt. The selected names are `host`, `accept`, `accept-encoding`,
`content-type`, `content-length`, `content-disposition`, `user-agent`, `allow`,
`location`, `etag`, `last-modified`, `cache-control`, `x-correlation-id` and
`x-request-id`. The record leaves out every other header, such as authentication and
cookie headers.

## Body chunks

`operation_bodies` holds each body in chunks. A chunk names its `operation_id`, which is
the position of its operation. Its `direction` is `request` or `response`; its
`position` starts at 1 in each direction. `body` holds at most 65536 bytes, and `digest`
is their SHA-256. The bytes are exact: white space, the spelling of decimals, left out
defaults, malformed JSON and invalid UTF-8 stay as the client sent them. An empty
complete body has no chunks.

The recorder writes a request to a temporary file first and copies it to the database
in chunks of bounded size. Every write to the database uses a short transaction. The
server releases its database connection before it computes the factory or sends a
response. A write of the record that waits runs outside the event loop, so other
requests go on.

## Transport observations

`response_generated` is true when the application has produced the complete response
body. The send counters count the calls to the ASGI transport that end, with or without
an error. A successful return shows only that the send call ended; the client may still
miss the bytes. A send that is cut off can leave its result unknown. For HEAD, the
record keeps the body the application produces, even when the transport leaves it out
of the response to the client.

A replay of the factory compares the tables of the factory and the snapshots of the
trace. The times, request identifiers and transport facts of the operations follow
their own order and checks.

## Finished run export

`GET /api/v1/runs/{id}/export` holds these files beside the factory tables and the
inputs of the run:

| File | Contents |
| --- | --- |
| `operations.parquet` | The operations of the run, with the operations that create or fork it. |
| `operation_bodies.parquet` | The exact chunks of the requests and responses; the responses of earlier exports appear only as references. |
| `operations.json` | The format, the run, the last operation included, the chunk size and the references to bodies held outside the export. |

The last operation included comes before the export itself, so an export leaves out its
own request and response. A successful response of an earlier export appears as a
reference: its operation, direction, chunk position, digest and length in bytes. Its
bytes stay in DuckDB and go into the offline bundle. So an export of a run that is
exported many times keeps a bounded size.

## Offline bundle

Stop the server with a normal shutdown, then run:

```sh
uv run python -m factory_simulator.api.record.transport \
  data/records/runs.duckdb data/records/transport.zip
```

The command opens the database read-only, with the package version that wrote it. It
checks the order of the chunks, the digests, the complete lengths and every reference
to an earlier export. The bundle holds every recorded body up to its last operation,
the responses of earlier exports and the operations without a run included. Its
`operations.json` holds the checksum of the database, the version and the counts of the
checks. The command refuses to write over an existing file.

The database grows with the recorded bodies and the facts of their operations. Each HTTP
export adds its own bytes to the database and to the offline bundle. The work of an
export and of its checks grows with the history and the references to earlier exports.
The server keeps every recorded operation. An ordinary request costs the same, whatever
the history, for a body of the same size.

## Availability and recovery

When the server cannot store the start of an operation, it gives a 503 response before
the handler of the route runs and logs the error. When the database fails, the writes it
misses are lost. When a later write of an operation fails, the operation keeps the last
facts stored; they can be incomplete.

The record of a startup begins once the database opens and its schema is accepted. An
error before that point appears only in the error output of the startup command. A
normal shutdown records its own operation. A restart gives every unfinished operation a
recovery time and rebuilds the open period of the factory by its normal replay. See
[Measures and the record](measures-and-the-record.md).
