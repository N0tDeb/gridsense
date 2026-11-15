# Security

## Supported use

GridSense 0.4.4 is a local simulation application. Its CLI binds the service to
`127.0.0.1`. It has no multiuser authentication or access controls. Deployment
to a shared or public network requires a separate access-control design and
review. Scenario and export inputs are simulated data, not field controls.

Dependencies are locked in `requirements-dev.lock` and
`frontend/package-lock.json`. The GitHub checks run `pip check`, Python lint,
application tests and an npm audit that fails on high or critical advisories.
An audit result describes the advisory database at the time of the check.

## Report a vulnerability

Use the repository's **Security → Report a vulnerability** form when private
vulnerability reporting is enabled. If the form is unavailable, ask the
maintainer to provide a private reporting channel before sharing sensitive
details. This archive does not specify a maintainer contact or response-time
commitment.

Include the affected version, reproduction steps and impact. Do not attach
credentials or private runtime databases. Ordinary non-sensitive defects can
use the bug-report issue template.
