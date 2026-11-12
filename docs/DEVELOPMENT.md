# Development

Source code, synthetic tests, generic documentation, and reproducible project configuration belong in Git. User process inputs, model files, manuals, SSH credentials, private keys, logs, screenshots, and generated archives do not.

## Change loop

1. Make one focused change on a short-lived branch.
2. Add or update a synthetic fixture when a parser or process convention changes.
3. Run the checks below.
4. Inspect `git diff --check`, `git status`, and the file list for private paths or source data.

```bash
python3 -m compileall -q soa_generator tests
python3 -m unittest discover -s tests -v
node -e "const fs=require('fs');const s=fs.readFileSync('web/index.html','utf8').match(/<script>([\\s\\S]*)<\\/script>/)[1];new Function(s);console.log('web script syntax ok')"
git diff --check
```

Project files use `soa-project/v1`. Process differences belong in a private `soa-adapter/v1` JSON file and should be validated with `/api/validate_adapter` before use.

## Privacy checks

- Keep original process data read-only and outside the repository.
- Never store SSH passwords, private keys, or raw credentials in project JSON, tests, or documentation.
- Use synthetic names, paths, limits, and model snippets in fixtures and examples.
- Review generated source packages before sharing them.
