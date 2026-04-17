## Review guidelines

<!-- This section is read by Codex CLI during automated PR reviews. -->
<!-- Customize these rules for your project's specific architecture and conventions. -->

- Focus on correctness and security; ignore style/formatting (linters handle that)
- Flag cross-boundary imports as high priority violations
- All API endpoints must have proper authentication
- Database queries must use parameterized statements, never string interpolation
- New endpoints must match any documented API contracts
- Pydantic Update schemas must include all fields the endpoint accepts (exclude_unset silently drops unrecognized fields)
- Do not flag pre-existing issues in unchanged code
