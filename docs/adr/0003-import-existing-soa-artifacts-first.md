# Import existing SOA artifacts before inferring rules

The surveyed PDKs already ship executable SOA data, but they use at least two different mechanisms: Spectre `assert`/eSOA files and model-internal `gsoa`/`bsource` behavior. The generator will first discover and parse the PDK's own SOA artifact, preserve its raw expressions and provenance, and generate a versioned derived file. The source is evidence rather than an immutable authority: users can override it in the derived configuration. Inference is a fallback for missing fields or missing rules, and it must remain visibly marked as inferred.

**Status**: accepted

**Consequences**: The importer needs mechanism detection, separate parsers for `sub` and `subs`, and a model-internal SOA classification. The UI must explain whether a value came from an executable assert, a model parameter, or an inference; “edit SOA” means editing the derived output configuration and never rewriting the source PDK. Export must support selecting one rule, a subset, or all rules, and import must recover the editable configuration.
