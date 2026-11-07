# Build a physical check matrix before exporting rules

The generator will derive a physical check matrix for each device from its ports, topology, device family, model evidence, and process documentation. Every applicable check remains visible even when its value is missing or inferred; missing values are left blank, inferred values require an explicit user action, and only complete enabled checks are exported. This preserves coverage without silently turning guesses into Spectre assertions.

The UI will show the generation route and source priority for every candidate, retain conflicting sources, and allow users to mark a native source as suspect and replace it in the derived configuration without changing the PDK. User-confirmed values always rank first; the default source order is native SOA, process documentation, model parameters, then experience inference. The parser UI can reorder source categories for a process, while each check can choose a different source only when multiple candidates or a conflict exists.

Manual values and inference fills remain visibly distinct. Before export, a credibility check will navigate through missing, conflicting, inferred, or otherwise unconfirmed items; a force-export action is allowed only after those risks are shown to the user.
