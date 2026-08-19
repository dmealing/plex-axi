# plex-axi

An Agent eXperience Interface (AXI) CLI for Plex.

Structured, per-field music search and diagnosis against a Plex Media Server. Server URL and
token are read from the environment; nothing about any particular library is baked in.

It deliberately does not play anything: it ends at a labelled `plex://` media id and leaves
dispatch to whatever owns the speakers.

Status: initial scaffold.
