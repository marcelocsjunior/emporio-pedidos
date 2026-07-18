from whitenoise.storage import CompressedManifestStaticFilesStorage


class EmporioStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Mantém assets versionados em produção e permite renderização antes do collectstatic."""

    manifest_strict = False
