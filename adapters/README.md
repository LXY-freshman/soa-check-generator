# Process adapters

An adapter is an independent `soa-adapter/v1` JSON file. It describes private naming conventions and evidence without modifying the source model files.

Copy `example.json`, then replace its synthetic identifiers and evidence with values from a private environment. Validate the result through `/api/validate_adapter` or the adapter tests before importing it.

`pattern` uses Python regular expressions. A matching rule may set `category`, `family`, `scope`, voltage metadata, topology, isolation type, and port roles. Unmatched devices continue through the built-in generic classifier.

An adapter may also provide `check_rules` as documented evidence. Each rule needs a pattern and Spectre expression; optional limits, terminal pairs, source path, page, and note are retained as provenance. These values are never written back to the original input.

Isolation junctions must name actual model-visible P/N ports and should be declared only when private documentation or model evidence supports them. The engine creates separate reverse and forward candidates, keeps them disabled by default, and does not turn a naming hint into a confirmed limit. Dielectric isolation can be marked to suppress PN-junction templates.

Example structure:

```json
{
  "pattern": "^demo_isolated_",
  "isolation_type": "junction",
  "port_roles": {"deep_well": "isolation_well", "substrate": "bulk_substrate"},
  "isolation_junctions": [
    {"p_port": "substrate", "n_port": "deep_well", "source": {"path": "private-manual.pdf"}}
  ]
}
```

Keep private manuals, model files, credentials, and source paths out of public commits. The public example intentionally contains no process-specific limits.
