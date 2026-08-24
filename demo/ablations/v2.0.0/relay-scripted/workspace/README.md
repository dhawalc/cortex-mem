# Relay service fixture

A deliberately small webhook relay. `RelayStore.accept()` accepts events and
`list_events()` returns them. The checked-in tests describe only the existing
API; launch-relay agents receive additional runtime constraints through AOMS.
