"""Read-only "MSA" catalog provider with one event per flyby, for SciQLop's catalog Jump mode."""
from datetime import datetime, timezone

from .flybys import flybys


def flyby_events() -> list:
    return [dict(uuid="msa-flyby-" + f.name.lower().replace(" ", "-"),
                 start=datetime.fromtimestamp(f.start, tz=timezone.utc),
                 stop=datetime.fromtimestamp(f.stop, tz=timezone.utc),
                 meta={"flyby": f.name, "closest_approach": f.closest_approach.isoformat()})
            for f in flybys()]


def make_flyby_catalog_provider():
    """Constructing it registers it with SciQLop's catalog registry; keep a reference."""
    from SciQLop.components.catalogs.backend.provider import Catalog, CatalogEvent, CatalogProvider

    class MSAFlybyCatalogProvider(CatalogProvider):
        def __init__(self):
            # Set before super().__init__: registering asks for catalogs() right away.
            self._catalog = Catalog(uuid="msa-flybys", name="Flybys", provider=self)
            super().__init__(name="MSA", description="BepiColombo flybys with MSA data.")
            self._set_events(self._catalog, [CatalogEvent(**event) for event in flyby_events()])
            self.catalog_added.emit(self._catalog)

        def catalogs(self) -> list:
            return [self._catalog]

    return MSAFlybyCatalogProvider()
