# bluetooth: Bluetooth specifications

The catalog at [bluetooth.com/specifications/specs/](https://www.bluetooth.com/specifications/specs/):
each row's name, version, type and status. `fetch` stores that table. `sync` downloads the HTML book the
specification page links and indexes its sections.

```
primarysource bluetooth fetch
primarysource bluetooth sync
primarysource bluetooth search "advertising"
primarysource bluetooth read "bluetooth:core-specification-7-0§4.E.1"
```

Books stay in `$PRIMARYSOURCE_HOME/bluetooth/`. The package does not contain the specifications. The Bluetooth
SIG publishes them for implementers; this collection does not redistribute the text.

A Core Specification section is `volume.part.number`, so volume 4 part E section 1 is `4.E.1`. A profile or
service section is the number printed in the book, such as `1.1`.
