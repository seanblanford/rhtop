# Local data and reporting

rhtop is a read-only client. It permits an exact list of MCP account, position,
order, search, and instrument catalog reads. It never submits, cancels, or
previews orders, and never modifies Robinhood watchlists.

OAuth uses the official MCP SDK with state verification and a loopback-only
callback. The endpoint is fixed to Robinhood, and authorization redirects must
use HTTPS on Robinhood domains. Browser launching cannot be enabled. rhtop has
its own credential vault and never opens credentials or settings from other applications.

The vault encrypts OAuth tokens, registered client metadata, selected account,
and live asset recents. Its key is held in an allowlisted native OS keyring, or
derived from a user-supplied passphrase with scrypt. Plaintext/null keyring
backends are not accepted. Private files use atomic replacement and Unix mode
0600; new application directories use 0700. Non-secret layout preferences and
offline demo recents use private JSON files. Native Windows ACL support has not
been implemented or verified; Windows distribution is a placeholder.

No snapshots, raw broker responses, account identifiers, or tokens are written
to logs. Transport logging and Textual's default traceback-with-locals rendering
are suppressed. Terminal output renders broker strings as plain text with
control characters removed. Masking protects personal values on screen; public
symbols, market metadata, and recent asset titles remain visible.

Report a suspected security issue directly to the maintainer through a private
communication channel. Do not post tokens, vault files, authorization URLs, or
unmasked account screenshots in public issues.
