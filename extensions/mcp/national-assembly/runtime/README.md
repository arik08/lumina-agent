# National Assembly MCP runtime

This directory contains the repository-bundled runtime for
[`hollobit/assembly-api-mcp`](https://github.com/hollobit/assembly-api-mcp) at
commit `f74c6b452c59d87e2fa7265fd985b90e4057a8ef`.

`index.js` and `244.index.js` were produced with `@vercel/ncc` 0.38.4 after
applying `assembly-api-mcp-network-retry.patch`. Runtime dependencies are
included in the bundle, so a normal Lumina installation does not clone the
upstream repository or run `npm install` for this MCP.

`NATIONAL_ASSEMBLY_MCP_DIR` remains available only for maintainers who
explicitly want to run and rebuild a compatible upstream checkout.

The upstream license is in `UPSTREAM_LICENSE.txt`; bundled dependency notices
are in `licenses.txt`.
