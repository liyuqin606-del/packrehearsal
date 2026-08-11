# Examples

Files in this directory are generated validation samples from PackRehearsal's
own repository. They demonstrate output shape and deterministic self-checking;
they are **not** evidence of external adoption.

- `self-scan.json`: safe static scan of the source tree at the delivered state.
- `self-scan-receipt.json`: timestamped receipt binding that report's hash.

Regenerate before a public release:

```bash
packrehearsal scan . --format json --output examples/self-scan.json \
  --receipt examples/self-scan-receipt.json
```
